from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from .paths import ROOT, RUNS_DIR
from .release_scope import ReleaseScope, caveat_severity, load_release_scope
from .spec_registry import ELECTION_BY_ID, SCENARIO_BY_ID
from .utils import file_sha256


SOURCE_V101 = ROOT / "work" / "longitudinal_2000_v1.0.1_H0A_H1_validated"
CANDIDATE_V102 = ROOT / "work" / "longitudinal_2000_v1.0.2_H0A_H1_candidate"


def _write_parquet_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _result_path(root: Path, filename: str) -> Path:
    return root / "01_resultats_python" / filename


def _selection_path(root: Path) -> Path:
    return root / "02_syntheses" / "canonical_run_selection.csv"


def validate_selection(selection: pd.DataFrame, scope: ReleaseScope) -> pd.DataFrame:
    required = {"election_id", "scenario_id", "run_id", "run_role"}
    missing = sorted(required.difference(selection.columns))
    if missing:
        raise AssertionError(f"canonical selection is missing fields: {missing}")
    selected = selection.loc[selection["scenario_id"].isin(scope.krt_scenarios)].copy()
    if len(selected) != scope.expected_krt_pairs:
        raise AssertionError(
            f"canonical selection has {len(selected)} scoped rows, expected {scope.expected_krt_pairs}"
        )
    if selected[["election_id", "scenario_id"]].duplicated().any():
        raise AssertionError("canonical selection contains duplicate election-scenario pairs")
    if set(selected["scenario_id"].astype(str)) != set(scope.krt_scenarios):
        raise AssertionError("canonical selection does not cover the configured scenarios")
    if not selected["run_role"].eq("canonical").all():
        raise AssertionError("every selected public KRT run must have run_role=canonical")
    return selected.sort_values(["scenario_id", "election_id"]).reset_index(drop=True)


def migrate_public_schema(source_root: Path, candidate_root: Path, scope: ReleaseScope) -> dict[str, Any]:
    source_commune = pd.read_parquet(_result_path(source_root, "longitudinal_krt_commune.parquet"))
    commune = pd.read_parquet(_result_path(candidate_root, "longitudinal_krt_commune.parquet"))
    rename = {}
    if "revenue" in commune.columns:
        rename["revenue"] = "revenue_ratio"
    if "capital" in commune.columns:
        rename["capital"] = "capital_ratio"
    commune = commune.rename(columns=rename)
    for required in ("revenue_ratio", "capital_ratio", "foreign_share"):
        if required not in commune.columns:
            raise AssertionError(f"missing migrated public field: {required}")

    panel = pd.read_csv(
        candidate_root / "03_panel_et_audit" / "panel_primaire_2000.csv",
        dtype={"unit_id": "string"},
    )
    if len(panel) != scope.panel_size or panel["unit_id"].duplicated().any():
        raise AssertionError("primary panel must contain the configured number of unique unit_id values")
    names = panel[["unit_id", "commune_name", "harmonization_version"]].rename(
        columns={
            "commune_name": "commune_name_canonical",
            "harmonization_version": "geography_version",
        }
    )
    commune["unit_id"] = commune["unit_id"].astype("string")
    for old in ("commune_name_canonical", "commune_name_reference_year", "geography_version"):
        if old in commune.columns:
            commune = commune.drop(columns=old)
    commune = commune.merge(names, on="unit_id", how="left", validate="many_to_one")
    if commune["commune_name_canonical"].isna().any() or commune["geography_version"].isna().any():
        raise AssertionError("canonical commune-name join lost rows")
    commune["commune_name_reference_year"] = 2022
    commune["public_schema_version"] = scope.public_schema_version

    aggregate = pd.read_parquet(_result_path(candidate_root, "longitudinal_krt_aggregate.parquet"))
    nls = pd.read_parquet(_result_path(candidate_root, "longitudinal_nls.parquet"))
    aggregate["public_schema_version"] = scope.public_schema_version
    nls["public_schema_version"] = scope.public_schema_version

    _write_parquet_atomic(commune, _result_path(candidate_root, "longitudinal_krt_commune.parquet"))
    _write_parquet_atomic(aggregate, _result_path(candidate_root, "longitudinal_krt_aggregate.parquet"))
    _write_parquet_atomic(nls, _result_path(candidate_root, "longitudinal_nls.parquet"))

    migration = pd.DataFrame(
        [
            {
                "v1_0_1_column": "revenue",
                "v1_0_2_column": "revenue_ratio",
                "treatment": "renamed",
                "scientific_value_changed": False,
                "comment": "Ratio communal joint aux sorties; non inclus comme covariable KRT.",
            },
            {
                "v1_0_1_column": "capital",
                "v1_0_2_column": "capital_ratio",
                "treatment": "renamed",
                "scientific_value_changed": False,
                "comment": "Ratio communal joint aux sorties; non inclus comme covariable KRT.",
            },
            {
                "v1_0_1_column": "immigrant_share",
                "v1_0_2_column": "foreign_share",
                "treatment": "historical_alias_deprecated",
                "scientific_value_changed": False,
                "comment": "L'alias historique etait deja absent de la table publique v1.0.1.",
            },
            {
                "v1_0_1_column": "",
                "v1_0_2_column": "commune_name_canonical",
                "treatment": "added",
                "scientific_value_changed": False,
                "comment": "Nom canonique joint depuis le referentiel communal 2022.",
            },
            {
                "v1_0_1_column": "",
                "v1_0_2_column": "commune_name_reference_year",
                "treatment": "added",
                "scientific_value_changed": False,
                "comment": "Annee de reference du nom canonique: 2022.",
            },
            {
                "v1_0_1_column": "",
                "v1_0_2_column": "geography_version",
                "treatment": "added",
                "scientific_value_changed": False,
                "comment": "Version du referentiel geographique harmonise.",
            },
            {
                "v1_0_1_column": "",
                "v1_0_2_column": "public_schema_version",
                "treatment": "added",
                "scientific_value_changed": False,
                "comment": "Version explicite de l'interface publique.",
            },
        ]
    )
    _write_csv(
        migration,
        candidate_root / "03_panel_et_audit" / "SCHEMA_MIGRATION_v1.0.1_to_v1.0.2.csv",
    )
    return {
        "source_commune_rows": int(len(source_commune)),
        "commune_rows": int(len(commune)),
        "aggregate_rows": int(len(aggregate)),
        "nls_rows": int(len(nls)),
        "renamed_columns": rename,
    }


def _canonical_manifests(candidate_root: Path, scope: ReleaseScope) -> list[dict[str, Any]]:
    selection = validate_selection(pd.read_csv(_selection_path(candidate_root), dtype="string"), scope)
    rows: list[dict[str, Any]] = []
    for selected in selection.itertuples(index=False):
        manifest_path = RUNS_DIR / str(selected.run_id) / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(manifest_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        parameters = manifest.get("parameters", {})
        if manifest.get("status") != "success":
            raise AssertionError(f"canonical run is not successful: {selected.run_id}")
        if parameters.get("election_id") != selected.election_id:
            raise AssertionError(f"election mismatch in canonical manifest {selected.run_id}")
        if parameters.get("scenario_id") != selected.scenario_id:
            raise AssertionError(f"scenario mismatch in canonical manifest {selected.run_id}")
        rows.append({"selection": selected._asdict(), "manifest": manifest})
    return rows


def build_canonical_diagnostics(candidate_root: Path, scope: ReleaseScope) -> tuple[pd.DataFrame, pd.DataFrame]:
    records: list[dict[str, Any]] = []
    for item in _canonical_manifests(candidate_root, scope):
        selected = item["selection"]
        manifest = item["manifest"]
        election = ELECTION_BY_ID[str(selected["election_id"])]
        diagnostic = manifest.get("canonical_mcmc_diagnostic", {})
        identification = manifest.get("identification_diagnostic", {})
        status = str(diagnostic.get("mcmc_status", selected.get("mcmc_status", "")))
        min_ess_values = [diagnostic.get("min_ess_bulk"), diagnostic.get("min_ess_tail")]
        min_ess = min(float(value) for value in min_ess_values if value is not None)
        severity = caveat_severity(
            official_status=status,
            max_rhat=diagnostic.get("max_rhat"),
            min_ess=min_ess,
            min_bfmi=diagnostic.get("min_bfmi"),
            divergences=diagnostic.get("divergences"),
            treedepth_saturated=diagnostic.get("max_treedepth_hits"),
        )
        records.append(
            {
                "election_id": election.election_id,
                "election_type": election.election_type,
                "year": election.year,
                "scenario_id": str(selected["scenario_id"]),
                "run_id": str(selected["run_id"]),
                "run_role": str(selected["run_role"]),
                "mcmc_status": status,
                "mcmc_caveat_severity": severity,
                "identification_status": str(identification.get("identification_status", selected.get("identification_status", ""))),
                "max_rhat": diagnostic.get("max_rhat"),
                "min_ess_bulk": diagnostic.get("min_ess_bulk"),
                "min_ess_tail": diagnostic.get("min_ess_tail"),
                "min_ess": min_ess,
                "min_bfmi": diagnostic.get("min_bfmi"),
                "divergences": diagnostic.get("divergences"),
                "max_treedepth_hits": diagnostic.get("max_treedepth_hits"),
                "mean_acceptance_rate": diagnostic.get("mean_acceptance_rate"),
                "elapsed_seconds": manifest.get("elapsed_seconds"),
                "peak_memory_mb": manifest.get("peak_memory_mb"),
                "n_communes": manifest.get("n_communes_used"),
                "panel_sha256": manifest.get("panel_sha256"),
                "input_model_ready_sha256": next(iter(manifest.get("input_sha256", {}).values()), ""),
                "diagnostic_schema_version": diagnostic.get("diagnostic_schema_version"),
                "identification_schema_version": identification.get("identification_schema_version"),
            }
        )
    diagnostics = pd.DataFrame(records).sort_values(["scenario_id", "year", "election_id"])
    if len(diagnostics) != scope.expected_krt_pairs:
        raise AssertionError("canonical diagnostic row count does not match release scope")
    summary = (
        diagnostics.groupby(["scenario_id", "mcmc_status"], dropna=False)
        .size()
        .rename("n_runs")
        .reset_index()
    )
    expected = scope.expected_krt_status_counts
    for scenario_id, counts in expected.items():
        for status, count in counts.items():
            observed = int(
                summary.loc[
                    summary["scenario_id"].eq(scenario_id) & summary["mcmc_status"].eq(status),
                    "n_runs",
                ].sum()
            )
            if observed != int(count):
                raise AssertionError(
                    f"unexpected canonical status count for {scenario_id}/{status}: {observed} != {count}"
                )
    synthesis = candidate_root / "02_syntheses"
    _write_csv(diagnostics, synthesis / "diagnostics_krt_par_election.csv")
    _write_csv(summary, synthesis / "diagnostics_krt_resume.csv")
    return diagnostics, summary


def build_trajectory_table(candidate_root: Path, scope: ReleaseScope) -> pd.DataFrame:
    aggregate = pd.read_parquet(_result_path(candidate_root, "longitudinal_krt_aggregate.parquet"))
    trajectory = aggregate.loc[aggregate["scenario_id"].isin(scope.krt_scenarios)].copy()
    trajectory["election_type"] = trajectory["election_id"].map(
        {election_id: election.election_type for election_id, election in ELECTION_BY_ID.items()}
    )
    trajectory = trajectory.sort_values(["scenario_id", "estimand", "election_type", "year", "election_id"])
    if len(trajectory) != scope.expected_krt_aggregate_rows:
        raise AssertionError("trajectory table does not match derived aggregate count")
    _write_csv(trajectory, candidate_root / "02_syntheses" / "trajectoires_krt.csv")
    return trajectory


def _figure_prefix(scenario_id: str) -> str:
    return scenario_id.lower().replace("-", "_")


def plot_contrast_trajectories(candidate_root: Path, scope: ReleaseScope, trajectory: pd.DataFrame) -> list[Path]:
    output = candidate_root / "04_figures" / "trajectories"
    essentials = candidate_root / "04_figures_essentielles"
    output.mkdir(parents=True, exist_ok=True)
    essentials.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    family_labels = {"legislative": "Legislatives", "presidential": "Presidentielles"}
    colors = {"legislative": "#2f6b9a", "presidential": "#d0823b"}
    contrast = trajectory.loc[trajectory["estimand"].eq("b_1_minus_b_2")].copy()
    for scenario_id in scope.krt_scenarios:
        part = contrast.loc[contrast["scenario_id"].eq(scenario_id)]
        fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.8), sharey=True, constrained_layout=True)
        for axis, election_type in zip(axes, ("legislative", "presidential")):
            sub = part.loc[part["election_type"].eq(election_type)].sort_values("year")
            x = sub["year"].to_numpy(dtype=int)
            mean = sub["mean"].to_numpy(dtype=float)
            lower = sub["q025"].to_numpy(dtype=float)
            upper = sub["q975"].to_numpy(dtype=float)
            axis.errorbar(
                x,
                mean,
                yerr=np.vstack([mean - lower, upper - mean]),
                color=colors[election_type],
                marker="o",
                linewidth=1.4,
                capsize=2.5,
            )
            axis.axhline(0.0, color="#555555", linewidth=0.8, linestyle="--")
            axis.set_title(family_labels[election_type])
            axis.set_xlabel("Annee du scrutin")
            axis.set_xticks(x)
            axis.tick_params(axis="x", rotation=55)
            axis.grid(axis="y", color="#dddddd", linewidth=0.6)
        axes[0].set_ylabel("Contraste agrege beta1 - beta2")
        fig.suptitle(f"{scenario_id} - trajectoire KRT sur le panel fixe de {scope.panel_size} communes")
        prefix = _figure_prefix(scenario_id) + "_contrast"
        for extension, dpi in (("png", 220), ("svg", None)):
            path = output / f"{prefix}.{extension}"
            fig.savefig(path, dpi=dpi, bbox_inches="tight")
            generated.append(path)
        essential = essentials / f"{prefix}.png"
        fig.savefig(essential, dpi=220, bbox_inches="tight")
        generated.append(essential)
        plt.close(fig)
    return generated


def plot_h2_h3_target_probabilities(
    candidate_root: Path,
    scope: ReleaseScope,
    trajectory: pd.DataFrame,
) -> Path | None:
    """Compare target probabilities descriptively, never as a joint posterior difference."""
    if not {"H2", "H3"}.issubset(scope.krt_scenarios):
        return None
    target = trajectory.loc[
        trajectory["scenario_id"].isin(["H2", "H3"])
        & trajectory["estimand"].eq("b_1")
    ].copy()
    if len(target) != scope.expected_elections * 2:
        raise AssertionError("H2/H3 target-probability trajectory is incomplete")
    styles = {
        "H2": {"color": "#2f6b9a", "marker": "o", "linestyle": "-", "label": "H2: P(gauche | ouvriers)"},
        "H3": {"color": "#d0823b", "marker": "s", "linestyle": "--", "label": "H3: P(gauche | employes)"},
    }
    family_labels = {"legislative": "Legislatives", "presidential": "Presidentielles"}
    fig, axes = plt.subplots(1, 2, figsize=(13.0, 5.1), sharey=True, constrained_layout=True)
    for axis, election_type in zip(axes, ("legislative", "presidential")):
        for scenario_id in ("H2", "H3"):
            sub = target.loc[
                target["election_type"].eq(election_type)
                & target["scenario_id"].eq(scenario_id)
            ].sort_values("year")
            style = styles[scenario_id]
            x = sub["year"].to_numpy(dtype=int)
            mean = sub["mean"].to_numpy(dtype=float)
            lower = sub["q025"].to_numpy(dtype=float)
            upper = sub["q975"].to_numpy(dtype=float)
            axis.errorbar(
                x,
                mean,
                yerr=np.vstack([mean - lower, upper - mean]),
                color=style["color"],
                marker=style["marker"],
                markerfacecolor="white" if scenario_id == "H3" else style["color"],
                linestyle=style["linestyle"],
                linewidth=1.45,
                capsize=2.4,
                label=style["label"],
            )
        axis.set_title(family_labels[election_type])
        axis.set_xlabel("Annee du scrutin")
        years = sorted(target.loc[target["election_type"].eq(election_type), "year"].unique())
        axis.set_xticks(years)
        axis.tick_params(axis="x", rotation=55)
        axis.grid(axis="y", color="#dddddd", linewidth=0.6)
        axis.set_ylim(0, 1)
    axes[0].set_ylabel("Probabilite agregee estimee du vote de gauche")
    axes[0].legend(frameon=False, loc="best")
    fig.suptitle(
        "H2 et H3 - probabilites cibles estimees separement\n"
        "Comparaison descriptive de deux modeles aux complements differents"
    )
    essentials = candidate_root / "04_figures_essentielles"
    essentials.mkdir(parents=True, exist_ok=True)
    path = essentials / "h2_h3_target_probabilities_descriptive.png"
    fig.savefig(path, dpi=220, bbox_inches="tight")
    svg = candidate_root / "04_figures" / "trajectories" / "h2_h3_target_probabilities_descriptive.svg"
    svg.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(svg, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_diagnostic_status(candidate_root: Path, scope: ReleaseScope, diagnostics: pd.DataFrame) -> Path:
    """Show MCMC status counts without merging them with identification status."""
    counts = (
        diagnostics.groupby(["scenario_id", "mcmc_status"])
        .size()
        .rename("n_runs")
        .reset_index()
    )
    scenarios = list(scope.krt_scenarios)
    statuses = ("pass", "caveat", "fail")
    colors = {"pass": "#2f6b9a", "caveat": "#d0823b", "fail": "#6b7280"}
    x = np.arange(len(scenarios))
    fig, axis = plt.subplots(figsize=(9.8, 4.8), constrained_layout=True)
    bottom = np.zeros(len(scenarios), dtype=float)
    for status in statuses:
        values = np.array([
            int(counts.loc[
                counts["scenario_id"].eq(scenario_id)
                & counts["mcmc_status"].eq(status),
                "n_runs",
            ].sum())
            for scenario_id in scenarios
        ])
        bars = axis.bar(x, values, bottom=bottom, label=status, color=colors[status], edgecolor="#27313a")
        for bar, value, base in zip(bars, values, bottom):
            if value:
                axis.text(
                    bar.get_x() + bar.get_width() / 2,
                    base + value / 2,
                    str(int(value)),
                    ha="center",
                    va="center",
                    fontsize=9,
                    color="white" if status != "caveat" else "#1f2933",
                    fontweight="bold",
                )
        bottom += values
    axis.set_xticks(x, scenarios)
    axis.set_ylabel("Nombre de runs canoniques")
    axis.set_title("Diagnostics MCMC canoniques par hypothese")
    axis.set_ylim(0, max(scope.expected_elections + 2, float(bottom.max()) + 2))
    axis.legend(frameon=False, ncol=3, loc="upper center")
    axis.grid(axis="y", color="#e5e7eb", linewidth=0.6)
    output = candidate_root / "04_figures_essentielles" / "mcmc_status_by_scenario.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return output


def write_chart_map(candidate_root: Path, scope: ReleaseScope) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for scenario_id in scope.krt_scenarios:
        records.append({
            "report_segment": f"Trajectoire {scenario_id}",
            "analytical_question": "Comment le contraste KRT evolue-t-il entre scrutins de meme famille ?",
            "chart_family": "Uncertainty & Benchmark",
            "chart_type": "faceted dot-and-interval trajectory",
            "fields": "year,election_type,mean,q025,q975",
            "supported_claim": "Trajectoire descriptive du contraste agrege avec incertitude posterieure.",
            "palette_policy": "hard two-root cap; one root per election family",
            "delivery_path": f"04_figures_essentielles/{_figure_prefix(scenario_id)}_contrast.png",
            "source": "01_resultats_python/longitudinal_krt_aggregate.parquet",
        })
    if {"H2", "H3"}.issubset(scope.krt_scenarios):
        records.append({
            "report_segment": "Probabilites cibles H2/H3",
            "analytical_question": "Comment P(gauche|ouvriers) et P(gauche|employes) evoluent-elles dans leurs modeles separes ?",
            "chart_family": "Uncertainty & Benchmark",
            "chart_type": "faceted two-series dot-and-interval trajectory",
            "fields": "year,election_type,scenario_id,mean,q025,q975",
            "supported_claim": "Comparaison visuelle descriptive des deux beta1; aucune difference posterieure jointe.",
            "palette_policy": "hard two-root cap plus line-style and marker-shape distinction",
            "delivery_path": "04_figures_essentielles/h2_h3_target_probabilities_descriptive.png",
            "source": "01_resultats_python/longitudinal_krt_aggregate.parquet",
        })
    records.extend([
        {
            "report_segment": "Comparaison KRT-NLS",
            "analytical_question": "Le contraste NLS reste-t-il compatible avec l'intervalle KRT par scrutin ?",
            "chart_family": "Uncertainty & Benchmark",
            "chart_type": "faceted point-and-interval comparison",
            "fields": "election_id,scenario_id,krt_contrast_mean,krt_contrast_q025,krt_contrast_q975,nls_contrast",
            "supported_claim": "Comparaison de methode sans pseudo-intervalle NLS.",
            "palette_policy": "single-root preferred plus neutral NLS markers",
            "delivery_path": "04_figures_essentielles/krt_nls_comparison.png",
            "source": "01_resultats_python/longitudinal_krt_aggregate.parquet;01_resultats_python/longitudinal_nls.parquet",
        },
        {
            "report_segment": "Diagnostics MCMC",
            "analytical_question": "Combien de runs canoniques sont pass, caveat ou fail par hypothese ?",
            "chart_family": "Composition",
            "chart_type": "stacked bar",
            "fields": "scenario_id,mcmc_status,n_runs",
            "supported_claim": "Etat numerique MCMC, distinct de l'identification ecologique.",
            "palette_policy": "hard two-root cap plus neutral fail",
            "delivery_path": "04_figures_essentielles/mcmc_status_by_scenario.png",
            "source": "02_syntheses/diagnostics_krt_par_election.csv",
        },
    ])
    frame = pd.DataFrame(records)
    _write_csv(frame, candidate_root / "04_figures_essentielles" / "CHART_MAP.csv")
    return frame


def build_krt_nls_comparison(candidate_root: Path, scope: ReleaseScope) -> pd.DataFrame:
    aggregate = pd.read_parquet(_result_path(candidate_root, "longitudinal_krt_aggregate.parquet"))
    nls = pd.read_parquet(_result_path(candidate_root, "longitudinal_nls.parquet"))
    krt = aggregate.loc[
        aggregate["scenario_id"].isin(scope.krt_scenarios)
        & aggregate["estimand"].eq("b_1_minus_b_2")
    ].copy()
    rows: list[dict[str, Any]] = []
    for (election_id, scenario_id), part in nls.loc[
        nls["scenario_id"].isin(scope.krt_scenarios)
    ].groupby(["election_id", "scenario_id"], sort=False):
        scenario = SCENARIO_BY_ID[str(scenario_id)]
        target_vote = scenario.vote_categories[0]
        cells = part.loc[
            part["estimand_type"].eq("cell_probability")
            & part["vote_category"].eq(target_vote)
        ].set_index("social_group")
        if not {"target_group", "complement_group"}.issubset(cells.index):
            raise AssertionError(f"missing NLS 2x2 cells for {election_id}/{scenario_id}")
        beta1 = float(cells.loc["target_group", "estimate"])
        beta2 = float(cells.loc["complement_group", "estimate"])
        rows.append(
            {
                "election_id": election_id,
                "scenario_id": scenario_id,
                "nls_run_id": str(cells.iloc[0]["run_id"]),
                "nls_target_vote": target_vote,
                "nls_beta1": beta1,
                "nls_beta2": beta2,
                "nls_contrast": beta1 - beta2,
                "nls_diagnostic_status": str(cells.iloc[0]["diagnostic_status"]),
            }
        )
    comparison = krt.rename(
        columns={
            "run_id": "krt_run_id",
            "mean": "krt_contrast_mean",
            "q025": "krt_contrast_q025",
            "q975": "krt_contrast_q975",
        }
    ).merge(pd.DataFrame(rows), on=["election_id", "scenario_id"], how="left", validate="one_to_one")
    comparison["nls_minus_krt"] = comparison["nls_contrast"] - comparison["krt_contrast_mean"]
    comparison["nls_inside_krt_interval"] = comparison["nls_contrast"].between(
        comparison["krt_contrast_q025"], comparison["krt_contrast_q975"]
    )
    comparison["absolute_krt_nls_gap"] = comparison["nls_minus_krt"].abs()
    comparison["election_type"] = comparison["election_id"].map(
        {election_id: election.election_type for election_id, election in ELECTION_BY_ID.items()}
    )
    comparison = comparison.sort_values(["scenario_id", "election_type", "year", "election_id"])
    if len(comparison) != scope.expected_krt_pairs:
        raise AssertionError("KRT-NLS comparison does not match configured pair count")
    filename = "krt_nls_comparison_" + "_".join(_figure_prefix(value) for value in scope.krt_scenarios) + ".csv"
    _write_csv(comparison, candidate_root / "02_syntheses" / filename)
    _plot_krt_nls(candidate_root, scope, comparison)
    return comparison


def _plot_krt_nls(candidate_root: Path, scope: ReleaseScope, comparison: pd.DataFrame) -> Path:
    fig, axes = plt.subplots(
        len(scope.krt_scenarios),
        1,
        figsize=(15, max(5.0, 4.4 * len(scope.krt_scenarios))),
        squeeze=False,
        constrained_layout=True,
    )
    for axis, scenario_id in zip(axes[:, 0], scope.krt_scenarios):
        part = comparison.loc[comparison["scenario_id"].eq(scenario_id)].reset_index(drop=True)
        x = np.arange(len(part))
        mean = part["krt_contrast_mean"].to_numpy(dtype=float)
        axis.errorbar(
            x,
            mean,
            yerr=np.vstack(
                [
                    mean - part["krt_contrast_q025"].to_numpy(dtype=float),
                    part["krt_contrast_q975"].to_numpy(dtype=float) - mean,
                ]
            ),
            fmt="o",
            color="#2f6b9a",
            markersize=4,
            capsize=2,
            label="KRT (intervalle 95 %)",
        )
        axis.scatter(x, part["nls_contrast"], marker="x", color="#222222", s=28, label="NLS (point)")
        axis.axhline(0, color="#777777", linewidth=0.8)
        labels = [
            f"{int(row.year)} {'L' if row.election_type == 'legislative' else 'P'}"
            for row in part.itertuples()
        ]
        axis.set_xticks(x, labels, rotation=60, ha="right")
        axis.set_ylabel("Contraste beta1 - beta2")
        axis.set_title(f"{scenario_id} - KRT et NLS par scrutin (L/P distingues)")
        axis.legend(frameon=False, ncol=2)
    path = candidate_root / "04_figures_essentielles" / "krt_nls_comparison.png"
    fig.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return path


def build_model_status(candidate_root: Path, scope: ReleaseScope, diagnostics: pd.DataFrame) -> pd.DataFrame:
    aggregate = pd.read_parquet(_result_path(candidate_root, "longitudinal_krt_aggregate.parquet"))
    nls = pd.read_parquet(_result_path(candidate_root, "longitudinal_nls.parquet"))
    nls_pairs = nls[["election_id", "scenario_id", "diagnostic_status"]].drop_duplicates()
    krt_counts = aggregate.groupby(["election_id", "scenario_id"]).size().rename("n_krt_estimands").reset_index()
    status = diagnostics.merge(krt_counts, on=["election_id", "scenario_id"], how="left", validate="one_to_one")
    status = status.merge(nls_pairs, on=["election_id", "scenario_id"], how="left", validate="one_to_one")
    status = status.rename(columns={"diagnostic_status": "nls_diagnostic_status"})
    status["krt_complete"] = status["n_krt_estimands"].eq(scope.aggregate_estimands_per_pair)
    status["nls_present"] = status["nls_diagnostic_status"].notna()
    _write_csv(status, candidate_root / "02_syntheses" / "etat_modeles_par_election.csv")
    return status


def build_hypothesis_definitions(candidate_root: Path, scope: ReleaseScope) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for scenario_id in scope.krt_scenarios:
        scenario = SCENARIO_BY_ID[scenario_id]
        records.append(
            {
                "scenario_id": scenario.scenario_id,
                "model_family": scenario.model_family,
                "social_groups": json.dumps(scenario.social_groups, ensure_ascii=False, sort_keys=True),
                "vote_categories": ";".join(scenario.vote_categories),
                "vote_definition": scenario.vote_definition,
                "denominator": scenario.denominator,
                "admissible_methods": ";".join(scenario.models),
                "nls_method_present": "rosen_nls_2x2_unadjusted" in scenario.models,
                "interpretation_note": (
                    "Modele non ajuste; les caracteristiques communales jointes aux sorties ne sont pas des covariables KRT."
                ),
            }
        )
    definitions = pd.DataFrame(records)
    if not definitions["nls_method_present"].all():
        raise AssertionError("every scoped 2x2 scenario must admit rosen_nls_2x2_unadjusted")
    _write_csv(definitions, candidate_root / "02_syntheses" / "definitions_hypotheses.csv")
    return definitions


def build_numerical_invariance(source_root: Path, candidate_root: Path, scope: ReleaseScope) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    source_commune = pd.read_parquet(_result_path(source_root, "longitudinal_krt_commune.parquet"))
    candidate_commune = pd.read_parquet(_result_path(candidate_root, "longitudinal_krt_commune.parquet"))
    commune_keys = ["election_id", "scenario_id", "unit_id"]
    source_commune = source_commune.sort_values(commune_keys).reset_index(drop=True)
    candidate_commune = candidate_commune.sort_values(commune_keys).reset_index(drop=True)
    common_columns = list(source_commune.columns)
    candidate_for_compare = candidate_commune.rename(
        columns={"revenue_ratio": "revenue", "capital_ratio": "capital"}
    )
    assert_frame_equal(
        source_commune[common_columns],
        candidate_for_compare[common_columns],
        check_exact=True,
        check_dtype=False,
        check_like=False,
    )
    checks.append({"artifact": "longitudinal_krt_commune.parquet", "status": "pass", "rows": len(source_commune), "comparison": "all v1.0.1 columns exact after schema aliases"})

    for filename, keys in (
        ("longitudinal_krt_aggregate.parquet", ["election_id", "scenario_id", "estimand"]),
        ("longitudinal_nls.parquet", ["election_id", "scenario_id", "run_id", "estimand_type", "social_group", "vote_category"]),
    ):
        source = pd.read_parquet(_result_path(source_root, filename)).sort_values(keys).reset_index(drop=True)
        candidate = pd.read_parquet(_result_path(candidate_root, filename)).sort_values(keys).reset_index(drop=True)
        assert_frame_equal(source, candidate[source.columns], check_exact=True, check_dtype=True, check_like=False)
        checks.append({"artifact": filename, "status": "pass", "rows": len(source), "comparison": "all v1.0.1 columns exact"})

    selection_source = pd.read_csv(_selection_path(source_root), dtype="string").sort_values(
        ["scenario_id", "election_id"]
    ).reset_index(drop=True)
    selection_candidate = pd.read_csv(_selection_path(candidate_root), dtype="string").sort_values(
        ["scenario_id", "election_id"]
    ).reset_index(drop=True)
    assert_frame_equal(selection_source, selection_candidate, check_exact=True, check_dtype=True)
    checks.append({"artifact": "canonical_run_selection.csv", "status": "pass", "rows": len(selection_source), "comparison": "canonical choices and statuses exact"})

    result = {
        "release_id": scope.release_id,
        "source_release": "longitudinal_2000_v1.0.1_H0A_H1_validated",
        "public_schema_version": scope.public_schema_version,
        "comparison_mode": "exact_values_after_key_sort; parquet binary hashes may differ",
        "scientific_values_changed": False,
        "status": "pass",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
    }
    output = candidate_root / "03_panel_et_audit" / "NUMERICAL_INVARIANCE_v1.0.1_to_v1.0.2.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


PUBLIC_DESCRIPTIONS: Mapping[str, str] = {
    "panel_id": "Identifiant public du panel longitudinal fixe.",
    "election_id": "Identifiant stable du scrutin et du tour.",
    "scenario_id": "Identifiant de l'hypothese electorale.",
    "run_id": "Identifiant du run canonique selectionne.",
    "unit_id": "Code stable de la commune harmonisee.",
    "commune_name_canonical": "Nom communal canonique du referentiel 2022.",
    "commune_name_reference_year": "Annee de reference du nom canonique.",
    "geography_version": "Version du referentiel geographique harmonise.",
    "revenue_ratio": "Ratio de revenu communal joint a la sortie; non utilise comme covariable KRT.",
    "capital_ratio": "Ratio de capital communal joint a la sortie; non utilise comme covariable KRT.",
    "foreign_share": "Part d'etrangers normalisee entre 0 et 1, jointe a la sortie.",
    "vbbm": "Indicateur territorial VBBM joint a la sortie.",
    "b1_mean": "Moyenne posterieure de beta1 communal.",
    "b1_sd": "Ecart-type posterieur de beta1 communal.",
    "b1_q025": "Quantile posterieur 2,5 % de beta1 communal.",
    "b1_q50": "Mediane posterieure de beta1 communal.",
    "b1_q975": "Quantile posterieur 97,5 % de beta1 communal.",
    "b2_mean": "Moyenne posterieure de beta2 communal.",
    "b2_sd": "Ecart-type posterieur de beta2 communal.",
    "b2_q025": "Quantile posterieur 2,5 % de beta2 communal.",
    "b2_q50": "Mediane posterieure de beta2 communal.",
    "b2_q975": "Quantile posterieur 97,5 % de beta2 communal.",
    "mcmc_status": "Diagnostic numerique MCMC canonique: pass, caveat ou fail.",
    "identification_status": "Diagnostic d'identification ecologique, distinct du diagnostic MCMC.",
    "estimate": "Estimation ponctuelle NLS; aucun pseudo-intervalle posterieur.",
    "public_schema_version": "Version de l'interface publique.",
}


def build_dictionaries(candidate_root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    public_files = [
        _result_path(candidate_root, "longitudinal_krt_commune.parquet"),
        _result_path(candidate_root, "longitudinal_krt_aggregate.parquet"),
        _result_path(candidate_root, "longitudinal_nls.parquet"),
    ]
    manual_rows: list[dict[str, Any]] = []
    for path in public_files:
        frame = pd.read_parquet(path)
        keys = {
            "longitudinal_krt_commune.parquet": {"election_id", "scenario_id", "unit_id"},
            "longitudinal_krt_aggregate.parquet": {"election_id", "scenario_id", "estimand"},
            "longitudinal_nls.parquet": {"election_id", "scenario_id", "run_id", "estimand_type", "social_group", "vote_category"},
        }[path.name]
        for column in frame.columns:
            manual_rows.append(
                {
                    "table": path.name,
                    "column": column,
                    "dtype": str(frame[column].dtype),
                    "is_key": column in keys,
                    "description": PUBLIC_DESCRIPTIONS.get(column, column.replace("_", " ")),
                    "role": "joined_commune_characteristic" if column in {"revenue_ratio", "capital_ratio", "foreign_share", "vbbm", "department", "region13"} else "public_output",
                }
            )
    manual = pd.DataFrame(manual_rows)
    _write_csv(manual, candidate_root / "03_panel_et_audit" / "DATA_DICTIONARY.csv")

    technical_rows: list[dict[str, Any]] = []
    folders = ("01_resultats_python", "02_syntheses", "03_panel_et_audit", "02_comparaison_python_r")
    for folder in folders:
        for path in sorted((candidate_root / folder).glob("*")):
            try:
                if path.suffix.lower() == ".parquet":
                    frame = pd.read_parquet(path)
                elif path.suffix.lower() == ".csv":
                    frame = pd.read_csv(path, nrows=5000, low_memory=False)
                else:
                    continue
            except Exception as exc:
                technical_rows.append(
                    {
                        "delivery_path": path.relative_to(candidate_root).as_posix(),
                        "column": "",
                        "dtype": "",
                        "description": "unreadable during dictionary build",
                        "dictionary_status": f"error:{type(exc).__name__}",
                    }
                )
                continue
            for column in frame.columns:
                technical_rows.append(
                    {
                        "delivery_path": path.relative_to(candidate_root).as_posix(),
                        "column": column,
                        "dtype": str(frame[column].dtype),
                        "description": PUBLIC_DESCRIPTIONS.get(column, column.replace("_", " ")),
                        "dictionary_status": "documented",
                    }
                )
    technical = pd.DataFrame(technical_rows)
    _write_csv(technical, candidate_root / "03_panel_et_audit" / "DATA_DICTIONARY_TECHNICAL.csv")
    return manual, technical


def build_scoped_artifacts(source_root: Path, candidate_root: Path, scope: ReleaseScope) -> dict[str, Any]:
    migration = migrate_public_schema(source_root, candidate_root, scope)
    diagnostics, summary = build_canonical_diagnostics(candidate_root, scope)
    trajectory = build_trajectory_table(candidate_root, scope)
    figures = plot_contrast_trajectories(candidate_root, scope, trajectory)
    target_figure = plot_h2_h3_target_probabilities(candidate_root, scope, trajectory)
    diagnostic_figure = plot_diagnostic_status(candidate_root, scope, diagnostics)
    chart_map = write_chart_map(candidate_root, scope)
    comparison = build_krt_nls_comparison(candidate_root, scope)
    model_status = build_model_status(candidate_root, scope, diagnostics)
    definitions = build_hypothesis_definitions(candidate_root, scope)
    invariance = build_numerical_invariance(source_root, candidate_root, scope)
    manual, technical = build_dictionaries(candidate_root)
    return {
        "migration": migration,
        "diagnostic_rows": len(diagnostics),
        "diagnostic_summary_rows": len(summary),
        "trajectory_rows": len(trajectory),
        "figure_count": len(figures) + 2 + int(target_figure is not None),
        "diagnostic_figure": diagnostic_figure.relative_to(candidate_root).as_posix(),
        "chart_map_rows": len(chart_map),
        "comparison_rows": len(comparison),
        "model_status_rows": len(model_status),
        "definition_rows": len(definitions),
        "invariance_status": invariance["status"],
        "dictionary_rows": len(manual),
        "technical_dictionary_rows": len(technical),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build schema-driven release artifacts without refitting models.")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=SOURCE_V101)
    parser.add_argument("--candidate-root", type=Path, default=CANDIDATE_V102)
    args = parser.parse_args()
    scope = load_release_scope(args.config)
    result = build_scoped_artifacts(args.source_root, args.candidate_root, scope)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
