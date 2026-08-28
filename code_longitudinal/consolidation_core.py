from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .audit_longitudinal import INVENTORY_PATH, PRESENCE_PATH, RUN_PLAN_PATH
from .build_longitudinal_panel import BALANCE_BY_ELECTION_PATH, BALANCE_PATH
from .paths import ROOT
from .spec_registry import ELECTION_BY_ID, HARMONIZATION_VERSION, SCENARIO_BY_ID, SPEC_VERSION


KRT_COMMUNE_COLUMNS = [
    "panel_id", "election_id", "year", "round", "scenario_id", "run_id", "model_key",
    "spec_version", "harmonization_version", "unit_id", "department", "region13", "vbbm",
    "vbbm_reference_year", "vbbm_status", "vbbm_source_column", "revenue",
    "revenue_reference_year", "revenue_status", "revenue_source_column", "capital",
    "capital_reference_year", "capital_status", "capital_source_column", "foreign_share",
    "foreign_share_reference_year", "foreign_share_status", "foreign_share_source_column", "N_g",
    "b1_weight", "b2_weight", "b1_mean", "b1_sd", "b1_q025", "b1_q50", "b1_q975",
    "b2_mean", "b2_sd", "b2_q025", "b2_q50", "b2_q975", "mcmc_status",
    "identification_status",
]

KRT_AGGREGATE_COLUMNS = [
    "panel_id", "election_id", "year", "round", "scenario_id", "run_id", "model_key",
    "spec_version", "harmonization_version", "estimand", "weight_basis", "mean", "median",
    "q025", "q975", "n_posterior_draws", "n_communes", "weight_total", "draws", "tune",
    "chains", "target_accept", "max_treedepth", "king_lambda", "mcmc_status",
    "identification_status",
]

NLS_COLUMNS = [
    "panel_id", "election_id", "year", "round", "scenario_id", "run_id", "model_key",
    "spec_version", "harmonization_version", "estimand_type", "social_group", "vote_category",
    "estimate", "n_communes", "N_total", "objective", "optimality", "bread_rank",
    "bread_condition", "n_starts", "n_successful_starts", "max_abs_solution_difference",
    "boundary_estimate", "fit_status", "diagnostic_status",
]


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame({column: pd.Series(dtype="object") for column in columns})


def _resolve_recorded_path(value: object) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else ROOT / path


def _manifest_value(manifest: dict[str, Any], name: str, default: object = "") -> object:
    parameters = manifest.get("parameters", {})
    return manifest.get(name, parameters.get(name, default)) if isinstance(parameters, dict) else manifest.get(name, default)


def _prepared_frame(run_dir: Path, manifest: dict[str, Any]) -> pd.DataFrame:
    prep = manifest.get("preparation_manifest", {})
    if not isinstance(prep, dict) or not prep.get("output"):
        raise ValueError(f"{run_dir.name}: missing preparation manifest output")
    path = _resolve_recorded_path(prep["output"])
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_parquet(path)
    frame["unit_id"] = frame["unit_id"].astype("string")
    return frame


def build_krt_commune(runs: list[tuple[Path, dict[str, Any]]], panel: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    geography = panel[["unit_id", "department"]].drop_duplicates("unit_id")
    for run_dir, manifest in runs:
        if _manifest_value(manifest, "model_key") != "krt_beta_binomial":
            continue
        latent_path = run_dir / "commune_latent_summaries.parquet"
        if not latent_path.exists():
            continue
        latent = pd.read_parquet(latent_path)
        latent["unit_id"] = latent["unit_id"].astype("string")
        prepared = _prepared_frame(run_dir, manifest)
        metadata_columns = [
            column
            for column in (
                "unit_id", "N_g", "vbbm", "vbbm_reference_year", "vbbm_status", "vbbm_source_column",
                "revenue", "revenue_reference_year", "revenue_status", "revenue_source_column",
                "capital", "capital_reference_year", "capital_status", "capital_source_column",
                "foreign_share", "foreign_share_reference_year", "foreign_share_status",
                "foreign_share_source_column", "region13",
            )
            if column in prepared
        ]
        merged = latent.merge(prepared[metadata_columns], on="unit_id", how="left", validate="one_to_one")
        merged = merged.merge(geography, on="unit_id", how="left", validate="one_to_one")
        election_id = str(_manifest_value(manifest, "election_id"))
        election = ELECTION_BY_ID[election_id]
        merged["panel_id"] = str(_manifest_value(manifest, "panel_id", _manifest_value(manifest, "sample_id")))
        merged["year"] = election.year
        merged["round"] = election.round
        merged["spec_version"] = str(_manifest_value(manifest, "spec_version", SPEC_VERSION))
        merged["harmonization_version"] = str(_manifest_value(manifest, "harmonization_version", HARMONIZATION_VERSION))
        merged["mcmc_status"] = str(manifest.get("diagnostic_status", ""))
        identification = manifest.get("identification_diagnostic", {})
        merged["identification_status"] = (
            str(identification.get("identification_status", "not_assessed"))
            if isinstance(identification, dict)
            else "not_assessed"
        )
        frames.append(merged.reindex(columns=KRT_COMMUNE_COLUMNS))
    result = pd.concat(frames, ignore_index=True) if frames else _empty(KRT_COMMUNE_COLUMNS)
    if not result.empty and result.duplicated(["run_id", "unit_id"]).any():
        raise AssertionError("KRT commune output contains duplicate run_id/unit_id keys")
    return result


def _contrast_summary(summary: pd.DataFrame) -> dict[str, float | int] | None:
    """Read the draw-wise contrast already persisted during the fit.

    Production intentionally deletes NetCDF traces after post-processing.  The
    aggregate CSV is therefore the durable source of the contrast and its
    interval; consolidation must not silently depend on a transient trace.
    """
    contrast = summary.loc[
        summary["beta_parameter"].astype(str).eq("b_1_minus_b_2")
        & summary["aggregation_method"].astype(str).eq("group_specific_population_v2")
    ]
    if contrast.empty:
        return None
    if len(contrast) != 1:
        raise AssertionError("stored KRT aggregate contains multiple canonical contrast rows")
    row = contrast.iloc[0]
    return {
        "mean": float(row["mean"]),
        "median": float(row["q50"]),
        "q025": float(row["q025"]),
        "q975": float(row["q975"]),
        "n_posterior_draws": int(row["n_posterior_draws"]),
    }


def build_krt_aggregate(runs: list[tuple[Path, dict[str, Any]]]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for run_dir, manifest in runs:
        if _manifest_value(manifest, "model_key") != "krt_beta_binomial":
            continue
        summary_path = run_dir / "aggregate_comparison_v2.csv"
        latent_path = run_dir / "commune_latent_summaries.parquet"
        if not summary_path.exists() or not latent_path.exists():
            continue
        summary = pd.read_csv(summary_path)
        summary = summary.loc[summary["aggregation_method"].eq("group_specific_population_v2")]
        latent = pd.read_parquet(latent_path)
        election_id = str(_manifest_value(manifest, "election_id"))
        election = ELECTION_BY_ID[election_id]
        identification = manifest.get("identification_diagnostic", {})
        common = {
            "panel_id": _manifest_value(manifest, "panel_id", _manifest_value(manifest, "sample_id")),
            "election_id": election_id,
            "year": election.year,
            "round": election.round,
            "scenario_id": _manifest_value(manifest, "scenario_id"),
            "run_id": manifest.get("run_id", run_dir.name),
            "model_key": "krt_beta_binomial",
            "spec_version": _manifest_value(manifest, "spec_version", SPEC_VERSION),
            "harmonization_version": _manifest_value(manifest, "harmonization_version", HARMONIZATION_VERSION),
            "n_communes": int(len(latent)),
            "draws": int(_manifest_value(manifest, "draws", 0)),
            "tune": int(_manifest_value(manifest, "tune", 0)),
            "chains": int(_manifest_value(manifest, "chains", 0)),
            "target_accept": float(_manifest_value(manifest, "target_accept", np.nan)),
            "max_treedepth": int(_manifest_value(manifest, "max_treedepth", 0)),
            "king_lambda": float(_manifest_value(manifest, "king_lambda", np.nan)),
            "mcmc_status": manifest.get("diagnostic_status", ""),
            "identification_status": identification.get("identification_status", "not_assessed") if isinstance(identification, dict) else "not_assessed",
        }
        weight_totals = {
            "b_1": float(pd.to_numeric(latent["b1_weight"], errors="raise").sum()),
            "b_2": float(pd.to_numeric(latent["b2_weight"], errors="raise").sum()),
        }
        beta_summary = summary.loc[summary["beta_parameter"].isin(weight_totals)]
        for item in beta_summary.to_dict("records"):
            parameter = str(item["beta_parameter"])
            rows.append(
                {
                    **common,
                    "estimand": parameter,
                    "weight_basis": item["weight_basis"],
                    "mean": item["mean"],
                    "median": item["q50"],
                    "q025": item["q025"],
                    "q975": item["q975"],
                    "n_posterior_draws": item["n_posterior_draws"],
                    "weight_total": weight_totals[parameter],
                }
            )
        contrast = _contrast_summary(summary)
        if contrast is not None:
            rows.append(
                {
                    **common,
                    "estimand": "b_1_minus_b_2",
                    "weight_basis": "group_specific_population_v2",
                    **contrast,
                    "weight_total": weight_totals["b_1"] + weight_totals["b_2"],
                }
            )
    result = pd.DataFrame(rows).reindex(columns=KRT_AGGREGATE_COLUMNS) if rows else _empty(KRT_AGGREGATE_COLUMNS)
    if not result.empty and result.duplicated(["run_id", "estimand"]).any():
        raise AssertionError("KRT aggregate output contains duplicate run_id/estimand keys")
    return result


def build_nls(runs: list[tuple[Path, dict[str, Any]]]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for run_dir, manifest in runs:
        model_key = str(_manifest_value(manifest, "model_key"))
        if not model_key.startswith("rosen_nls"):
            continue
        estimates_path = run_dir / "longitudinal_estimates.csv"
        diagnostics_path = run_dir / "model_diagnostics.csv"
        if not estimates_path.exists() or not diagnostics_path.exists():
            continue
        estimates = pd.read_csv(estimates_path)
        diagnostics = pd.read_csv(diagnostics_path).iloc[0].to_dict()
        starts_path = run_dir / "nls_start_diagnostics.csv"
        starts = pd.read_csv(starts_path) if starts_path.exists() else pd.DataFrame()
        max_difference = (
            float(pd.to_numeric(starts["max_abs_prediction_difference_from_best"], errors="coerce").max())
            if not starts.empty and "max_abs_prediction_difference_from_best" in starts
            else np.nan
        )
        common = {
            "panel_id": _manifest_value(manifest, "panel_id", _manifest_value(manifest, "sample_id")),
            "run_id": manifest.get("run_id", run_dir.name),
            "spec_version": _manifest_value(manifest, "spec_version", SPEC_VERSION),
            "harmonization_version": _manifest_value(manifest, "harmonization_version", HARMONIZATION_VERSION),
            "objective": diagnostics.get("objective_sse_unweighted", np.nan),
            "optimality": diagnostics.get("optimality", np.nan),
            "bread_rank": diagnostics.get("bread_rank", np.nan),
            "bread_condition": diagnostics.get("bread_condition", np.nan),
            "n_starts": diagnostics.get("n_starts", np.nan),
            "n_successful_starts": diagnostics.get("n_successful_starts", np.nan),
            "max_abs_solution_difference": max_difference,
            "fit_status": diagnostics.get("fit_status", ""),
            "diagnostic_status": diagnostics.get("diagnostic_status", ""),
        }
        for item in estimates.to_dict("records"):
            rows.append(
                {
                    **common,
                    "election_id": item["election_id"],
                    "year": item["year"],
                    "round": item["round"],
                    "scenario_id": item["scenario_id"],
                    "model_key": item["model_key"],
                    "estimand_type": "cell_probability",
                    "social_group": item["social_group"],
                    "vote_category": item["vote_category"],
                    "estimate": item["estimate"],
                    "n_communes": item["n_communes_used"],
                    "N_total": item["N_total"],
                    "boundary_estimate": bool(float(item["estimate"]) <= 1e-6 or float(item["estimate"]) >= 1 - 1e-6),
                }
            )
        scenario = SCENARIO_BY_ID.get(str(_manifest_value(manifest, "scenario_id")))
        if scenario is not None and scenario.model_family == "2x2":
            first_vote = scenario.vote_categories[0]
            groups = list(scenario.social_groups)
            selected = estimates.loc[estimates["vote_category"].eq(first_vote)].set_index("social_group")
            if all(group in selected.index for group in groups[:2]):
                first = estimates.iloc[0]
                rows.append(
                    {
                        **common,
                        "election_id": first["election_id"],
                        "year": first["year"],
                        "round": first["round"],
                        "scenario_id": first["scenario_id"],
                        "model_key": first["model_key"],
                        "estimand_type": "group_contrast",
                        "social_group": f"{groups[0]}_minus_{groups[1]}",
                        "vote_category": first_vote,
                        "estimate": float(selected.loc[groups[0], "estimate"] - selected.loc[groups[1], "estimate"]),
                        "n_communes": first["n_communes_used"],
                        "N_total": first["N_total"],
                        "boundary_estimate": False,
                    }
                )
    result = pd.DataFrame(rows).reindex(columns=NLS_COLUMNS) if rows else _empty(NLS_COLUMNS)
    keys = ["run_id", "estimand_type", "social_group", "vote_category"]
    if not result.empty and result.duplicated(keys).any():
        raise AssertionError("NLS output contains duplicate estimand keys")
    return result


def build_unified_audit(panel_id: str, panel: pd.DataFrame, runs: list[tuple[Path, dict[str, Any]]]) -> pd.DataFrame:
    inventory = pd.read_parquet(INVENTORY_PATH).assign(record_type="election_inventory", panel_id=panel_id)
    run_plan = pd.read_parquet(RUN_PLAN_PATH).assign(record_type="run_plan", panel_id=panel_id)
    presence = pd.read_parquet(PRESENCE_PATH)
    panel_membership = panel[["unit_id", "included_primary_2000", "master_draw_order"]].copy()
    presence = presence.merge(panel_membership, on="unit_id", how="left", validate="many_to_one")
    presence["included_primary_2000"] = presence["included_primary_2000"].fillna(False)
    presence = presence.assign(record_type="unit_election", panel_id=panel_id)
    parts = [presence, inventory, run_plan]
    for path, record_type in ((BALANCE_PATH, "balance"), (BALANCE_BY_ELECTION_PATH, "balance_by_election")):
        if path.exists():
            parts.append(pd.read_parquet(path).assign(record_type=record_type, panel_id=panel_id))
    config_rows: list[dict[str, object]] = []
    for run_dir, manifest in runs:
        config_rows.append(
            {
                "record_type": "model_configuration",
                "panel_id": panel_id,
                "election_id": _manifest_value(manifest, "election_id"),
                "scenario_id": _manifest_value(manifest, "scenario_id"),
                "run_id": manifest.get("run_id", run_dir.name),
                "model_key": _manifest_value(manifest, "model_key"),
                "status": manifest.get("status", ""),
                "diagnostic_status": manifest.get("diagnostic_status", ""),
                "parameters_json": json.dumps(manifest.get("parameters", {}), ensure_ascii=False, sort_keys=True),
                "spec_version": _manifest_value(manifest, "spec_version", SPEC_VERSION),
                "harmonization_version": _manifest_value(manifest, "harmonization_version", HARMONIZATION_VERSION),
            }
        )
    if config_rows:
        parts.append(pd.DataFrame(config_rows))
    return pd.concat(parts, ignore_index=True, sort=False)
