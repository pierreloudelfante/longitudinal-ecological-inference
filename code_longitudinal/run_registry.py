from __future__ import annotations

import json
import shlex
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .paths import OUTPUT_DIR, RUNS_DIR, ensure_runtime_dirs
from .utils import canonical_hash, file_sha256, new_run_id, package_versions, write_json


@dataclass(frozen=True)
class RunHandle:
    run_id: str
    run_key: str
    run_dir: Path
    stage: str
    payload: dict[str, Any]


def _executed_registry_path() -> Path:
    """Private append-only ledger of attempted executions.

    ``run_registry.csv`` is the public consolidated view and also contains the
    scenarios that have not been run yet.  Keeping the execution ledger
    separate prevents those planned rows from affecting deterministic resume.
    """
    return OUTPUT_DIR / "run_registry_executed.csv"


def read_registry() -> pd.DataFrame:
    path = _executed_registry_path()
    if path.exists() and path.stat().st_size:
        return pd.read_csv(path, dtype="string")

    # One-time compatibility with repositories created before the execution
    # ledger and public registry were split.
    legacy = OUTPUT_DIR / "run_registry.csv"
    if not legacy.exists() or not legacy.stat().st_size:
        return pd.DataFrame()
    frame = pd.read_csv(legacy, dtype="string")
    if "status" in frame:
        frame = frame.loc[~frame["status"].eq("planned")].copy()
    if "run_id" in frame:
        frame = frame.loc[frame["run_id"].notna() & frame["run_id"].ne("")].copy()
    return frame


def selected_successful_run_dirs() -> list[Path]:
    """Return the latest immutable success for each statistical configuration.

    Grouping on stage and parameters also absorbs deliberate forced reruns and
    one-time cache-path migrations, while every physical run remains preserved.
    """
    selected: dict[str, tuple[str, Path]] = {}
    for manifest_path in RUNS_DIR.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("status") != "success":
            continue
        run_key = canonical_hash(
            {"stage": manifest.get("stage", ""), "parameters": manifest.get("parameters", {})}
        )
        finished = str(manifest.get("finished_at_utc", ""))
        current = selected.get(run_key)
        if run_key and (current is None or finished > current[0]):
            selected[run_key] = (finished, manifest_path.parent)
    return sorted(value[1] for value in selected.values())


def begin_run(
    *,
    stage: str,
    parameters: dict[str, Any],
    input_paths: Iterable[Path] = (),
    force: bool = False,
) -> RunHandle | None:
    ensure_runtime_dirs()
    inputs = {str(path): file_sha256(path) for path in input_paths if path.exists() and path.is_file()}
    payload = {"stage": stage, "parameters": parameters, "inputs": inputs}
    run_key = canonical_hash(payload)
    registry = read_registry()
    if not force and not registry.empty:
        same = registry.loc[registry["run_key"].eq(run_key) & registry["status"].eq("success")]
        if not same.empty:
            return None
    run_id = new_run_id(run_key)
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    initial = {
        "run_id": run_id,
        "run_key": run_key,
        "stage": stage,
        "status": "running",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": " ".join(shlex.quote(item) for item in sys.argv),
        "parameters": parameters,
        "input_sha256": inputs,
        "package_versions": package_versions(["python", "pandas", "numpy", "scipy", "matplotlib", "pyei", "pymc", "arviz", "pyarrow"]),
    }
    write_json(run_dir / "manifest.json", initial)
    return RunHandle(run_id, run_key, run_dir, stage, initial)


def finish_run(
    handle: RunHandle,
    *,
    status: str,
    metadata: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    finished = datetime.now(timezone.utc).isoformat()
    manifest = dict(handle.payload)
    manifest.update(metadata or {})
    manifest.update({"status": status, "finished_at_utc": finished, "error": error})
    write_json(handle.run_dir / "manifest.json", manifest)
    row = {
        "run_id": handle.run_id,
        "run_key": handle.run_key,
        "stage": handle.stage,
        "status": status,
        "started_at_utc": handle.payload["started_at_utc"],
        "finished_at_utc": finished,
        "election_id": (metadata or {}).get("election_id", ""),
        "scenario_id": (metadata or {}).get("scenario_id", ""),
        "model_key": (metadata or {}).get("model_key", ""),
        "sample_id": (metadata or {}).get("sample_id", ""),
        "n_communes_requested": (metadata or {}).get("n_communes_requested", ""),
        "n_communes_used": (metadata or {}).get("n_communes_used", ""),
        "diagnostic_status": (metadata or {}).get("diagnostic_status", ""),
        "run_dir": str(handle.run_dir),
        "error": error or "",
    }
    registry = read_registry()
    registry = pd.concat([registry, pd.DataFrame([row])], ignore_index=True)
    registry.to_csv(_executed_registry_path(), index=False, encoding="utf-8-sig")
    return manifest


def mark_run_interrupted(run_dir: Path, *, error: str = "interrupted_external_process") -> dict[str, Any]:
    """Close a stale ``running`` manifest after its process has disappeared.

    This recovery operation never deletes or overwrites a successful run.  It
    appends a failed execution to the ledger so the interruption remains
    visible before a clean retry is started.
    """
    resolved = run_dir.resolve()
    if resolved.parent != RUNS_DIR.resolve():
        raise ValueError(f"run directory is outside RUNS_DIR: {resolved}")
    manifest_path = resolved / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "running":
        raise ValueError(f"run is not stale-running: {manifest.get('status')}")
    parameters = manifest.get("parameters", {})
    handle = RunHandle(
        run_id=str(manifest["run_id"]),
        run_key=str(manifest["run_key"]),
        run_dir=resolved,
        stage=str(manifest["stage"]),
        payload=manifest,
    )
    return finish_run(
        handle,
        status="failed",
        metadata={
            "election_id": parameters.get("election_id", ""),
            "scenario_id": parameters.get("scenario_id", ""),
            "model_key": parameters.get("model_key", ""),
            "sample_id": "",
            "n_communes_requested": parameters.get("sample_size", ""),
            "n_communes_used": 0,
            "diagnostic_status": "fail",
        },
        error=error,
    )


def run_output_path(handle: RunHandle, name: str) -> Path:
    return handle.run_dir / name
