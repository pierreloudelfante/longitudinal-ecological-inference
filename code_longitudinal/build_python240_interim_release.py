from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .build_python_longitudinal_outputs_current import (
    EXPECTED,
    LABELS,
    SCENARIOS,
    _comparison_figure,
    _diagnostic_figure,
    _nls_estimands,
    _save_figure,
    _trajectory_figure,
)
from .paths import ROOT


SOURCE_ROOT = ROOT / "outputs" / "longitudinal_2000_v1" / "production"
CANDIDATE_ROOT = SOURCE_ROOT / "all_2x2_candidate"
NLS_PATH = SOURCE_ROOT / "rxc_nls_panel_extension_v11" / "longitudinal_nls_292_candidate.parquet"
PANEL_PATH = ROOT / "panel" / "longitudinal_2000_v1.parquet"
DEFAULT_OUTPUT_ROOT = ROOT / "work" / "longitudinal_2000_v1_python_240_interim"

AGGREGATE_PATH = CANDIDATE_ROOT / "longitudinal_krt_aggregate_240_candidate.parquet"
COMMUNE_PATH = CANDIDATE_ROOT / "longitudinal_krt_commune_240_candidate.parquet"
SELECTION_PATH = CANDIDATE_ROOT / "krt_240_candidate_selection.csv"
SOURCE_MANIFEST_PATH = CANDIDATE_ROOT / "krt_240_candidate_manifest.json"

EXPECTED_PAIRS = 240
EXPECTED_AGGREGATE_ROWS = 720
EXPECTED_COMMUNE_ROWS = 480_000
EXPECTED_COMMUNES_PER_PAIR = 2_000

PALETTE = {
    "blue": "#2F5DA8",
    "gold": "#C99700",
    "pink": "#C03A7A",
    "orange": "#D97706",
    "ink": "#1F2937",
    "grid": "#E5E7EB",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _configure_plotting() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": PALETTE["ink"],
            "axes.labelcolor": PALETTE["ink"],
            "text.color": PALETTE["ink"],
            "xtick.color": PALETTE["ink"],
            "ytick.color": PALETTE["ink"],
            "font.family": "DejaVu Sans",
        }
    )


def _load_sources() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]:
    required = [AGGREGATE_PATH, COMMUNE_PATH, SELECTION_PATH, SOURCE_MANIFEST_PATH, NLS_PATH]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Sources Python manquantes: {missing}")

    aggregate = pd.read_parquet(AGGREGATE_PATH)
    commune = pd.read_parquet(COMMUNE_PATH)
    selection = pd.read_csv(SELECTION_PATH)
    nls = pd.read_parquet(NLS_PATH)
    source_manifest = json.loads(SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))
    return aggregate, commune, selection, nls, source_manifest


def _validate_sources(
    aggregate: pd.DataFrame,
    commune: pd.DataFrame,
    selection: pd.DataFrame,
    source_manifest: dict[str, object],
) -> dict[str, object]:
    pair_columns = ["election_id", "scenario_id"]
    aggregate_pairs = aggregate[pair_columns].drop_duplicates()
    commune_pairs = commune[pair_columns].drop_duplicates()
    selection_pairs = selection[pair_columns].drop_duplicates()
    communes_per_pair = commune.groupby(pair_columns, sort=False)["unit_id"].nunique()

    checks = {
        "selection_policy_initial_only": source_manifest.get("selection_policy") == "initial_only",
        "source_manifest_selected_pairs_240": source_manifest.get("selected_pairs") == EXPECTED_PAIRS,
        "aggregate_pairs_240": len(aggregate_pairs) == EXPECTED_PAIRS,
        "aggregate_rows_720": len(aggregate) == EXPECTED_AGGREGATE_ROWS,
        "commune_pairs_240": len(commune_pairs) == EXPECTED_PAIRS,
        "commune_rows_480000": len(commune) == EXPECTED_COMMUNE_ROWS,
        "communes_2000_per_pair": bool(communes_per_pair.eq(EXPECTED_COMMUNES_PER_PAIR).all()),
        "selection_pairs_240": len(selection_pairs) == EXPECTED_PAIRS,
        "selection_rows_240": len(selection) == EXPECTED_PAIRS,
        "aggregate_key_unique": not aggregate.duplicated(pair_columns + ["estimand"]).any(),
        "commune_key_unique": not commune.duplicated(pair_columns + ["unit_id"]).any(),
        "selection_key_unique": not selection.duplicated(pair_columns).any(),
        "aggregate_intervals_ordered": bool(
            (aggregate["q025"] <= aggregate["median"]).all()
            and (aggregate["median"] <= aggregate["q975"]).all()
        ),
        "aggregate_estimates_finite": bool(
            np.isfinite(aggregate[["mean", "median", "q025", "q975"]].to_numpy()).all()
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    validation = {
        "schema_version": "python_240_interim_validation_v1",
        "checked_at_utc": _utc_now(),
        "status": "pass" if not failed else "fail",
        "checks": checks,
        "failed_checks": failed,
        "important_reservation": (
            "La couverture 240/240 est complète, mais les statuts MCMC initiaux sont conservés "
            "tels quels conformément au choix utilisateur; ils ne constituent pas tous un feu vert diagnostique."
        ),
    }
    if failed:
        raise AssertionError(f"Validation Python 240 échouée: {failed}")
    return validation


def _normalize_base(aggregate: pd.DataFrame) -> pd.DataFrame:
    base = aggregate.copy()
    base.insert(0, "source_model", "Python_NumPyro_KRT")
    base.insert(1, "engine", "numpyro")
    base.insert(
        6,
        "election_family",
        np.where(base["election_id"].astype(str).str.startswith("leg_"), "legislative", "presidential"),
    )
    base = base.rename(
        columns={
            "mean": "estimate_mean",
            "median": "estimate_median",
            "q025": "interval_95_low",
            "q975": "interval_95_high",
        }
    )
    return base.sort_values(["scenario_id", "year", "round", "estimand"]).reset_index(drop=True)


def _coverage_and_diagnostics(selection: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    coverage_rows: list[dict[str, object]] = []
    diagnostic_rows: list[dict[str, object]] = []
    for scenario_id in SCENARIOS:
        subset = selection.loc[selection["scenario_id"].eq(scenario_id)].copy()
        expected = EXPECTED[scenario_id]
        coverage_rows.append(
            {
                "scenario_id": scenario_id,
                "description": LABELS[scenario_id],
                "expected_pairs": expected,
                "completed_pairs": len(subset),
                "coverage_fraction": len(subset) / expected,
                "missing_pairs": expected - len(subset),
                "status": "complete" if len(subset) == expected else "partial",
            }
        )
        for diagnostic_name, column in (
            ("MCMC", "mcmc_status"),
            ("Identification", "identification_status"),
        ):
            counts = subset[column].fillna("missing").value_counts()
            for status in ("pass", "caveat", "fail", "missing"):
                diagnostic_rows.append(
                    {
                        "scenario_id": scenario_id,
                        "description": LABELS[scenario_id],
                        "diagnostic": diagnostic_name,
                        "status": status,
                        "count": int(counts.get(status, 0)),
                        "pairs": len(subset),
                    }
                )
    return pd.DataFrame(coverage_rows), pd.DataFrame(diagnostic_rows)


def _contrast_summary(base: pd.DataFrame) -> pd.DataFrame:
    contrast = base.loc[base["estimand"].eq("b_1_minus_b_2")].copy()
    return (
        contrast.groupby(["scenario_id", "election_family"], as_index=False)
        .agg(
            median_contrast=("estimate_mean", "median"),
            mean_contrast=("estimate_mean", "mean"),
            min_contrast=("estimate_mean", "min"),
            max_contrast=("estimate_mean", "max"),
            elections=("election_id", "nunique"),
        )
        .sort_values(["scenario_id", "election_family"])
        .reset_index(drop=True)
    )


def _write_parquet_and_csv(frame: pd.DataFrame, base_path: Path, csv: bool = True) -> None:
    base_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(base_path.with_suffix(".parquet"), index=False)
    if csv:
        frame.to_csv(base_path.with_suffix(".csv"), index=False, encoding="utf-8-sig")


def _build_global_figures(
    output_root: Path,
    coverage: pd.DataFrame,
    diagnostics: pd.DataFrame,
    contrast_summary: pd.DataFrame,
) -> list[dict[str, object]]:
    _configure_plotting()
    figure_root = output_root / "03_FIGURES" / "globales"
    catalog: list[dict[str, object]] = []

    fig, axis = plt.subplots(figsize=(10.5, 5.8))
    ordered = coverage.iloc[::-1]
    axis.barh(ordered["scenario_id"], ordered["coverage_fraction"] * 100, color=PALETTE["blue"])
    axis.set_xlim(0, 105)
    axis.set_xlabel("Couverture des scrutins attendus (%)")
    axis.set_title("Couverture Python/NumPyro par hypothèse", loc="left", fontweight="bold")
    axis.text(
        0,
        1.02,
        "240 couples canoniques initiaux; H6–H7 portent sur 16 scrutins, les autres sur 26",
        transform=axis.transAxes,
        color="#4B5563",
        fontsize=9,
    )
    for y, value in enumerate(ordered["coverage_fraction"] * 100):
        axis.text(value + 1, y, f"{value:.0f}%", va="center", fontsize=9)
    axis.grid(axis="x", color=PALETTE["grid"], linewidth=0.8)
    axis.spines[["top", "right", "left"]].set_visible(False)
    paths = _save_figure(fig, figure_root, "couverture_python_240_par_hypothese")
    catalog.append(
        {
            "figure_id": "coverage_python_240",
            "title": "Couverture Python/NumPyro par hypothèse",
            "question": "Les 240 couples canoniques sont-ils tous présents ?",
            "family": "comparison",
            "source_table": "02_BASE_TRANSPARENTE/couverture_python_240.parquet",
            "paths": [path.relative_to(output_root).as_posix() for path in paths],
        }
    )

    mcmc = diagnostics.loc[
        diagnostics["diagnostic"].eq("MCMC") & diagnostics["status"].isin(["pass", "caveat", "fail"])
    ].copy()
    pivot = mcmc.pivot(index="scenario_id", columns="status", values="count").fillna(0).reindex(SCENARIOS)
    fig, axis = plt.subplots(figsize=(11.5, 6.2))
    bottom = np.zeros(len(pivot))
    for status, color in (("pass", PALETTE["blue"]), ("caveat", PALETTE["gold"]), ("fail", PALETTE["pink"])):
        values = pivot.get(status, pd.Series(0, index=pivot.index)).to_numpy()
        axis.bar(pivot.index, values, bottom=bottom, label=status, color=color)
        bottom += values
    axis.set_ylabel("Nombre de couples")
    axis.set_title("Statuts MCMC des ajustements initiaux sélectionnés", loc="left", fontweight="bold")
    axis.text(
        0,
        1.02,
        "Les statuts imparfaits restent visibles et ne sont pas remplacés par des relances ciblées",
        transform=axis.transAxes,
        color="#4B5563",
        fontsize=9,
    )
    axis.legend(frameon=False, ncol=3, loc="upper left")
    axis.grid(axis="y", color=PALETTE["grid"], linewidth=0.8)
    axis.spines[["top", "right"]].set_visible(False)
    paths = _save_figure(fig, figure_root, "diagnostics_mcmc_python_240")
    catalog.append(
        {
            "figure_id": "mcmc_status_python_240",
            "title": "Statuts MCMC des ajustements initiaux sélectionnés",
            "question": "Quelle part de la couverture 240/240 porte une réserve diagnostique ?",
            "family": "composition",
            "source_table": "02_BASE_TRANSPARENTE/diagnostics_python_240.parquet",
            "paths": [path.relative_to(output_root).as_posix() for path in paths],
        }
    )

    fig, axis = plt.subplots(figsize=(12.2, 7.0))
    scenarios = list(SCENARIOS)
    y = np.arange(len(scenarios))
    width = 0.34
    for offset, family, color in (
        (-width / 2, "legislative", PALETTE["blue"]),
        (width / 2, "presidential", PALETTE["pink"]),
    ):
        values = (
            contrast_summary.loc[contrast_summary["election_family"].eq(family)]
            .set_index("scenario_id")
            .reindex(scenarios)["median_contrast"]
        )
        axis.barh(y + offset, values, height=width, label=family, color=color)
    axis.axvline(0, color=PALETTE["ink"], linestyle="--", linewidth=1)
    axis.set_yticks(y, scenarios)
    axis.invert_yaxis()
    axis.set_xlabel("Médiane interannuelle du contraste estimé")
    axis.set_title("Contrastes Python médians par hypothèse et famille électorale", loc="left", fontweight="bold")
    axis.text(
        0,
        1.02,
        "Résumé descriptif des estimations initiales; les législatives et présidentielles restent séparées",
        transform=axis.transAxes,
        color="#4B5563",
        fontsize=9,
    )
    axis.legend(frameon=False, ncol=2, loc="lower right")
    axis.grid(axis="x", color=PALETTE["grid"], linewidth=0.8)
    axis.spines[["top", "right", "left"]].set_visible(False)
    paths = _save_figure(fig, figure_root, "contrastes_medians_python_par_famille")
    catalog.append(
        {
            "figure_id": "median_contrasts_python_by_family",
            "title": "Contrastes Python médians par hypothèse et famille électorale",
            "question": "Comment résumer les contrastes sans fusionner les familles électorales ?",
            "family": "comparison",
            "source_table": "02_BASE_TRANSPARENTE/contrastes_python_par_hypothese_famille.parquet",
            "paths": [path.relative_to(output_root).as_posix() for path in paths],
        }
    )
    return catalog


def _build_scenario_outputs(
    output_root: Path,
    aggregate: pd.DataFrame,
    selection: pd.DataFrame,
    nls: pd.DataFrame,
) -> list[dict[str, object]]:
    nls = nls.loc[nls["scenario_id"].isin(SCENARIOS)].copy()
    nls_estimands = _nls_estimands(nls)
    catalog: list[dict[str, object]] = []
    for scenario_id in SCENARIOS:
        scenario_aggregate = aggregate.loc[aggregate["scenario_id"].eq(scenario_id)].copy()
        scenario_selection = selection.loc[selection["scenario_id"].eq(scenario_id)].copy()
        scenario_nls_estimands = nls_estimands.loc[nls_estimands["scenario_id"].eq(scenario_id)].copy()
        comparison = scenario_aggregate.merge(
            scenario_nls_estimands,
            on=["panel_id", "election_id", "year", "round", "scenario_id", "estimand"],
            how="left",
            validate="one_to_one",
        )
        if comparison["nls_estimate"].isna().any():
            raise AssertionError(f"{scenario_id}: appariement NLS incomplet")
        scenario_root = output_root / "03_FIGURES" / "par_hypothese" / scenario_id
        completed = len(scenario_selection)
        expected = EXPECTED[scenario_id]
        items = (
            (
                "trajectory",
                _trajectory_figure(scenario_aggregate, scenario_id, completed, expected),
                f"{scenario_id}_trajectoires_krt_python",
                "Trajectoires KRT Python et intervalles à 95 %",
                "01_DONNEES_CANONIQUES/krt_aggregate_python_240.parquet",
            ),
            (
                "krt_vs_nls",
                _comparison_figure(comparison, scenario_id, completed, expected),
                f"{scenario_id}_comparaison_krt_nls",
                "Comparaison descriptive KRT Python et NLS",
                "02_BASE_TRANSPARENTE/base_resultats_python_long.parquet",
            ),
            (
                "diagnostics",
                _diagnostic_figure(scenario_selection, scenario_id),
                f"{scenario_id}_diagnostics_par_scrutin",
                "Diagnostics des ajustements initiaux par scrutin",
                "02_BASE_TRANSPARENTE/diagnostics_python_240.parquet",
            ),
        )
        for suffix, figure, stem, title, source_table in items:
            paths = _save_figure(figure, scenario_root, stem)
            catalog.append(
                {
                    "figure_id": f"{scenario_id}_{suffix}",
                    "scenario_id": scenario_id,
                    "title": title,
                    "question": f"Lecture longitudinale de {LABELS[scenario_id]}",
                    "family": "trend" if suffix != "diagnostics" else "status",
                    "source_table": source_table,
                    "paths": [path.relative_to(output_root).as_posix() for path in paths],
                }
            )
    return catalog


def _dictionary(frame: pd.DataFrame, dataset: str) -> pd.DataFrame:
    descriptions = {
        "source_model": "Modèle source de la ligne.",
        "engine": "Moteur d'estimation utilisé.",
        "panel_id": "Identifiant du panel harmonisé.",
        "election_id": "Identifiant canonique du scrutin et du tour.",
        "year": "Année du scrutin.",
        "round": "Tour du scrutin.",
        "election_family": "Famille électorale, législative ou présidentielle.",
        "scenario_id": "Hypothèse sociale × électorale.",
        "estimand": "Paramètre agrégé: b_1, b_2 ou b_1_minus_b_2.",
        "estimate_mean": "Moyenne postérieure pondérée.",
        "estimate_median": "Médiane postérieure pondérée.",
        "interval_95_low": "Borne basse de l'intervalle postérieur à 95 %.",
        "interval_95_high": "Borne haute de l'intervalle postérieur à 95 %.",
        "mcmc_status": "Statut diagnostique MCMC conservé depuis l'ajustement initial.",
        "identification_status": "Statut d'identification conservé depuis l'ajustement initial.",
        "selection_status": "Statut de sélection canonique du run initial.",
    }
    return pd.DataFrame(
        {
            "dataset": dataset,
            "column": frame.columns,
            "dtype": [str(frame[column].dtype) for column in frame.columns],
            "description": [descriptions.get(column, "Champ source conservé pour audit et reproductibilité.") for column in frame.columns],
        }
    )


def _artifact_payload(
    output_root: Path,
    coverage: pd.DataFrame,
    diagnostics: pd.DataFrame,
    contrast_summary: pd.DataFrame,
    source_manifest: dict[str, object],
) -> dict[str, object]:
    title = "Résultats Python/NumPyro — état intermédiaire 240/240"
    generated_at = _utc_now()
    mcmc = diagnostics.loc[
        diagnostics["diagnostic"].eq("MCMC") & diagnostics["status"].isin(["pass", "caveat", "fail"])
    ].copy()
    mcmc["status_label"] = mcmc["status"].map(
        {"pass": "Pass", "caveat": "Réserve", "fail": "Échec diagnostique"}
    )
    mcmc_fail = int(mcmc.loc[mcmc["status"].eq("fail"), "count"].sum())
    headline = [
        {
            "pairs": EXPECTED_PAIRS,
            "aggregate_rows": EXPECTED_AGGREGATE_ROWS,
            "commune_rows": EXPECTED_COMMUNE_ROWS,
            "mcmc_fail": mcmc_fail,
        }
    ]
    sources = [
        {
            "id": "python_manifest",
            "label": "Manifeste canonique Python 240",
            "path": "01_DONNEES_CANONIQUES/krt_240_candidate_manifest.json",
            "query": {
                "description": "Sélection canonique initial_only des 240 couples Python/NumPyro.",
                "language": "python",
                "tables_used": ["outputs.longitudinal_2000_v1.production.all_2x2_candidate"],
                "executed_at": source_manifest.get("created_at_utc"),
                "filters": ["selection_policy = initial_only", "targeted reruns excluded from selection"],
            },
        },
        {
            "id": "python_aggregate",
            "label": "Résultats agrégés Python/NumPyro",
            "path": "01_DONNEES_CANONIQUES/krt_aggregate_python_240.parquet",
            "query": {
                "description": "Agrégation des trois estimands pour chaque couple scrutin × hypothèse.",
                "language": "python",
                "tables_used": ["01_DONNEES_CANONIQUES/krt_aggregate_python_240.parquet"],
                "metric_definitions": [
                    "estimate_mean: moyenne postérieure pondérée par les poids communaux déclarés",
                    "b_1_minus_b_2: contraste entre groupe cible et groupe complémentaire",
                ],
            },
        },
        {
            "id": "python_selection",
            "label": "Sélection et diagnostics Python",
            "path": "01_DONNEES_CANONIQUES/krt_selection_python_240.parquet",
            "query": {
                "description": "Un run canonique initial par couple, avec statuts diagnostiques conservés.",
                "language": "python",
                "tables_used": ["01_DONNEES_CANONIQUES/krt_selection_python_240.parquet"],
            },
        },
    ]
    cards = [
        {
            "id": "pairs_card",
            "dataset": "headline_metrics",
            "sourceId": "python_manifest",
            "description": "Couverture complète des couples scrutin × hypothèse.",
            "metrics": [{"label": "Couples Python", "field": "pairs", "format": "number"}],
        },
        {
            "id": "aggregate_card",
            "dataset": "headline_metrics",
            "sourceId": "python_aggregate",
            "description": "Trois estimands agrégés par couple.",
            "metrics": [{"label": "Lignes agrégées", "field": "aggregate_rows", "format": "number"}],
        },
        {
            "id": "commune_card",
            "dataset": "headline_metrics",
            "sourceId": "python_aggregate",
            "description": "2 000 communes par couple canonique.",
            "metrics": [{"label": "Lignes communales", "field": "commune_rows", "format": "compact"}],
        },
        {
            "id": "mcmc_fail_card",
            "dataset": "headline_metrics",
            "sourceId": "python_selection",
            "description": "Statuts initiaux conservés pour transparence; aucune relance ciblée sélectionnée.",
            "metrics": [{"label": "Échecs diagnostiques MCMC", "field": "mcmc_fail", "format": "number"}],
        },
    ]
    charts = [
        {
            "id": "mcmc_status_chart",
            "title": "Statuts MCMC par hypothèse",
            "subtitle": "Comptage des ajustements initiaux sélectionnés; les réserves restent visibles",
            "showDescription": True,
            "intent": "composition",
            "question": "Quelle part des 240 ajustements porte une réserve diagnostique ?",
            "rationale": "Barres empilées pour comparer la composition des statuts par hypothèse.",
            "type": "bar",
            "dataset": "mcmc_status",
            "sourceId": "python_selection",
            "encodings": {
                "x": {"field": "scenario_id", "type": "nominal", "label": "Hypothèse"},
                "y": {"field": "count", "type": "quantitative", "label": "Nombre de couples"},
                "color": {"field": "status_label", "type": "nominal", "label": "Statut"},
                "tooltip": [
                    {"field": "description", "type": "text", "label": "Définition"},
                    {"field": "pairs", "type": "quantitative", "label": "Couples attendus"},
                ],
            },
            "settings": {"groupMode": "stacked", "orientation": "vertical", "sort": "custom"},
            "palette": {"kind": "categorical", "name": "blue-gold-pink"},
            "layout": "full",
            "surface": {"surface": "export", "viewMode": "both", "showControls": True},
        },
        {
            "id": "contrast_summary_chart",
            "title": "Contrastes médians par hypothèse et famille électorale",
            "subtitle": "Médiane interannuelle des estimations b₁−b₂; législatives et présidentielles séparées",
            "showDescription": True,
            "intent": "comparison",
            "question": "Comment résumer les contrastes sans fusionner les familles électorales ?",
            "rationale": "Barres groupées parce que les deux familles constituent une comparaison discrète.",
            "type": "bar",
            "dataset": "contrast_summary",
            "sourceId": "python_aggregate",
            "encodings": {
                "x": {"field": "scenario_id", "type": "nominal", "label": "Hypothèse"},
                "y": {"field": "median_contrast", "type": "quantitative", "label": "Contraste médian"},
                "color": {"field": "election_family", "type": "nominal", "label": "Famille électorale"},
                "tooltip": [
                    {"field": "elections", "type": "quantitative", "label": "Scrutins"},
                    {"field": "min_contrast", "type": "quantitative", "label": "Minimum"},
                    {"field": "max_contrast", "type": "quantitative", "label": "Maximum"},
                ],
            },
            "settings": {"groupMode": "grouped", "orientation": "vertical", "sort": "custom"},
            "referenceLines": [{"axis": "y", "value": 0, "label": "Absence de contraste", "lineStyle": "dashed", "color": "neutral"}],
            "palette": {"kind": "categorical", "name": "blue-pink"},
            "layout": "full",
            "surface": {"surface": "export", "viewMode": "both", "showControls": True},
        },
    ]
    tables = [
        {
            "id": "coverage_table",
            "title": "Couverture par hypothèse",
            "subtitle": "Nombre de scrutins attendus et sélectionnés dans la consolidation initial_only",
            "showDescription": True,
            "dataset": "coverage",
            "sourceId": "python_manifest",
            "defaultSort": {"field": "scenario_id", "direction": "asc"},
            "density": "spacious",
            "layout": "full",
            "columns": [
                {"field": "scenario_id", "label": "Hypothèse", "type": "text"},
                {"field": "description", "label": "Définition", "type": "text"},
                {"field": "expected_pairs", "label": "Attendus", "format": "number"},
                {"field": "completed_pairs", "label": "Sélectionnés", "format": "number"},
                {"field": "coverage_fraction", "label": "Couverture", "format": "percent"},
                {"field": "status", "label": "Statut", "type": "text"},
            ],
        }
    ]
    blocks = [
        {"id": "title", "type": "markdown", "body": f"# {title}"},
        {
            "id": "technical_summary",
            "type": "markdown",
            "sourceId": "python_manifest",
            "body": (
                "## Les 240 couples Python sont matérialisés, avec leurs réserves diagnostiques\n\n"
                "- **Couverture :** 240 couples scrutin × hypothèse sont sélectionnés selon la politique `initial_only`.\n"
                "- **Granularité :** 720 lignes agrégées et 480 000 lignes communales sont disponibles en Parquet.\n"
                f"- **Diagnostic :** {mcmc_fail} ajustements initiaux portent le statut MCMC `fail`; ils restent inclus pour respecter le périmètre demandé et sont signalés, pas masqués.\n"
                "- **Portée :** ce rendu est exclusivement Python/NumPyro. La comparaison avec R sera ajoutée après la couverture R 240/240."
            ),
        },
        {"id": "headline", "type": "metric-strip", "cardIds": [card["id"] for card in cards]},
        {
            "id": "diagnostic_intro",
            "type": "markdown",
            "body": (
                "## La couverture numérique n'efface pas les diagnostics imparfaits\n\n"
                "La figure distingue les statuts des ajustements initiaux retenus. Un couple présent dans la base n'est donc pas automatiquement interprétable comme une estimation robuste; la base conserve explicitement `mcmc_status` et `identification_status`."
            ),
        },
        {"id": "diagnostic_chart_block", "type": "chart", "chartId": "mcmc_status_chart", "layout": "full"},
        {
            "id": "contrast_intro",
            "type": "markdown",
            "body": (
                "## Les contrastes sont présentés séparément pour les deux familles électorales\n\n"
                "Le résumé ci-dessous compare les médianes interannuelles de `b_1_minus_b_2`. Il s'agit d'un aperçu descriptif: les trajectoires complètes et leurs intervalles à 95 % sont livrées séparément pour chaque hypothèse."
            ),
        },
        {"id": "contrast_chart_block", "type": "chart", "chartId": "contrast_summary_chart", "layout": "full"},
        {
            "id": "scope_definitions",
            "type": "markdown",
            "body": (
                "## Périmètre, unités et définitions\n\n"
                "Chaque couple associe un scrutin canonique à une hypothèse sociale × électorale. Les trois estimands sont `b_1`, `b_2` et leur différence `b_1_minus_b_2`. Les lignes communales conservent 2 000 unités harmonisées par couple; les résultats agrégés utilisent les poids déclarés dans la source."
            ),
        },
        {"id": "coverage_table_block", "type": "table", "tableId": "coverage_table", "layout": "full"},
        {
            "id": "methodology",
            "type": "markdown",
            "body": (
                "## Méthode et traçabilité\n\n"
                "Les résultats proviennent des ajustements canoniques initiaux NumPyro/KRT. Les relances ciblées déjà produites sont conservées uniquement comme artefacts d'audit et ne participent pas à cette sélection. Les fichiers Parquet canoniques sont copiés sans transformation; la base longue renomme seulement les champs d'estimation pour une lecture homogène."
            ),
        },
        {
            "id": "limitations",
            "type": "markdown",
            "body": (
                "## Limites, incertitude et robustesse\n\n"
                "Cette version ne valide pas la convergence de tous les ajustements: les statuts `caveat` et `fail` doivent rester visibles dans toute interprétation. Elle ne contient pas encore la réplication R ni la comparaison Python–R. Les figures globales résument des trajectoires hétérogènes et ne remplacent pas les graphiques détaillés par hypothèse."
            ),
        },
        {
            "id": "next_steps",
            "type": "markdown",
            "body": (
                "## Prochaine étape recommandée\n\n"
                "1. Terminer les seuls couples R manquants jusqu'à 240/240.\n"
                "2. Consolider la comparaison Python–R sans modifier la sélection Python `initial_only`.\n"
                "3. Réutiliser cette arborescence, ses Parquet et ses figures dans la livraison professeur et la présentation finale."
            ),
        },
        {
            "id": "further_questions",
            "type": "markdown",
            "body": (
                "## Questions encore ouvertes\n\n"
                "- Quels écarts Python–R persistent une fois les 240 couples R consolidés ?\n"
                "- Les réserves diagnostiques se concentrent-elles sur certaines années ou hypothèses ?\n"
                "- Quelles conclusions restent stables lorsqu'on sépare strictement législatives et présidentielles ?"
            ),
        },
    ]
    manifest = {
        "version": 1,
        "surface": "report",
        "title": title,
        "description": "Rendu technique intermédiaire des 240 estimations Python/NumPyro.",
        "generatedAt": generated_at,
        "cards": cards,
        "charts": charts,
        "tables": tables,
        "sources": sources,
        "blocks": blocks,
    }
    snapshot = {
        "version": 1,
        "generatedAt": generated_at,
        "status": "ready",
        "datasets": {
            "headline_metrics": headline,
            "coverage": coverage.to_dict(orient="records"),
            "mcmc_status": mcmc[
                ["scenario_id", "description", "status", "status_label", "count", "pairs"]
            ].to_dict(orient="records"),
            "contrast_summary": contrast_summary.to_dict(orient="records"),
        },
    }
    return {
        "surface": "report",
        "manifest": manifest,
        "snapshot": snapshot,
        "sources": sources,
        "package_info": {
            "artifact_role": "python_240_interim_report",
            "release_root": output_root.name,
        },
    }


def _write_documents(
    output_root: Path,
    validation: dict[str, object],
    coverage: pd.DataFrame,
    diagnostics: pd.DataFrame,
    figure_catalog: pd.DataFrame,
) -> None:
    docs = output_root / "00_LIRE_D_ABORD"
    docs.mkdir(parents=True, exist_ok=True)
    mcmc = diagnostics.loc[diagnostics["diagnostic"].eq("MCMC")]
    fail_count = int(mcmc.loc[mcmc["status"].eq("fail"), "count"].sum())
    caveat_count = int(mcmc.loc[mcmc["status"].eq("caveat"), "count"].sum())
    pass_count = int(mcmc.loc[mcmc["status"].eq("pass"), "count"].sum())
    readme = f"""# Livraison intermédiaire Python/NumPyro — 240/240

Cette arborescence matérialise dès maintenant les **240 couples canoniques Python/NumPyro**, pendant que la réplication R poursuit ses couples manquants.

## À ouvrir en premier

1. `04_RAPPORT/RAPPORT_RESULTATS_PYTHON_240.html` — rapport autonome et portable.
2. `02_BASE_TRANSPARENTE/base_resultats_python_long.parquet` — base agrégée normalisée.
3. `03_FIGURES/FIGURE_CATALOG.csv` — catalogue des figures PNG/SVG.
4. `00_LIRE_D_ABORD/LIMITES_ET_DIAGNOSTICS.md` — réserves indispensables.

## Couverture

- Couples sélectionnés : **{int(coverage['completed_pairs'].sum())}/240**.
- Lignes agrégées : **720**.
- Lignes communales : **480 000**.
- Politique de sélection : **initial_only**.
- Relances ciblées : conservées pour audit, exclues de la sélection.

## Important

La couverture est complète, mais elle ne signifie pas que tous les diagnostics sont satisfaisants. Parmi les ajustements initiaux sélectionnés : **{pass_count} pass**, **{caveat_count} caveat** et **{fail_count} fail** au niveau MCMC. Les statuts restent présents dans toutes les bases pertinentes.

La comparaison Python–R et le ZIP professeur final ne sont pas encore inclus dans cette version intermédiaire.
"""
    (docs / "README.md").write_text(readme, encoding="utf-8")

    methods = """# Méthodes Python et construction des sorties

## Source statistique

Les estimations proviennent du modèle KRT exécuté avec NumPyro sur le panel harmonisé `longitudinal_2000_v1`. Chaque couple correspond à un scrutin canonique et à une hypothèse sociale × électorale.

## Sélection

La consolidation applique strictement `initial_only`. Les artefacts issus de relances ciblées restent disponibles pour audit mais ne remplacent pas les ajustements canoniques initiaux.

## Granularités livrées

- commune : une ligne par couple × commune, soit 480 000 lignes ;
- agrégée : trois estimands par couple, soit 720 lignes ;
- sélection : une ligne par couple, soit 240 lignes ;
- base longue : version agrégée normalisée avec famille électorale, moteur, diagnostics et intervalles.

## Estimands

- `b_1` : probabilité estimée pour le groupe cible ;
- `b_2` : probabilité estimée pour le groupe complémentaire ;
- `b_1_minus_b_2` : contraste entre les deux groupes.
"""
    (docs / "METHODES_PYTHON.md").write_text(methods, encoding="utf-8")

    limits = f"""# Limites et diagnostics

Cette version est complète en **couverture** mais reste assortie de réserves diagnostiques.

- MCMC pass : {pass_count}
- MCMC caveat : {caveat_count}
- MCMC fail : {fail_count}
- Validation structurelle des Parquet : {validation['status']}

Les statuts `fail` ne sont ni supprimés ni remplacés, conformément au périmètre demandé. Toute interprétation substantielle doit donc filtrer ou stratifier les résultats selon `mcmc_status` et `identification_status`.

La réplication R est encore en cours. Aucun accord ou désaccord Python–R ne doit être déduit de cette livraison intermédiaire.
"""
    (docs / "LIMITES_ET_DIAGNOSTICS.md").write_text(limits, encoding="utf-8")

    notes = {
        "schema_version": "python_240_interim_source_notes_v1",
        "created_at_utc": _utc_now(),
        "audience": "technical",
        "delivery_mode": "html",
        "required_structure_mapping": {
            "title": "artifact manifest title and first markdown block",
            "technical_summary": "technical_summary",
            "key_findings_with_visual_evidence": ["mcmc_status_chart", "contrast_summary_chart"],
            "scope_data_metric_definitions": "scope_definitions",
            "methodology": "methodology",
            "limitations_uncertainty_robustness": "limitations",
            "recommended_next_steps": "next_steps",
            "further_questions": "further_questions",
        },
        "chart_map": figure_catalog.to_dict(orient="records"),
        "quantitative_segments_without_visual": [],
        "important_caveat": "coverage complete; diagnostics not universally satisfactory; R absent",
    }
    _write_json(output_root / "04_RAPPORT" / "SOURCE_NOTES.json", notes)


def _tree_lines(root: Path) -> list[str]:
    lines = [root.name + "/"]
    paths = sorted(path for path in root.rglob("*") if path.name != "MANIFEST.json")
    for path in paths:
        relative = path.relative_to(root)
        indent = "  " * len(relative.parts)
        suffix = "/" if path.is_dir() else ""
        lines.append(f"{indent}{relative.name}{suffix}")
    return lines


def _catalogue(output_root: Path) -> pd.DataFrame:
    excluded = {"MANIFEST.json", "CATALOGUE_SORTIES.csv", "CATALOGUE_SORTIES.parquet"}
    rows: list[dict[str, object]] = []
    for path in sorted(item for item in output_root.rglob("*") if item.is_file()):
        if path.name in excluded:
            continue
        relative = path.relative_to(output_root).as_posix()
        rows.append(
            {
                "path": relative,
                "extension": path.suffix.lower(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "role": relative.split("/", maxsplit=1)[0],
            }
        )
    return pd.DataFrame(rows)


def prepare(output_root: Path) -> dict[str, object]:
    if output_root.exists():
        raise FileExistsError(
            f"Le dossier intermédiaire existe déjà: {output_root}. Utiliser finalize ou choisir un autre --output-root."
        )
    for relative in (
        "00_LIRE_D_ABORD",
        "01_DONNEES_CANONIQUES",
        "02_BASE_TRANSPARENTE",
        "03_FIGURES/globales",
        "03_FIGURES/par_hypothese",
        "04_RAPPORT",
        "05_REPRODUCTION",
    ):
        (output_root / relative).mkdir(parents=True, exist_ok=True)

    aggregate, commune, selection, nls, source_manifest = _load_sources()
    validation = _validate_sources(aggregate, commune, selection, source_manifest)
    base = _normalize_base(aggregate)
    coverage, diagnostics = _coverage_and_diagnostics(selection)
    contrast_summary = _contrast_summary(base)

    canonical = output_root / "01_DONNEES_CANONIQUES"
    shutil.copy2(AGGREGATE_PATH, canonical / "krt_aggregate_python_240.parquet")
    shutil.copy2(COMMUNE_PATH, canonical / "krt_commune_python_240.parquet")
    shutil.copy2(SOURCE_MANIFEST_PATH, canonical / "krt_240_candidate_manifest.json")
    selection.to_parquet(canonical / "krt_selection_python_240.parquet", index=False)
    selection.to_csv(canonical / "krt_selection_python_240.csv", index=False, encoding="utf-8-sig")
    if PANEL_PATH.exists():
        shutil.copy2(PANEL_PATH, canonical / "panel_longitudinal_2000_v1.parquet")

    transparent = output_root / "02_BASE_TRANSPARENTE"
    _write_parquet_and_csv(base, transparent / "base_resultats_python_long")
    _write_parquet_and_csv(coverage, transparent / "couverture_python_240")
    _write_parquet_and_csv(diagnostics, transparent / "diagnostics_python_240")
    _write_parquet_and_csv(
        contrast_summary,
        transparent / "contrastes_python_par_hypothese_famille",
    )
    dictionary = pd.concat(
        [
            _dictionary(base, "base_resultats_python_long"),
            _dictionary(selection, "krt_selection_python_240"),
        ],
        ignore_index=True,
    )
    dictionary.to_csv(transparent / "DICTIONNAIRE_COLONNES.csv", index=False, encoding="utf-8-sig")
    _write_json(transparent / "VALIDATION_DONNEES.json", validation)

    figure_catalog = _build_global_figures(output_root, coverage, diagnostics, contrast_summary)
    figure_catalog += _build_scenario_outputs(output_root, aggregate, selection, nls)
    figure_frame = pd.DataFrame(figure_catalog)
    figure_frame["paths"] = figure_frame["paths"].map(json.dumps)
    figure_frame.to_csv(output_root / "03_FIGURES" / "FIGURE_CATALOG.csv", index=False, encoding="utf-8-sig")
    figure_frame.to_parquet(output_root / "03_FIGURES" / "FIGURE_CATALOG.parquet", index=False)

    artifact = _artifact_payload(output_root, coverage, diagnostics, contrast_summary, source_manifest)
    _write_json(output_root / "04_RAPPORT" / "artifact.json", artifact)
    _write_documents(output_root, validation, coverage, diagnostics, pd.DataFrame(figure_catalog))
    shutil.copy2(Path(__file__), output_root / "05_REPRODUCTION" / Path(__file__).name)
    (output_root / "05_REPRODUCTION" / "REPRODUIRE.md").write_text(
        """# Reproduire la livraison intermédiaire Python

Depuis la racine `longitudinal_2022` :

```powershell
& '..\\pour_moi_avec_data\\.venv-ei\\Scripts\\python.exe' -m code_longitudinal.build_python240_interim_release prepare
```

Le rapport HTML est ensuite construit à partir de `04_RAPPORT/artifact.json` par le générateur portable Data Analytics. Le mode `finalize` recalcule le catalogue, les empreintes SHA-256 et le manifeste après ce rendu.
""",
        encoding="utf-8",
    )
    (output_root / "00_LIRE_D_ABORD" / "ARBORESCENCE.txt").write_text(
        "\n".join(_tree_lines(output_root)) + "\n", encoding="utf-8"
    )
    return finalize(output_root)


def finalize(output_root: Path) -> dict[str, object]:
    if not output_root.exists():
        raise FileNotFoundError(output_root)
    catalogue = _catalogue(output_root)
    catalogue.to_csv(output_root / "02_BASE_TRANSPARENTE" / "CATALOGUE_SORTIES.csv", index=False, encoding="utf-8-sig")
    catalogue.to_parquet(output_root / "02_BASE_TRANSPARENTE" / "CATALOGUE_SORTIES.parquet", index=False)
    report_path = output_root / "04_RAPPORT" / "RAPPORT_RESULTATS_PYTHON_240.html"
    validation_path = output_root / "02_BASE_TRANSPARENTE" / "VALIDATION_DONNEES.json"
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    manifest = {
        "schema_version": "longitudinal_python_240_interim_release_v1",
        "created_at_utc": _utc_now(),
        "status": "complete_for_python_scope_with_diagnostic_reservations",
        "scope": "python_numpyro_only",
        "python_pairs": EXPECTED_PAIRS,
        "python_aggregate_rows": EXPECTED_AGGREGATE_ROWS,
        "python_commune_rows": EXPECTED_COMMUNE_ROWS,
        "selection_policy": "initial_only",
        "targeted_reruns_selected": False,
        "r_comparison_included": False,
        "r_status": "still_running_outside_this_package",
        "data_validation_status": validation["status"],
        "report_html_ready": report_path.exists(),
        "report_html_path": report_path.relative_to(output_root).as_posix() if report_path.exists() else None,
        "file_count_excluding_manifest": len(catalogue),
        "catalogue_path": "02_BASE_TRANSPARENTE/CATALOGUE_SORTIES.parquet",
        "files": catalogue.to_dict(orient="records"),
    }
    _write_json(output_root / "MANIFEST.json", manifest)
    (output_root / "00_LIRE_D_ABORD" / "ARBORESCENCE.txt").write_text(
        "\n".join(_tree_lines(output_root)) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: value for key, value in manifest.items() if key != "files"}, ensure_ascii=False, indent=2))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Python-only 240/240 interim professor release.")
    parser.add_argument("mode", choices=("prepare", "finalize"))
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    expected_parent = (ROOT / "work").resolve()
    if expected_parent not in output_root.parents:
        raise ValueError(f"--output-root doit rester dans {expected_parent}")
    if args.mode == "prepare":
        prepare(output_root)
    else:
        finalize(output_root)


if __name__ == "__main__":
    main()
