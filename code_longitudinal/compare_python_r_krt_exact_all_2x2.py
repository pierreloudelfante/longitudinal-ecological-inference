from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .consolidate_r_krt_exact_all_2x2 import (
    AGGREGATE_PATH as R_AGGREGATE_PATH,
    COMMUNE_PATH as R_COMMUNE_PATH,
    EXPECTED_PAIRS,
    MANIFEST_PATH as R_CONSOLIDATION_MANIFEST_PATH,
)
from .paths import OUTPUT_DIR, ROOT
from .spec_registry import SPEC_VERSION
from .utils import file_sha256, portable_path, write_json


PYTHON_ROOT = OUTPUT_DIR / SPEC_VERSION / "production" / "all_2x2_candidate"
PYTHON_AGGREGATE_PATH = PYTHON_ROOT / "longitudinal_krt_aggregate_240_candidate.parquet"
PYTHON_COMMUNE_PATH = PYTHON_ROOT / "longitudinal_krt_commune_240_candidate.parquet"
OUTPUT_ROOT = OUTPUT_DIR / SPEC_VERSION / "r_replication"
AGGREGATE_COMPARISON_PATH = OUTPUT_ROOT / "python_r_krt_exact_aggregate_comparison.csv"
COMMUNE_COMPARISON_PATH = OUTPUT_ROOT / "python_r_krt_exact_commune_comparison.csv"
MANIFEST_PATH = OUTPUT_ROOT / "python_r_krt_exact_comparison_manifest.json"


def compare() -> dict[str, object]:
    required = (
        PYTHON_AGGREGATE_PATH,
        PYTHON_COMMUNE_PATH,
        R_AGGREGATE_PATH,
        R_COMMUNE_PATH,
    )
    missing = [portable_path(path, root=ROOT) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing comparison inputs: {missing}")

    py_aggregate = pd.read_parquet(PYTHON_AGGREGATE_PATH)
    r_aggregate = pd.read_parquet(R_AGGREGATE_PATH)
    keys = ["election_id", "scenario_id", "estimand"]
    py_aggregate = py_aggregate[keys + ["mean", "median", "q025", "q975", "run_id"]].rename(
        columns={
            "mean": "python_mean",
            "median": "python_median",
            "q025": "python_q025",
            "q975": "python_q975",
            "run_id": "python_run_id",
        }
    )
    r_aggregate = r_aggregate[keys + ["mean", "median", "q025", "q975"]].rename(
        columns={
            "mean": "r_mean",
            "median": "r_median",
            "q025": "r_q025",
            "q975": "r_q975",
        }
    )
    aggregate = py_aggregate.merge(r_aggregate, on=keys, how="inner", validate="one_to_one")
    aggregate["difference_r_minus_python"] = aggregate["r_mean"] - aggregate["python_mean"]
    aggregate["absolute_difference"] = aggregate["difference_r_minus_python"].abs()
    aggregate["interval_overlap"] = (
        aggregate[["python_q975", "r_q975"]].min(axis=1)
        >= aggregate[["python_q025", "r_q025"]].max(axis=1)
    )
    aggregate.to_csv(AGGREGATE_COMPARISON_PATH, index=False, encoding="utf-8-sig")

    py_commune = pd.read_parquet(
        PYTHON_COMMUNE_PATH,
        columns=["election_id", "scenario_id", "unit_id", "b1_mean", "b2_mean"],
    )
    r_commune = pd.read_parquet(
        R_COMMUNE_PATH,
        columns=["election_id", "scenario_id", "unit_id", "b1_mean", "b2_mean"],
    )
    py_commune["unit_id"] = py_commune["unit_id"].astype("string")
    r_commune["unit_id"] = r_commune["unit_id"].astype("string")
    commune = py_commune.merge(
        r_commune,
        on=["election_id", "scenario_id", "unit_id"],
        how="inner",
        suffixes=("_python", "_r"),
        validate="one_to_one",
    )
    commune_rows: list[dict[str, object]] = []
    for (election_id, scenario_id), group in commune.groupby(["election_id", "scenario_id"]):
        if len(group) != 2000:
            raise AssertionError(f"Python/R unit coverage mismatch for {(election_id, scenario_id)}")
        for beta in ("b1", "b2"):
            python_values = group[f"{beta}_mean_python"].to_numpy(float)
            r_values = group[f"{beta}_mean_r"].to_numpy(float)
            difference = r_values - python_values
            commune_rows.append(
                {
                    "election_id": election_id,
                    "scenario_id": scenario_id,
                    "parameter": beta.replace("b", "b_"),
                    "n_communes": len(group),
                    "mean_difference_r_minus_python": float(np.mean(difference)),
                    "mean_absolute_difference": float(np.mean(np.abs(difference))),
                    "root_mean_squared_difference": float(np.sqrt(np.mean(difference**2))),
                    "max_absolute_difference": float(np.max(np.abs(difference))),
                    "pearson_correlation": float(np.corrcoef(python_values, r_values)[0, 1]),
                }
            )
    commune_comparison = pd.DataFrame(commune_rows).sort_values(
        ["scenario_id", "election_id", "parameter"]
    )
    commune_comparison.to_csv(COMMUNE_COMPARISON_PATH, index=False, encoding="utf-8-sig")

    r_manifest = json.loads(R_CONSOLIDATION_MANIFEST_PATH.read_text(encoding="utf-8-sig"))
    matched_aggregate_pairs = aggregate[["election_id", "scenario_id"]].drop_duplicates()
    matched_commune_pairs = commune_comparison[["election_id", "scenario_id"]].drop_duplicates()
    ready = bool(
        r_manifest.get("ready") is True
        and len(matched_aggregate_pairs) == EXPECTED_PAIRS
        and len(aggregate) == EXPECTED_PAIRS * 3
        and len(matched_commune_pairs) == EXPECTED_PAIRS
        and len(commune_comparison) == EXPECTED_PAIRS * 2
    )
    result = {
        "schema_version": "longitudinal_python_r_krt_exact_comparison_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_model": "PyEI_PyMC_KRT_king99_beta_binomial",
        "r_model": "exact_reimplementation_of_pyei_ei_beta_binom_model",
        "r_engine": "R_NIMBLE",
        "mathematical_model_identical": True,
        "sampler_identical": False,
        "expected_pairs": EXPECTED_PAIRS,
        "matched_aggregate_pairs": len(matched_aggregate_pairs),
        "matched_commune_pairs": len(matched_commune_pairs),
        "aggregate_rows": len(aggregate),
        "commune_summary_rows": len(commune_comparison),
        "maximum_aggregate_absolute_difference": (
            float(aggregate["absolute_difference"].max()) if not aggregate.empty else None
        ),
        "aggregate_interval_overlap_rate": (
            float(aggregate["interval_overlap"].mean()) if not aggregate.empty else None
        ),
        "ready": ready,
        "aggregate_comparison_path": portable_path(AGGREGATE_COMPARISON_PATH, root=ROOT),
        "commune_comparison_path": portable_path(COMMUNE_COMPARISON_PATH, root=ROOT),
        "hashes": {
            portable_path(path, root=ROOT): file_sha256(path)
            for path in (AGGREGATE_COMPARISON_PATH, COMMUNE_COMPARISON_PATH)
        },
    }
    write_json(MANIFEST_PATH, result)
    return result


def main() -> None:
    print(json.dumps(compare(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
