from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .paths import ROOT
from .release_scope import load_release_scope
from .utils import write_json


SOURCE_V102_CONFIG = ROOT / "config" / "releases" / "v1.0.2.json"


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return json.loads(frame.replace({np.nan: None}).to_json(orient="records", force_ascii=False))


def _source(
    source_id: str,
    label: str,
    path: str,
    description: str,
    definitions: list[str],
    *,
    panel_size: int,
    sql: str,
) -> dict[str, Any]:
    return {
        "id": source_id,
        "label": label,
        "path": path,
        "query": {
            "engine": "local_parquet",
            "language": "sql",
            "description": (
                description
                + " Requete SQL equivalente a la selection Python materialisee dans le snapshot; "
                "le notebook d'audit conserve le calcul canonique execute."
            ),
            "sql": sql,
            "tables_used": [path],
            "filters": ["Selection des runs canoniques uniquement", f"Panel fixe de {panel_size:,} communes"],
            "metric_definitions": definitions,
        },
    }


def build_report_artifact(release_root: Path, config_path: Path, output_path: Path) -> dict[str, Any]:
    scope = load_release_scope(config_path)
    source_scope = load_release_scope(SOURCE_V102_CONFIG)
    h23_scenarios = tuple(
        scenario for scenario in scope.krt_scenarios if scenario not in source_scope.krt_scenarios
    )
    h23_pairs = scope.expected_elections * len(h23_scenarios)
    aggregate = pd.read_parquet(release_root / "01_resultats_python" / "longitudinal_krt_aggregate.parquet")
    commune = pd.read_parquet(release_root / "01_resultats_python" / "longitudinal_krt_commune.parquet")
    nls = pd.read_parquet(release_root / "01_resultats_python" / "longitudinal_nls.parquet")
    diagnostics = pd.read_csv(release_root / "02_syntheses" / "diagnostics_krt_par_election.csv")
    comparison_path = release_root / "02_syntheses" / "krt_nls_comparison_h0a_h1_h2_h3.csv"
    comparison = pd.read_csv(comparison_path)
    definitions = pd.read_csv(release_root / "02_syntheses" / "definitions_hypotheses.csv")
    aggregate["election_type"] = aggregate["election_id"].str.slice(0, 3).map(
        {"leg": "legislative", "pre": "presidential"}
    )
    generated_at = datetime.now(timezone.utc).isoformat()
    scenario_sql = ", ".join("'" + scenario.replace("'", "''") + "'" for scenario in scope.krt_scenarios)

    diagnostic_counts = (
        diagnostics.groupby(["scenario_id", "mcmc_status"])
        .size()
        .unstack(fill_value=0)
        .reindex(scope.krt_scenarios, fill_value=0)
        .reset_index()
    )
    for column in ("pass", "caveat", "fail"):
        if column not in diagnostic_counts:
            diagnostic_counts[column] = 0
    identification_counts = (
        diagnostics.groupby(["scenario_id", "identification_status"])
        .size()
        .rename("n_runs")
        .reset_index()
    )
    target = aggregate.loc[
        aggregate["scenario_id"].isin(["H2", "H3"])
        & aggregate["estimand"].eq("b_1")
    ].copy()
    target_leg = target.loc[target["election_type"].eq("legislative")]
    target_pre = target.loc[target["election_type"].eq("presidential")]
    target_leg = target_leg.assign(
        line_style=target_leg["scenario_id"].map({"H2": "solid", "H3": "dashed"})
    )
    target_pre = target_pre.assign(
        line_style=target_pre["scenario_id"].map({"H2": "solid", "H3": "dashed"})
    )
    contrasts = aggregate.loc[aggregate["estimand"].eq("b_1_minus_b_2")].copy()
    contrasts["line_style"] = contrasts["scenario_id"].map(
        {"H0A": "dotted", "H1": "dashed", "H2": "solid", "H3": "solid"}
    )
    contrasts_leg = contrasts.loc[contrasts["election_type"].eq("legislative")]
    contrasts_pre = contrasts.loc[contrasts["election_type"].eq("presidential")]

    top_gaps = comparison.sort_values("absolute_krt_nls_gap", ascending=False).head(12).copy()
    top_gaps = top_gaps[[
        "election_id", "year", "scenario_id", "krt_contrast_mean", "krt_contrast_q025",
        "krt_contrast_q975", "nls_contrast", "absolute_krt_nls_gap", "nls_inside_krt_interval",
        "mcmc_status", "identification_status",
    ]]
    max_gap = float(comparison["absolute_krt_nls_gap"].max())
    inside_share = float(comparison["nls_inside_krt_interval"].mean())
    status_h23 = diagnostic_counts.loc[diagnostic_counts["scenario_id"].isin(["H2", "H3"])]
    h23_pass = int(status_h23["pass"].sum())
    h23_caveat = int(status_h23["caveat"].sum())
    h23_fail = int(status_h23["fail"].sum())

    sources = [
        _source(
            "krt_aggregate",
            "Agregats KRT canoniques",
            "01_resultats_python/longitudinal_krt_aggregate.parquet",
            "Agregats ponderes des tirages posterieurs des runs canoniques H0A-H3.",
            [
                "beta1: probabilite estimee pour le groupe cible du scenario.",
                "beta2: probabilite estimee pour le groupe complementaire du scenario.",
                "contraste: beta1 - beta2; intervalle a 95 % issu des tirages KRT.",
            ],
            panel_size=scope.panel_size,
            sql=(
                "SELECT * FROM read_parquet('01_resultats_python/longitudinal_krt_aggregate.parquet') "
                f"WHERE scenario_id IN ({scenario_sql})"
            ),
        ),
        _source(
            "krt_commune",
            "Resumes communaux KRT canoniques",
            "01_resultats_python/longitudinal_krt_commune.parquet",
            "Resumes communaux des deux beta et huit champs d'incertitude par scrutin et scenario.",
            ["Grain: unit_id x election_id x scenario_id.", "Poids beta1 et beta2 fondes sur les tailles de groupes."],
            panel_size=scope.panel_size,
            sql=(
                "SELECT * FROM read_parquet('01_resultats_python/longitudinal_krt_commune.parquet') "
                f"WHERE scenario_id IN ({scenario_sql})"
            ),
        ),
        _source(
            "nls_results",
            "Estimations NLS longitudinales",
            "01_resultats_python/longitudinal_nls.parquet",
            "Estimations NLS ponctuelles canoniques; aucun pseudo-intervalle posterieur.",
            [
                f"{scope.expected_nls_pairs} couples election-scenario publics, dont "
                f"{scope.expected_elections * 2} couples H2/H3 deja existants."
            ],
            panel_size=scope.panel_size,
            sql="SELECT * FROM read_parquet('01_resultats_python/longitudinal_nls.parquet')",
        ),
        {
            "id": "diagnostics_summary",
            "label": "Diagnostics KRT par election",
            "path": "02_syntheses/diagnostics_krt_par_election.csv",
            "query": {
                "engine": "local_csv",
                "language": "sql",
                "description": (
                    "Diagnostics MCMC canoniques et statut d'identification ecologique separes. "
                    "Requete SQL equivalente a la lecture Python materialisee dans le snapshot."
                ),
                "sql": "SELECT * FROM read_csv_auto('02_syntheses/diagnostics_krt_par_election.csv')",
                "tables_used": ["02_syntheses/diagnostics_krt_par_election.csv"],
                "filters": ["Un run canonique par election_id x scenario_id"],
                "metric_definitions": [
                    "mcmc_status derive de R-hat, ESS, BFMI, divergences et saturation de profondeur.",
                    "identification_status mesure l'information ecologique et ne declenche pas de relance MCMC.",
                ],
            },
        },
        {
            "id": "krt_nls_comparison",
            "label": "Comparaison KRT-NLS H0A-H3",
            "path": "02_syntheses/krt_nls_comparison_h0a_h1_h2_h3.csv",
            "query": {
                "engine": "local_csv",
                "language": "sql",
                "description": (
                    "Jointure un-a-un des contrastes KRT et NLS par election et scenario. "
                    "Requete SQL equivalente a la table Python deja materialisee."
                ),
                "sql": "SELECT * FROM read_csv_auto('02_syntheses/krt_nls_comparison_h0a_h1_h2_h3.csv')",
                "tables_used": [
                    "01_resultats_python/longitudinal_krt_aggregate.parquet",
                    "01_resultats_python/longitudinal_nls.parquet",
                ],
                "filters": ["Estimand KRT b_1_minus_b_2", "NLS sur la categorie de vote cible"],
                "metric_definitions": ["Ecart absolu = |contraste NLS - moyenne du contraste KRT|."],
            },
        },
    ]

    cards = [
        {"id": "card_krt_pairs", "dataset": "headline", "sourceId": "krt_aggregate", "description": "Un run canonique par scrutin et scenario.", "metrics": [{"label": "Couples KRT", "field": "krt_pairs", "format": "number"}]},
        {"id": "card_communes", "dataset": "headline", "sourceId": "krt_commune", "description": "Memes unit_id dans tous les runs.", "metrics": [{"label": "Communes fixes", "field": "panel_size", "format": "number"}]},
        {"id": "card_commune_rows", "dataset": "headline", "sourceId": "krt_commune", "description": "Grain commune x scrutin x scenario.", "metrics": [{"label": "Lignes communales KRT", "field": "commune_rows", "format": "compact"}]},
        {"id": "card_nls_pairs", "dataset": "headline", "sourceId": "nls_results", "description": "Perimetre NLS public inchange.", "metrics": [{"label": "Couples NLS", "field": "nls_pairs", "format": "number"}]},
    ]
    charts = [
        {
            "id": "h23_target_leg",
            "title": "Vote de gauche estime des ouvriers et employes - legislatives",
            "subtitle": "Beta1 de H2 et H3, modeles separes; panel fixe de 2 000 communes",
            "intent": "trend",
            "question": "Comment evoluent les probabilites cibles H2 et H3 dans les legislatives ?",
            "rationale": "Une trajectoire a deux series montre les profils temporels sans construire de difference posterieure jointe.",
            "comparisonContext": {"grain": "scrutin legislatif", "unit": "probabilite", "denominator": "exprimes"},
            "type": "line",
            "dataset": "h23_target_leg",
            "sourceId": "krt_aggregate",
            "xAxisTitle": "Annee du scrutin",
            "yAxisTitle": "Probabilite estimee",
            "encodings": {
                "x": {"field": "year", "type": "quantitative", "label": "Annee du scrutin"},
                "y": {"field": "mean", "type": "quantitative", "label": "Probabilite estimee"},
                "color": {"field": "scenario_id", "type": "nominal", "label": "Hypothese"},
                "lineStyle": {"field": "line_style", "type": "nominal", "label": "Trace"},
                "tooltip": [
                    {"field": "scenario_id", "type": "nominal", "label": "Hypothese"},
                    {"field": "mean", "type": "quantitative", "label": "Moyenne", "format": "percent"},
                    {"field": "q025", "type": "quantitative", "label": "Q2,5 %", "format": "percent"},
                    {"field": "q975", "type": "quantitative", "label": "Q97,5 %", "format": "percent"},
                ],
            },
            "valueFormat": "percent",
            "layout": "full",
            "surface": {"viewMode": "both", "showControls": True},
        },
        {
            "id": "h23_target_pre",
            "title": "Vote de gauche estime des ouvriers et employes - presidentielles",
            "subtitle": "Beta1 de H2 et H3, modeles separes; panel fixe de 2 000 communes",
            "intent": "trend",
            "question": "Comment evoluent les probabilites cibles H2 et H3 dans les presidentielles ?",
            "rationale": "Une trajectoire separee evite de relier des familles de scrutin heterogenes.",
            "comparisonContext": {"grain": "scrutin presidentiel", "unit": "probabilite", "denominator": "exprimes"},
            "type": "line",
            "dataset": "h23_target_pre",
            "sourceId": "krt_aggregate",
            "xAxisTitle": "Annee du scrutin",
            "yAxisTitle": "Probabilite estimee",
            "encodings": {
                "x": {"field": "year", "type": "quantitative", "label": "Annee du scrutin"},
                "y": {"field": "mean", "type": "quantitative", "label": "Probabilite estimee"},
                "color": {"field": "scenario_id", "type": "nominal", "label": "Hypothese"},
                "lineStyle": {"field": "line_style", "type": "nominal", "label": "Trace"},
                "tooltip": [
                    {"field": "scenario_id", "type": "nominal", "label": "Hypothese"},
                    {"field": "mean", "type": "quantitative", "label": "Moyenne", "format": "percent"},
                    {"field": "q025", "type": "quantitative", "label": "Q2,5 %", "format": "percent"},
                    {"field": "q975", "type": "quantitative", "label": "Q97,5 %", "format": "percent"},
                ],
            },
            "valueFormat": "percent",
            "layout": "full",
            "surface": {"viewMode": "both", "showControls": True},
        },
        {
            "id": "contrasts_leg",
            "title": "Contrastes KRT H0A-H3 - legislatives",
            "subtitle": "Moyennes posterieures beta1-beta2; les intervalles exacts restent dans la table source",
            "intent": "trend",
            "question": "Comment evoluent les quatre contrastes dans les legislatives ?",
            "rationale": "Quatre trajectoires sur une meme famille de scrutin rendent les directions comparables sans fusionner les estimands.",
            "comparisonContext": {"grain": "scrutin legislatif", "unit": "difference de probabilites"},
            "type": "line",
            "dataset": "contrasts_leg",
            "sourceId": "krt_aggregate",
            "xAxisTitle": "Annee du scrutin",
            "yAxisTitle": "Beta1 - beta2",
            "encodings": {
                "x": {"field": "year", "type": "quantitative", "label": "Annee du scrutin"},
                "y": {"field": "mean", "type": "quantitative", "label": "Beta1 - beta2"},
                "color": {"field": "scenario_id", "type": "nominal", "label": "Hypothese"},
                "lineStyle": {"field": "line_style", "type": "nominal", "label": "Trace"},
                "tooltip": [
                    {"field": "scenario_id", "type": "nominal", "label": "Hypothese"},
                    {"field": "mean", "type": "quantitative", "label": "Moyenne"},
                    {"field": "q025", "type": "quantitative", "label": "Q2,5 %"},
                    {"field": "q975", "type": "quantitative", "label": "Q97,5 %"},
                ],
            },
            "valueFormat": "number",
            "unit": "prob.",
            "referenceLines": [{"axis": "y", "value": 0, "label": "Aucun ecart", "color": "neutral", "lineStyle": "dashed"}],
            "layout": "full",
            "surface": {"viewMode": "both", "showControls": True},
        },
        {
            "id": "contrasts_pre",
            "title": "Contrastes KRT H0A-H3 - presidentielles",
            "subtitle": "Moyennes posterieures beta1-beta2; famille de scrutin tracee separement",
            "intent": "trend",
            "question": "Comment evoluent les quatre contrastes dans les presidentielles ?",
            "rationale": "La separation des presidentielles preserve une base de comparaison electorale homogene.",
            "comparisonContext": {"grain": "scrutin presidentiel", "unit": "difference de probabilites"},
            "type": "line",
            "dataset": "contrasts_pre",
            "sourceId": "krt_aggregate",
            "xAxisTitle": "Annee du scrutin",
            "yAxisTitle": "Beta1 - beta2",
            "encodings": {
                "x": {"field": "year", "type": "quantitative", "label": "Annee du scrutin"},
                "y": {"field": "mean", "type": "quantitative", "label": "Beta1 - beta2"},
                "color": {"field": "scenario_id", "type": "nominal", "label": "Hypothese"},
                "lineStyle": {"field": "line_style", "type": "nominal", "label": "Trace"},
                "tooltip": [
                    {"field": "scenario_id", "type": "nominal", "label": "Hypothese"},
                    {"field": "mean", "type": "quantitative", "label": "Moyenne"},
                    {"field": "q025", "type": "quantitative", "label": "Q2,5 %"},
                    {"field": "q975", "type": "quantitative", "label": "Q97,5 %"},
                ],
            },
            "valueFormat": "number",
            "unit": "prob.",
            "referenceLines": [{"axis": "y", "value": 0, "label": "Aucun ecart", "color": "neutral", "lineStyle": "dashed"}],
            "layout": "full",
            "surface": {"viewMode": "both", "showControls": True},
        },
        {
            "id": "mcmc_status",
            "title": "Diagnostics MCMC canoniques par hypothese",
            "subtitle": f"{scope.expected_elections} scrutins par hypothese; identification ecologique exclue de ce comptage",
            "intent": "composition",
            "question": "Comment se repartissent les statuts pass, caveat et fail ?",
            "rationale": f"Une barre empilee conserve le total fixe de {scope.expected_elections} runs et rend la composition des diagnostics comparable.",
            "comparisonContext": {"grain": "run canonique", "unit": "nombre de runs", "denominator": f"{scope.expected_elections} scrutins par hypothese"},
            "type": "stackedBar",
            "dataset": "diagnostic_counts",
            "sourceId": "diagnostics_summary",
            "xAxisTitle": "Hypothese",
            "yAxisTitle": "Nombre de runs",
            "encodings": {
                "x": {"field": "scenario_id", "type": "nominal", "label": "Hypothese"},
                "y": {"fields": ["pass", "caveat", "fail"], "type": "quantitative", "label": "Nombre de runs"},
            },
            "valueFormat": "number",
            "layout": "full",
            "surface": {"viewMode": "both", "showControls": True},
        },
        {
            "id": "krt_nls_scatter",
            "title": f"Contrastes KRT et NLS sur les {scope.expected_krt_pairs} couples du perimetre",
            "subtitle": "Un point par election et scenario; l'ecart est un diagnostic de methode, pas une validation croisee formelle",
            "intent": "relationship",
            "question": "Les contrastes KRT et NLS restent-ils proches sur le perimetre complet ?",
            "rationale": f"Un nuage de {scope.expected_krt_pairs} points revele la concordance globale et les observations eloignees sans inventer d'incertitude NLS.",
            "comparisonContext": {"grain": "election x scenario", "unit": "difference de probabilites"},
            "type": "scatter",
            "dataset": "krt_nls",
            "sourceId": "krt_nls_comparison",
            "xAxisTitle": "Contraste NLS",
            "yAxisTitle": "Contraste KRT moyen",
            "encodings": {
                "x": {"field": "nls_contrast", "type": "quantitative", "label": "Contraste NLS"},
                "y": {"field": "krt_contrast_mean", "type": "quantitative", "label": "Contraste KRT"},
                "color": {"field": "scenario_id", "type": "nominal", "label": "Hypothese"},
                "tooltip": [
                    {"field": "election_id", "type": "text", "label": "Scrutin"},
                    {"field": "scenario_id", "type": "nominal", "label": "Hypothese"},
                    {"field": "absolute_krt_nls_gap", "type": "quantitative", "label": "Ecart absolu"},
                ],
            },
            "valueFormat": "number",
            "layout": "full",
            "surface": {"viewMode": "both", "showControls": True},
        },
    ]
    tables = [
        {
            "id": "definitions",
            "title": f"Definitions des {len(scope.krt_scenarios)} hypotheses",
            "subtitle": "Groupes, categories de vote et complements utilises dans les modeles 2x2 non ajustes",
            "dataset": "definitions",
            "sourceId": "krt_aggregate",
            "defaultSort": {"field": "scenario_id", "direction": "asc"},
            "density": "spacious",
            "layout": "full",
            "columns": [
                {"field": "scenario_id", "label": "Hypothese", "type": "text"},
                {"field": "social_groups", "label": "Groupes sociaux", "type": "text"},
                {"field": "vote_categories", "label": "Categories de vote", "type": "text"},
                {"field": "denominator", "label": "Denominateur", "type": "text"},
            ],
        },
        {
            "id": "largest_gaps",
            "title": "Plus grands ecarts ponctuels KRT-NLS",
            "subtitle": "Douze couples classes par ecart absolu; les intervalles sont uniquement ceux du KRT",
            "dataset": "largest_gaps",
            "sourceId": "krt_nls_comparison",
            "defaultSort": {"field": "absolute_krt_nls_gap", "direction": "desc"},
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "election_id", "label": "Scrutin", "type": "text"},
                {"field": "scenario_id", "label": "H", "type": "text"},
                {"field": "krt_contrast_mean", "label": "KRT", "format": "number"},
                {"field": "nls_contrast", "label": "NLS", "format": "number"},
                {"field": "absolute_krt_nls_gap", "label": "Ecart absolu", "format": "number"},
                {"field": "nls_inside_krt_interval", "label": "NLS dans IC KRT", "type": "text"},
            ],
        },
        {
            "id": "identification_counts",
            "title": "Identification ecologique par hypothese",
            "subtitle": "Comptage distinct des diagnostics MCMC; une caveat d'identification ne justifie pas une chaine plus longue",
            "dataset": "identification_counts",
            "sourceId": "diagnostics_summary",
            "defaultSort": {"field": "scenario_id", "direction": "asc"},
            "density": "spacious",
            "layout": "full",
            "columns": [
                {"field": "scenario_id", "label": "Hypothese", "type": "text"},
                {"field": "identification_status", "label": "Statut d'identification", "type": "text"},
                {"field": "n_runs", "label": "Runs", "format": "number"},
            ],
        },
    ]

    blocks = [
        {"id": "title", "type": "markdown", "body": "# Estimations ecologiques longitudinales H0A-H3"},
        {
            "id": "technical_summary",
            "type": "markdown",
            "sourceId": "krt_aggregate",
            "body": (
                "## La v1.1 etend la chaine validee a H2 et H3\n\n"
                f"La release contient **{scope.expected_krt_pairs} couples KRT canoniques**, "
                f"**{scope.expected_krt_commune_rows:,} lignes communales** et conserve **{scope.expected_nls_pairs} couples NLS**. "
                f"Les {h23_pairs} nouveaux KRT H2/H3 comptent **{h23_pass} pass**, **{h23_caveat} caveat** et **{h23_fail} fail**. "
                f"Les H0A/H1 sont numériquement identiques à la v1.0.2. `ready=true` couvre uniquement {scope.ready_scope}."
            ),
        },
        {"id": "headline_metrics", "type": "metric-strip", "cardIds": [card["id"] for card in cards], "layout": "full"},
        {
            "id": "scope_definitions_text",
            "type": "markdown",
            "body": (
                "## Les estimands doivent etre lus avant les trajectoires\n\n"
                "H2 estime le vote de gauche des **ouvriers** face à tous les non-ouvriers; H3 estime celui des **employés** face à tous les non-employés. "
                "Leurs compléments diffèrent. H2/H3 ne décomposent donc pas formellement H1 et ne produisent pas un posterior joint ouvriers–employés."
            ),
        },
        {"id": "definitions_table", "type": "table", "tableId": "definitions", "layout": "full"},
        {
            "id": "h23_target_text",
            "type": "markdown",
            "sourceId": "krt_aggregate",
            "body": (
                "## H2 et H3 ajoutent deux trajectoires cibles distinctes\n\n"
                "Les deux graphiques montrent les β1 agrégés de H2 et H3. Ils permettent une comparaison visuelle descriptive de "
                "`P(gauche | ouvriers)` et `P(gauche | employés)`, mais aucune bande de leur différence n'est construite à partir de postérieurs indépendants."
            ),
        },
        {"id": "h23_leg_chart", "type": "chart", "chartId": "h23_target_leg", "layout": "full"},
        {"id": "h23_pre_chart", "type": "chart", "chartId": "h23_target_pre", "layout": "full"},
        {
            "id": "contrast_text",
            "type": "markdown",
            "sourceId": "krt_aggregate",
            "body": (
                "## Les contrastes restent spécifiques à chaque hypothèse\n\n"
                "Les trajectoires ci-dessous séparent législatives et présidentielles. Chaque point est la moyenne postérieure de β1−β2; "
                "les quantiles exacts à 2,5 % et 97,5 % figurent dans le Parquet agrégé et les figures statiques de la livraison."
            ),
        },
        {"id": "contrast_leg_chart", "type": "chart", "chartId": "contrasts_leg", "layout": "full"},
        {"id": "contrast_pre_chart", "type": "chart", "chartId": "contrasts_pre", "layout": "full"},
        {
            "id": "method_text",
            "type": "markdown",
            "body": (
                "## Méthode et périmètre de calcul\n\n"
                f"Les KRT utilisent le modèle beta-binomial de King via PyEI/PyMC avec le backend NUTS `{scope.mcmc.sampler_backend}`, "
                "retenu après benchmark diagnostique du graphe exact à 2 000 communes, quatre chaînes, 1 000 chauffe, 1 000 tirages, "
                "`target_accept=0.99`, `max_treedepth=14` et `king_lambda=0.5`. Les graines sont dérivées de façon stable par scrutin et hypothèse. "
                "Les runs `caveat_severe` ou `fail` reçoivent au plus une relance 2 000/2 000 selon la règle préenregistrée."
            ),
        },
        {
            "id": "diagnostic_text",
            "type": "markdown",
            "sourceId": "diagnostics_summary",
            "body": (
                "## Convergence MCMC et identification restent deux diagnostics différents\n\n"
                "R-hat, ESS, BFMI, divergences et profondeur concernent l'échantillonnage MCMC. Les bornes écologiques et la variation du plan "
                "concernent l'identification. Une chaîne plus longue peut améliorer le premier ensemble, jamais garantir le second."
            ),
        },
        {"id": "mcmc_chart", "type": "chart", "chartId": "mcmc_status", "layout": "full"},
        {"id": "identification_table", "type": "table", "tableId": "identification_counts", "layout": "full"},
        {
            "id": "krt_nls_text",
            "type": "markdown",
            "sourceId": "krt_nls_comparison",
            "body": (
                "## La comparaison KRT-NLS reste un diagnostic de sensibilité à la méthode\n\n"
                f"L'écart ponctuel maximal est **{max_gap:.3f}** et **{inside_share:.1%}** des points NLS se situent dans l'intervalle KRT correspondant. "
                "Le NLS est présenté sans pseudo-intervalle postérieur. Un écart important impose un audit des entrées et de l'identification, pas un réglage opportuniste des priors."
            ),
        },
        {"id": "krt_nls_chart", "type": "chart", "chartId": "krt_nls_scatter", "layout": "full"},
        {"id": "largest_gaps_table", "type": "table", "tableId": "largest_gaps", "layout": "full"},
        {
            "id": "limitations",
            "type": "markdown",
            "body": (
                "## Limites et robustesse\n\n"
                "- Les modèles H0A-H3 sont non ajustés; revenu, capital, VBBM, région et département sont des caractéristiques jointes, pas des régresseurs.\n"
                "- Les changements entre dates sont descriptifs; aucun modèle temporel hiérarchique n'est estimé.\n"
                "- Les comparaisons H2/H3 ne sont pas des différences postérieures jointes.\n"
                "- La reproduction complète nécessite le dépôt parent et les archives brutes; les NetCDF ne sont pas livrés."
            ),
        },
        {
            "id": "next_steps",
            "type": "markdown",
            "body": (
                "## La suite doit revenir à l'extension scientifique\n\n"
                "1. H6/H7 sur le vote FN-RN.\n"
                "2. H0B/H0C avec abstention séparée.\n"
                "3. H4/H5.\n"
                "4. RxC 3×2 `{ouvriers, employés, autres} × {gauche, non-gauche}` pour une comparaison jointe plus propre."
            ),
        },
        {
            "id": "further_questions",
            "type": "markdown",
            "body": (
                "## Questions encore ouvertes\n\n"
                "Quels scrutins combinent caveat MCMC et identification faible ? Les écarts KRT-NLS les plus élevés viennent-ils du plan écologique ou d'une sensibilité substantielle ? "
                "Le futur RxC 3×2 confirme-t-il l'ordre descriptif observé entre les deux β1 séparés ?"
            ),
        },
    ]

    artifact = {
        "surface": "report",
        "manifest": {
            "version": 1,
            "surface": "report",
            "title": "Estimations ecologiques longitudinales H0A-H3",
            "description": f"Rapport technique de la release longitudinale v1.1 sur un panel fixe de {scope.panel_size:,} communes.",
            "generatedAt": generated_at,
            "cards": cards,
            "charts": charts,
            "tables": tables,
            "sources": sources,
            "blocks": blocks,
        },
        "snapshot": {
            "version": 1,
            "generatedAt": generated_at,
            "status": "ready",
            "datasets": {
                "headline": [{
                    "krt_pairs": scope.expected_krt_pairs,
                    "panel_size": scope.panel_size,
                    "commune_rows": len(commune),
                    "nls_pairs": len(nls[["election_id", "scenario_id"]].drop_duplicates()),
                }],
                "h23_target_leg": _records(target_leg),
                "h23_target_pre": _records(target_pre),
                "contrasts_leg": _records(contrasts_leg),
                "contrasts_pre": _records(contrasts_pre),
                "diagnostic_counts": _records(diagnostic_counts[["scenario_id", "pass", "caveat", "fail"]]),
                "identification_counts": _records(identification_counts),
                "krt_nls": _records(comparison[[
                    "election_id", "year", "scenario_id", "election_type", "krt_contrast_mean",
                    "krt_contrast_q025", "krt_contrast_q975", "nls_contrast",
                    "absolute_krt_nls_gap", "nls_inside_krt_interval", "mcmc_status", "identification_status",
                ]]),
                "largest_gaps": _records(top_gaps),
                "definitions": _records(definitions),
            },
        },
        "sources": sources,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(output_path, artifact)
    notes = release_root / "05_methodologie_et_code" / "REPORT_SOURCE_NOTES.md"
    notes.parent.mkdir(parents=True, exist_ok=True)
    notes.write_text(
        "# Notes de construction du rapport v1.1\n\n"
        "Audience: technique. Surface primaire: HTML autonome construit depuis `artifact.json`; le PDF est une conversion de cette surface.\n\n"
        "Structure couverte: synthese technique; constats avec visuels; definitions; methode; limites et robustesses; suite; questions ouvertes.\n\n"
        "Les graphiques H2/H3 sont descriptifs et n'impliquent aucune difference posterieure jointe. Les diagnostics MCMC et d'identification sont separes.\n",
        encoding="utf-8",
    )
    return {
        "artifact_path": output_path.resolve().relative_to(ROOT).as_posix()
        if output_path.resolve().is_relative_to(ROOT)
        else str(output_path.resolve()),
        "blocks": len(blocks),
        "charts": len(charts),
        "tables": len(tables),
        "datasets": len(artifact["snapshot"]["datasets"]),
        "sources": len(sources),
        "status": "ready",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the canonical portable-report artifact for v1.1.")
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_report_artifact(args.release_root, args.config, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
