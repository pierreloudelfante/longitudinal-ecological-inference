from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from reproducibility.replication_scope import get_scope

from .paths import OUTPUT_DIR, ROOT
from .spec_registry import SPEC_VERSION
from .utils import file_sha256, portable_path, write_json


PRODUCTION_DIR = OUTPUT_DIR / SPEC_VERSION / "production" / "all_2x2_candidate"
REPLICATION_DIR = OUTPUT_DIR / SPEC_VERSION / "r_replication"

PYTHON_AGGREGATE = PRODUCTION_DIR / "longitudinal_krt_aggregate_240_candidate.parquet"
PYTHON_COMMUNE = PRODUCTION_DIR / "longitudinal_krt_commune_240_candidate.parquet"
PYTHON_SELECTION = PRODUCTION_DIR / "krt_240_candidate_selection.csv"
R_AGGREGATE = REPLICATION_DIR / "longitudinal_king_ei_r_aggregate_all_2x2.parquet"
R_COMMUNE = REPLICATION_DIR / "longitudinal_king_ei_r_commune_all_2x2.parquet"

AGGREGATE_OUTPUT = REPLICATION_DIR / "king_python_r_full_240_aggregate_comparison.parquet"
COMMUNE_OUTPUT = REPLICATION_DIR / "king_python_r_full_240_commune_summary.parquet"
MANIFEST_OUTPUT = REPLICATION_DIR / "king_python_r_full_240_comparison_manifest.json"

EXPECTED_PAIRS = 240
EXPECTED_COMMUNES_PER_PAIR = 2000
ESTIMAND_MAP = {
    "beta1_aggregate": "b_1",
    "beta2_aggregate": "b_2",
    "contrast_aggregate": "b_1_minus_b_2",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _assert_pair_coverage(frame: pd.DataFrame, *, label: str) -> None:
    pairs = set(frame[["election_id", "scenario_id"]].itertuples(index=False, name=None))
    expected = get_scope().pairs
    if pairs != expected:
        raise AssertionError(f"{label} pair coverage differs: missing={sorted(expected - pairs)}, unexpected={sorted(pairs - expected)}")


def _build_aggregate_comparison() -> pd.DataFrame:
    expected_pairs = get_scope().pair_count
    python = pd.read_parquet(PYTHON_AGGREGATE)
    r_ei = pd.read_parquet(R_AGGREGATE)
    _assert_pair_coverage(python, label="Python aggregate")
    _assert_pair_coverage(r_ei, label="R aggregate")

    python = python[
        [
            "panel_id",
            "election_id",
            "year",
            "round",
            "scenario_id",
            "run_id",
            "estimand",
            "mean",
            "median",
            "q025",
            "q975",
            "n_posterior_draws",
            "n_communes",
            "mcmc_status",
            "identification_status",
            "selection_status",
        ]
    ].rename(
        columns={
            "mean": "mean_python_krt",
            "median": "q50_python_krt",
            "q025": "q025_python_krt",
            "q975": "q975_python_krt",
            "n_posterior_draws": "draws_python_krt",
            "n_communes": "n_communes_python",
        }
    )
    r_ei = r_ei.copy()
    r_ei["estimand"] = r_ei["estimand"].map(ESTIMAND_MAP)
    if r_ei["estimand"].isna().any():
        raise AssertionError("unknown R aggregate estimand")
    r_ei = r_ei[
        [
            "panel_id",
            "election_id",
            "scenario_id",
            "estimand",
            "mean",
            "sd",
            "q025",
            "q50",
            "q975",
            "n_posterior_draws",
        ]
    ].rename(
        columns={
            "mean": "mean_r_ei",
            "sd": "sd_r_ei",
            "q025": "q025_r_ei",
            "q50": "q50_r_ei",
            "q975": "q975_r_ei",
            "n_posterior_draws": "draws_r_ei",
        }
    )

    keys = ["panel_id", "election_id", "scenario_id", "estimand"]
    result = python.merge(r_ei, on=keys, how="inner", validate="one_to_one")
    if len(result) != expected_pairs * 3:
        raise AssertionError(f"expected {expected_pairs * 3} aggregate comparisons; found {len(result)}")
    result["difference_r_minus_python"] = result["mean_r_ei"] - result["mean_python_krt"]
    result["absolute_difference"] = result["difference_r_minus_python"].abs()
    result["intervals_overlap"] = (
        np.maximum(result["q025_python_krt"], result["q025_r_ei"])
        <= np.minimum(result["q975_python_krt"], result["q975_r_ei"])
    )
    result["comparison_interpretation"] = (
        "robustesse_inter_modele; R_ei_truncated_normal_non_identique_au_KRT_beta_binomial"
    )
    return result.sort_values(["scenario_id", "election_id", "estimand"]).reset_index(drop=True)


def _build_commune_summary() -> pd.DataFrame:
    expected_pairs = get_scope().pair_count
    python = pd.read_parquet(PYTHON_COMMUNE)
    r_ei = pd.read_parquet(R_COMMUNE)
    _assert_pair_coverage(python, label="Python commune")
    _assert_pair_coverage(r_ei, label="R commune")
    keys = ["panel_id", "election_id", "scenario_id", "unit_id"]
    python_columns = keys + [
        "run_id",
        "b1_mean",
        "b1_q025",
        "b1_q975",
        "b2_mean",
        "b2_q025",
        "b2_q975",
        "mcmc_status",
        "identification_status",
        "selection_status",
    ]
    r_columns = keys + [
        "b1_mean",
        "b1_q025",
        "b1_q975",
        "b2_mean",
        "b2_q025",
        "b2_q975",
    ]
    merged = python[python_columns].merge(
        r_ei[r_columns],
        on=keys,
        how="inner",
        suffixes=("_python", "_r"),
        validate="one_to_one",
    )
    if len(merged) != expected_pairs * EXPECTED_COMMUNES_PER_PAIR:
        raise AssertionError(
            "the Python/R commune intersection is incomplete: "
            f"{len(merged)} rows instead of {expected_pairs * EXPECTED_COMMUNES_PER_PAIR}"
        )

    rows: list[dict[str, object]] = []
    for parameter in ("b1", "b2"):
        mean_python = f"{parameter}_mean_python"
        mean_r = f"{parameter}_mean_r"
        difference = merged[mean_r] - merged[mean_python]
        overlap = (
            np.maximum(merged[f"{parameter}_q025_python"], merged[f"{parameter}_q025_r"])
            <= np.minimum(merged[f"{parameter}_q975_python"], merged[f"{parameter}_q975_r"])
        )
        work = merged[
            keys[:3]
            + ["run_id", "mcmc_status", "identification_status", "selection_status", mean_python, mean_r]
        ].copy()
        work["difference"] = difference
        work["absolute_difference"] = difference.abs()
        work["interval_overlap"] = overlap
        for group_key, group in work.groupby(["panel_id", "election_id", "scenario_id"], sort=True):
            correlation = group[[mean_python, mean_r]].corr().iloc[0, 1]
            rows.append(
                {
                    "panel_id": group_key[0],
                    "election_id": group_key[1],
                    "scenario_id": group_key[2],
                    "parameter": parameter.replace("b", "b_"),
                    "n_communes": len(group),
                    "mean_difference_r_minus_python": float(group["difference"].mean()),
                    "mean_absolute_difference": float(group["absolute_difference"].mean()),
                    "median_absolute_difference": float(group["absolute_difference"].median()),
                    "p95_absolute_difference": float(group["absolute_difference"].quantile(0.95)),
                    "correlation_of_commune_means": float(correlation),
                    "interval_overlap_rate": float(group["interval_overlap"].mean()),
                    "python_run_id": str(group["run_id"].iloc[0]),
                    "selection_status": str(group["selection_status"].iloc[0]),
                    "mcmc_status": str(group["mcmc_status"].iloc[0]),
                    "identification_status": str(group["identification_status"].iloc[0]),
                }
            )
    result = pd.DataFrame(rows)
    if len(result) != expected_pairs * 2:
        raise AssertionError(f"expected {expected_pairs * 2} commune summaries; found {len(result)}")
    return result.sort_values(["scenario_id", "election_id", "parameter"]).reset_index(drop=True)


def compare() -> dict[str, object]:
    required = (PYTHON_AGGREGATE, PYTHON_COMMUNE, PYTHON_SELECTION, R_AGGREGATE, R_COMMUNE)
    missing = [portable_path(path, root=ROOT) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing comparison inputs: {missing}")
    aggregate = _build_aggregate_comparison()
    commune = _build_commune_summary()
    aggregate.to_parquet(AGGREGATE_OUTPUT, index=False)
    commune.to_parquet(COMMUNE_OUTPUT, index=False)
    result = {
        "schema_version": "king_python_r_full_240_comparison_v1",
        "created_at_utc": _utc_now(),
        "status": "complete",
        "expected_pairs": get_scope().pair_count,
        "python_r_pairs_compared": int(
            aggregate[["election_id", "scenario_id"]].drop_duplicates().shape[0]
        ),
        "aggregate_rows": len(aggregate),
        "commune_summary_rows": len(commune),
        "models_mathematically_identical": False,
        "comparison_role": "sensitivity analysis across two distinct ecological-inference formulations",
        "aggregate_path": portable_path(AGGREGATE_OUTPUT, root=ROOT),
        "aggregate_sha256": file_sha256(AGGREGATE_OUTPUT),
        "commune_summary_path": portable_path(COMMUNE_OUTPUT, root=ROOT),
        "commune_summary_sha256": file_sha256(COMMUNE_OUTPUT),
        "input_sha256": {
            portable_path(path, root=ROOT): file_sha256(path) for path in required
        },
    }
    write_json(MANIFEST_OUTPUT, result)
    return result


def main() -> None:
    print(json.dumps(compare(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
