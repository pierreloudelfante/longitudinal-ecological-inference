from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import psutil

from .build_longitudinal_panel import load_longitudinal_panel_manifest
from .paths import OUTPUT_DIR, ROOT
from .spec_registry import SPEC_VERSION
from .utils import file_sha256, portable_path, write_json


R_SCRIPT = ROOT / "r_replication" / "run_krt_replication_nimble.R"
R_PREFLIGHT_SCRIPT = ROOT / "r_replication" / "preflight_nimble.R"
R_LIBRARIES = (ROOT / ".cache" / "R" / "library", ROOT / ".r_lib")
REPLICATION_DIR = OUTPUT_DIR / SPEC_VERSION / "r_replication"
RUN_DIR = REPLICATION_DIR / "krt_exact_nimble_runs"
PROGRESS_PATH = REPLICATION_DIR / "krt_exact_nimble_progress_all_2x2.parquet"
PLAN_PATH = REPLICATION_DIR / "krt_exact_nimble_plan_240.csv"
PLAN_MANIFEST_PATH = REPLICATION_DIR / "krt_exact_nimble_plan_240.json"
STATUS_PATH = REPLICATION_DIR / "krt_exact_nimble_all_2x2_status.json"
PYTHON_WATCHER_STATUS = (
    OUTPUT_DIR / SPEC_VERSION / "production" / "all_2x2_candidate" / "watcher_status.json"
)

DEFAULT_SCENARIOS = ("H0A", "H1", "H2", "H3", "H0B", "H0C", "H4", "H5", "H6", "H7")
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
ENGINE_VERSION = "nimble_exact_king99_v1"
WARMUP = 1000
DRAWS = 1000
CHAINS = 4
MAX_FIT_SECONDS = 12 * 60 * 60
MEMORY_LIMIT_FRACTION = 0.80
PREDICTED_R_PEAK_MB = 3072.0
TERMINAL_PYTHON_WATCHER_STATUSES = {
    "completed",
    "completed_python_comparison_pending",
    "python_consolidation_failed",
    "coverage_refresh_failed",
}

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _keep_system_awake() -> object:
    """Prevent sleep while the resumable R queue is waiting or sampling."""
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
    candidate = Path(r"C:\Program Files\R\R-4.6.0\bin\Rscript.exe")
    if candidate.is_file():
        return candidate
    raise FileNotFoundError("Rscript was not found")


def _r_preflight(rscript: Path, environment: dict[str, str]) -> dict[str, object]:
    """Prove that the project library and the NIMBLE C++ toolchain work."""
    completed = subprocess.run(
        [str(rscript), str(R_PREFLIGHT_SCRIPT)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    if completed.returncode != 0 or "r_nimble_preflight=PASS" not in stdout:
        raise RuntimeError(
            "R/NIMBLE preflight failed before production: "
            f"returncode={completed.returncode}; stdout={stdout[-2000:]!r}; "
            f"stderr={stderr[-4000:]!r}"
        )
    return {
        "status": "pass",
        "rscript": str(rscript),
        "preflight_script": portable_path(R_PREFLIGHT_SCRIPT, root=ROOT),
        "preflight_script_sha256": file_sha256(R_PREFLIGHT_SCRIPT),
        "r_libs_user": environment.get("R_LIBS_USER", ""),
        "stdout": stdout,
        "stderr_tail": stderr[-2000:],
    }


def _stable_seed(election_id: str, scenario_id: str) -> int:
    payload = f"{BASE_SEED}|{SPEC_VERSION}|{ENGINE_VERSION}|{scenario_id}|{election_id}"
    value = int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")
    return value % (2**31 - 1) or 1


def _model_ready_inputs(panel_id: str, scenarios: tuple[str, ...]) -> list[Path]:
    paths: list[Path] = []
    for scenario_id in scenarios:
        expected = EXPECTED_ELECTIONS[scenario_id]
        selected = sorted(
            (OUTPUT_DIR / "model_ready").glob(
                f"*__{scenario_id}__{panel_id}__n2000.csv"
            )
        )
        if len(selected) != expected:
            raise AssertionError(
                f"expected {expected} {scenario_id} model-ready CSV files; found {len(selected)}"
            )
        paths.extend(selected)
    return paths


def _read_manifest(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _manifest_is_reusable(path: Path, input_csv: Path, election_id: str, scenario_id: str) -> bool:
    manifest = _read_manifest(path)
    if manifest is None:
        return False
    output_dir = path.parent
    required_outputs = {
        "commune_latent_summaries_r.csv": 4000,
        "aggregate_summaries_r.csv": 3,
        "parameter_diagnostics_r.csv": None,
    }
    if not all((output_dir / name).is_file() for name in required_outputs):
        return False
    try:
        commune = pd.read_csv(output_dir / "commune_latent_summaries_r.csv", usecols=["unit_id"])
        aggregate = pd.read_csv(output_dir / "aggregate_summaries_r.csv", usecols=["estimand"])
    except (OSError, ValueError, pd.errors.ParserError):
        return False
    return bool(
        manifest.get("status") == "success"
        and manifest.get("model") == "exact_reimplementation_of_pyei_ei_beta_binom_model"
        and manifest.get("election_id") == election_id
        and manifest.get("scenario_id") == scenario_id
        and int(manifest.get("n_communes", -1)) == 2000
        and int(manifest.get("chains", -1)) == CHAINS
        and int(manifest.get("warmup", -1)) == WARMUP
        and int(manifest.get("draws_per_chain", -1)) == DRAWS
        and manifest.get("input_sha256") == file_sha256(input_csv)
        and manifest.get("runner_script_sha256") == file_sha256(R_SCRIPT)
        and len(commune) == 4000
        and len(aggregate) == 3
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
        "schema_version": "longitudinal_r_krt_exact_all_2x2_status_v1",
        "updated_at_utc": _utc_now(),
        "model": "exact_reimplementation_of_pyei_ei_beta_binom_model",
        "engine": "R_NIMBLE",
        "mathematical_identity_with_python_model": True,
        "panel_size": 2000,
        "pairs_expected": 240,
        "base_seed": BASE_SEED,
        "seed_derivation_version": SEED_DERIVATION_VERSION,
        "warmup": WARMUP,
        "draws_per_chain": DRAWS,
        "chains": CHAINS,
        "max_fit_seconds": MAX_FIT_SECONDS,
        "king_lambda": 0.5,
        **fields,
    }
    write_json(STATUS_PATH, payload)


def _wait_for_python_completion() -> None:
    while True:
        watcher = _read_manifest(PYTHON_WATCHER_STATUS) or {}
        watcher_status = str(watcher.get("status", "missing"))
        pipeline_pids = [int(value) for value in watcher.get("pipeline_pids", [])]
        live_pipeline_pids = [pid for pid in pipeline_pids if psutil.pid_exists(pid)]
        if watcher_status in TERMINAL_PYTHON_WATCHER_STATUSES:
            return
        if pipeline_pids and not live_pipeline_pids:
            _write_status(
                status="python_streams_ended_without_terminal_watcher_status",
                python_watcher_status=watcher_status,
            )
            return
        _write_status(
            status="waiting_for_python_240_attempts",
            python_watcher_status=watcher_status,
            live_python_pipeline_pids=live_pipeline_pids,
            policy="R exact starts only after the Python initial and targeted-rerun streams end",
        )
        time.sleep(30)


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
            policy="one exact R fit at a time; never interrupt a Python estimation",
        )
        time.sleep(30)


def run(
    *,
    scenarios: tuple[str, ...],
    force: bool = False,
    dry_run: bool = False,
    wait_for_python: bool = True,
) -> dict[str, object]:
    unknown = sorted(set(scenarios) - set(EXPECTED_ELECTIONS))
    if unknown:
        raise ValueError(f"unknown scenarios: {unknown}")
    panel_manifest = load_longitudinal_panel_manifest()
    panel_id = str(panel_manifest["panel_id"])
    panel_sha256 = str(panel_manifest["panel_sha256"])
    inputs = _model_ready_inputs(panel_id, scenarios)
    expected_pairs = sum(EXPECTED_ELECTIONS[scenario_id] for scenario_id in scenarios)
    if len(inputs) != expected_pairs:
        raise AssertionError(f"expected {expected_pairs} inputs; found {len(inputs)}")
    rscript = _rscript_path()
    missing_libraries = [path for path in R_LIBRARIES if not path.is_dir()]
    if missing_libraries:
        raise FileNotFoundError(f"missing R libraries: {missing_libraries}")
    environment = os.environ.copy()
    environment["R_LIBS_USER"] = os.pathsep.join(
        str(path.resolve()) for path in R_LIBRARIES
    )
    r_preflight = _r_preflight(rscript, environment)
    _write_status(status="r_preflight_pass", r_preflight=r_preflight)
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    plan_rows: list[dict[str, object]] = []
    for sequence, input_csv in enumerate(inputs, start=1):
        election_id, scenario_id = input_csv.name.split("__", maxsplit=2)[:2]
        plan_rows.append(
            {
                "sequence": sequence,
                "panel_id": panel_id,
                "panel_sha256": panel_sha256,
                "election_id": election_id,
                "scenario_id": scenario_id,
                "run_seed": _stable_seed(election_id, scenario_id),
                "input_csv": portable_path(input_csv, root=ROOT),
                "input_sha256": file_sha256(input_csv),
                "output_dir": portable_path(RUN_DIR / f"{election_id}__{scenario_id}", root=ROOT),
                "r_model_script": portable_path(R_SCRIPT, root=ROOT),
                "r_model_script_sha256": file_sha256(R_SCRIPT),
                "chains": CHAINS,
                "warmup": WARMUP,
                "draws_per_chain": DRAWS,
                "max_fit_seconds": MAX_FIT_SECONDS,
                "king_lambda": 0.5,
            }
        )
    pd.DataFrame(plan_rows).to_csv(PLAN_PATH, index=False, encoding="utf-8-sig")
    plan_manifest = {
        "schema_version": "longitudinal_r_krt_exact_plan_v1",
        "created_at_utc": _utc_now(),
        "model": "exact_reimplementation_of_pyei_ei_beta_binom_model",
        "engine": "R_NIMBLE",
        "mathematical_identity_with_python_model": True,
        "panel_id": panel_id,
        "panel_sha256": panel_sha256,
        "pairs_expected": expected_pairs,
        "pairs_planned": len(plan_rows),
        "max_fit_seconds": MAX_FIT_SECONDS,
        "unique_pairs": len({(row["election_id"], row["scenario_id"]) for row in plan_rows}),
        "unique_input_hashes": len({str(row["input_sha256"]) for row in plan_rows}),
        "unique_run_seeds": len({int(row["run_seed"]) for row in plan_rows}),
        "scenario_counts": pd.DataFrame(plan_rows).groupby("scenario_id").size().astype(int).to_dict(),
        "plan_path": portable_path(PLAN_PATH, root=ROOT),
        "plan_sha256": file_sha256(PLAN_PATH),
        "r_model_script": portable_path(R_SCRIPT, root=ROOT),
        "r_model_script_sha256": file_sha256(R_SCRIPT),
        "ready": bool(
            len(plan_rows) == expected_pairs
            and len({(row["election_id"], row["scenario_id"]) for row in plan_rows}) == expected_pairs
            and len({int(row["run_seed"]) for row in plan_rows}) == expected_pairs
        ),
    }
    write_json(PLAN_MANIFEST_PATH, plan_manifest)

    reusable = 0
    for input_csv in inputs:
        election_id, scenario_id = input_csv.name.split("__", maxsplit=2)[:2]
        reusable += int(
            _manifest_is_reusable(
                RUN_DIR / f"{election_id}__{scenario_id}" / "manifest_r.json",
                input_csv,
                election_id,
                scenario_id,
            )
        )
    if dry_run:
        result = {
            "status": "dry_run_pass",
            "panel_id": panel_id,
            "panel_sha256": panel_sha256,
            "scenarios": list(scenarios),
            "pairs_total": expected_pairs,
            "pairs_reusable": reusable,
            "pairs_to_run": expected_pairs - reusable,
            "max_fit_seconds": MAX_FIT_SECONDS,
            "rscript": str(rscript),
            "r_model_script": portable_path(R_SCRIPT, root=ROOT),
            "r_model_script_sha256": file_sha256(R_SCRIPT),
            "plan_path": portable_path(PLAN_PATH, root=ROOT),
            "plan_sha256": file_sha256(PLAN_PATH),
            "plan_manifest_path": portable_path(PLAN_MANIFEST_PATH, root=ROOT),
            "plan_manifest_sha256": file_sha256(PLAN_MANIFEST_PATH),
        }
        _write_status(**result)
        return result

    if wait_for_python:
        _wait_for_python_completion()

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
        reusable = not force and _manifest_is_reusable(
            manifest_path, input_csv, election_id, scenario_id
        )
        status = "skipped_existing_success" if reusable else "pending"
        error = ""
        seed = _stable_seed(election_id, scenario_id)
        if not reusable:
            _wait_for_memory(sequence, expected_pairs, election_id, scenario_id)
            _write_status(
                status="running",
                sequence=sequence,
                pairs_total=expected_pairs,
                election_id=election_id,
                scenario_id=scenario_id,
                run_seed=seed,
                memory=_memory_snapshot(),
            )
            started = time.perf_counter()
            timeout_error = ""
            with (output_dir / "runner_stdout.log").open("w", encoding="utf-8") as stdout, (
                output_dir / "runner_stderr.log"
            ).open("w", encoding="utf-8") as stderr:
                try:
                    completed = subprocess.run(
                        [
                            str(rscript),
                            str(R_SCRIPT),
                            str(input_csv),
                            str(output_dir),
                            str(seed),
                            str(WARMUP),
                            str(DRAWS),
                            str(CHAINS),
                            "2000",
                        ],
                        cwd=ROOT,
                        env=environment,
                        stdout=stdout,
                        stderr=stderr,
                        text=True,
                        check=False,
                        timeout=MAX_FIT_SECONDS,
                    )
                except subprocess.TimeoutExpired:
                    completed = None
                    timeout_error = (
                        f"R/NIMBLE fit exceeded the {MAX_FIT_SECONDS}-second ceiling; "
                        "the pair was recorded as failed and the queue continued."
                    )
            elapsed_seconds = time.perf_counter() - started
            if completed is not None and completed.returncode == 0 and _manifest_is_reusable(
                manifest_path, input_csv, election_id, scenario_id
            ):
                status = "success"
            else:
                status = "failed"
                stderr_tail = (output_dir / "runner_stderr.log").read_text(
                    encoding="utf-8", errors="replace"
                )[-8000:]
                error = "\n".join(part for part in (timeout_error, stderr_tail) if part)
        else:
            elapsed_seconds = 0.0

        row = {
            "sequence": sequence,
            "panel_id": panel_id,
            "panel_sha256": panel_sha256,
            "election_id": election_id,
            "scenario_id": scenario_id,
            "status": status,
            "error": error,
            "run_seed": seed,
            "elapsed_seconds": elapsed_seconds,
            "input_csv": portable_path(input_csv, root=ROOT),
            "input_sha256": file_sha256(input_csv),
            "output_dir": portable_path(output_dir, root=ROOT),
            "model": "exact_reimplementation_of_pyei_ei_beta_binom_model",
            "engine": "R_NIMBLE",
            "mathematical_identity_with_python_model": True,
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
    try:
        from .consolidate_r_krt_exact_all_2x2 import consolidate

        result["consolidation"] = consolidate()
    except Exception as exc:  # keep the resumable run ledger even if post-processing fails
        result["consolidation_error"] = f"{type(exc).__name__}: {exc}"
    try:
        from .compare_python_r_krt_exact_all_2x2 import compare

        result["comparison"] = compare()
    except Exception as exc:  # comparison is allowed to remain partial or pending
        result["comparison_error"] = f"{type(exc).__name__}: {exc}"
    _write_status(**result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the exact King99 beta-binomial model for all 240 2x2 pairs in R/NIMBLE."
    )
    parser.add_argument("--scenarios", nargs="+", default=list(DEFAULT_SCENARIOS))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-wait-for-python", action="store_true")
    args = parser.parse_args()
    with _keep_system_awake():
        result = run(
            scenarios=tuple(args.scenarios),
            force=args.force,
            dry_run=args.dry_run,
            wait_for_python=not args.no_wait_for_python,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
