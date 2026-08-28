from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from .compare_python_r_ei_all_2x2 import (
    _canonical_h0a_h1,
    _latest_python_runs,
    _preregistered_selected_run_ids,
    _valid_python_manifest,
)
from .paths import OUTPUT_DIR, ROOT, RUNS_DIR
from .run_rxc_panel_extension_v11 import EXPECTED_PANEL_SHA256
from .spec_registry import SPEC_VERSION
from .utils import file_sha256, portable_path, write_json


OUTPUT_ROOT = OUTPUT_DIR / SPEC_VERSION / "production" / "all_2x2_candidate"
COMMUNE_PATH = OUTPUT_ROOT / "longitudinal_krt_commune_240_candidate.parquet"
AGGREGATE_PATH = OUTPUT_ROOT / "longitudinal_krt_aggregate_240_candidate.parquet"
SELECTION_PATH = OUTPUT_ROOT / "krt_240_candidate_selection.csv"
MANIFEST_PATH = OUTPUT_ROOT / "krt_240_candidate_manifest.json"

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
CANONICAL_PANEL_ID = "longitudinal_2000_v1__strict_nested_3000__seed_20260803"
UNCERTAINTY_COLUMNS = [
    "b1_sd", "b1_q025", "b1_q50", "b1_q975",
    "b2_sd", "b2_q025", "b2_q50", "b2_q975",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _all_valid_runs_by_id() -> dict[str, tuple[Path, dict[str, Any]]]:
    result: dict[str, tuple[Path, dict[str, Any]]] = {}
    for manifest_path in RUNS_DIR.glob("*/manifest.json"):
        manifest = _valid_python_manifest(manifest_path)
        if manifest is not None:
            result[str(manifest["run_id"])] = (manifest_path.parent, manifest)
    return result


def _model_ready_path(manifest: dict[str, Any]) -> Path:
    preparation = manifest.get("preparation_manifest", {})
    candidate = preparation.get("output") if isinstance(preparation, dict) else None
    if candidate:
        path = Path(str(candidate))
        if path.exists():
            return path
    for raw_path in manifest.get("input_sha256", {}):
        path = Path(str(raw_path))
        if path.suffix.lower() == ".parquet" and path.exists():
            return path
    raise FileNotFoundError(f"model-ready input is unavailable for {manifest.get('run_id')}")


def _diagnostics(manifest: dict[str, Any]) -> tuple[str, str]:
    mcmc = manifest.get("canonical_mcmc_diagnostic", {})
    identification = manifest.get("identification_diagnostic", {})
    return (
        str(mcmc.get("mcmc_status", manifest.get("diagnostic_status", "unknown"))),
        str(identification.get("identification_status", "unknown")),
    )


@lru_cache(maxsize=1)
def _geography_reference() -> pd.DataFrame:
    reference = _canonical_h0a_h1()[1]
    geography_columns = [
        "unit_id", "department", "commune_name_canonical", "geography_version",
        "commune_name_reference_year",
    ]
    return reference[geography_columns].drop_duplicates("unit_id")


def _extension_commune(run_dir: Path, manifest: dict[str, Any], selection_status: str) -> pd.DataFrame:
    latent = pd.read_parquet(run_dir / "commune_latent_summaries.parquet")
    prepared = pd.read_parquet(_model_ready_path(manifest))
    prepared["unit_id"] = prepared["unit_id"].astype("string")
    latent["unit_id"] = latent["unit_id"].astype("string")
    metadata_columns = [
        "unit_id", "year", "round", "N_g", "region13", "vbbm",
        "vbbm_reference_year", "vbbm_status", "vbbm_source_column",
        "revenue", "revenue_reference_year", "revenue_status", "revenue_source_column",
        "capital", "capital_reference_year", "capital_status", "capital_source_column",
        "foreign_share", "foreign_share_reference_year", "foreign_share_status",
        "foreign_share_source_column",
    ]
    available = [column for column in metadata_columns if column in prepared]
    if prepared["unit_id"].duplicated().any():
        raise AssertionError("duplicate unit_id in model-ready input")
    commune = latent.merge(prepared[available], on="unit_id", how="left", validate="one_to_one")
    if len(commune) != 2000 or commune["N_g"].isna().any():
        raise AssertionError("extension commune/model-ready join is incomplete")
    commune = commune.rename(columns={"revenue": "revenue_ratio", "capital": "capital_ratio"})

    commune = commune.merge(_geography_reference(), on="unit_id", how="left", validate="many_to_one")
    if commune["commune_name_canonical"].isna().any():
        raise AssertionError("canonical geography join is incomplete")

    parameters = manifest["parameters"]
    mcmc_status, identification_status = _diagnostics(manifest)
    commune["source_panel_id"] = str(parameters["panel_id"])
    commune["panel_id"] = CANONICAL_PANEL_ID
    commune["run_id"] = str(manifest["run_id"])
    commune["model_key"] = "krt_beta_binomial"
    commune["spec_version"] = str(parameters["spec_version"])
    commune["harmonization_version"] = str(parameters["harmonization_version"])
    commune["mcmc_status"] = mcmc_status
    commune["identification_status"] = identification_status
    commune["public_schema_version"] = str(parameters.get("public_schema_version", "longitudinal_public_schema_v1.0.2"))
    commune["selection_status"] = selection_status
    return commune


def _extension_aggregate(run_dir: Path, manifest: dict[str, Any], selection_status: str) -> pd.DataFrame:
    aggregate = pd.read_csv(run_dir / "aggregate_comparison_v2.csv")
    aggregate = aggregate.loc[aggregate["aggregation_method"].eq("group_specific_population_v2")].copy()
    if len(aggregate) != 3:
        raise AssertionError("extension aggregate does not contain exactly three corrected estimands")
    aggregate = aggregate.rename(columns={"beta_parameter": "estimand", "q50": "median"})
    parameters = manifest["parameters"]
    prepared = pd.read_parquet(_model_ready_path(manifest), columns=["year", "round"])
    mcmc_status, identification_status = _diagnostics(manifest)
    aggregate["source_panel_id"] = str(parameters["panel_id"])
    aggregate["panel_id"] = CANONICAL_PANEL_ID
    aggregate["year"] = int(prepared["year"].iloc[0])
    aggregate["round"] = int(prepared["round"].iloc[0])
    aggregate["run_id"] = str(manifest["run_id"])
    aggregate["spec_version"] = str(parameters["spec_version"])
    aggregate["harmonization_version"] = str(parameters["harmonization_version"])
    aggregate["n_communes"] = 2000
    aggregate["draws"] = int(parameters["draws"])
    aggregate["tune"] = int(parameters["tune"])
    aggregate["chains"] = int(parameters["chains"])
    aggregate["target_accept"] = float(parameters["target_accept"])
    aggregate["max_treedepth"] = int(parameters["max_treedepth"])
    aggregate["king_lambda"] = float(parameters["king_lambda"])
    aggregate["mcmc_status"] = mcmc_status
    aggregate["identification_status"] = identification_status
    aggregate["public_schema_version"] = str(parameters.get("public_schema_version", "longitudinal_public_schema_v1.0.2"))
    aggregate["selection_status"] = selection_status
    return aggregate


def consolidate() -> dict[str, object]:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    canonical_aggregate, canonical_commune = _canonical_h0a_h1()
    canonical_aggregate = canonical_aggregate.copy()
    canonical_commune = canonical_commune.copy()
    canonical_aggregate["source_panel_id"] = canonical_aggregate["panel_id"]
    canonical_commune["source_panel_id"] = canonical_commune["panel_id"]
    canonical_aggregate["panel_id"] = CANONICAL_PANEL_ID
    canonical_commune["panel_id"] = CANONICAL_PANEL_ID
    canonical_aggregate["selection_status"] = "canonical_v1.0.2"
    canonical_commune["selection_status"] = "canonical_v1.0.2"
    commune_parts = [canonical_commune]
    aggregate_parts = [canonical_aggregate]
    selection_rows: list[dict[str, object]] = []
    for row in canonical_aggregate[["election_id", "scenario_id", "run_id", "mcmc_status", "identification_status"]].drop_duplicates().itertuples(index=False):
        selection_rows.append(
            {
                "election_id": row.election_id,
                "scenario_id": row.scenario_id,
                "run_id": row.run_id,
                "selection_status": "canonical_v1.0.2",
                "mcmc_status": row.mcmc_status,
                "identification_status": row.identification_status,
            }
        )

    latest = _latest_python_runs()
    selected = _preregistered_selected_run_ids()
    by_id = _all_valid_runs_by_id()
    canonical_pairs = {(str(row.election_id), str(row.scenario_id)) for row in canonical_aggregate[["election_id", "scenario_id"]].drop_duplicates().itertuples(index=False)}
    extension_pairs = sorted(set(latest) - canonical_pairs)
    for key in extension_pairs:
        if key in selected and selected[key][0] in by_id:
            run_id, selection_status = selected[key]
            run_dir, manifest = by_id[run_id]
        else:
            run_dir, manifest = latest[key]
            selection_status = "latest_completed_fit_provisional"
        commune = _extension_commune(run_dir, manifest, selection_status)
        aggregate = _extension_aggregate(run_dir, manifest, selection_status)
        commune_parts.append(commune)
        aggregate_parts.append(aggregate)
        mcmc_status, identification_status = _diagnostics(manifest)
        selection_rows.append(
            {
                "election_id": key[0],
                "scenario_id": key[1],
                "run_id": str(manifest["run_id"]),
                "selection_status": selection_status,
                "mcmc_status": mcmc_status,
                "identification_status": identification_status,
            }
        )

    commune = pd.concat(commune_parts, ignore_index=True, sort=False)
    aggregate = pd.concat(aggregate_parts, ignore_index=True, sort=False)
    selection_frame = pd.DataFrame(selection_rows).sort_values(["scenario_id", "election_id"])
    if selection_frame[["election_id", "scenario_id"]].duplicated().any():
        raise AssertionError("duplicate candidate selection key")
    if commune[["election_id", "scenario_id", "unit_id"]].duplicated().any():
        raise AssertionError("duplicate candidate commune key")
    if aggregate[["election_id", "scenario_id", "estimand"]].duplicated().any():
        raise AssertionError("duplicate candidate aggregate key")
    if not set(UNCERTAINTY_COLUMNS).issubset(commune):
        raise AssertionError("the eight commune uncertainty fields are missing")
    if commune[UNCERTAINTY_COLUMNS].isna().any().any():
        raise AssertionError("null commune uncertainty values in candidate")
    pair_count = len(selection_frame)
    if len(commune) != pair_count * 2000 or len(aggregate) != pair_count * 3:
        raise AssertionError("candidate row counts do not match selected pairs")
    if not commune["panel_id"].eq(CANONICAL_PANEL_ID).all():
        raise AssertionError("candidate contains a foreign panel")

    commune.to_parquet(COMMUNE_PATH, index=False)
    aggregate.to_parquet(AGGREGATE_PATH, index=False)
    selection_frame.to_csv(SELECTION_PATH, index=False, encoding="utf-8-sig")
    expected_pairs = sum(EXPECTED_BY_SCENARIO.values())
    scenario_counts = selection_frame.groupby("scenario_id")["election_id"].nunique().to_dict()
    missing_by_scenario = {
        scenario_id: expected - int(scenario_counts.get(scenario_id, 0))
        for scenario_id, expected in EXPECTED_BY_SCENARIO.items()
    }
    provisional = int(selection_frame["selection_status"].eq("latest_completed_fit_provisional").sum())
    mcmc_fail = int(selection_frame["mcmc_status"].eq("fail").sum())
    complete_coverage = pair_count == expected_pairs
    result = {
        "schema_version": "longitudinal_krt_all_2x2_candidate_v1",
        "created_at_utc": _utc_now(),
        "panel_sha256": EXPECTED_PANEL_SHA256,
        "expected_pairs": expected_pairs,
        "selected_pairs": pair_count,
        "missing_pairs": expected_pairs - pair_count,
        "missing_by_scenario": missing_by_scenario,
        "provisional_selections": provisional,
        "mcmc_fail_selections": mcmc_fail,
        "commune_rows": len(commune),
        "aggregate_rows": len(aggregate),
        "ready": bool(complete_coverage and provisional == 0 and mcmc_fail == 0),
        "ready_reason": (
            "all pairs selected without provisional or MCMC fail status"
            if complete_coverage and provisional == 0 and mcmc_fail == 0
            else "candidate remains partial or contains unresolved/provisional diagnostics"
        ),
        "commune_path": portable_path(COMMUNE_PATH, root=ROOT),
        "commune_sha256": file_sha256(COMMUNE_PATH),
        "aggregate_path": portable_path(AGGREGATE_PATH, root=ROOT),
        "aggregate_sha256": file_sha256(AGGREGATE_PATH),
        "selection_path": portable_path(SELECTION_PATH, root=ROOT),
        "selection_sha256": file_sha256(SELECTION_PATH),
    }
    write_json(MANIFEST_PATH, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Consolidate every currently available 2x2 KRT estimate.")
    parser.parse_args()
    print(json.dumps(consolidate(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
