from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .paths import OUTPUT_DIR, ROOT
from .spec_registry import SPEC_VERSION
from .utils import file_sha256, portable_path, write_json


REPLICATION_DIR = OUTPUT_DIR / SPEC_VERSION / "r_replication"
RUN_DIR = REPLICATION_DIR / "king_ei_runs"
COMMUNE_PATH = REPLICATION_DIR / "longitudinal_king_ei_r_commune_retained6.parquet"
AGGREGATE_PATH = REPLICATION_DIR / "longitudinal_king_ei_r_aggregate_retained6.parquet"
RUN_AUDIT_PATH = REPLICATION_DIR / "king_ei_retained6_run_audit.csv"
MANIFEST_PATH = REPLICATION_DIR / "king_ei_retained6_consolidation_manifest.json"

EXPECTED_BY_SCENARIO = {
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
RETAINED_SCENARIOS = ("H0A", "H1", "H0B", "H0C", "H2", "H3")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_valid_run(run_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    manifest_path = run_dir / "manifest_r.json"
    commune_path = run_dir / "commune_latent_summaries_r.csv"
    aggregate_path = run_dir / "aggregate_summaries_r.csv"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    input_path = Path(str(manifest["input_csv"]))
    if not input_path.is_absolute():
        input_path = ROOT / input_path
    checks = {
        "manifest_success": manifest.get("status") == "success",
        "panel_size_2000": int(manifest.get("n_communes", -1)) == 2000,
        "input_exists": input_path.exists(),
        "input_hash_match": input_path.exists()
        and file_sha256(input_path) == str(manifest.get("input_sha256", "")),
        "mathematical_identity_false": manifest.get("mathematical_identity_with_python_model") is False,
    }
    if not all(checks.values()):
        raise AssertionError(f"invalid R EI manifest {manifest_path}: {checks}")

    commune = pd.read_csv(commune_path, dtype={"unit_id": "string", "panel_id": "string"})
    aggregate = pd.read_csv(aggregate_path, dtype={"panel_id": "string"})
    if len(commune) != 4000 or commune["unit_id"].nunique() != 2000:
        raise AssertionError(f"invalid commune output size in {run_dir}")
    if set(commune["parameter"]) != {"b_1", "b_2"}:
        raise AssertionError(f"invalid beta parameters in {run_dir}")
    if commune[["unit_id", "parameter"]].duplicated().any():
        raise AssertionError(f"duplicate commune-parameter key in {run_dir}")
    if len(aggregate) != 3 or set(aggregate["estimand"]) != {
        "beta1_aggregate",
        "beta2_aggregate",
        "contrast_aggregate",
    }:
        raise AssertionError(f"invalid aggregate output in {run_dir}")

    election_id = str(manifest["election_id"])
    scenario_id = str(manifest["scenario_id"])
    if not commune["election_id"].eq(election_id).all() or not commune["scenario_id"].eq(scenario_id).all():
        raise AssertionError(f"commune metadata mismatch in {run_dir}")
    if not aggregate["election_id"].eq(election_id).all() or not aggregate["scenario_id"].eq(scenario_id).all():
        raise AssertionError(f"aggregate metadata mismatch in {run_dir}")

    audit = {
        "election_id": election_id,
        "scenario_id": scenario_id,
        "status": "valid",
        "n_communes": 2000,
        "commune_long_rows": len(commune),
        "aggregate_rows": len(aggregate),
        "input_path": portable_path(input_path, root=ROOT),
        "input_sha256": str(manifest["input_sha256"]),
        "ei_version": str(manifest.get("ei_version", "")),
        "eiPack_version": str(manifest.get("eiPack_version", "")),
        "seed": int(manifest["seed"]),
        "elapsed_seconds": float(manifest["elapsed_seconds"]),
        "run_dir": portable_path(run_dir, root=ROOT),
    }
    return commune, aggregate, audit


def consolidate(
    *,
    scenarios: tuple[str, ...] = RETAINED_SCENARIOS,
    allow_partial: bool = False,
) -> dict[str, object]:
    unknown = sorted(set(scenarios) - set(EXPECTED_BY_SCENARIO))
    if unknown:
        raise ValueError(f"unknown scenarios: {unknown}")
    commune_parts: list[pd.DataFrame] = []
    aggregate_parts: list[pd.DataFrame] = []
    audits: list[dict[str, object]] = []
    invalid: list[dict[str, str]] = []
    for run_dir in sorted(RUN_DIR.iterdir() if RUN_DIR.exists() else []):
        if not run_dir.is_dir() or "__" not in run_dir.name:
            continue
        manifest_path = run_dir / "manifest_r.json"
        if not manifest_path.exists():
            continue
        try:
            commune, aggregate, audit = _load_valid_run(run_dir)
        except Exception as exc:
            invalid.append({"run_dir": portable_path(run_dir, root=ROOT), "error": f"{type(exc).__name__}: {exc}"})
            continue
        scenario_id = str(audit["scenario_id"])
        if scenario_id not in scenarios:
            continue
        commune_parts.append(commune)
        aggregate_parts.append(aggregate)
        audits.append(audit)

    if not audits:
        raise RuntimeError("no valid R EI runs are available")
    audit_frame = pd.DataFrame(audits).sort_values(["scenario_id", "election_id"])
    audit_frame.to_csv(RUN_AUDIT_PATH, index=False, encoding="utf-8-sig")
    pair_counts = audit_frame.groupby("scenario_id")["election_id"].nunique().to_dict()
    missing_by_scenario = {
        scenario_id: expected - int(pair_counts.get(scenario_id, 0))
        for scenario_id, expected in EXPECTED_BY_SCENARIO.items()
        if scenario_id in scenarios
    }
    missing_pairs = sum(missing_by_scenario.values())
    if (missing_pairs or invalid) and not allow_partial:
        raise AssertionError(
            f"R EI scope incomplete: missing={missing_by_scenario}, invalid={len(invalid)}"
        )

    commune_long = pd.concat(commune_parts, ignore_index=True)
    value_columns = ["mean", "sd", "q025", "q50", "q975"]
    commune_wide = commune_long.pivot(
        index=["panel_id", "election_id", "scenario_id", "unit_id", "sample_rank"],
        columns="parameter",
        values=value_columns,
    )
    commune_wide.columns = [f"{parameter.replace('_', '')}_{metric}" for metric, parameter in commune_wide.columns]
    commune_wide = commune_wide.reset_index()
    rename = {
        "b1_mean": "b1_mean",
        "b1_sd": "b1_sd",
        "b1_q025": "b1_q025",
        "b1_q50": "b1_q50",
        "b1_q975": "b1_q975",
        "b2_mean": "b2_mean",
        "b2_sd": "b2_sd",
        "b2_q025": "b2_q025",
        "b2_q50": "b2_q50",
        "b2_q975": "b2_q975",
    }
    commune_wide = commune_wide.rename(columns=rename)
    uncertainty = [
        "b1_sd", "b1_q025", "b1_q50", "b1_q975",
        "b2_sd", "b2_q025", "b2_q50", "b2_q975",
    ]
    if not set(uncertainty).issubset(commune_wide):
        raise AssertionError("the eight commune uncertainty fields are incomplete")
    if commune_wide[["election_id", "scenario_id", "unit_id"]].duplicated().any():
        raise AssertionError("duplicate R EI commune key after consolidation")

    aggregate = pd.concat(aggregate_parts, ignore_index=True)
    if aggregate[["election_id", "scenario_id", "estimand"]].duplicated().any():
        raise AssertionError("duplicate R EI aggregate key after consolidation")
    commune_wide.to_parquet(COMMUNE_PATH, index=False)
    aggregate.to_parquet(AGGREGATE_PATH, index=False)

    expected_pairs = sum(EXPECTED_BY_SCENARIO[item] for item in scenarios)
    complete = missing_pairs == 0 and not invalid
    result = {
        "schema_version": "longitudinal_r_ei_retained_scope_consolidation_v1",
        "created_at_utc": _utc_now(),
        "status": "complete" if complete else "partial",
        "model": "King_1997_truncated_bivariate_normal_EI_R_ei_depending_on_eiPack",
        "comparison_target": "Python_PyMC_KRT_king99_beta_binomial",
        "mathematical_identity_with_python_model": False,
        "scenarios": list(scenarios),
        "expected_pairs": expected_pairs,
        "valid_pairs": len(audit_frame),
        "missing_pairs": missing_pairs,
        "missing_by_scenario": missing_by_scenario,
        "invalid_runs": invalid,
        "commune_rows": len(commune_wide),
        "aggregate_rows": len(aggregate),
        "commune_path": portable_path(COMMUNE_PATH, root=ROOT),
        "commune_sha256": file_sha256(COMMUNE_PATH),
        "aggregate_path": portable_path(AGGREGATE_PATH, root=ROOT),
        "aggregate_sha256": file_sha256(AGGREGATE_PATH),
        "run_audit_path": portable_path(RUN_AUDIT_PATH, root=ROOT),
        "run_audit_sha256": file_sha256(RUN_AUDIT_PATH),
    }
    write_json(MANIFEST_PATH, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Consolidate the retained R ei/eiPack estimates.")
    parser.add_argument("--scenarios", nargs="+", default=list(RETAINED_SCENARIOS))
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            consolidate(scenarios=tuple(args.scenarios), allow_partial=args.allow_partial),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
