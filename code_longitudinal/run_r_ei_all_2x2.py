from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import psutil

from .build_longitudinal_panel import load_longitudinal_panel_manifest
from .paths import OUTPUT_DIR, ROOT
from .spec_registry import SPEC_VERSION
from .utils import file_sha256, portable_path, write_json


R_SCRIPT = ROOT / "r_replication" / "run_king_ei_replication.R"
R_PROJECT_LIBRARY = ROOT / ".r_lib"
REPLICATION_DIR = OUTPUT_DIR / SPEC_VERSION / "r_replication"
RUN_DIR = REPLICATION_DIR / "king_ei_runs"
PROGRESS_PATH = REPLICATION_DIR / "king_ei_progress_all_2x2.parquet"
STATUS_PATH = REPLICATION_DIR / "king_ei_all_2x2_status.json"

DEFAULT_SCENARIOS = ("H2", "H3", "H6", "H7", "H0B", "H0C", "H4", "H5", "H1", "H0A")
EXPECTED_ELECTIONS = {
    "H0A": 26,
    "H0B": 26,
    "H0C": 26,
    "H1": 26,
    "H2": 26,
    "H3": 26,
    "H4": 26,
    "H5": 26,
    "H6": 16,
    "H7": 16,
}
BASE_SEED = 20260802
SEED_DERIVATION_VERSION = "sha256_first8_mod_int31_v1"
MEMORY_LIMIT_FRACTION = float(
    os.environ.get("LONGITUDINAL_R_MEMORY_LIMIT_FRACTION", "0.80")
)
PREDICTED_R_PEAK_MB = 1024.0


def _r_library_search_path() -> str:
    """Use the project library first, then any installed per-user R library.

    The project library contains the study-specific packages.  On Windows,
    compiled transitive dependencies may already live in R's normal per-user
    library; retaining that path avoids silently hiding them when
    ``R_LIBS_USER`` is set for the subprocess.
    """
    libraries = [R_PROJECT_LIBRARY]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        user_root = Path(local_app_data) / "R" / "win-library"
        if user_root.is_dir():
            libraries.extend(
                path for path in sorted(user_root.iterdir(), reverse=True) if path.is_dir()
            )
    return os.pathsep.join(str(path.resolve()) for path in libraries)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rscript_path() -> Path:
    configured = os.environ.get("LONGITUDINAL_RSCRIPT")
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return path.resolve()
        raise FileNotFoundError(f"LONGITUDINAL_RSCRIPT does not point to a file: {path}")
    discovered = shutil.which("Rscript")
    if discovered:
        return Path(discovered).resolve()
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        r_root = Path(program_files) / "R"
        for candidate in sorted(r_root.glob("R-*/bin/Rscript.exe"), reverse=True):
            if candidate.is_file():
                return candidate.resolve()
    raise FileNotFoundError("Rscript was not found")


def _stable_seed(election_id: str, scenario_id: str) -> int:
    payload = f"{BASE_SEED}|{SPEC_VERSION}|R_ei_1.3.3|{scenario_id}|{election_id}"
    value = int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")
    return value % (2**31 - 1) or 1


def _model_ready_inputs(panel_id: str, scenarios: tuple[str, ...]) -> list[Path]:
    paths: list[Path] = []
    for scenario_id in scenarios:
        expected = EXPECTED_ELECTIONS[scenario_id]
        pattern = f"*__{scenario_id}__{panel_id}__n2000.csv"
        selected = sorted((OUTPUT_DIR / "model_ready").glob(pattern))
        if len(selected) != expected:
            raise AssertionError(
                f"expected {expected} {scenario_id} model-ready CSV files; found {len(selected)}"
            )
        paths.extend(selected)
    return paths


def _manifest_is_reusable(path: Path, input_csv: Path, scenario_id: str) -> bool:
    if not path.exists():
        return False
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(
        manifest.get("status") == "success"
        and int(manifest.get("n_communes", -1)) == 2000
        and manifest.get("scenario_id") == scenario_id
        and manifest.get("input_sha256") == file_sha256(input_csv)
        and manifest.get("mathematical_identity_with_python_model") is False
    )


def _memory_snapshot() -> dict[str, float | bool]:
    memory = psutil.virtual_memory()
    projected_available = memory.available - PREDICTED_R_PEAK_MB * 1024**2
    allowed = projected_available >= memory.total * (1.0 - MEMORY_LIMIT_FRACTION)
    return {
        "total_mb": memory.total / 1024**2,
        "available_mb": memory.available / 1024**2,
        "used_fraction": memory.percent / 100.0,
        "predicted_r_peak_mb": PREDICTED_R_PEAK_MB,
        "projected_used_fraction": 1.0 - projected_available / memory.total,
        "allowed": allowed,
    }


def _write_status(**fields: object) -> None:
    payload = {
        "schema_version": "longitudinal_r_ei_all_2x2_status_v1",
        "updated_at_utc": _utc_now(),
        "model": "King_1997_truncated_bivariate_normal_EI_R_ei_depending_on_eiPack",
        "comparison_target": "Python_PyMC_KRT_king99_beta_binomial",
        "mathematical_identity_with_python_model": False,
        "panel_size": 2000,
        "base_seed": BASE_SEED,
        "seed_derivation_version": SEED_DERIVATION_VERSION,
        "memory_limit_fraction": MEMORY_LIMIT_FRACTION,
        **fields,
    }
    write_json(STATUS_PATH, payload)


def _wait_for_memory(sequence: int, total: int, election_id: str, scenario_id: str) -> None:
    while True:
        memory = _memory_snapshot()
        if bool(memory["allowed"]):
            return
        _write_status(
            status="waiting_for_memory",
            sequence=sequence,
            pairs_total=total,
            election_id=election_id,
            scenario_id=scenario_id,
            memory=memory,
            policy="wait_only; configurable conservative memory ceiling",
        )
        time.sleep(30)


def run(*, scenarios: tuple[str, ...], force: bool = False, dry_run: bool = False) -> dict[str, object]:
    unknown = sorted(set(scenarios) - set(EXPECTED_ELECTIONS))
    if unknown:
        raise ValueError(f"unknown scenarios: {unknown}")
    panel_manifest = load_longitudinal_panel_manifest()
    panel_id = str(panel_manifest["panel_id"])
    panel_sha256 = str(panel_manifest["panel_sha256"])
    inputs = _model_ready_inputs(panel_id, scenarios)
    rscript = _rscript_path()
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    R_PROJECT_LIBRARY.mkdir(parents=True, exist_ok=True)

    expected_pairs = sum(EXPECTED_ELECTIONS[scenario_id] for scenario_id in scenarios)
    if len(inputs) != expected_pairs:
        raise AssertionError(f"expected {expected_pairs} inputs; found {len(inputs)}")

    if dry_run:
        reusable = 0
        for input_csv in inputs:
            election_id, scenario_id = input_csv.name.split("__", maxsplit=2)[:2]
            manifest_path = RUN_DIR / f"{election_id}__{scenario_id}" / "manifest_r.json"
            reusable += int(_manifest_is_reusable(manifest_path, input_csv, scenario_id))
        result = {
            "status": "dry_run_pass",
            "panel_id": panel_id,
            "panel_sha256": panel_sha256,
            "scenarios": list(scenarios),
            "pairs_total": expected_pairs,
            "pairs_reusable": reusable,
            "pairs_to_run": expected_pairs - reusable,
            "rscript": str(rscript),
        }
        _write_status(**result)
        return result

    environment = os.environ.copy()
    environment["R_LIBS_USER"] = _r_library_search_path()
    progress_rows: list[dict[str, object]] = []
    if PROGRESS_PATH.exists():
        progress_rows = pd.read_parquet(PROGRESS_PATH).to_dict("records")
    latest_by_pair = {
        (str(row["election_id"]), str(row["scenario_id"])): row for row in progress_rows
    }

    for sequence, input_csv in enumerate(inputs, start=1):
        election_id, scenario_id = input_csv.name.split("__", maxsplit=2)[:2]
        output_dir = RUN_DIR / f"{election_id}__{scenario_id}"
        manifest_path = output_dir / "manifest_r.json"
        output_dir.mkdir(parents=True, exist_ok=True)
        reusable = not force and _manifest_is_reusable(manifest_path, input_csv, scenario_id)
        status = "skipped_existing_success" if reusable else "pending"
        error = ""
        seed = _stable_seed(election_id, scenario_id)
        if not reusable:
            _wait_for_memory(sequence, expected_pairs, election_id, scenario_id)
            memory_before = _memory_snapshot()
            _write_status(
                status="running",
                sequence=sequence,
                pairs_total=expected_pairs,
                election_id=election_id,
                scenario_id=scenario_id,
                run_seed=seed,
                memory=memory_before,
            )
            with (output_dir / "runner_stdout.log").open("w", encoding="utf-8") as stdout, (
                output_dir / "runner_stderr.log"
            ).open("w", encoding="utf-8") as stderr:
                completed = subprocess.run(
                    [str(rscript), str(R_SCRIPT), str(input_csv), str(output_dir), str(seed)],
                    cwd=ROOT,
                    env=environment,
                    stdout=stdout,
                    stderr=stderr,
                    text=True,
                    check=False,
                )
            if completed.returncode == 0 and _manifest_is_reusable(
                manifest_path, input_csv, scenario_id
            ):
                status = "success"
            else:
                status = "failed"
                error = (output_dir / "runner_stderr.log").read_text(
                    encoding="utf-8", errors="replace"
                )[-8000:]

        row = {
            "sequence": sequence,
            "panel_id": panel_id,
            "panel_sha256": panel_sha256,
            "election_id": election_id,
            "scenario_id": scenario_id,
            "status": status,
            "error": error,
            "run_seed": seed,
            "input_csv": portable_path(input_csv, root=ROOT),
            "input_sha256": file_sha256(input_csv),
            "output_dir": portable_path(output_dir, root=ROOT),
            "model": "King_1997_truncated_bivariate_normal_EI_R_ei_depending_on_eiPack",
            "comparison_target": "Python_PyMC_KRT_king99_beta_binomial",
            "mathematical_identity_with_python_model": False,
            "updated_at_utc": _utc_now(),
        }
        latest_by_pair[(election_id, scenario_id)] = row
        current = pd.DataFrame(latest_by_pair.values()).sort_values(["sequence", "election_id"])
        current.to_parquet(PROGRESS_PATH, index=False)
        _write_status(
            status="running" if sequence < expected_pairs else "complete",
            sequence=sequence,
            pairs_total=expected_pairs,
            pairs_successful=int(current["status"].isin(["success", "skipped_existing_success"]).sum()),
            pairs_failed=int(current["status"].eq("failed").sum()),
            election_id=election_id,
            scenario_id=scenario_id,
        )

    progress = pd.DataFrame(latest_by_pair.values())
    failures = progress.loc[progress["status"].eq("failed")]
    result = {
        "status": "complete" if failures.empty else "complete_with_failures",
        "panel_id": panel_id,
        "panel_sha256": panel_sha256,
        "scenarios": list(scenarios),
        "pairs_total": expected_pairs,
        "pairs_successful": int(progress["status"].isin(["success", "skipped_existing_success"]).sum()),
        "pairs_failed": len(failures),
        "progress_path": portable_path(PROGRESS_PATH, root=ROOT),
    }
    _write_status(**result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run all eligible longitudinal 2x2 hypotheses with R ei/eiPack."
    )
    parser.add_argument("--scenarios", nargs="+", default=list(DEFAULT_SCENARIOS))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = run(scenarios=tuple(args.scenarios), force=args.force, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
