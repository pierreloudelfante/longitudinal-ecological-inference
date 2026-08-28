from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .audit_longitudinal import INVENTORY_PATH, PRESENCE_PATH, RUN_PLAN_PATH
from .build_panel import load_settings
from .build_longitudinal_panel import (
    BALANCE_BY_ELECTION_PATH,
    BALANCE_PATH,
    PANEL_MANIFEST_PATH,
    PANEL_PATH,
    load_longitudinal_panel_manifest,
)
from .paths import FIGURE_DIR, OUTPUT_DIR, ROOT, RUNS_DIR, ensure_runtime_dirs
from .postprocess_aggregates_v2 import aggregate_krt_trace_files_v2
from .spec_registry import (
    ELECTION_BY_ID,
    HARMONIZATION_VERSION,
    SCENARIO_BY_ID,
    SPEC_VERSION,
)
from .utils import file_sha256, portable_path, write_json


FINAL_DIR = OUTPUT_DIR / SPEC_VERSION / "final"
KRT_COMMUNE_PATH = FINAL_DIR / "longitudinal_krt_commune.parquet"
KRT_AGGREGATE_PATH = FINAL_DIR / "longitudinal_krt_aggregate.parquet"
NLS_PATH = FINAL_DIR / "longitudinal_nls.parquet"
AUDIT_PATH = FINAL_DIR / "longitudinal_audit.parquet"
REGRESSION_PATH = FINAL_DIR / "benchmark_regression.parquet"
FINAL_MANIFEST_PATH = FINAL_DIR / "release_manifest.json"
DELIVERABLE_DIR = ROOT / "deliverables" / SPEC_VERSION


KRT_COMMUNE_COLUMNS = [
    "panel_id",
    "election_id",
    "year",
    "round",
    "scenario_id",
    "run_id",
    "model_key",
    "spec_version",
    "harmonization_version",
    "unit_id",
    "department",
    "region13",
    "vbbm",
    "vbbm_reference_year",
    "vbbm_status",
    "vbbm_source_column",
    "revenue",
    "revenue_reference_year",
    "revenue_status",
    "revenue_source_column",
    "capital",
    "capital_reference_year",
    "capital_status",
    "capital_source_column",
    "foreign_share",
    "foreign_share_reference_year",
    "foreign_share_status",
    "foreign_share_source_column",
    "N_g",
    "b1_weight",
    "b2_weight",
    "b1_mean",
    "b1_sd",
    "b1_q025",
    "b1_q50",
    "b1_q975",
    "b2_mean",
    "b2_sd",
    "b2_q025",
    "b2_q50",
    "b2_q975",
    "mcmc_status",
    "identification_status",
]

KRT_AGGREGATE_COLUMNS = [
    "panel_id",
    "election_id",
    "year",
    "round",
    "scenario_id",
    "run_id",
    "model_key",
    "spec_version",
    "harmonization_version",
    "estimand",
    "weight_basis",
    "mean",
    "median",
    "q025",
    "q975",
    "n_posterior_draws",
    "n_communes",
    "weight_total",
    "draws",
    "tune",
    "chains",
    "target_accept",
    "max_treedepth",
    "king_lambda",
    "mcmc_status",
    "identification_status",
]

NLS_COLUMNS = [
    "panel_id",
    "election_id",
    "year",
    "round",
    "scenario_id",
    "run_id",
    "model_key",
    "spec_version",
    "harmonization_version",
    "estimand_type",
    "social_group",
    "vote_category",
    "estimate",
    "n_communes",
    "N_total",
    "objective",
    "optimality",
    "bread_rank",
    "bread_condition",
    "n_starts",
    "n_successful_starts",
    "max_abs_solution_difference",
    "boundary_estimate",
    "fit_status",
    "diagnostic_status",
]


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame({column: pd.Series(dtype="object") for column in columns})


def _resolve_recorded_path(value: object) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else ROOT / path


def _matching_run_manifests(panel_id: str) -> list[tuple[Path, dict[str, Any]]]:
    selected: dict[tuple[str, str, str, str], tuple[str, Path, dict[str, Any]]] = {}
    for manifest_path in RUNS_DIR.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("status") != "success":
            continue
        parameters = manifest.get("parameters", {})
        if not isinstance(parameters, dict):
            continue
        recorded_panel = str(manifest.get("panel_id", parameters.get("panel_id", manifest.get("sample_id", ""))))
        if recorded_panel != panel_id:
            continue
        key = (
            str(manifest.get("election_id", parameters.get("election_id", ""))),
            str(manifest.get("scenario_id", parameters.get("scenario_id", ""))),
            str(manifest.get("model_key", parameters.get("model_key", ""))),
            str(parameters.get("covariate_name", "")),
        )
        finished = str(manifest.get("finished_at_utc", ""))
        current = selected.get(key)
        if current is None or finished > current[0]:
            selected[key] = (finished, manifest_path.parent, manifest)
    return [(item[1], item[2]) for item in sorted(selected.values(), key=lambda row: row[1].name)]


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


def _manifest_value(manifest: dict[str, Any], name: str, default: object = "") -> object:
    parameters = manifest.get("parameters", {})
    return manifest.get(name, parameters.get(name, default)) if isinstance(parameters, dict) else manifest.get(name, default)


def _build_krt_commune(
    runs: list[tuple[Path, dict[str, Any]]],
    panel: pd.DataFrame,
) -> pd.DataFrame:
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
                "foreign_share", "foreign_share_reference_year", "foreign_share_status", "foreign_share_source_column",
                "region13",
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
        merged["harmonization_version"] = str(
            _manifest_value(manifest, "harmonization_version", HARMONIZATION_VERSION)
        )
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
        raise AssertionError("longitudinal KRT commune output contains duplicate run_id/unit_id keys")
    return result


def _contrast_summary(run_dir: Path) -> dict[str, float | int] | None:
    trace_path = run_dir / "trace.nc"
    latent_path = run_dir / "commune_latent_summaries.parquet"
    if not trace_path.exists() or not latent_path.exists():
        return None
    draws = aggregate_krt_trace_files_v2(trace_path, latent_path, include_legacy_comparison=False)
    values = np.asarray(draws["b_1_group_weighted"] - draws["b_2_group_weighted"], dtype=float).reshape(-1)
    return {
        "mean": float(values.mean()),
        "median": float(np.median(values)),
        "q025": float(np.quantile(values, 0.025)),
        "q975": float(np.quantile(values, 0.975)),
        "n_posterior_draws": int(values.size),
    }


def _build_krt_aggregate(runs: list[tuple[Path, dict[str, Any]]]) -> pd.DataFrame:
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
            "harmonization_version": _manifest_value(
                manifest, "harmonization_version", HARMONIZATION_VERSION
            ),
            "n_communes": int(len(latent)),
            "draws": int(_manifest_value(manifest, "draws", 0)),
            "tune": int(_manifest_value(manifest, "tune", 0)),
            "chains": int(_manifest_value(manifest, "chains", 0)),
            "target_accept": float(_manifest_value(manifest, "target_accept", np.nan)),
            "max_treedepth": int(_manifest_value(manifest, "max_treedepth", 0)),
            "king_lambda": float(_manifest_value(manifest, "king_lambda", np.nan)),
            "mcmc_status": manifest.get("diagnostic_status", ""),
            "identification_status": identification.get("identification_status", "not_assessed")
            if isinstance(identification, dict)
            else "not_assessed",
        }
        weight_totals = {
            "b_1": float(pd.to_numeric(latent["b1_weight"], errors="raise").sum()),
            "b_2": float(pd.to_numeric(latent["b2_weight"], errors="raise").sum()),
        }
        for item in summary.to_dict("records"):
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
        contrast = _contrast_summary(run_dir)
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
        raise AssertionError("longitudinal KRT aggregate output contains duplicate run_id/estimand keys")
    return result


def _build_nls(runs: list[tuple[Path, dict[str, Any]]]) -> pd.DataFrame:
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
            "harmonization_version": _manifest_value(
                manifest, "harmonization_version", HARMONIZATION_VERSION
            ),
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
                contrast = float(selected.loc[groups[0], "estimate"] - selected.loc[groups[1], "estimate"])
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
                        "estimate": contrast,
                        "n_communes": first["n_communes_used"],
                        "N_total": first["N_total"],
                        "boundary_estimate": False,
                    }
                )
    result = pd.DataFrame(rows).reindex(columns=NLS_COLUMNS) if rows else _empty(NLS_COLUMNS)
    keys = ["run_id", "estimand_type", "social_group", "vote_category"]
    if not result.empty and result.duplicated(keys).any():
        raise AssertionError("longitudinal NLS output contains duplicate estimand keys")
    return result


def _build_unified_audit(
    panel_id: str,
    panel: pd.DataFrame,
    runs: list[tuple[Path, dict[str, Any]]],
) -> pd.DataFrame:
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
                "harmonization_version": _manifest_value(
                    manifest, "harmonization_version", HARMONIZATION_VERSION
                ),
            }
        )
    if config_rows:
        parts.append(pd.DataFrame(config_rows))
    return pd.concat(parts, ignore_index=True, sort=False)


def _build_regression_bridge(nls: pd.DataFrame, krt: pd.DataFrame) -> pd.DataFrame:
    benchmark_dir = OUTPUT_DIR / "v2" / "priority_3000_final"
    rows: list[pd.DataFrame] = []
    old_nls_path = benchmark_dir / "nls_estimates_3000_v1.csv"
    if old_nls_path.exists() and not nls.empty:
        old = pd.read_csv(old_nls_path).rename(columns={"estimate": "benchmark_estimate"})
        new = nls.loc[nls["estimand_type"].eq("cell_probability")].rename(columns={"estimate": "new_estimate"})
        keys = ["election_id", "scenario_id", "model_key", "social_group", "vote_category"]
        compared = old.merge(new[keys + ["new_estimate", "panel_id"]], on=keys, how="inner")
        compared["comparison_type"] = "nls_cell"
        compared["difference"] = compared["new_estimate"] - compared["benchmark_estimate"]
        rows.append(compared)
    old_krt_path = benchmark_dir / "aggregate_drawwise_corrected_3000_v1.csv"
    if old_krt_path.exists() and not krt.empty:
        old = pd.read_csv(old_krt_path).rename(columns={"mean": "benchmark_estimate"})
        new = krt.loc[krt["estimand"].isin(["b_1", "b_2"])].rename(
            columns={"estimand": "beta_parameter", "mean": "new_estimate"}
        )
        keys = ["election_id", "scenario_id", "beta_parameter"]
        compared = old.merge(new[keys + ["new_estimate", "panel_id", "model_key"]], on=keys, how="inner")
        compared["comparison_type"] = "krt_aggregate"
        compared["difference"] = compared["new_estimate"] - compared["benchmark_estimate"]
        rows.append(compared)
    return pd.concat(rows, ignore_index=True, sort=False) if rows else pd.DataFrame()


def _plot_trajectories(krt: pd.DataFrame, nls: pd.DataFrame) -> int:
    if krt.empty and nls.empty:
        return 0
    import matplotlib.pyplot as plt

    output = FIGURE_DIR / SPEC_VERSION / "trajectories"
    output.mkdir(parents=True, exist_ok=True)
    count = 0
    family_styles = {
        "legislative": {"prefix": "leg_", "label": "législatives", "color": "#1f77b4"},
        "presidential": {"prefix": "pre_", "label": "présidentielles", "color": "#ff7f0e"},
    }
    for scenario_id in ("H0A", "H1"):
        figure, axis = plt.subplots(figsize=(10, 5.5))
        krt_part = krt.loc[
            krt["scenario_id"].eq(scenario_id) & krt["estimand"].eq("b_1_minus_b_2")
        ].copy()
        nls_part = nls.loc[
            nls["scenario_id"].eq(scenario_id) & nls["estimand_type"].eq("group_contrast")
        ].copy()
        for style in family_styles.values():
            krt_family = krt_part.loc[
                krt_part["election_id"].str.startswith(style["prefix"])
            ].sort_values("year")
            if not krt_family.empty:
                axis.plot(
                    krt_family["year"],
                    krt_family["mean"],
                    color=style["color"],
                    marker="o",
                    linestyle="-",
                    label=f"KRT {style['label']}",
                )
                axis.fill_between(
                    krt_family["year"],
                    krt_family["q025"],
                    krt_family["q975"],
                    color=style["color"],
                    alpha=0.15,
                )
            nls_family = nls_part.loc[
                nls_part["election_id"].str.startswith(style["prefix"])
            ].sort_values("year")
            if not nls_family.empty:
                axis.plot(
                    nls_family["year"],
                    nls_family["estimate"],
                    color=style["color"],
                    marker="s",
                    linestyle="--",
                    label=f"NLS {style['label']}",
                )
        axis.axhline(0, color="#666666", linewidth=0.8)
        axis.set_title(f"Trajectoire longitudinale {scenario_id}")
        axis.set_xlabel("Année")
        axis.set_ylabel("Contraste β₁−β₂")
        axis.grid(alpha=0.25)
        axis.legend()
        figure.tight_layout()
        figure.savefig(output / f"{scenario_id.lower()}_contrast.png", dpi=180)
        figure.savefig(output / f"{scenario_id.lower()}_contrast.svg")
        plt.close(figure)
        count += 2
    return count


def _density_audit_2022(krt_commune: pd.DataFrame) -> int:
    part = krt_commune.loc[krt_commune["election_id"].eq("leg_2022_r1")]
    if part.empty:
        return 0
    import matplotlib.pyplot as plt
    from scipy.stats import gaussian_kde

    output = FIGURE_DIR / SPEC_VERSION / "density_audit_2022"
    output.mkdir(parents=True, exist_ok=True)
    metrics: list[dict[str, object]] = []
    count = 0
    for scenario_id, frame in part.groupby("scenario_id", sort=True):
        x = frame["b1_mean"].to_numpy(dtype=float)
        y = frame["b2_mean"].to_numpy(dtype=float)
        figure, axes = plt.subplots(2, 3, figsize=(14, 9))
        axes[0, 0].scatter(x, y, s=7, alpha=0.35)
        axes[0, 0].set_title("Nuage brut")
        axes[0, 1].hexbin(x, y, gridsize=35, mincnt=1, cmap="viridis")
        axes[0, 1].set_title("Hexbin")
        grid = np.mgrid[0:1:100j, 0:1:100j]
        positions = np.vstack([grid[0].ravel(), grid[1].ravel()])
        native = gaussian_kde(np.vstack([x, y]))(positions).reshape(grid[0].shape)
        axes[0, 2].contourf(grid[0], grid[1], native, levels=15)
        axes[0, 2].set_title("KDE spécifique 2022")
        common = gaussian_kde(np.vstack([x, y]), bw_method=0.25)(positions).reshape(grid[0].shape)
        axes[1, 0].contourf(grid[0], grid[1], common, levels=15)
        axes[1, 0].set_title("KDE bande commune")
        clipped_x = np.clip(x, 1e-5, 1 - 1e-5)
        clipped_y = np.clip(y, 1e-5, 1 - 1e-5)
        logit = np.vstack([np.log(clipped_x / (1 - clipped_x)), np.log(clipped_y / (1 - clipped_y))])
        axes[1, 1].hexbin(logit[0], logit[1], gridsize=35, mincnt=1, cmap="magma")
        axes[1, 1].set_title("Transformation logit")
        axes[1, 2].hist(frame["b1_q975"] - frame["b1_q025"], bins=35, alpha=0.55, label="β₁")
        axes[1, 2].hist(frame["b2_q975"] - frame["b2_q025"], bins=35, alpha=0.55, label="β₂")
        axes[1, 2].set_title("Largeurs des intervalles")
        axes[1, 2].legend()
        for axis in axes.flat[:4]:
            axis.set_xlabel("β₁")
            axis.set_ylabel("β₂")
        figure.suptitle(f"Audit de densité 2022 — {scenario_id}")
        figure.tight_layout()
        figure.savefig(output / f"{scenario_id.lower()}_density_audit.png", dpi=180)
        figure.savefig(output / f"{scenario_id.lower()}_density_audit.svg")
        plt.close(figure)
        metrics.append(
            {
                "scenario_id": scenario_id,
                "n_communes": len(frame),
                "share_b1_near_boundary": float(np.mean((x < 0.01) | (x > 0.99))),
                "share_b2_near_boundary": float(np.mean((y < 0.01) | (y > 0.99))),
                "median_b1_interval_width": float(np.median(frame["b1_q975"] - frame["b1_q025"])),
                "median_b2_interval_width": float(np.median(frame["b2_q975"] - frame["b2_q025"])),
            }
        )
        count += 2
    pd.DataFrame(metrics).to_parquet(output / "density_audit_metrics.parquet", index=False)
    return count


def _validate_final_outputs(
    krt_commune: pd.DataFrame,
    krt_aggregate: pd.DataFrame,
    nls: pd.DataFrame,
    audit: pd.DataFrame,
) -> dict[str, object]:
    run_plan = pd.read_parquet(RUN_PLAN_PATH)
    expected_nls = int(run_plan["preparation_status"].eq("admissible").sum())
    expected_krt = int((
        run_plan["preparation_status"].eq("admissible")
        & run_plan["scenario_id"].isin(["H0A", "H1"])
    ).sum())
    actual_nls = int(nls[["election_id", "scenario_id"]].drop_duplicates().shape[0]) if not nls.empty else 0
    actual_krt = int(krt_aggregate[["election_id", "scenario_id"]].drop_duplicates().shape[0]) if not krt_aggregate.empty else 0
    quantiles_complete = bool(
        krt_commune[[
            "b1_sd", "b1_q025", "b1_q50", "b1_q975", "b2_sd", "b2_q025", "b2_q50", "b2_q975"
        ]].notna().all().all()
    ) if not krt_commune.empty else False
    contrasts = krt_aggregate.loc[krt_aggregate["estimand"].eq("b_1_minus_b_2")]
    contrast_complete = bool(
        len(contrasts) == actual_krt
        and contrasts
        [["mean", "median", "q025", "q975"]]
        .notna()
        .all()
        .all()
    ) if actual_krt else False
    accepted_mcmc = bool(krt_aggregate["mcmc_status"].isin(["pass", "caveat"]).all()) if actual_krt else False
    mcmc = load_settings()["mcmc"]
    production_krt = bool(
        krt_aggregate[["run_id", "draws", "tune", "chains", "target_accept", "max_treedepth", "king_lambda"]]
        .drop_duplicates("run_id")
        .assign(
            valid=lambda frame: (
                frame["draws"].eq(int(mcmc["production_draws"]))
                & frame["tune"].eq(int(mcmc["production_tune"]))
                & frame["chains"].eq(int(mcmc["production_chains"]))
                & np.isclose(frame["target_accept"], float(mcmc["target_accept"]))
                & frame["max_treedepth"].eq(int(mcmc["max_treedepth"]))
                & np.isclose(frame["king_lambda"], float(mcmc["king_lambda"]))
            )
        )["valid"]
        .all()
    ) if actual_krt else False
    unit_election = audit.loc[audit["record_type"].eq("unit_election")]
    audit_unique = not unit_election.duplicated(["unit_id", "election_id"]).any()
    ready = bool(
        actual_nls == expected_nls
        and actual_krt == expected_krt
        and quantiles_complete
        and contrast_complete
        and accepted_mcmc
        and production_krt
        and audit_unique
    )
    return {
        "ready": ready,
        "expected_nls_pairs": expected_nls,
        "actual_nls_pairs": actual_nls,
        "expected_krt_pairs": expected_krt,
        "actual_krt_pairs": actual_krt,
        "commune_quantiles_complete": quantiles_complete,
        "krt_contrasts_complete": contrast_complete,
        "mcmc_statuses_accepted": accepted_mcmc,
        "krt_production_settings_valid": production_krt,
        "unit_election_audit_unique": audit_unique,
    }


def finalize_longitudinal() -> dict[str, object]:
    ensure_runtime_dirs()
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    panel_manifest = load_longitudinal_panel_manifest()
    panel_id = str(panel_manifest["panel_id"])
    panel = pd.read_parquet(PANEL_PATH)
    panel["unit_id"] = panel["unit_id"].astype("string")
    runs = _matching_run_manifests(panel_id)
    krt_commune = _build_krt_commune(runs, panel)
    krt_aggregate = _build_krt_aggregate(runs)
    nls = _build_nls(runs)
    audit = _build_unified_audit(panel_id, panel, runs)
    krt_commune.to_parquet(KRT_COMMUNE_PATH, index=False)
    krt_aggregate.to_parquet(KRT_AGGREGATE_PATH, index=False)
    nls.to_parquet(NLS_PATH, index=False)
    audit.to_parquet(AUDIT_PATH, index=False)
    regression = _build_regression_bridge(nls, krt_aggregate)
    regression.to_parquet(REGRESSION_PATH, index=False)
    trajectory_files = _plot_trajectories(krt_aggregate, nls)
    density_files = _density_audit_2022(krt_commune)
    validation = _validate_final_outputs(krt_commune, krt_aggregate, nls, audit)
    outputs = {
        "longitudinal_krt_commune": KRT_COMMUNE_PATH,
        "longitudinal_krt_aggregate": KRT_AGGREGATE_PATH,
        "longitudinal_nls": NLS_PATH,
        "longitudinal_audit": AUDIT_PATH,
    }
    manifest = {
        "schema_version": "longitudinal_release_manifest_v1",
        "spec_version": SPEC_VERSION,
        "harmonization_version": HARMONIZATION_VERSION,
        "panel_id": panel_id,
        "panel_sha256": panel_manifest["panel_sha256"],
        "validation": validation,
        "selected_successful_runs": len(runs),
        "trajectory_files": trajectory_files,
        "density_audit_files": density_files,
        "outputs": {
            name: {
                "path": portable_path(path, root=ROOT),
                "rows": int(pd.read_parquet(path).shape[0]),
                "sha256": file_sha256(path),
            }
            for name, path in outputs.items()
        },
        "benchmark_regression": {
            "path": portable_path(REGRESSION_PATH, root=ROOT),
            "rows": int(len(regression)),
            "sha256": file_sha256(REGRESSION_PATH),
        },
        "netcdf_included_in_release": False,
    }
    write_json(FINAL_MANIFEST_PATH, manifest)
    return manifest


def build_longitudinal_release(*, allow_incomplete: bool = False) -> dict[str, object]:
    manifest = finalize_longitudinal()
    if not manifest["validation"]["ready"] and not allow_incomplete:
        raise RuntimeError("longitudinal release is incomplete; inspect release_manifest.json")
    DELIVERABLE_DIR.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for source in (KRT_COMMUNE_PATH, KRT_AGGREGATE_PATH, NLS_PATH, AUDIT_PATH, REGRESSION_PATH, FINAL_MANIFEST_PATH):
        target = DELIVERABLE_DIR / source.name
        shutil.copy2(source, target)
        copied.append(target)
    readme = DELIVERABLE_DIR / "README.md"
    readme.write_text(
        "# longitudinal_2000_v1\n\n"
        "Release longitudinale sur panel communal versionné. Les quatre fichiers Parquet "
        "constituent l'interface publique. Les traces NetCDF ne sont pas incluses.\n",
        encoding="utf-8",
    )
    copied.append(readme)
    release_manifest = {
        "spec_version": SPEC_VERSION,
        "complete": bool(manifest["validation"]["ready"]),
        "files": [
            {
                "path": path.relative_to(DELIVERABLE_DIR).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }
            for path in copied
        ],
        "contains_netcdf": False,
    }
    write_json(DELIVERABLE_DIR / "file_manifest.json", release_manifest)
    return release_manifest


__all__ = [
    "AUDIT_PATH",
    "FINAL_MANIFEST_PATH",
    "KRT_AGGREGATE_PATH",
    "KRT_COMMUNE_PATH",
    "NLS_PATH",
    "build_longitudinal_release",
    "finalize_longitudinal",
]
