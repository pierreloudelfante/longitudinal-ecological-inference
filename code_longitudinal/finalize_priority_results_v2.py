from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .diagnostics_v2 import audit_trace, summary_row
from .identification_v2 import assess_identification
from .paths import DOCS_DIR, FIGURE_DIR, OUTPUT_DIR, ROOT, RUNS_DIR, ensure_runtime_dirs
from .postprocess_aggregates_v2 import aggregate_krt_trace_files_v2, summarize_krt_aggregates_v2
from .prepare_inputs import x_columns, y_columns
from .preserve_v1_integrity import DEFAULT_MANIFEST as PRESERVATION_MANIFEST, verify_manifest
from .spec_registry import SCENARIO_BY_ID
from .utils import write_json


BEST_RUNS_PATH = OUTPUT_DIR / "priority_best_runs.csv"
V2_OUTPUT_DIR = OUTPUT_DIR / "v2" / "priority_500_reanalysis"
V2_FIGURE_DIR = FIGURE_DIR / "v2" / "priority_500_reanalysis"
REPORT_PATH = DOCS_DIR / "PRIORITY_RESULTS_FOR_PROFESSOR_V2.md"
CHART_MAP_PATH = DOCS_DIR / "PRIORITY_CHART_MAP_V2.md"
ZIP_PATH = ROOT / "deliverables" / "longitudinal_priority_results_v2_corrige_3000_en_cours.zip"
SHA_PATH = ZIP_PATH.with_suffix(".zip.sha256")
PPC_METRICS_PATH = OUTPUT_DIR / "v2" / "ppc_krt" / "ppc_metrics.csv"
PANEL_3000_AUDIT_PATH = OUTPUT_DIR / "v2" / "priority_model_ready_3000_audit.csv"
PRODUCTION_PROGRESS_PATH = OUTPUT_DIR / "v2" / "priority_production_progress_v2.json"
NLS_AUDIT_PATH = OUTPUT_DIR / "v2" / "nls_priority" / "audit.json"

BLUE = "#315C8C"
GOLD = "#C6922B"
INK = "#20262E"
GREY = "#AAB2BD"
RED = "#A14E45"

SCENARIO_LABELS = {
    "H0A": "Abstention — ouvriers et employés vs autres CSP",
    "H1": "Vote à gauche — ouvriers et employés vs autres CSP",
    "H2": "Vote à gauche — ouvriers vs autres CSP",
    "H4": "Vote à droite — agriculteurs et indépendants vs salariés",
}


def _input_path(manifest: dict[str, Any]) -> Path:
    paths = [Path(path) for path in manifest.get("input_sha256", {}) if str(path).endswith(".parquet")]
    if len(paths) != 1:
        raise ValueError(f"expected one model-ready parquet, found {len(paths)}")
    return paths[0]


def _aligned_frame(run_dir: Path, manifest: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = pd.read_parquet(_input_path(manifest))
    latent = pd.read_parquet(run_dir / "commune_latent_summaries.parquet")
    frame = frame.copy()
    frame["unit_id"] = frame["unit_id"].astype(str)
    latent = latent.copy()
    latent["unit_id"] = latent["unit_id"].astype(str)
    if frame["unit_id"].duplicated().any() or latent["unit_id"].duplicated().any():
        raise ValueError("duplicate unit_id in trace alignment inputs")
    by_unit = frame.set_index("unit_id", drop=False)
    missing = set(latent["unit_id"]) - set(by_unit.index)
    if missing:
        raise ValueError(f"latent units absent from model input: {sorted(missing)[:5]}")
    aligned = by_unit.loc[latent["unit_id"]].reset_index(drop=True)
    return aligned, latent.reset_index(drop=True)


def _interpretation_status(mcmc_status: str, identification_status: str) -> str:
    if mcmc_status == "pass" and identification_status == "pass":
        return "supported"
    if mcmc_status == "pass" and identification_status == "caveat":
        return "supported_with_identification_caveat"
    if mcmc_status == "caveat":
        return "mcmc_caveat"
    return "exploratory_only"


def _bootstrap_group_mean(
    values: np.ndarray,
    weights: np.ndarray,
    *,
    seed: int,
    replicates: int = 2000,
) -> np.ndarray:
    if len(values) != len(weights) or len(values) == 0:
        raise ValueError("bootstrap values and weights must be aligned and non-empty")
    rng = np.random.default_rng(seed)
    output = np.empty(replicates, dtype=float)
    for start in range(0, replicates, 200):
        size = min(200, replicates - start)
        indices = rng.integers(0, len(values), size=(size, len(values)))
        sampled_weights = weights[indices]
        output[start : start + size] = np.sum(values[indices] * sampled_weights, axis=1) / np.sum(
            sampled_weights, axis=1
        )
    return output


def analyze_selected_runs() -> dict[str, Any]:
    best = pd.read_csv(BEST_RUNS_PATH)
    aggregate_rows: list[pd.DataFrame] = []
    estimate_rows: list[dict[str, Any]] = []
    contrast_rows: list[dict[str, Any]] = []
    diagnostics_rows: list[dict[str, Any]] = []
    identification_rows: list[dict[str, Any]] = []
    bootstrap_rows: list[dict[str, Any]] = []
    detailed_audits: dict[str, Any] = {}
    draw_index: dict[tuple[str, int], dict[str, np.ndarray]] = {}

    for selection in best.itertuples():
        run_id = str(selection.run_id)
        run_dir = RUNS_DIR / run_id
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        scenario_id = str(selection.scenario_id)
        scenario = SCENARIO_BY_ID[scenario_id]
        aligned, latent = _aligned_frame(run_dir, manifest)
        year = int(str(selection.election_id).split("_")[1][:4])

        draws = aggregate_krt_trace_files_v2(
            run_dir / "trace.nc", run_dir / "commune_latent_summaries.parquet"
        )
        summary = summarize_krt_aggregates_v2(draws)
        summary.insert(0, "run_id", run_id)
        summary.insert(1, "election_id", selection.election_id)
        summary.insert(2, "year", year)
        summary.insert(3, "scenario_id", scenario_id)
        aggregate_rows.append(summary)

        x = aligned[x_columns(scenario)[0]].to_numpy(dtype=float)
        y = aligned[y_columns(scenario)[0]].to_numpy(dtype=float) / aligned["N_g"].to_numpy(dtype=float)
        identification = assess_identification(x, y)
        identification_rows.append(
            {"run_id": run_id, "election_id": selection.election_id, "year": year, "scenario_id": scenario_id, **identification}
        )
        audit = audit_trace(
            run_dir / "trace.nc",
            fit_status="success",
            identification_status=str(identification["identification_status"]),
            expected_chains=int(selection.chains),
            expected_draws_per_chain=int(selection.draws),
            max_treedepth=int(selection.max_treedepth),
        )
        detailed_audits[run_id] = audit
        diagnostic_row = {
            "run_id": run_id,
            "election_id": selection.election_id,
            "year": year,
            "scenario_id": scenario_id,
            **summary_row(audit),
        }
        diagnostic_row["interpretation_status"] = _interpretation_status(
            str(audit["mcmc_status"]), str(identification["identification_status"])
        )
        diagnostics_rows.append(diagnostic_row)

        b1 = np.asarray(draws["b_1_group_weighted"].values, dtype=float).reshape(-1)
        b2 = np.asarray(draws["b_2_group_weighted"].values, dtype=float).reshape(-1)
        draw_index[(scenario_id, year)] = {"b1": b1, "b2": b2, "delta": b1 - b2}
        for beta_name, group, vote_draws in (
            ("b_1", list(scenario.social_groups)[0], b1),
            ("b_2", list(scenario.social_groups)[1], b2),
        ):
            for vote, values in (
                (scenario.vote_categories[0], vote_draws),
                (scenario.vote_categories[1], 1.0 - vote_draws),
            ):
                estimate_rows.append(
                    {
                        "run_id": run_id,
                        "election_id": selection.election_id,
                        "year": year,
                        "scenario_id": scenario_id,
                        "social_group": group,
                        "beta_parameter": beta_name,
                        "vote_category": vote,
                        "estimate": float(values.mean()),
                        "lower": float(np.quantile(values, 0.025)),
                        "median": float(np.quantile(values, 0.50)),
                        "upper": float(np.quantile(values, 0.975)),
                        "aggregation_method": "group_specific_population_v2",
                        "n_communes": len(aligned),
                        "mcmc_status": audit["mcmc_status"],
                        "identification_status": identification["identification_status"],
                        "interpretation_status": diagnostic_row["interpretation_status"],
                    }
                )
            weights = latent["b1_weight" if beta_name == "b_1" else "b2_weight"].to_numpy(float)
            commune_means = latent["b1_mean" if beta_name == "b_1" else "b2_mean"].to_numpy(float)
            boot = _bootstrap_group_mean(
                commune_means,
                weights,
                seed=20260804 + year + (1 if beta_name == "b_1" else 2),
            )
            bootstrap_rows.append(
                {
                    "run_id": run_id,
                    "election_id": selection.election_id,
                    "year": year,
                    "scenario_id": scenario_id,
                    "beta_parameter": beta_name,
                    "estimate_from_commune_means": float(np.sum(commune_means * weights) / np.sum(weights)),
                    "bootstrap_se": float(boot.std(ddof=1)),
                    "bootstrap_lower": float(np.quantile(boot, 0.025)),
                    "bootstrap_upper": float(np.quantile(boot, 0.975)),
                    "replicates": len(boot),
                    "scope": "descriptive commune-resampling sensitivity; no model refit",
                }
            )

        delta = b1 - b2
        contrast_rows.append(
            {
                "run_id": run_id,
                "election_id": selection.election_id,
                "year": year,
                "scenario_id": scenario_id,
                "contrast": "group_1_minus_group_2",
                "estimate": float(delta.mean()),
                "lower": float(np.quantile(delta, 0.025)),
                "median": float(np.quantile(delta, 0.50)),
                "upper": float(np.quantile(delta, 0.975)),
                "probability_gt_zero": float(np.mean(delta > 0)),
                "mcmc_status": audit["mcmc_status"],
                "identification_status": identification["identification_status"],
                "interpretation_status": diagnostic_row["interpretation_status"],
            }
        )

    changes: list[dict[str, Any]] = []
    for scenario_id in sorted(best["scenario_id"].unique()):
        for earlier, later in ((1962, 1986), (1986, 2022), (1962, 2022)):
            first = draw_index[(scenario_id, earlier)]["delta"]
            second = draw_index[(scenario_id, later)]["delta"]
            rng = np.random.default_rng(20260804 + earlier + later + sum(map(ord, scenario_id)))
            size = 50_000
            change = second[rng.integers(0, len(second), size=size)] - first[
                rng.integers(0, len(first), size=size)
            ]
            changes.append(
                {
                    "scenario_id": scenario_id,
                    "earlier_year": earlier,
                    "later_year": later,
                    "contrast_change": "delta_later_minus_delta_earlier",
                    "estimate": float(change.mean()),
                    "lower": float(np.quantile(change, 0.025)),
                    "median": float(np.quantile(change, 0.50)),
                    "upper": float(np.quantile(change, 0.975)),
                    "probability_gt_zero": float(np.mean(change > 0)),
                    "resamples": size,
                    "assumption": "independent posterior draws across election-specific fits",
                }
            )

    V2_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    aggregates = pd.concat(aggregate_rows, ignore_index=True)
    estimates = pd.DataFrame(estimate_rows)
    contrasts = pd.DataFrame(contrast_rows)
    changes_frame = pd.DataFrame(changes)
    diagnostics = pd.DataFrame(diagnostics_rows)
    identification_frame = pd.DataFrame(identification_rows)
    bootstrap = pd.DataFrame(bootstrap_rows)
    artifacts = {
        "aggregates": aggregates,
        "estimates": estimates,
        "contrasts": contrasts,
        "changes": changes_frame,
        "diagnostics": diagnostics,
        "identification": identification_frame,
        "bootstrap": bootstrap,
    }
    filenames = {
        "aggregates": "aggregate_comparison_v2.csv",
        "estimates": "corrected_estimates_v2.csv",
        "contrasts": "within_period_contrasts_v2.csv",
        "changes": "longitudinal_contrast_changes_v2.csv",
        "diagnostics": "official_diagnostics_v2.csv",
        "identification": "identification_metrics_v2.csv",
        "bootstrap": "panel_bootstrap_sensitivity_v2.csv",
    }
    for key, frame in artifacts.items():
        frame.to_csv(V2_OUTPUT_DIR / filenames[key], index=False, encoding="utf-8-sig")
    write_json(V2_OUTPUT_DIR / "official_diagnostics_details_v2.json", detailed_audits)
    return artifacts


def _save_figure(fig: plt.Figure, stem: str) -> None:
    V2_FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(V2_FIGURE_DIR / f"{stem}.png", dpi=180, bbox_inches="tight", facecolor="white")
    fig.savefig(V2_FIGURE_DIR / f"{stem}.svg", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_corrected_estimates(estimates: pd.DataFrame, scenario_id: str) -> None:
    scenario = SCENARIO_BY_ID[scenario_id]
    data = estimates.loc[
        estimates["scenario_id"].eq(scenario_id)
        & estimates["vote_category"].eq(scenario.vote_categories[0])
    ].copy()
    groups = list(scenario.social_groups)
    fig, axes = plt.subplots(1, 2, figsize=(10.8, 4.4), sharey=True)
    for axis, group, color in zip(axes, groups, (BLUE, GOLD), strict=True):
        part = data.loc[data["social_group"].eq(group)].sort_values("year")
        x = np.arange(len(part))
        mean = part["estimate"].to_numpy(float)
        lower = part["lower"].to_numpy(float)
        upper = part["upper"].to_numpy(float)
        axis.errorbar(x, mean, yerr=np.vstack([mean - lower, upper - mean]), fmt="o", ms=7, color=color, capsize=4)
        axis.set_xticks(x, part["year"].astype(int))
        axis.set_title(group.replace("_", " "))
        axis.set_ylim(0, 1)
        axis.grid(axis="y", color="#E2E6EA", lw=0.8)
        axis.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel(f"Probabilité estimée : {scenario.vote_categories[0]}")
    fig.suptitle(f"{scenario_id} — agrégats corrigés, pondération propre à chaque groupe", color=INK, fontsize=14)
    fig.text(0.5, 0.01, "Points : moyenne postérieure; barres : intervalle crédible à 95 %. Réanalyse V2 des traces V1.", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, 0.05, 1, 0.92))
    _save_figure(fig, f"corrected_{scenario_id}_v2")


def plot_aggregation_shift(aggregates: pd.DataFrame) -> None:
    data = aggregates.loc[aggregates["aggregation_method"].eq("group_specific_population_v2")].copy()
    data["difference_pp"] = 100 * data["mean_difference_from_legacy"]
    data["label"] = data["scenario_id"] + "-" + data["year"].astype(str) + "-" + data["beta_parameter"]
    data = data.sort_values("difference_pp")
    fig, ax = plt.subplots(figsize=(10.5, 8.0))
    colors = np.where(data["difference_pp"] >= 0, BLUE, GOLD)
    ax.barh(data["label"], data["difference_pp"], color=colors)
    ax.axvline(0, color=INK, lw=1)
    ax.set_xlabel("Correction par rapport à l’agrégat V1 (points de pourcentage)")
    ax.set_title("Effet de la correction des poids d’agrégation", color=INK, fontsize=14)
    ax.grid(axis="x", color="#E2E6EA", lw=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    _save_figure(fig, "aggregation_correction_shift_v2")


def plot_contrasts(contrasts: pd.DataFrame) -> None:
    data = contrasts.sort_values(["scenario_id", "year"]).reset_index(drop=True)
    labels = data["scenario_id"] + " — " + data["year"].astype(str)
    y = np.arange(len(data))
    mean = data["estimate"].to_numpy(float)
    lower = data["lower"].to_numpy(float)
    upper = data["upper"].to_numpy(float)
    colors = data["mcmc_status"].map({"pass": BLUE, "caveat": GOLD, "fail": GREY}).fillna(GREY)
    fig, ax = plt.subplots(figsize=(10.5, 7.0))
    for idx in range(len(data)):
        ax.errorbar(mean[idx], y[idx], xerr=[[mean[idx] - lower[idx]], [upper[idx] - mean[idx]]], fmt="o", color=colors.iloc[idx], capsize=3)
    ax.axvline(0, color=INK, lw=1, ls="--")
    ax.set_yticks(y, labels)
    ax.set_xlabel("Contraste β₁ − β₂ pour la catégorie politique cible")
    ax.set_title("Contrastes intra-période corrigés", color=INK, fontsize=14)
    ax.grid(axis="x", color="#E2E6EA", lw=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    _save_figure(fig, "within_period_contrasts_v2")


def plot_diagnostics(diagnostics: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(9.7, 5.8))
    colors = diagnostics["mcmc_status"].map({"pass": BLUE, "caveat": GOLD, "fail": RED}).fillna(GREY)
    ax.scatter(diagnostics["max_rhat"], diagnostics["min_ess_bulk"], c=colors, s=65, edgecolor=INK, lw=0.5)
    for row in diagnostics.itertuples():
        ax.annotate(f"{row.scenario_id}-{row.year}", (row.max_rhat, row.min_ess_bulk), xytext=(4, 4), textcoords="offset points", fontsize=8)
    ax.axvline(1.01, color=INK, ls="--", lw=1)
    ax.axhline(400, color=INK, ls=":", lw=1)
    ax.set_xlabel("R-hat maximal — toutes variables postérieures")
    ax.set_ylabel("ESS bulk minimal — toutes variables postérieures")
    ax.set_title("Verdict MCMC officiel unique V2", color=INK, fontsize=14)
    ax.grid(color="#E2E6EA", lw=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    _save_figure(fig, "official_diagnostics_v2")


def _markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    show = frame.loc[:, columns].copy()
    for column in show.select_dtypes(include=["float"]).columns:
        show[column] = show[column].map(lambda value: f"{value:.3f}" if pd.notna(value) else "")
    header = "| " + " | ".join(str(column) for column in show.columns) + " |"
    separator = "| " + " | ".join("---" for _ in show.columns) + " |"
    rows = [
        "| "
        + " | ".join(str(value).replace("|", "\\|").replace("\n", " ") for value in row)
        + " |"
        for row in show.itertuples(index=False, name=None)
    ]
    return "\n".join([header, separator, *rows])


def write_report(artifacts: dict[str, pd.DataFrame], integrity: dict[str, Any]) -> None:
    aggregates = artifacts["aggregates"]
    estimates = artifacts["estimates"]
    contrasts = artifacts["contrasts"]
    changes = artifacts["changes"]
    diagnostics = artifacts["diagnostics"]
    identification = artifacts["identification"]
    corrected = aggregates.loc[aggregates["aggregation_method"].eq("group_specific_population_v2")]
    max_shift = corrected.loc[corrected["mean_difference_from_legacy"].abs().idxmax()]
    ppc = pd.read_csv(PPC_METRICS_PATH) if PPC_METRICS_PATH.exists() else pd.DataFrame()
    panel_audit = pd.read_csv(PANEL_3000_AUDIT_PATH) if PANEL_3000_AUDIT_PATH.exists() else pd.DataFrame()
    progress = json.loads(PRODUCTION_PROGRESS_PATH.read_text(encoding="utf-8")) if PRODUCTION_PROGRESS_PATH.exists() else {"status": "not_started"}
    nls_audit = json.loads(NLS_AUDIT_PATH.read_text(encoding="utf-8")) if NLS_AUDIT_PATH.exists() else {"executed": False, "status_counts": {}}
    production_items = list(progress.get("items", {}).values())
    production_status_counts = {
        status: sum(str(item.get("status")) == status for item in production_items)
        for status in ("success", "failed", "running", "pending")
    }
    completed_durations = [
        float(item["elapsed_seconds"])
        for item in production_items
        if item.get("status") == "success" and item.get("elapsed_seconds") is not None
    ]
    seconds_per_fit = float(np.median(completed_durations)) if completed_durations else float("nan")
    remaining_fits = production_status_counts["pending"] + production_status_counts["running"]
    remaining_hours = (
        seconds_per_fit * remaining_fits / 3600.0
        if np.isfinite(seconds_per_fit)
        else float("nan")
    )
    remaining_text = f"environ {remaining_hours:.1f} h" if np.isfinite(remaining_hours) else "non estimable"

    h0a = contrasts.loc[contrasts["scenario_id"].eq("H0A")].sort_values("year")
    h1 = contrasts.loc[contrasts["scenario_id"].eq("H1")].sort_values("year")
    primary_changes = changes.loc[
        changes["earlier_year"].eq(1962) & changes["later_year"].eq(2022)
    ].sort_values("scenario_id")
    report = f"""# Résultats longitudinaux prioritaires — correction V2 et production 3 000 communes

## Résumé technique

- **Le contenu V1 est conservé bit à bit.** Le manifeste de préservation contrôle {integrity['file_count']} fichiers; état actuel : `integrity_ok={integrity['integrity_ok']}`. L’archive V1 originale est incluse telle quelle dans l’archive V2.
- **L’erreur d’agrégation est corrigée sans réestimer les traces V1.** Chaque tirage utilise désormais `Σ N₁ᵢβ₁ᵢ / ΣN₁ᵢ` et `Σ N₂ᵢβ₂ᵢ / ΣN₂ᵢ`. L’écart maximal constaté face à l’export V1 est de {100*abs(float(max_shift['mean_difference_from_legacy'])):.2f} points, pour {max_shift['scenario_id']} en {int(max_shift['year'])} ({max_shift['beta_parameter']}).
- **Il n’existe plus deux diagnostics concurrents.** Le verdict officiel V2 porte sur toutes les variables postérieures, BFMI, divergences et profondeur d’arbre. {int(diagnostics['mcmc_status'].eq('pass').sum())}/12 traces passent, {int(diagnostics['mcmc_status'].eq('caveat').sum())} ont une réserve et {int(diagnostics['mcmc_status'].eq('fail').sum())} échouent.
- **Les 12 jeux d’entrée à 3 000 communes sont prêts, mais les 12 MCMC ne sont pas terminées.** Exactement {int(panel_audit['n_used'].min()) if not panel_audit.empty else 0} communes sont présentes dans chaque hypothèse/date, sans exclusion. État réel : {production_status_counts['success']}/12 estimations terminées, {production_status_counts['pending']} en attente, {production_status_counts['failed']} en échec; exécution `{progress.get('status', 'not_started')}`. Temps restant si la production reprend au rythme observé : {remaining_text}.
- **Le benchmark NLS 2×2 est exécuté sur les mêmes 12 entrées à 3 000 communes.** État : `executed={nls_audit.get('executed', False)}`, résultats : `{nls_audit.get('status_counts', {})}`.

## Les contrastes corrigés montrent un basculement net pour H0A

{_markdown_table(h0a, ['year', 'estimate', 'lower', 'upper', 'probability_gt_zero', 'mcmc_status', 'identification_status'])}

Pour H0A, le contraste `ouvriers+employés − autres CSP` passe d’un niveau négatif en 1962 à positif en 2022. Cette lecture reste une inférence écologique : les diagnostics d’identification quantifient la largeur des bornes de tomographie et imposent une réserve lorsque celles-ci sont larges.

![Contrastes intra-période](../figures/v2/priority_500_reanalysis/within_period_contrasts_v2.png)

## H1 varie moins nettement entre les périodes

{_markdown_table(h1, ['year', 'estimate', 'lower', 'upper', 'probability_gt_zero', 'mcmc_status', 'identification_status'])}

Les changements 1962→2022 sont calculés par rééchantillonnage indépendant des deux postérieures électorales; ils ne constituent pas une trajectoire individuelle.

{_markdown_table(primary_changes, ['scenario_id', 'estimate', 'lower', 'upper', 'probability_gt_zero'])}

## La correction des poids modifie matériellement certains agrégats

![Effet de la correction des poids](../figures/v2/priority_500_reanalysis/aggregation_correction_shift_v2.png)

Les probabilités sont conditionnelles au groupe social. Le dénominateur pertinent est donc l’effectif du groupe, et non l’effectif communal total. Les anciens nombres restent disponibles uniquement comme comparaison historique et ne sont plus étiquetés comme estimateur canonique.

## Un seul diagnostic MCMC gouverne chaque trace

![Diagnostic officiel V2](../figures/v2/priority_500_reanalysis/official_diagnostics_v2.png)

Les métriques par bloc (`hyperparameters`, `latent_preferences`) servent à localiser un problème mais ne portent aucun second verdict. En particulier, plusieurs H2/H4 ont des β communaux apparemment stables alors que leurs hyperparamètres et/ou le BFMI échouent : ils restent exploratoires.

`b_1` et `b_2` sont les probabilités latentes communales étudiées. `c_1`, `c_2`, `d_1` et `d_2` sont seulement des hyperparamètres internes de la même estimation KRT; ils ne correspondent ni à d’autres communes, ni à une seconde estimation, ni à un second diagnostic. Chaque run possède un seul verdict officiel dans `mcmc_diagnostics_v2.json`.

## Les contrôles prédictifs sont rassurants mais ne prouvent pas l’identification

{('Les 12 PPC couvrent la part agrégée observée; RMSE communale de ' + f"{ppc['rmse'].min():.4f} à {ppc['rmse'].max():.4f}, couverture de {100*ppc['precinct_coverage'].min():.2f}% à {100*ppc['precinct_coverage'].max():.2f}%, p-value de Pearson de {ppc['bayesian_p_value_pearson_upper_tail'].min():.3f} à {ppc['bayesian_p_value_pearson_upper_tail'].max():.3f}." if not ppc.empty else 'Les PPC ne sont pas encore disponibles.')}

Les traces historiques présentent aussi un écart d’une voix dans 11 à 32 communes par run, dû au retour flottant `(Y/N)×N` de PyEI. Le PPC utilise le compte effectivement ajusté; le nouveau pipeline V2 stabilise ce retour numérique pour les futures traces.

## Périmètre, données et définitions

- Hypothèses principales : H0A, H1, H2 et H4, pour 1962, 1986 et 2022.
- Réanalyse immédiate : 12 traces KRT V1, panel 500/494/500, sans modification des traces.
- Production V2 : panel commun exact de 3 000 communes observables et analytiquement valides aux trois dates.
- Catégorie cible : première catégorie politique déclarée par le scénario; β₁ et β₂ sont les probabilités latentes de cette catégorie dans chacun des deux groupes sociaux.
- Densités jointes : distribution entre communes des moyennes postérieures `(β₁,β₂)`; elles ne sont pas la postérieure bivariée d’une commune unique.

## Méthode et robustesse

1. Vérification SHA256 des 129 fichiers V1 protégés.
2. Recalcul draw-wise des agrégats avec poids de groupe.
3. Contrastes intra-période et changements entre périodes avec incertitude.
4. Diagnostic MCMC officiel unique sur toutes les variables.
5. Bornes de tomographie et variation de la composition sociale comme diagnostic d’identification.
6. PPC binomial par commune et agrégé.
7. Bootstrap descriptif des communes, sans prétendre remplacer une réestimation de panel.
8. Nouveau panel longitudinal commun de 3 000 communes; contrôles d’équilibre contre l’univers commun et l’univers 2022 complet.

## Limites et questions encore ouvertes

- La réanalyse V2 sur 500/494/500 communes corrige l’estimateur mais ne remplace pas les relances sur 3 000 communes. À l’état de cette archive, seules H0A-1962 et H0A-1986 sont terminées à 3 000.
- Les densités jointes déjà livrées comparent les trois périodes à partir des traces historiques 500/494/500. Une comparaison complète à 3 000 communes exigera les dix MCMC encore en attente.
- Une bonne calibration PPC n’établit pas l’identification des comportements individuels.
- Les H2/H4 qui échouent au diagnostic complet nécessitent une paramétrisation moyenne/concentration ou une sensibilité de prior avant interprétation forte.
- Le bootstrap de communes ne refait pas le modèle; il mesure seulement la sensibilité descriptive au panel observé.
- King doit rester un benchmark séquentiel ciblé, pas être confondu avec la production KRT principale.

## Prochaines étapes suivies

1. Terminer les 12 fits KRT sur 3 000 communes avec 4 chaînes, 1 000 tune, 1 000 draws et `target_accept=0,99`.
2. Auditer chaque fit avec le verdict V2 et conserver les échecs au lieu de les masquer.
3. Relancer seulement les H2/H4 problématiques sous paramétrisation améliorée.
4. Ajouter le benchmark King limité; les 12 NLS 2×2 intercept-only sont déjà produits et clairement étiquetés.
5. Remplacer dans le rapport final les résultats 500 par les résultats 3 000 lorsqu’ils sont disponibles.

## Fichiers d’audit

- `outputs/v2/priority_500_reanalysis/` : agrégats corrigés, contrastes, diagnostics, identification et bootstrap.
- `outputs/v2/ppc_krt/` : métriques et détails PPC.
- `outputs/v2/nls_priority/` : 12 benchmarks NLS sur le panel commun de 3 000 communes.
- `panel/panel_3000_common_1962_1986_2022_v2*` : panel exact, équilibre et manifeste.
- `outputs/v2/preservation_manifest_v1.json` : empreintes du contenu protégé.
- `deliverables/longitudinal_priority_results_v2_corrige_3000_en_cours.zip` : archive versionnée incluant l’archive V1 intacte et les deux runs KRT déjà terminés à 3 000 communes.
"""
    REPORT_PATH.write_text(report, encoding="utf-8")


def write_chart_map() -> None:
    CHART_MAP_PATH.write_text(
        """# Carte des figures V2

| Figure | Question | Forme | Source | Limite |
| --- | --- | --- | --- | --- |
| `corrected_H0A_v2` | Quels niveaux H0A après correction des poids ? | points + intervalles | `corrected_estimates_v2.csv` | traces V1, panel 500/494/500 |
| `corrected_H1_v2` | Quels niveaux H1 après correction des poids ? | points + intervalles | `corrected_estimates_v2.csv` | traces V1, panel 500/494/500 |
| `aggregation_correction_shift_v2` | De combien le mauvais dénominateur déplaçait-il les résultats ? | barres divergentes | `aggregate_comparison_v2.csv` | comparaison historique seulement |
| `within_period_contrasts_v2` | β₁−β₂ est-il positif ou négatif ? | points + intervalles | `within_period_contrasts_v2.csv` | l’inférence reste écologique |
| `official_diagnostics_v2` | Quels runs passent le verdict complet ? | nuage R-hat/ESS | `official_diagnostics_v2.csv` | BFMI et raisons dans le tableau |
| `figures/v2/ppc_krt/*` | Le modèle reproduit-il les marges observées ? | PPC quatre panneaux | `outputs/v2/ppc_krt/*` | calibration ≠ identification |
| `figures/v2/densities/*` | Comment (β₁,β₂) varie-t-il entre périodes ? | KDE commune + HDR | `priority_joint_beta_data.csv` | moyenne postérieure par commune |
""",
        encoding="utf-8",
    )


def build_zip() -> None:
    files: list[Path] = [
        REPORT_PATH,
        CHART_MAP_PATH,
        PRESERVATION_MANIFEST,
        ROOT / "deliverables" / "longitudinal_priority_results_clear.zip",
        ROOT / "deliverables" / "longitudinal_priority_results_clear.zip.sha256",
        ROOT / "deliverables" / "longitudinal_2022_release_01.zip",
        ROOT / "deliverables" / "longitudinal_2022_release_01.sha256",
        ROOT / "panel" / "panel_3000_common_1962_1986_2022_v2.csv",
        ROOT / "panel" / "panel_3000_common_1962_1986_2022_v2_balance.csv",
        ROOT / "panel" / "panel_3000_common_1962_1986_2022_v2_attempts.csv",
        ROOT / "panel" / "panel_3000_common_1962_1986_2022_v2_manifest.json",
        PANEL_3000_AUDIT_PATH,
        PRODUCTION_PROGRESS_PATH,
        OUTPUT_DIR / "v2" / "priority_production_diagnostics_v2.csv",
        OUTPUT_DIR / "v2" / "priority_model_ready_3000_manifest.json",
        DOCS_DIR / "PPC_V2_METHOD.md",
        DOCS_DIR / "ETAT_ARCHIVE_CORRIGEE_3000.md",
        DOCS_DIR / "METHODE_ECHANTILLONNAGE_PANEL_3000.md",
    ]
    files.extend(sorted(V2_OUTPUT_DIR.glob("*")))
    files.extend(sorted(V2_FIGURE_DIR.glob("*")))
    files.extend(sorted((OUTPUT_DIR / "v2" / "ppc_krt").glob("*")))
    files.extend(sorted((OUTPUT_DIR / "v2" / "nls_priority").rglob("*")))
    files.extend(sorted((OUTPUT_DIR / "v2" / "diagnostic_audits").glob("*")))
    files.extend(sorted((FIGURE_DIR / "v2" / "ppc_krt").glob("*")))
    files.extend(sorted((FIGURE_DIR / "v2" / "densities").glob("*")))
    files.extend(
        ROOT / "code_longitudinal" / name
        for name in (
            "postprocess_aggregates_v2.py",
            "diagnostics_v2.py",
            "identification_v2.py",
            "ppc_v2.py",
            "build_common_panel_v2.py",
            "prepare_priority_v2.py",
            "preserve_v1_integrity.py",
            "finalize_priority_results_v2.py",
            "density_figures_v2.py",
            "run_priority_production_v2.py",
            "run_nls_priority_v2.py",
            "run_2x2_batch.py",
            "run_nls_batch.py",
            "prepare_inputs.py",
        )
    )
    if PRODUCTION_PROGRESS_PATH.exists():
        production = json.loads(PRODUCTION_PROGRESS_PATH.read_text(encoding="utf-8"))
        canonical_run_files = (
            "manifest.json",
            "longitudinal_estimates.csv",
            "aggregate_comparison_v2.csv",
            "mcmc_diagnostics_v2.json",
            "mcmc_variable_metrics_v2.csv",
            "mcmc_block_metrics_v2.csv",
            "commune_latent_summaries.parquet",
        )
        for item in production.get("items", {}).values():
            if item.get("status") != "success" or not item.get("run_id"):
                continue
            run_dir = RUNS_DIR / str(item["run_id"])
            files.extend(run_dir / filename for filename in canonical_run_files)
    files = [path for path in dict.fromkeys(files) if path.exists() and path.is_file()]
    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr(
            "README.md",
            "# Résultats longitudinaux V2 corrigés\n\n"
            "Commencer par `docs/ETAT_ARCHIVE_CORRIGEE_3000.md`, puis lire "
            "`docs/PRIORITY_RESULTS_FOR_PROFESSOR_V2.md` et "
            "`docs/METHODE_ECHANTILLONNAGE_PANEL_3000.md`. L’archive V1 originale est incluse "
            "sans modification. Les traces NetCDF restent dans le dossier de travail.\n",
        )
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
    digest = hashlib.sha256(ZIP_PATH.read_bytes()).hexdigest()
    SHA_PATH.write_text(f"{digest}  {ZIP_PATH.name}\n", encoding="ascii")


def validate_outputs(artifacts: dict[str, pd.DataFrame], integrity: dict[str, Any]) -> dict[str, Any]:
    estimates = artifacts["estimates"]
    contrasts = artifacts["contrasts"]
    diagnostics = artifacts["diagnostics"]
    checks = {
        "integrity_ok": bool(integrity["integrity_ok"]),
        "estimate_rows": len(estimates),
        "estimate_duplicate_keys": int(
            estimates.duplicated(["run_id", "social_group", "vote_category"]).sum()
        ),
        "estimate_intervals_valid": bool(
            ((estimates["lower"] <= estimates["estimate"]) & (estimates["estimate"] <= estimates["upper"])).all()
        ),
        "estimate_probabilities_valid": bool(
            estimates[["lower", "estimate", "upper"]].ge(0).all().all()
            and estimates[["lower", "estimate", "upper"]].le(1).all().all()
        ),
        "contrast_rows": len(contrasts),
        "official_diagnostic_rows": len(diagnostics),
        "official_status_values_valid": bool(diagnostics["mcmc_status"].isin(["pass", "caveat", "fail"]).all()),
        "no_legacy_diagnostic_fields": not any(
            column in diagnostics.columns for column in ("diagnostic_status", "diagnostic_verdict", "classification")
        ),
    }
    checks["ready"] = bool(
        checks["integrity_ok"]
        and checks["estimate_rows"] == 48
        and checks["estimate_duplicate_keys"] == 0
        and checks["estimate_intervals_valid"]
        and checks["estimate_probabilities_valid"]
        and checks["contrast_rows"] == 12
        and checks["official_diagnostic_rows"] == 12
        and checks["official_status_values_valid"]
        and checks["no_legacy_diagnostic_fields"]
    )
    write_json(V2_OUTPUT_DIR / "validation_summary_v2.json", checks)
    if not checks["ready"]:
        raise AssertionError(f"V2 output validation failed: {checks}")
    return checks


def _load_saved_artifacts() -> dict[str, pd.DataFrame]:
    filenames = {
        "aggregates": "aggregate_comparison_v2.csv",
        "estimates": "corrected_estimates_v2.csv",
        "contrasts": "within_period_contrasts_v2.csv",
        "changes": "longitudinal_contrast_changes_v2.csv",
        "diagnostics": "official_diagnostics_v2.csv",
        "identification": "identification_metrics_v2.csv",
        "bootstrap": "panel_bootstrap_sensitivity_v2.csv",
    }
    return {
        key: pd.read_csv(V2_OUTPUT_DIR / filename)
        for key, filename in filenames.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Finalise the non-destructive longitudinal V2 release.")
    parser.add_argument(
        "--refresh-deliverables-only",
        action="store_true",
        help="Refresh the report and archive from validated CSVs without reopening NetCDF traces.",
    )
    args = parser.parse_args()
    ensure_runtime_dirs()
    integrity = verify_manifest(PRESERVATION_MANIFEST)
    if not integrity["integrity_ok"]:
        raise RuntimeError(f"V1 preservation check failed: {integrity}")
    if args.refresh_deliverables_only:
        artifacts = _load_saved_artifacts()
    else:
        artifacts = analyze_selected_runs()
        for scenario_id in ("H0A", "H1"):
            plot_corrected_estimates(artifacts["estimates"], scenario_id)
        plot_aggregation_shift(artifacts["aggregates"])
        plot_contrasts(artifacts["contrasts"])
        plot_diagnostics(artifacts["diagnostics"])
    validate_outputs(artifacts, integrity)
    write_chart_map()
    write_report(artifacts, integrity)
    build_zip()
    print(
        json.dumps(
            {
                "report": str(REPORT_PATH),
                "zip": str(ZIP_PATH),
                "sha256": SHA_PATH.read_text(encoding="ascii").split()[0],
                "integrity_ok": integrity["integrity_ok"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
