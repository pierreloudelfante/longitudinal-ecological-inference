from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .paths import OUTPUT_DIR, ROOT, RUNS_DIR
from .build_longitudinal_panel import load_longitudinal_panel_manifest
from .spec_registry import SPEC_VERSION
from .utils import file_sha256, portable_path, write_json


REPLICATION_DIR = OUTPUT_DIR / SPEC_VERSION / "r_replication"
R_COMMUNE_PATH = REPLICATION_DIR / "longitudinal_king_ei_r_commune_retained6.parquet"
R_AGGREGATE_PATH = REPLICATION_DIR / "longitudinal_king_ei_r_aggregate_retained6.parquet"
PYTHON_FINAL_DIR = OUTPUT_DIR / SPEC_VERSION / "final" / "longitudinal_2000_v1.0.2_H0A_H1"
AGGREGATE_COMPARISON_PATH = REPLICATION_DIR / "king_python_r_retained6_aggregate_comparison.parquet"
COMMUNE_SUMMARY_PATH = REPLICATION_DIR / "king_python_r_retained6_commune_summary.parquet"
SELECTION_AUDIT_PATH = REPLICATION_DIR / "king_python_r_retained6_python_selection.csv"
MANIFEST_PATH = REPLICATION_DIR / "king_python_r_retained6_comparison_manifest.json"
RETAINED_SCENARIOS = ("H0A", "H1", "H0B", "H0C", "H2", "H3")
EXPECTED_PAIR_COUNT = 26 * len(RETAINED_SCENARIOS)
EXPECTED_PANEL_SHA256 = str(load_longitudinal_panel_manifest()["panel_sha256"])

ESTIMAND_MAP = {
    "beta1_aggregate": "b_1",
    "beta2_aggregate": "b_2",
    "contrast_aggregate": "b_1_minus_b_2",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_python_manifest(path: Path) -> dict[str, Any] | None:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    parameters = manifest.get("parameters", {})
    if not isinstance(parameters, dict):
        return None
    if (
        manifest.get("status") != "success"
        or parameters.get("model_key") != "krt_beta_binomial"
        or int(parameters.get("sample_size", 0)) != 2000
        or parameters.get("panel_sha256") != EXPECTED_PANEL_SHA256
    ):
        return None
    required = (
        path.parent / "aggregate_comparison_v2.csv",
        path.parent / "commune_latent_summaries.parquet",
    )
    if not all(item.exists() for item in required):
        return None
    return manifest


def _latest_python_runs() -> dict[tuple[str, str], tuple[Path, dict[str, Any]]]:
    matches: dict[tuple[str, str], tuple[Path, dict[str, Any]]] = {}
    for manifest_path in RUNS_DIR.glob("*/manifest.json"):
        manifest = _valid_python_manifest(manifest_path)
        if manifest is None:
            continue
        parameters = manifest["parameters"]
        key = (str(parameters["election_id"]), str(parameters["scenario_id"]))
        current = matches.get(key)
        finished = str(manifest.get("finished_at_utc", ""))
        if current is None or finished > str(current[1].get("finished_at_utc", "")):
            matches[key] = (manifest_path.parent, manifest)
    return matches


def _preregistered_selected_run_ids() -> dict[tuple[str, str], tuple[str, str]]:
    """Collect explicit selections without inventing a canonical run.

    H2/H3 write a supervisor selection, while the other extension scopes write
    targeted-rerun progress.  Only non-empty selected IDs are authoritative;
    unresolved pairs deliberately fall through to a provisional latest-fit
    comparison.
    """
    selected: dict[tuple[str, str], tuple[str, str]] = {}
    production_root = OUTPUT_DIR / SPEC_VERSION / "production"
    for path in production_root.glob("*/h23_canonical_selection_partial.csv"):
        frame = pd.read_csv(path, dtype="string")
        for row in frame.itertuples(index=False):
            run_id = str(getattr(row, "run_id", "") or "")
            if run_id:
                selected[(str(row.election_id), str(row.scenario_id))] = (
                    run_id,
                    "selected_by_h23_supervisor",
                )
    for path in production_root.glob("*/targeted_rerun_scope_progress.csv"):
        frame = pd.read_csv(path, dtype="string")
        for row in frame.itertuples(index=False):
            run_id = str(getattr(row, "selected_run_id", "") or "")
            if run_id and run_id.lower() != "nan":
                selected[(str(row.election_id), str(row.scenario_id))] = (
                    run_id,
                    "selected_by_targeted_rerun_scope",
                )
    return selected


def _canonical_h0a_h1() -> tuple[pd.DataFrame, pd.DataFrame]:
    aggregate = pd.read_parquet(PYTHON_FINAL_DIR / "longitudinal_krt_aggregate.parquet")
    commune = pd.read_parquet(PYTHON_FINAL_DIR / "longitudinal_krt_commune.parquet")
    if aggregate[["election_id", "scenario_id", "estimand"]].duplicated().any():
        raise AssertionError("duplicate canonical H0A/H1 aggregate key")
    if commune[["election_id", "scenario_id", "unit_id"]].duplicated().any():
        raise AssertionError("duplicate canonical H0A/H1 commune key")
    return aggregate, commune


def _load_python_available(
    r_pairs: set[tuple[str, str]],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    canonical_aggregate, canonical_commune = _canonical_h0a_h1()
    aggregate_parts: list[pd.DataFrame] = []
    commune_parts: list[pd.DataFrame] = []
    selection_rows: list[dict[str, object]] = []
    canonical_pairs = set(
        canonical_aggregate[["election_id", "scenario_id"]].itertuples(index=False, name=None)
    )
    latest = _latest_python_runs()
    by_run_id = {
        str(manifest["run_id"]): (run_dir, manifest)
        for run_dir, manifest in latest.values()
    }
    # A selected strengthened rerun is not necessarily the chronologically
    # latest attempt, so index every valid run by ID as well.
    for manifest_path in RUNS_DIR.glob("*/manifest.json"):
        manifest = _valid_python_manifest(manifest_path)
        if manifest is not None:
            by_run_id[str(manifest["run_id"])] = (manifest_path.parent, manifest)
    selected_ids = _preregistered_selected_run_ids()
    for election_id, scenario_id in sorted(r_pairs):
        key = (election_id, scenario_id)
        if key in canonical_pairs:
            aggregate = canonical_aggregate.loc[
                canonical_aggregate["election_id"].eq(election_id)
                & canonical_aggregate["scenario_id"].eq(scenario_id)
            ].copy()
            commune = canonical_commune.loc[
                canonical_commune["election_id"].eq(election_id)
                & canonical_commune["scenario_id"].eq(scenario_id)
            ].copy()
            run_id = str(aggregate["run_id"].iloc[0])
            selection_status = "canonical_v1.0.2"
            mcmc_status = str(aggregate["mcmc_status"].iloc[0])
            identification_status = str(aggregate["identification_status"].iloc[0])
        elif key in selected_ids and selected_ids[key][0] in by_run_id:
            selected_run_id, selection_status = selected_ids[key]
            run_dir, manifest = by_run_id[selected_run_id]
            raw = pd.read_csv(run_dir / "aggregate_comparison_v2.csv")
            aggregate = raw.loc[
                raw["aggregation_method"].eq("group_specific_population_v2")
            ].copy()
            aggregate = aggregate.rename(columns={"beta_parameter": "estimand"})
            aggregate["election_id"] = election_id
            aggregate["scenario_id"] = scenario_id
            aggregate["run_id"] = str(manifest["run_id"])
            diagnostic = manifest.get("canonical_mcmc_diagnostic", {})
            aggregate["mcmc_status"] = str(diagnostic.get("mcmc_status", manifest.get("diagnostic_status", "unknown")))
            aggregate["identification_status"] = str(
                manifest.get("identification_diagnostic", {}).get("identification_status", "unknown")
            )
            commune = pd.read_parquet(run_dir / "commune_latent_summaries.parquet")
            commune["election_id"] = election_id
            commune["scenario_id"] = scenario_id
            commune["run_id"] = str(manifest["run_id"])
            run_id = str(manifest["run_id"])
            mcmc_status = str(aggregate["mcmc_status"].iloc[0])
            identification_status = str(aggregate["identification_status"].iloc[0])
        elif key in latest:
            run_dir, manifest = latest[key]
            raw = pd.read_csv(run_dir / "aggregate_comparison_v2.csv")
            aggregate = raw.loc[
                raw["aggregation_method"].eq("group_specific_population_v2")
            ].copy()
            aggregate = aggregate.rename(columns={"beta_parameter": "estimand"})
            aggregate["election_id"] = election_id
            aggregate["scenario_id"] = scenario_id
            aggregate["run_id"] = str(manifest["run_id"])
            diagnostic = manifest.get("canonical_mcmc_diagnostic", {})
            aggregate["mcmc_status"] = str(diagnostic.get("mcmc_status", manifest.get("diagnostic_status", "unknown")))
            aggregate["identification_status"] = str(
                manifest.get("identification_diagnostic", {}).get("identification_status", "unknown")
            )
            commune = pd.read_parquet(run_dir / "commune_latent_summaries.parquet")
            commune["election_id"] = election_id
            commune["scenario_id"] = scenario_id
            commune["run_id"] = str(manifest["run_id"])
            run_id = str(manifest["run_id"])
            selection_status = "latest_completed_fit_provisional"
            mcmc_status = str(aggregate["mcmc_status"].iloc[0])
            identification_status = str(aggregate["identification_status"].iloc[0])
        else:
            continue
        if len(aggregate) != 3 or len(commune) != 2000:
            raise AssertionError(f"invalid Python output dimensions for {key}")
        aggregate_parts.append(aggregate)
        commune_parts.append(commune)
        selection_rows.append(
            {
                "election_id": election_id,
                "scenario_id": scenario_id,
                "python_run_id": run_id,
                "selection_status": selection_status,
                "mcmc_status": mcmc_status,
                "identification_status": identification_status,
            }
        )
    if not aggregate_parts:
        raise RuntimeError("no Python/R pair overlap is available")
    return (
        pd.concat(aggregate_parts, ignore_index=True),
        pd.concat(commune_parts, ignore_index=True),
        pd.DataFrame(selection_rows),
    )


def compare() -> dict[str, object]:
    r_aggregate = pd.read_parquet(R_AGGREGATE_PATH)
    r_commune = pd.read_parquet(R_COMMUNE_PATH)
    r_pairs = set(r_aggregate[["election_id", "scenario_id"]].itertuples(index=False, name=None))
    py_aggregate, py_commune, selection = _load_python_available(r_pairs)
    selection.to_csv(SELECTION_AUDIT_PATH, index=False, encoding="utf-8-sig")

    r_aggregate = r_aggregate.copy()
    r_aggregate["estimand"] = r_aggregate["estimand"].map(ESTIMAND_MAP)
    r_aggregate = r_aggregate.rename(
        columns={
            "mean": "mean_r_ei",
            "sd": "sd_r_ei",
            "q025": "q025_r_ei",
            "q50": "q50_r_ei",
            "q975": "q975_r_ei",
            "n_posterior_draws": "draws_r_ei",
        }
    )
    py_aggregate = py_aggregate.rename(
        columns={
            "mean": "mean_python_krt",
            "median": "q50_python_krt",
            "q025": "q025_python_krt",
            "q975": "q975_python_krt",
        }
    )
    # Canonical public tables call the posterior median ``median`` whereas
    # per-run aggregate_comparison_v2 files call it ``q50``.  Preserve both
    # interfaces and normalize row-wise after concatenating mixed sources.
    if "q50" in py_aggregate:
        if "q50_python_krt" in py_aggregate:
            py_aggregate["q50_python_krt"] = py_aggregate["q50_python_krt"].combine_first(
                py_aggregate["q50"]
            )
        else:
            py_aggregate = py_aggregate.rename(columns={"q50": "q50_python_krt"})
    py_columns = [
        "election_id", "scenario_id", "estimand", "run_id", "mean_python_krt",
        "q025_python_krt", "q975_python_krt", "mcmc_status", "identification_status",
    ]
    if "q50_python_krt" in py_aggregate:
        py_columns.append("q50_python_krt")
    aggregate = r_aggregate.merge(
        py_aggregate[py_columns],
        on=["election_id", "scenario_id", "estimand"],
        how="inner",
        validate="one_to_one",
    )
    aggregate = aggregate.merge(
        selection[["election_id", "scenario_id", "selection_status"]],
        on=["election_id", "scenario_id"],
        how="left",
        validate="many_to_one",
    )
    aggregate["difference_r_minus_python"] = aggregate["mean_r_ei"] - aggregate["mean_python_krt"]
    aggregate["absolute_difference"] = aggregate["difference_r_minus_python"].abs()
    aggregate["intervals_overlap"] = np.maximum(
        aggregate["q025_r_ei"], aggregate["q025_python_krt"]
    ) <= np.minimum(aggregate["q975_r_ei"], aggregate["q975_python_krt"])
    aggregate["comparison_interpretation"] = (
        "robustness_between_nonidentical_King_models_not_bitwise_replication"
    )
    aggregate.to_parquet(AGGREGATE_COMPARISON_PATH, index=False)

    joined = r_commune.merge(
        py_commune[
            [
                "election_id", "scenario_id", "unit_id",
                "b1_mean", "b1_q025", "b1_q975",
                "b2_mean", "b2_q025", "b2_q975",
            ]
        ],
        on=["election_id", "scenario_id", "unit_id"],
        suffixes=("_r_ei", "_python_krt"),
        how="inner",
        validate="one_to_one",
    )
    summary_rows: list[dict[str, object]] = []
    for (election_id, scenario_id), part in joined.groupby(["election_id", "scenario_id"], sort=True):
        for beta in ("b1", "b2"):
            difference = part[f"{beta}_mean_r_ei"] - part[f"{beta}_mean_python_krt"]
            overlap = np.maximum(
                part[f"{beta}_q025_r_ei"], part[f"{beta}_q025_python_krt"]
            ) <= np.minimum(part[f"{beta}_q975_r_ei"], part[f"{beta}_q975_python_krt"])
            summary_rows.append(
                {
                    "election_id": election_id,
                    "scenario_id": scenario_id,
                    "parameter": beta.replace("b", "b_"),
                    "n_communes": len(part),
                    "mean_difference_r_minus_python": float(difference.mean()),
                    "mean_absolute_difference": float(difference.abs().mean()),
                    "median_absolute_difference": float(difference.abs().median()),
                    "p95_absolute_difference": float(difference.abs().quantile(0.95)),
                    "correlation_of_commune_means": float(
                        part[f"{beta}_mean_r_ei"].corr(part[f"{beta}_mean_python_krt"])
                    ),
                    "interval_overlap_rate": float(overlap.mean()),
                }
            )
    commune_summary = pd.DataFrame(summary_rows).merge(
        selection,
        on=["election_id", "scenario_id"],
        how="left",
        validate="many_to_one",
    )
    commune_summary.to_parquet(COMMUNE_SUMMARY_PATH, index=False)

    pair_count = aggregate[["election_id", "scenario_id"]].drop_duplicates().shape[0]
    provisional = int(selection["selection_status"].eq("latest_completed_fit_provisional").sum())
    result = {
        "schema_version": "longitudinal_python_r_ei_retained_scope_comparison_v1",
        "created_at_utc": _utc_now(),
        "status": (
            "complete"
            if pair_count == EXPECTED_PAIR_COUNT and provisional == 0
            else "partial_provisional"
        ),
        "python_model": "PyMC_KRT_king99_beta_binomial",
        "r_model": "King_1997_truncated_bivariate_normal_EI_R_ei_depending_on_eiPack",
        "mathematical_identity": False,
        "scenarios": list(RETAINED_SCENARIOS),
        "expected_pairs": EXPECTED_PAIR_COUNT,
        "interpretation": "robustness_between_nonidentical_King_models_not_bitwise_replication",
        "r_pairs_available": len(r_pairs),
        "python_r_pairs_compared": pair_count,
        "provisional_python_pair_selections": provisional,
        "aggregate_rows": len(aggregate),
        "aggregate_interval_overlap_rate": float(aggregate["intervals_overlap"].mean()),
        "aggregate_median_absolute_difference": float(aggregate["absolute_difference"].median()),
        "aggregate_max_absolute_difference": float(aggregate["absolute_difference"].max()),
        "commune_summary_rows": len(commune_summary),
        "aggregate_comparison_path": portable_path(AGGREGATE_COMPARISON_PATH, root=ROOT),
        "aggregate_comparison_sha256": file_sha256(AGGREGATE_COMPARISON_PATH),
        "commune_summary_path": portable_path(COMMUNE_SUMMARY_PATH, root=ROOT),
        "commune_summary_sha256": file_sha256(COMMUNE_SUMMARY_PATH),
        "selection_audit_path": portable_path(SELECTION_AUDIT_PATH, root=ROOT),
        "selection_audit_sha256": file_sha256(SELECTION_AUDIT_PATH),
    }
    write_json(MANIFEST_PATH, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare available Python KRT and R ei estimates.")
    parser.parse_args()
    print(json.dumps(compare(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
