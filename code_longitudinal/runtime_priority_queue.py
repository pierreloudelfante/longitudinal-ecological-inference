from __future__ import annotations

import argparse
import ctypes
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

from .paths import ROOT


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write the small runtime status without importing the analytics stack."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


@contextmanager
def _keep_system_awake() -> object:
    if os.name != "nt":
        yield
        return
    es_continuous = 0x80000000
    es_system_required = 0x00000001
    previous = ctypes.windll.kernel32.SetThreadExecutionState(
        es_continuous | es_system_required
    )
    if previous == 0:
        raise OSError("SetThreadExecutionState failed")
    try:
        yield
    finally:
        ctypes.windll.kernel32.SetThreadExecutionState(es_continuous)


def _load_plan(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("stages"), list) or not payload["stages"]:
        raise ValueError("the priority plan must contain at least one stage")
    return payload


def _original_process(spec: dict[str, Any]) -> psutil.Process | None:
    """Return the exact process described by *spec*, never a reused PID."""
    pid = int(spec["pid"])
    try:
        process = psutil.Process(pid)
        if abs(process.create_time() - float(spec["create_time"])) > 1e-3:
            return None
        marker = str(spec.get("command_contains", ""))
        if marker and marker not in " ".join(process.cmdline()):
            raise RuntimeError(f"PID {pid} no longer matches marker {marker!r}")
        return process
    except psutil.NoSuchProcess:
        return None


def _process_snapshot(spec: dict[str, Any]) -> dict[str, Any]:
    process = _original_process(spec)
    if process is None:
        return {"pid": int(spec["pid"]), "original_process_alive": False}
    return {
        "pid": process.pid,
        "original_process_alive": True,
        "status": process.status(),
        "rss_mb": process.memory_info().rss / (1024**2),
    }


def _memory_snapshot() -> dict[str, float]:
    memory = psutil.virtual_memory()
    return {
        "total_mb": float(memory.total / (1024**2)),
        "available_mb": float(memory.available / (1024**2)),
        "used_percent": float(memory.percent),
        "available_fraction": float(memory.available / memory.total),
    }


def _trim_working_set(process: psutil.Process) -> bool:
    if os.name != "nt":
        return False
    process_set_quota = 0x0100
    process_query_information = 0x0400
    handle = ctypes.windll.kernel32.OpenProcess(
        process_set_quota | process_query_information,
        False,
        process.pid,
    )
    if not handle:
        return False
    try:
        return bool(ctypes.windll.psapi.EmptyWorkingSet(handle))
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _apply_memory_guard(
    stage: dict[str, Any],
    *,
    suspended_by_controller: bool,
) -> tuple[bool, dict[str, Any] | None]:
    guard = stage.get("memory_guard")
    if not guard:
        return suspended_by_controller, None
    process = _original_process(guard["process"])
    memory = _memory_snapshot()
    minimum_fraction = float(guard.get("minimum_available_fraction", 0.20))
    predicted_peak_mb = float(guard.get("resume_predicted_peak_memory_mb", 1024.0))
    floor_mb = memory["total_mb"] * minimum_fraction
    resume_threshold_mb = floor_mb + predicted_peak_mb
    action = "none"
    trimmed = False
    if process is None:
        action = "original_process_absent"
    elif not suspended_by_controller and memory["available_mb"] < floor_mb:
        process.suspend()
        trimmed = _trim_working_set(process)
        suspended_by_controller = True
        action = "suspended_below_memory_floor"
    elif suspended_by_controller and memory["available_mb"] >= resume_threshold_mb:
        process.resume()
        suspended_by_controller = False
        action = "resumed_with_predicted_headroom"
    return suspended_by_controller, {
        "pid": int(guard["process"]["pid"]),
        "suspended_by_controller": suspended_by_controller,
        "action": action,
        "working_set_trimmed": trimmed,
        "memory_floor_mb": floor_mb,
        "resume_threshold_mb": resume_threshold_mb,
    }


def _write_status(
    status_path: Path,
    *,
    plan_path: Path,
    state: str,
    stage_index: int,
    stage: dict[str, Any] | None,
    extra: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "state": state,
        "controller_pid": os.getpid(),
        "plan_path": plan_path.resolve().relative_to(ROOT).as_posix(),
        "stage_index": stage_index,
        "stage_label": "" if stage is None else str(stage.get("label", "")),
        "updated_at_utc": _utc_now(),
        "memory": _memory_snapshot(),
    }
    if stage is not None:
        payload["wait_for"] = [
            _process_snapshot(item) for item in stage.get("wait_for", [])
        ]
        payload["resume"] = [
            _process_snapshot(item) for item in stage.get("resume", [])
        ]
    if extra:
        payload.update(extra)
    _write_json(status_path, payload)


def _wait_for_stage_predecessors(
    *,
    plan_path: Path,
    status_path: Path,
    stage_index: int,
    stage: dict[str, Any],
    poll_seconds: float,
) -> None:
    guard = stage.get("memory_guard") or {}
    guard_suspended = bool(guard.get("initially_suspended", False))
    while True:
        guard_suspended, guard_status = _apply_memory_guard(
            stage,
            suspended_by_controller=guard_suspended,
        )
        alive = [
            item for item in stage.get("wait_for", []) if _original_process(item) is not None
        ]
        _write_status(
            status_path,
            plan_path=plan_path,
            state="waiting_for_predecessor",
            stage_index=stage_index,
            stage=stage,
            extra={
                "predecessors_still_alive": len(alive),
                "memory_guard": guard_status,
            },
        )
        if not alive:
            return
        time.sleep(poll_seconds)


def _wait_for_memory_gate(
    *,
    plan_path: Path,
    status_path: Path,
    stage_index: int,
    stage: dict[str, Any],
    poll_seconds: float,
) -> None:
    required_fraction = float(stage.get("minimum_available_fraction", 0.20))
    predicted_peak_mb = float(stage.get("predicted_peak_memory_mb", 0.0))
    while True:
        memory = _memory_snapshot()
        required_available_mb = (
            memory["total_mb"] * required_fraction + predicted_peak_mb
        )
        if memory["available_mb"] >= required_available_mb:
            return
        _write_status(
            status_path,
            plan_path=plan_path,
            state="waiting_for_memory_gate",
            stage_index=stage_index,
            stage=stage,
            extra={
                "minimum_available_fraction": required_fraction,
                "predicted_peak_memory_mb": predicted_peak_mb,
                "required_available_memory_mb": required_available_mb,
            },
        )
        time.sleep(poll_seconds)


def _resume_stage(stage: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for spec in stage.get("resume", []):
        process = _original_process(spec)
        if process is None:
            actions.append({"pid": int(spec["pid"]), "action": "original_process_absent"})
            continue
        before = process.status()
        # Windows can report ``running`` for a process whose threads remain
        # suspended after its working set was trimmed. NtResumeProcess is a
        # safe no-op for a genuinely running process, so always request the
        # resume instead of trusting the coarse status label.
        process.resume()
        actions.append(
            {
                "pid": process.pid,
                "action": "resume_requested",
                "status_before": before,
                "status_after": process.status(),
            }
        )
    return actions


def run(plan_path: Path) -> Path:
    plan = _load_plan(plan_path)
    status_value = plan.get("status_path", "")
    status_path = (
        (ROOT / status_value).resolve()
        if status_value
        else plan_path.with_name(f"{plan_path.stem}_status.json")
    )
    poll_seconds = float(plan.get("poll_seconds", 30.0))
    with _keep_system_awake():
        for stage_index, stage in enumerate(plan["stages"], start=1):
            _wait_for_stage_predecessors(
                plan_path=plan_path,
                status_path=status_path,
                stage_index=stage_index,
                stage=stage,
                poll_seconds=poll_seconds,
            )
            _wait_for_memory_gate(
                plan_path=plan_path,
                status_path=status_path,
                stage_index=stage_index,
                stage=stage,
                poll_seconds=poll_seconds,
            )
            actions = _resume_stage(stage)
            _write_status(
                status_path,
                plan_path=plan_path,
                state="stage_resumed",
                stage_index=stage_index,
                stage=stage,
                extra={"resume_actions": actions},
            )
        _write_status(
            status_path,
            plan_path=plan_path,
            state="completed",
            stage_index=len(plan["stages"]),
            stage=None,
        )
    return status_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resume long-running KRT streams in a deterministic memory-safe order."
    )
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    plan_path = args.plan if args.plan.is_absolute() else (ROOT / args.plan)
    status_path = run(plan_path.resolve())
    print(json.dumps({"status_path": str(status_path)}, indent=2))


if __name__ == "__main__":
    main()
