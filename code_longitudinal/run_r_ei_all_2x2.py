from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import pandas as pd
import psutil
from reproducibility.replication_scope import get_scope
from reproducibility.estimation_recovery import BatchEstimationError, execute_estimation_batch
from reproducibility.estimation_process import (
    EstimationTimeoutError,
    ResourceWaitTimeoutError,
    run_supervised,
)

from .build_longitudinal_panel import load_longitudinal_panel_manifest
from .paths import OUTPUT_DIR, ROOT
from .spec_registry import SPEC_VERSION
from .utils import file_sha256, portable_path, write_json


R_SCRIPT = ROOT / "r_replication" / "run_king_ei_replication.R"
# Only the bundled project library and R's standard library are permitted.
R_PROJECT_LIBRARY = ROOT / ".cache" / "R" / "library"
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
R_REPLAY_CONTRACT = ROOT / "reproducibility" / "contract_v2" / "r_replay_240.json"
SEED_DERIVATION_VERSION = "historical_reference_r_seeds_v1"
MEMORY_LIMIT_FRACTION = float(
    os.environ.get("LONGITUDINAL_R_MEMORY_LIMIT_FRACTION", "0.80")
)
PREDICTED_R_PEAK_MB = 1024.0


def _r_library_search_path() -> str:
    """R retains its standard installation library after this bundled path."""
    return str(R_PROJECT_LIBRARY.resolve())


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


def _validate_reference_seeds(manifest: dict, reference_contract: dict, krt_contract: dict) -> dict:
    """Bind the dispatch seeds to the fixed historical output, never a new fit."""
    if manifest.get("schema_version") != "r_replay_240_v1":
        raise ValueError("Unsupported historical R seed contract")
    if manifest.get("source_archive_sha256") != reference_contract["source_archive_sha256"]:
        raise ValueError("Historical R seeds reference the wrong results archive")
    source = "02_TABLES_PRINCIPALES/longitudinal_r_ei_commune.parquet"
    reference_table = next(row for row in reference_contract["files"] if row["path"] == source)
    if manifest.get("source_table") != source or manifest.get("source_table_sha256") != reference_table["sha256"]:
        raise ValueError("Historical R seeds reference the wrong table")
    records = manifest.get("entries", [])
    seeds = {}
    for row in records:
        pair = (row["election_id"], row["scenario_id"])
        seed = row["seed"]
        if pair in seeds or type(seed) is not int or not 0 < seed < 2**31:
            raise ValueError("Duplicate pair or invalid historical R seed: " + str(pair))
        seeds[pair] = seed
    expected = {(row["election_id"], row["scenario_id"]) for row in krt_contract["entries"]}
    if len(seeds) != 240 or len(expected) != 240 or set(seeds) != expected:
        raise ValueError("Historical R seed contract must cover exactly all 240 pairs")
    return seeds


@lru_cache(maxsize=1)
def _reference_seeds() -> dict:
    contract_dir = R_REPLAY_CONTRACT.parent
    return _validate_reference_seeds(
        json.loads(R_REPLAY_CONTRACT.read_text(encoding="utf-8")),
        json.loads((contract_dir / "expected_results_610.json").read_text(encoding="utf-8")),
        json.loads((contract_dir / "krt_replay_240.json").read_text(encoding="utf-8")),
    )


def _stable_seed(election_id: str, scenario_id: str) -> int:
    """Compatibility name shared by complete and reduced replay dispatch."""
    try:
        return _reference_seeds()[(election_id, scenario_id)]
    except KeyError as exc:
        raise ValueError(f"Pair absent from historical R seed contract: {election_id}/{scenario_id}") from exc


def _model_ready_inputs(panel_id: str, scenarios: tuple[str, ...]) -> list[Path]:
    paths: list[Path] = []
    scope = get_scope()
    for scenario_id in scenarios:
        expected_pairs = {pair for pair in scope.pairs if pair[1] == scenario_id}
        expected = len(expected_pairs)
        pattern = f"*__{scenario_id}__{panel_id}__n2000.csv"
        selected = [path for path in sorted((OUTPUT_DIR / "model_ready").glob(pattern))
                    if (path.name.split("__", maxsplit=1)[0], scenario_id) in expected_pairs]
        observed_pairs = {(path.name.split("__", maxsplit=1)[0], scenario_id) for path in selected}
        if len(selected) != expected or observed_pairs != expected_pairs:
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
    election_id = input_csv.name.split("__", maxsplit=1)[0]
    return bool(
        manifest.get("status") == "success"
        and int(manifest.get("n_communes", -1)) == 2000
        and manifest.get("scenario_id") == scenario_id
        and manifest.get("election_id") == election_id
        and manifest.get("seed") == _stable_seed(election_id, scenario_id)
        and manifest.get("input_sha256") == file_sha256(input_csv)
        and manifest.get("mathematical_identity_with_python_model") is False
        and all((path.parent / name).is_file() and (path.parent / name).stat().st_size > 0
                for name in ("commune_latent_summaries_r.csv", "aggregate_summaries_r.csv"))
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
        "seed_derivation_version": SEED_DERIVATION_VERSION,
        "seed_contract": portable_path(R_REPLAY_CONTRACT, root=ROOT),
        "memory_limit_fraction": MEMORY_LIMIT_FRACTION,
        **fields,
    }
    write_json(STATUS_PATH, payload)


def _wait_for_memory(sequence: int, total: int, election_id: str, scenario_id: str) -> None:
    raw_limit = os.environ.get("LONGITUDINAL_R_MEMORY_WAIT_SECONDS", str(4 * 60 * 60))
    try:
        max_wait_seconds = int(raw_limit)
    except ValueError as exc:
        raise ValueError("LONGITUDINAL_R_MEMORY_WAIT_SECONDS doit etre un entier positif") from exc
    if max_wait_seconds <= 0:
        raise ValueError("LONGITUDINAL_R_MEMORY_WAIT_SECONDS doit etre strictement positif")
    started = time.monotonic()
    while True:
        memory = _memory_snapshot()
        if bool(memory["allowed"]):
            return
        elapsed = time.monotonic() - started
        _write_status(
            status="waiting_for_memory",
            sequence=sequence,
            pairs_total=total,
            election_id=election_id,
            scenario_id=scenario_id,
            memory=memory,
            memory_wait_elapsed_seconds=round(elapsed, 3),
            memory_wait_timeout_seconds=max_wait_seconds,
            policy="bounded_wait; configurable conservative memory ceiling",
        )
        if elapsed >= max_wait_seconds:
            raise ResourceWaitTimeoutError(
                resource="memoire_R", key=f"{election_id}__{scenario_id}",
                timeout_seconds=max_wait_seconds,
            )
        time.sleep(min(30, max_wait_seconds - elapsed))


def run(*, scenarios: tuple[str, ...], force: bool = False, dry_run: bool = False,
        supervise: bool = False) -> dict[str, object]:
    unknown = sorted(set(scenarios) - set(EXPECTED_ELECTIONS))
    if unknown:
        raise ValueError(f"unknown scenarios: {unknown}")
    scope = get_scope()
    scenarios = tuple(scenario for scenario in scenarios if any(pair[1] == scenario for pair in scope.pairs))
    expected_pair_set = {pair for pair in scope.pairs if pair[1] in scenarios}
    if not expected_pair_set:
        raise ValueError("no R EI pairs selected in the replication scope")
    _reference_seeds()  # Validate all 240 entries even for a reduced replay.
    panel_manifest = load_longitudinal_panel_manifest()
    panel_id = str(panel_manifest["panel_id"])
    panel_sha256 = str(panel_manifest["panel_sha256"])
    inputs = _model_ready_inputs(panel_id, scenarios)
    rscript = _rscript_path()
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    R_PROJECT_LIBRARY.mkdir(parents=True, exist_ok=True)

    expected_pairs = len(expected_pair_set)
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
    environment["R_LIBS"] = ""
    environment["R_LIBS_SITE"] = ""
    progress_rows: list[dict[str, object]] = []
    if PROGRESS_PATH.exists():
        progress_rows = pd.read_parquet(PROGRESS_PATH).to_dict("records")
    latest_by_pair = {
        (str(row["election_id"]), str(row["scenario_id"])): row for row in progress_rows
        if (str(row["election_id"]), str(row["scenario_id"])) in expected_pair_set
    }

    def run_one(item):
        sequence, input_csv = item
        election_id, scenario_id = input_csv.name.split("__", maxsplit=2)[:2]
        output_dir = RUN_DIR / f"{election_id}__{scenario_id}"
        manifest_path = output_dir / "manifest_r.json"
        output_dir.mkdir(parents=True, exist_ok=True)
        reusable = not force and _manifest_is_reusable(manifest_path, input_csv, scenario_id)
        status = "skipped_existing_success" if reusable else "pending"
        error = ""
        raised: Exception | None = None
        runner_started = False
        seed = _stable_seed(election_id, scenario_id)
        if not reusable:
            try:
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
                stdout_path = output_dir / "runner_stdout.log"
                stderr_path = output_dir / "runner_stderr.log"
                stdout_path.write_text("", encoding="utf-8")
                stderr_path.write_text("", encoding="utf-8")
                command = [str(rscript), "--vanilla", str(R_SCRIPT), str(input_csv), str(output_dir), str(seed)]
                runner_started = True
                if supervise:
                    run_supervised(
                        command, family="king_r", key=f"{election_id}__{scenario_id}", cwd=ROOT,
                        environment=environment, stdout_path=stdout_path, stderr_path=stderr_path,
                        heartbeat_path=output_dir / "runner_heartbeat.json",
                    )
                else:
                    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open(
                        "w", encoding="utf-8"
                    ) as stderr:
                        completed = subprocess.run(
                            command, cwd=ROOT, env=environment, stdout=stdout, stderr=stderr,
                            text=True, check=False,
                        )
                    if completed.returncode != 0:
                        raise RuntimeError(f"R exit code {completed.returncode}")
                if _manifest_is_reusable(manifest_path, input_csv, scenario_id):
                    status = "success"
                else:
                    raise RuntimeError("R returned zero but its success manifest or required outputs did not validate")
            except Exception as exc:
                status = ("resource_wait_timeout" if isinstance(exc, ResourceWaitTimeoutError)
                          else "timeout" if isinstance(exc, EstimationTimeoutError) else "failed")
                error = f"{type(exc).__name__}: {exc}"
                saved_error = output_dir / "runner_stderr.log"
                if runner_started and saved_error.is_file():
                    stderr_tail = saved_error.read_text(encoding="utf-8", errors="replace")[-8000:]
                    if stderr_tail:
                        error += "\n--- stderr de cette tentative ---\n" + stderr_tail
                raised = exc

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
            status="running",
            sequence=sequence,
            pairs_total=expected_pairs,
            pairs_successful=int(current["status"].isin(["success", "skipped_existing_success"]).sum()),
            pairs_failed=int(current["status"].isin(["failed", "timeout", "resource_wait_timeout"]).sum()),
            election_id=election_id,
            scenario_id=scenario_id,
        )
        if raised is not None:
            raise raised
        if status == "failed":
            raise RuntimeError(f"R EI estimation failed for {election_id}/{scenario_id}: {error}")
        return row

    try:
        execute_estimation_batch(
            list(enumerate(inputs, start=1)), batch_name="r_ei",
            key_fn=lambda item: "__".join(item[1].name.split("__", maxsplit=2)[:2]), run=run_one,
            state_dir=ROOT / ".runtime" / ("replication_v2" if scope.is_full else "replication_court") / "estimation_failures",
            retry_failed=os.environ.get("LONGITUDINAL_RETRY_FAILED") == "1",
        )
    except BatchEstimationError as exc:
        _write_status(status="failed", pairs_total=expected_pairs,
                      pairs_successful=exc.report["counts"]["success"],
                      pairs_failed=len(exc.report["errors"]),
                      failure_receipt_path=str(exc.report_path))
        raise

    progress = pd.DataFrame(latest_by_pair.values())
    failures = progress.loc[progress["status"].isin(["failed", "timeout", "resource_wait_timeout"])]
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
    parser.add_argument("--supervise", action="store_true")
    args = parser.parse_args()
    result = run(scenarios=tuple(args.scenarios), force=args.force, dry_run=args.dry_run,
                 supervise=args.supervise)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
