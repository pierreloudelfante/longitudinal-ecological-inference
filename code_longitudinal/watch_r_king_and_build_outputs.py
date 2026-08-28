from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
R_OUTPUT = ROOT / "outputs" / "longitudinal_2000_v1" / "r_replication"
RUNNER_STATUS = R_OUTPUT / "king_ei_all_2x2_status.json"
WATCHER_STATUS = R_OUTPUT / "king_ei_postprocess_watcher_status.json"
LOG_DIR = R_OUTPUT / "postprocess_logs"
SCENARIOS = ("H0A", "H1", "H0B", "H0C", "H6", "H7")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def write_status(**updates: object) -> None:
    current = load_json(WATCHER_STATUS)
    current.update(
        {
            "schema_version": "king_ei_postprocess_watcher_v1",
            "updated_at_utc": utc_now(),
            "runner_status_path": str(RUNNER_STATUS.relative_to(ROOT)).replace("\\", "/"),
            **updates,
        }
    )
    WATCHER_STATUS.parent.mkdir(parents=True, exist_ok=True)
    temporary = WATCHER_STATUS.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(WATCHER_STATUS)


def run_step(name: str, command: list[str], *, required: bool) -> dict:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{name}.log"
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    duration = time.perf_counter() - started
    log_path.write_text(
        "COMMAND\n" + " ".join(command) + "\n\nSTDOUT\n" + completed.stdout
        + "\n\nSTDERR\n" + completed.stderr,
        encoding="utf-8",
    )
    result = {
        "name": name,
        "required": required,
        "returncode": completed.returncode,
        "duration_seconds": duration,
        "log_path": str(log_path.relative_to(ROOT)).replace("\\", "/"),
        "status": "complete" if completed.returncode == 0 else "failed",
    }
    if required and completed.returncode != 0:
        raise RuntimeError(f"Required post-processing step failed: {name}")
    return result


def main() -> None:
    write_status(status="waiting_for_r_estimation", steps=[])
    while True:
        runner = load_json(RUNNER_STATUS)
        runner_status = str(runner.get("status", "missing"))
        sequence = int(runner.get("sequence", 0) or 0)
        total = int(runner.get("pairs_total", 240) or 240)
        if runner_status in {"complete", "complete_with_failures"} or sequence >= total:
            break
        write_status(
            status="waiting_for_r_estimation",
            runner_status=runner_status,
            runner_sequence=sequence,
            runner_pairs_total=total,
        )
        time.sleep(30)

    steps: list[dict] = []
    write_status(status="postprocessing", runner_status=runner_status, steps=steps)
    commands = [
        (
            "consolidate_r_ei_all_hypotheses",
            [sys.executable, "-m", "code_longitudinal.consolidate_r_ei_all_2x2", "--scenarios", *SCENARIOS],
            True,
        ),
        (
            "summarize_r_king_runtimes",
            [
                sys.executable,
                "-m",
                "code_longitudinal.summarize_r_king_ei_runtimes",
                "--scenarios",
                *SCENARIOS,
            ],
            True,
        ),
        (
            "r_density_cross_validation_all_hypotheses",
            [
                sys.executable,
                "-m",
                "code_longitudinal.build_r_density_cross_validation",
                "--output-dir",
                str(ROOT / "work" / "r_density_cross_validation_H0A_H1_H0B_H0C_H6_H7_20260827"),
                "--scenarios",
                *SCENARIOS,
            ],
            True,
        ),
        (
            "compare_python_r_ei_retained_scope",
            [sys.executable, "-m", "code_longitudinal.compare_python_r_ei_all_2x2"],
            False,
        ),
        (
            "package_r_code_and_results",
            [sys.executable, "-m", "code_longitudinal.package_r_king_all_hypotheses"],
            True,
        ),
    ]
    try:
        for name, command, required in commands:
            write_status(status="postprocessing", active_step=name, steps=steps)
            result = run_step(name, command, required=required)
            steps.append(result)
            write_status(status="postprocessing", active_step=None, steps=steps)
    except Exception as exc:
        write_status(status="failed", error=f"{type(exc).__name__}: {exc}", steps=steps)
        raise

    optional_failures = [step["name"] for step in steps if step["status"] == "failed"]
    write_status(
        status="complete" if not optional_failures else "complete_with_optional_failures",
        active_step=None,
        optional_failures=optional_failures,
        steps=steps,
    )


if __name__ == "__main__":
    main()
