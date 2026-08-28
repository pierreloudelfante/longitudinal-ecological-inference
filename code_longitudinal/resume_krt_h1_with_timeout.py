from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .paths import OUTPUT_DIR
from .spec_registry import ELECTIONS, SPEC_VERSION
from .utils import write_json


ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = OUTPUT_DIR / "runs"
PRODUCTION_DIR = OUTPUT_DIR / SPEC_VERSION / "production"
DEFERRED_PATH = PRODUCTION_DIR / "krt_h1_deferred_retries.json"


def _successful_h1() -> set[str]:
    successful: set[str] = set()
    for path in RUNS_DIR.glob("*/manifest.json"):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        parameters = manifest.get("parameters") or {}
        if (
            manifest.get("status") == "success"
            and parameters.get("scenario_id") == "H1"
            and parameters.get("model_key") == "krt_beta_binomial"
            and parameters.get("sample_size") == 2000
            and str(parameters.get("panel_id", "")).startswith("longitudinal_2000_v1")
        ):
            successful.add(str(parameters.get("election_id")))
    return successful


def _ordered_elections() -> list[str]:
    anchors = ["leg_1962_r1", "leg_1986_r1", "leg_2022_r1"]
    remaining = sorted(
        (item for item in ELECTIONS if item.election_id not in anchors),
        key=lambda item: (item.year, item.election_type, item.election_id),
    )
    return anchors + [item.election_id for item in remaining]


def _run(election_id: str, timeout_seconds: int) -> dict[str, object]:
    command = [
        sys.executable,
        "-m",
        "code_longitudinal.run_pipeline",
        "--stage",
        "krt-longitudinal",
        "--election-id",
        election_id,
        "--scenario-id",
        "H1",
        "--production",
        "--cores",
        "1",
    ]
    started = datetime.now(timezone.utc)
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    try:
        return_code = process.wait(timeout=timeout_seconds)
        status = "success" if return_code == 0 else "failed"
        reason = "" if return_code == 0 else f"exit_code_{return_code}"
    except subprocess.TimeoutExpired:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        status = "deferred_timeout"
        reason = f"runtime_exceeded_{timeout_seconds}_seconds"
    return {
        "election_id": election_id,
        "status": status,
        "reason": reason,
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout-minutes", type=int, default=45)
    args = parser.parse_args()
    timeout_seconds = int(args.timeout_minutes * 60)
    PRODUCTION_DIR.mkdir(parents=True, exist_ok=True)
    log_rows: list[dict[str, object]] = []

    successful = _successful_h1()
    for election_id in _ordered_elections():
        if election_id in successful:
            continue
        result = _run(election_id, timeout_seconds)
        log_rows.append(result)
        successful = _successful_h1()
        if result["status"] == "success" and election_id not in successful:
            result["status"] = "failed_validation"
            result["reason"] = "command_returned_zero_without_validated_success_manifest"
        write_json(
            DEFERRED_PATH,
            {
                "schema_version": "krt_h1_timeout_resume_v1",
                "timeout_minutes": args.timeout_minutes,
                "successful_h1_elections": sorted(successful),
                "events": log_rows,
            },
        )

    frame = pd.DataFrame(log_rows)
    frame.to_parquet(PRODUCTION_DIR / "krt_h1_timeout_resume.parquet", index=False)


if __name__ == "__main__":
    main()
