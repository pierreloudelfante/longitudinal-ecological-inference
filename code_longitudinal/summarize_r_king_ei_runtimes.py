from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .paths import ROOT


R_OUTPUT = ROOT / "outputs" / "longitudinal_2000_v1" / "r_replication"
RUN_ROOT = R_OUTPUT / "king_ei_runs"
EXPECTED_RUNS = {
    "H0A": 26,
    "H1": 26,
    "H0B": 26,
    "H0C": 26,
    "H2": 26,
    "H3": 26,
    "H4": 26,
    "H5": 26,
    "H6": 16,
    "H7": 16,
}
SCENARIO_ORDER = ("H0A", "H1", "H0B", "H0C", "H2", "H3", "H4", "H5", "H6", "H7")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_runs(scenarios: tuple[str, ...]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for path in sorted(RUN_ROOT.glob("*/manifest_r.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("status") != "success":
            continue
        scenario_id = str(manifest.get("scenario_id", ""))
        if scenario_id not in scenarios:
            continue
        rows.append(
            {
                "model_family": "king_ei_r_classical",
                "model": manifest.get("model"),
                "scenario_id": scenario_id,
                "election_id": str(manifest.get("election_id", "")),
                "n_communes": int(manifest.get("n_communes", 0)),
                "elapsed_seconds": float(manifest.get("elapsed_seconds", np.nan)),
                "started_at_utc": manifest.get("started_at_utc"),
                "finished_at_utc": manifest.get("finished_at_utc"),
                "hessian_condition_number": float(
                    manifest.get("hessian_condition_number", np.nan)
                ),
                "resampling_batches": int(manifest.get("resampling_batches", 0)),
                "native_importance_draws": int(manifest.get("native_importance_draws", 0)),
                "run_seed": int(manifest.get("seed", 0)),
                "manifest_path": path.relative_to(ROOT).as_posix(),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise AssertionError("no successful R King EI run manifest was found")
    if frame.duplicated(["scenario_id", "election_id"]).any():
        raise AssertionError("duplicate successful R King EI run manifests")
    frame["started_at_utc"] = pd.to_datetime(frame["started_at_utc"], utc=True, errors="coerce")
    frame["finished_at_utc"] = pd.to_datetime(frame["finished_at_utc"], utc=True, errors="coerce")
    if not np.isfinite(frame["elapsed_seconds"]).all() or (frame["elapsed_seconds"] <= 0).any():
        raise AssertionError("invalid R King EI elapsed time")
    order = {scenario_id: index for index, scenario_id in enumerate(scenarios)}
    return frame.sort_values(
        ["scenario_id", "election_id"],
        key=lambda values: values.map(order) if values.name == "scenario_id" else values,
    ).reset_index(drop=True)


def _summarize(runs: pd.DataFrame, scenarios: tuple[str, ...]) -> pd.DataFrame:
    global_median = float(runs["elapsed_seconds"].median())
    rows: list[dict[str, object]] = []
    for scenario_id in scenarios:
        subset = runs.loc[runs["scenario_id"].eq(scenario_id)]
        completed = len(subset)
        expected = EXPECTED_RUNS[scenario_id]
        cumulative = float(subset["elapsed_seconds"].sum()) if completed else 0.0
        first_start = subset["started_at_utc"].min() if completed else pd.NaT
        last_finish = subset["finished_at_utc"].max() if completed else pd.NaT
        wall_seconds = (
            float((last_finish - first_start).total_seconds())
            if completed and pd.notna(first_start) and pd.notna(last_finish)
            else np.nan
        )
        remaining = expected - completed
        rows.append(
            {
                "model_family": "king_ei_r_classical",
                "scenario_id": scenario_id,
                "expected_runs": expected,
                "completed_runs": completed,
                "remaining_runs": remaining,
                "completion_fraction": completed / expected,
                "cumulative_elapsed_seconds": cumulative,
                "cumulative_elapsed_minutes": cumulative / 60,
                "mean_elapsed_seconds": float(subset["elapsed_seconds"].mean()) if completed else np.nan,
                "median_elapsed_seconds": float(subset["elapsed_seconds"].median()) if completed else np.nan,
                "min_elapsed_seconds": float(subset["elapsed_seconds"].min()) if completed else np.nan,
                "max_elapsed_seconds": float(subset["elapsed_seconds"].max()) if completed else np.nan,
                "first_started_at_utc": first_start,
                "last_finished_at_utc": last_finish,
                "observed_wall_window_seconds": wall_seconds,
                "projection_seconds_per_remaining_run": global_median,
                "projected_remaining_seconds": remaining * global_median,
                "projected_total_seconds": cumulative + remaining * global_median,
                "projection_status": "actual_complete" if remaining == 0 else "projection_from_global_completed_median",
            }
        )

    expected_total = sum(EXPECTED_RUNS[item] for item in scenarios)
    completed_total = len(runs)
    cumulative_total = float(runs["elapsed_seconds"].sum())
    remaining_total = expected_total - completed_total
    first_start = runs["started_at_utc"].min()
    last_finish = runs["finished_at_utc"].max()
    rows.append(
        {
            "model_family": "king_ei_r_classical",
            "scenario_id": "ALL",
            "expected_runs": expected_total,
            "completed_runs": completed_total,
            "remaining_runs": remaining_total,
            "completion_fraction": completed_total / expected_total,
            "cumulative_elapsed_seconds": cumulative_total,
            "cumulative_elapsed_minutes": cumulative_total / 60,
            "mean_elapsed_seconds": float(runs["elapsed_seconds"].mean()),
            "median_elapsed_seconds": global_median,
            "min_elapsed_seconds": float(runs["elapsed_seconds"].min()),
            "max_elapsed_seconds": float(runs["elapsed_seconds"].max()),
            "first_started_at_utc": first_start,
            "last_finished_at_utc": last_finish,
            "observed_wall_window_seconds": float((last_finish - first_start).total_seconds()),
            "projection_seconds_per_remaining_run": global_median,
            "projected_remaining_seconds": remaining_total * global_median,
            "projected_total_seconds": cumulative_total + remaining_total * global_median,
            "projection_status": "actual_complete" if remaining_total == 0 else "projection_from_global_completed_median",
        }
    )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize observed R King EI runtimes.")
    parser.add_argument("--scenarios", nargs="+", default=list(SCENARIO_ORDER))
    args = parser.parse_args()
    scenarios = tuple(args.scenarios)
    unknown = sorted(set(scenarios) - set(EXPECTED_RUNS))
    if unknown:
        raise ValueError(f"unknown scenarios: {unknown}")
    runs = _load_runs(scenarios)
    summary = _summarize(runs, scenarios)
    run_parquet = R_OUTPUT / "king_ei_r_runtime_by_run.parquet"
    summary_parquet = R_OUTPUT / "king_ei_r_runtime_by_hypothesis.parquet"
    run_csv = R_OUTPUT / "king_ei_r_runtime_by_run.csv"
    summary_csv = R_OUTPUT / "king_ei_r_runtime_by_hypothesis.csv"
    runs.to_parquet(run_parquet, index=False)
    summary.to_parquet(summary_parquet, index=False)
    runs.to_csv(run_csv, index=False)
    summary.to_csv(summary_csv, index=False)
    all_row = summary.loc[summary["scenario_id"].eq("ALL")].iloc[0]
    manifest = {
        "schema_version": "longitudinal_r_king_ei_runtime_summary_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_family": "king_ei_r_classical",
        "scope_scenarios": list(scenarios),
        "expected_runs_scope": int(all_row["expected_runs"]),
        "completed_runs": int(all_row["completed_runs"]),
        "remaining_runs": int(all_row["remaining_runs"]),
        "observed_cumulative_seconds": float(all_row["cumulative_elapsed_seconds"]),
        "projected_total_seconds": float(all_row["projected_total_seconds"]),
        "projection_basis": all_row["projection_status"],
        "outputs": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in (run_parquet, summary_parquet, run_csv, summary_csv)
        ],
    }
    manifest_path = R_OUTPUT / "king_ei_r_runtime_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
