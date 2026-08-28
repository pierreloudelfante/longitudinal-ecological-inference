from __future__ import annotations

"""Resumable, non-destructive NLS V2 runner for 2x2 hypotheses.

The default command only writes an auditable execution plan. Optimisation is
started only with ``--execute``. All fit attempts, current-state pointers,
progress tables and audit summaries live under ``outputs/v2/nls_priority``.
Existing historical run directories are never read as resume state and are
never modified.
"""

import argparse
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from .build_common_panel_v2 import COMMON_ELECTION_IDS, DEFAULT_OUTPUT as DEFAULT_PANEL
from .build_panel import load_settings
from .nls import NLSData, aggregate_probabilities, fit_nls, probabilities, sandwich_standard_errors, unpack_params
from .paths import OUTPUT_DIR, ROOT
from .prepare_inputs import model_ready_path, prepare_model_ready, x_columns, y_columns
from .spec_registry import ELECTIONS, ELECTION_BY_ID, SCENARIOS, SCENARIO_BY_ID, scenario_is_allowed
from .utils import canonical_hash, file_sha256


PRIORITY_ELECTIONS = COMMON_ELECTION_IDS
PRIORITY_SCENARIOS = ("H0A", "H1", "H2", "H4")
MODEL_KEY = "rosen_nls_2x2_unadjusted"
ALGORITHM_VERSION = "nls_priority_v2.0"
DEFAULT_OUTPUT_ROOT = OUTPUT_DIR / "v2" / "nls_priority"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def priority_scope() -> list[tuple[str, str]]:
    """Return the required 4-hypothesis by 3-period priority cross-product."""

    return [
        (election_id, scenario_id)
        for scenario_id in PRIORITY_SCENARIOS
        for election_id in PRIORITY_ELECTIONS
    ]


def full_series_scope() -> list[tuple[str, str]]:
    """Return every registry-authorised 2x2 hypothesis/election pair."""

    return [
        (election.election_id, scenario.scenario_id)
        for election in ELECTIONS
        for scenario in SCENARIOS
        if scenario.model_family == "2x2" and scenario_is_allowed(scenario, election)
    ]


def validate_common_panel(panel_path: Path, *, expected_size: int = 3000) -> dict[str, Any]:
    """Validate the immutable common panel contract used by priority fits."""

    panel_path = Path(panel_path).resolve()
    if not panel_path.exists():
        raise FileNotFoundError(f"common panel does not exist: {panel_path}")
    panel = pd.read_csv(panel_path, dtype={"unit_id": "string", "sample_id": "string"}, low_memory=False)
    required = {"unit_id", "sample_id", "sample_rank"}
    missing = required - set(panel.columns)
    if missing:
        raise ValueError(f"common panel lacks columns: {sorted(missing)}")
    if len(panel) != expected_size:
        raise ValueError(f"common panel has {len(panel)} rows, expected exactly {expected_size}")
    if panel["unit_id"].isna().any() or panel["unit_id"].duplicated().any():
        raise ValueError("common panel unit_id values must be complete and unique")
    if panel["sample_rank"].isna().any() or panel["sample_rank"].duplicated().any():
        raise ValueError("common panel sample_rank values must be complete and unique")
    sample_ids = panel["sample_id"].dropna().astype(str).unique()
    if len(sample_ids) != 1:
        raise ValueError("common panel must contain exactly one sample_id")
    return {
        "path": str(panel_path),
        "sha256": file_sha256(panel_path),
        "sample_id": str(sample_ids[0]),
        "sample_size": int(len(panel)),
        "unit_ids": panel.sort_values("sample_rank")["unit_id"].astype(str).tolist(),
    }


def build_plan(
    *,
    full_series: bool = False,
    panel_path: Path = DEFAULT_PANEL,
    panel_sha256: str | None = None,
    settings: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """Build a deterministic execution plan without preparing or fitting data."""

    panel_path = Path(panel_path).resolve()
    if panel_sha256 is None:
        panel_sha256 = file_sha256(panel_path)
    if settings is None:
        settings = load_settings()["nls"]
    scope = full_series_scope() if full_series else priority_scope()
    scope_name = "full_series" if full_series else "priority_three_periods"
    rows: list[dict[str, Any]] = []
    for index, (election_id, scenario_id) in enumerate(scope, start=1):
        election = ELECTION_BY_ID[election_id]
        scenario = SCENARIO_BY_ID[scenario_id]
        key_payload = {
            "algorithm_version": ALGORITHM_VERSION,
            "election_id": election_id,
            "scenario_id": scenario_id,
            "model_key": MODEL_KEY,
            "sample_size": 3000,
            "panel_sha256": panel_sha256,
            "nls_settings": dict(settings),
        }
        rows.append(
            {
                "plan_index": index,
                "scope": scope_name,
                "election_id": election_id,
                "election_type": election.election_type,
                "year": election.year,
                "round": election.round,
                "scenario_id": scenario_id,
                "model_key": MODEL_KEY,
                "sample_size": 3000,
                "panel_path": str(panel_path),
                "panel_sha256": panel_sha256,
                "require_exact_3000": not full_series,
                "run_key": canonical_hash(key_payload),
                "planned_status": "pending",
            }
        )
    plan = pd.DataFrame(rows)
    if plan.duplicated(["election_id", "scenario_id"]).any():
        raise AssertionError("NLS V2 plan contains duplicate election/scenario pairs")
    return plan


def resume_decision(current: Mapping[str, Any] | None, *, retry_running: bool = False) -> str:
    """Return ``run``, ``skip_success`` or ``skip_running`` for one plan item."""

    if not current:
        return "run"
    status = str(current.get("status", ""))
    if status == "success":
        artifact = current.get("attempt_manifest")
        if artifact and Path(str(artifact)).exists():
            return "skip_success"
        return "run"
    if status == "running" and not retry_running:
        return "skip_running"
    return "run"


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    frame.to_csv(temporary, index=False, encoding="utf-8-sig")
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _diagnostic_status(success: bool, rank: int, n_parameters: int, condition: float) -> str:
    if not success or not np.isfinite(condition) or condition > 1e12:
        return "fail"
    if rank < n_parameters or condition > 1e8:
        return "warning"
    return "pass"


def _load_or_prepare_frame(
    row: Mapping[str, Any],
    *,
    panel_meta: Mapping[str, Any],
    prepare_missing: bool,
) -> tuple[pd.DataFrame, Path]:
    election = ELECTION_BY_ID[str(row["election_id"])]
    scenario = SCENARIO_BY_ID[str(row["scenario_id"])]
    input_path = model_ready_path(
        election,
        scenario,
        str(panel_meta["sample_id"]),
        sample_size=int(row["sample_size"]),
    )
    if not input_path.exists():
        if not prepare_missing:
            raise FileNotFoundError(
                f"model-ready input is missing: {input_path}; prepare it first or use --prepare-missing"
            )
        frame, _, _ = prepare_model_ready(
            election,
            scenario,
            sample_size=int(row["sample_size"]),
            panel_path=Path(str(panel_meta["path"])),
        )
    else:
        frame = pd.read_parquet(input_path)
    frame = frame.sort_values("sample_rank").reset_index(drop=True)
    if frame["unit_id"].astype(str).duplicated().any():
        raise ValueError(f"{row['election_id']}/{row['scenario_id']}: duplicate model-ready unit_id")
    if bool(row["require_exact_3000"]):
        actual_ids = frame["unit_id"].astype(str).tolist()
        if len(frame) != 3000 or actual_ids != list(panel_meta["unit_ids"]):
            raise ValueError(
                f"{row['election_id']}/{row['scenario_id']}: priority input is not the exact ordered 3,000-unit common panel"
            )
    return frame, input_path


def _fit_one(
    row: Mapping[str, Any],
    *,
    panel_meta: Mapping[str, Any],
    settings: Mapping[str, Any],
    output_root: Path,
    prepare_missing: bool,
) -> dict[str, Any]:
    run_key = str(row["run_key"])
    stable_dir = output_root / "runs" / run_key[:16]
    attempt_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    attempt_dir = stable_dir / "attempts" / attempt_id
    attempt_dir.mkdir(parents=True, exist_ok=False)
    attempt_manifest = attempt_dir / "manifest.json"
    current_path = stable_dir / "current.json"
    started_at = utc_now()
    started = time.perf_counter()
    running = {
        "schema_version": ALGORITHM_VERSION,
        "status": "running",
        "run_key": run_key,
        "attempt_id": attempt_id,
        "attempt_manifest": str(attempt_manifest),
        "started_at_utc": started_at,
        "election_id": row["election_id"],
        "scenario_id": row["scenario_id"],
        "model_key": MODEL_KEY,
    }
    _atomic_json(attempt_manifest, running)
    _atomic_json(current_path, running)
    try:
        frame, input_path = _load_or_prepare_frame(
            row, panel_meta=panel_meta, prepare_missing=prepare_missing
        )
        scenario = SCENARIO_BY_ID[str(row["scenario_id"])]
        x = frame.loc[:, list(x_columns(scenario))].to_numpy(dtype=float)
        n = frame["N_g"].to_numpy(dtype=float)
        y = frame.loc[:, list(y_columns(scenario))].to_numpy(dtype=float)
        t = y / n[:, None]
        z = np.empty((len(frame), 0), dtype=float)
        data = NLSData(x=x, t=t, n=n, z=z)
        best, starts = fit_nls(
            data,
            n_starts=int(settings["n_starts"]),
            start_scale=float(settings["start_scale"]),
            n_start_strata=int(settings["n_start_strata"]),
            max_nfev=int(settings["max_nfev"]),
            tolerance=float(settings["tolerance"]),
            random_seed=int(settings["random_seed"]),
        )
        pi, fitted = probabilities(best.x, x, z, t.shape[1])
        aggregates = aggregate_probabilities(x, n, pi)
        standard_errors, sandwich = sandwich_standard_errors(best.x, data)
        condition = float(sandwich["bread_condition"])
        rank = int(sandwich["bread_rank"])
        diagnostic_status = _diagnostic_status(bool(best.success), rank, int(best.x.size), condition)
        elapsed = time.perf_counter() - started

        estimate_rows: list[dict[str, Any]] = []
        for group_index, group in enumerate(scenario.social_groups):
            for vote_index, vote in enumerate(scenario.vote_categories):
                estimate_rows.append(
                    {
                        "run_key": run_key,
                        "attempt_id": attempt_id,
                        "sample_id": panel_meta["sample_id"],
                        "election_id": row["election_id"],
                        "scenario_id": row["scenario_id"],
                        "model_key": MODEL_KEY,
                        "social_group": group,
                        "vote_category": vote,
                        "estimate": float(aggregates[group_index, vote_index]),
                        "n_communes": len(frame),
                        "N_total": int(n.sum()),
                        "diagnostic_status": diagnostic_status,
                    }
                )
        estimates = pd.DataFrame(estimate_rows)

        coefficients = unpack_params(best.x, x.shape[1], t.shape[1], 1)
        coefficient_se = unpack_params(standard_errors, x.shape[1], t.shape[1], 1)
        coefficient_rows: list[dict[str, Any]] = []
        for group_index, group in enumerate(scenario.social_groups):
            for vote_index, vote in enumerate(scenario.vote_categories[:-1]):
                coefficient_rows.append(
                    {
                        "run_key": run_key,
                        "attempt_id": attempt_id,
                        "election_id": row["election_id"],
                        "scenario_id": row["scenario_id"],
                        "social_group": group,
                        "vote_category": vote,
                        "reference_vote_category": scenario.vote_categories[-1],
                        "term": "alpha",
                        "estimate": float(coefficients[group_index, vote_index, 0]),
                        "std_error": float(coefficient_se[group_index, vote_index, 0]),
                    }
                )
        coefficient_frame = pd.DataFrame(coefficient_rows)
        start_frame = pd.DataFrame(starts)
        start_frame.insert(0, "run_key", run_key)
        start_frame.insert(1, "attempt_id", attempt_id)
        diagnostics = pd.DataFrame(
            [
                {
                    "run_key": run_key,
                    "attempt_id": attempt_id,
                    "election_id": row["election_id"],
                    "scenario_id": row["scenario_id"],
                    "n_communes": len(frame),
                    "N_total": int(n.sum()),
                    "elapsed_seconds": elapsed,
                    "objective_sse_unweighted": float(np.sum((t[:, :-1] - fitted[:, :-1]) ** 2)),
                    "optimizer_success": bool(best.success),
                    "optimizer_status": int(best.status),
                    "optimizer_message": str(best.message),
                    "nfev": int(best.nfev),
                    "optimality": float(best.optimality),
                    "n_parameters": int(best.x.size),
                    "n_starts": len(starts),
                    "n_successful_starts": int(sum(bool(item["success"]) for item in starts)),
                    "diagnostic_status": diagnostic_status,
                    **sandwich,
                }
            ]
        )
        estimates.to_csv(attempt_dir / "estimates.csv", index=False, encoding="utf-8-sig")
        coefficient_frame.to_csv(attempt_dir / "coefficients.csv", index=False, encoding="utf-8-sig")
        start_frame.to_csv(attempt_dir / "start_diagnostics.csv", index=False, encoding="utf-8-sig")
        diagnostics.to_csv(attempt_dir / "model_diagnostics.csv", index=False, encoding="utf-8-sig")
        completed = {
            **running,
            "status": "success",
            "finished_at_utc": utc_now(),
            "elapsed_seconds": elapsed,
            "fit_status": "success" if bool(best.success) else "warning",
            "diagnostic_status": diagnostic_status,
            "n_communes": len(frame),
            "N_total": int(n.sum()),
            "input_path": str(input_path),
            "input_sha256": file_sha256(input_path),
            "panel_path": panel_meta["path"],
            "panel_sha256": panel_meta["sha256"],
            "nls_settings": dict(settings),
            "outputs": {
                "estimates": str(attempt_dir / "estimates.csv"),
                "coefficients": str(attempt_dir / "coefficients.csv"),
                "start_diagnostics": str(attempt_dir / "start_diagnostics.csv"),
                "model_diagnostics": str(attempt_dir / "model_diagnostics.csv"),
            },
        }
        _atomic_json(attempt_manifest, completed)
        _atomic_json(current_path, completed)
        return completed
    except Exception as exc:
        failed = {
            **running,
            "status": "failed",
            "finished_at_utc": utc_now(),
            "elapsed_seconds": time.perf_counter() - started,
            "error": f"{type(exc).__name__}: {exc}",
        }
        _atomic_json(attempt_manifest, failed)
        _atomic_json(current_path, failed)
        return failed


def _filter_plan(
    plan: pd.DataFrame,
    *,
    elections: Iterable[str],
    scenarios: Iterable[str],
    max_runs: int | None,
) -> pd.DataFrame:
    selected = plan.copy()
    election_filter = set(elections)
    scenario_filter = set(scenarios)
    if election_filter:
        unknown = election_filter - set(selected["election_id"])
        if unknown:
            raise ValueError(f"elections outside selected scope: {sorted(unknown)}")
        selected = selected.loc[selected["election_id"].isin(election_filter)]
    if scenario_filter:
        unknown = scenario_filter - set(selected["scenario_id"])
        if unknown:
            raise ValueError(f"scenarios outside selected scope: {sorted(unknown)}")
        selected = selected.loc[selected["scenario_id"].isin(scenario_filter)]
    if max_runs is not None:
        if max_runs <= 0:
            raise ValueError("max_runs must be positive")
        selected = selected.head(max_runs)
    return selected.reset_index(drop=True)


def execute_plan(
    plan: pd.DataFrame,
    *,
    panel_meta: Mapping[str, Any],
    settings: Mapping[str, Any],
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    prepare_missing: bool = False,
    retry_running: bool = False,
    fail_fast: bool = False,
) -> pd.DataFrame:
    """Execute or resume a selected plan, preserving every attempt directory."""

    output_root = Path(output_root)
    progress_path = output_root / "progress.csv"
    progress_rows: list[dict[str, Any]] = []
    for _, row in plan.iterrows():
        stable_dir = output_root / "runs" / str(row["run_key"])[:16]
        current = _read_json(stable_dir / "current.json")
        if current and current.get("run_key") not in (None, row["run_key"]):
            raise RuntimeError(
                f"run-key prefix collision in {stable_dir}: "
                f"{current.get('run_key')} != {row['run_key']}"
            )
        decision = resume_decision(current, retry_running=retry_running)
        if decision != "run":
            result = {
                "status": decision,
                "run_key": row["run_key"],
                "election_id": row["election_id"],
                "scenario_id": row["scenario_id"],
                "attempt_manifest": current.get("attempt_manifest", "") if current else "",
                "elapsed_seconds": 0.0,
            }
        else:
            result = _fit_one(
                row,
                panel_meta=panel_meta,
                settings=settings,
                output_root=output_root,
                prepare_missing=prepare_missing,
            )
        progress_rows.append(
            {
                "plan_index": row["plan_index"],
                "scope": row["scope"],
                "election_id": row["election_id"],
                "scenario_id": row["scenario_id"],
                "run_key": row["run_key"],
                "status": result.get("status", "unknown"),
                "diagnostic_status": result.get("diagnostic_status", ""),
                "n_communes": result.get("n_communes", ""),
                "elapsed_seconds": result.get("elapsed_seconds", ""),
                "attempt_manifest": result.get("attempt_manifest", ""),
                "error": result.get("error", ""),
                "updated_at_utc": utc_now(),
            }
        )
        _atomic_csv(progress_path, pd.DataFrame(progress_rows))
        if fail_fast and result.get("status") == "failed":
            break
    return pd.DataFrame(progress_rows)


def _write_audit(
    *,
    output_root: Path,
    plan: pd.DataFrame,
    panel_meta: Mapping[str, Any],
    executed: bool,
    progress: pd.DataFrame | None = None,
) -> None:
    counts = progress["status"].value_counts().to_dict() if progress is not None and not progress.empty else {}
    _atomic_json(
        output_root / "audit.json",
        {
            "schema_version": ALGORITHM_VERSION,
            "created_at_utc": utc_now(),
            "scope": str(plan["scope"].iloc[0]) if len(plan) else "empty",
            "fits_in_selected_plan": int(len(plan)),
            "executed": executed,
            "status_counts": counts,
            "panel_path": panel_meta["path"],
            "panel_sha256": panel_meta["sha256"],
            "panel_sample_id": panel_meta["sample_id"],
            "panel_size": panel_meta["sample_size"],
            "historical_outputs_modified": False,
        },
    )


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan or execute intercept-only NLS V2 fits.")
    parser.add_argument("--full-series", action="store_true", help="Plan all authorised 2x2 election/scenario pairs.")
    parser.add_argument("--execute", action="store_true", help="Run optimisation; omitted means plan-only.")
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--election", action="append", default=[])
    parser.add_argument("--scenario", action="append", default=[])
    parser.add_argument("--max-runs", type=int)
    parser.add_argument("--prepare-missing", action="store_true")
    parser.add_argument("--retry-running", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    panel_meta = validate_common_panel(args.panel)
    settings = load_settings()["nls"]
    plan = build_plan(
        full_series=args.full_series,
        panel_path=args.panel,
        panel_sha256=str(panel_meta["sha256"]),
        settings=settings,
    )
    plan = _filter_plan(
        plan,
        elections=args.election,
        scenarios=args.scenario,
        max_runs=args.max_runs,
    )
    output_root = args.output_root if args.output_root.is_absolute() else ROOT / args.output_root
    output_root.mkdir(parents=True, exist_ok=True)
    plan_name = "plan_full_series.csv" if args.full_series else "plan_priority.csv"
    _atomic_csv(output_root / plan_name, plan)
    progress: pd.DataFrame | None = None
    if args.execute:
        progress = execute_plan(
            plan,
            panel_meta=panel_meta,
            settings=settings,
            output_root=output_root,
            prepare_missing=args.prepare_missing,
            retry_running=args.retry_running,
            fail_fast=args.fail_fast,
        )
    _write_audit(
        output_root=output_root,
        plan=plan,
        panel_meta=panel_meta,
        executed=args.execute,
        progress=progress,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
