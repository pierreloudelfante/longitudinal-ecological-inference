from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .build_longitudinal_panel import PANEL_PATH
from .paths import ROOT, RUNS_DIR
from .utils import file_sha256, write_json


EXPECTED_PANEL_SHA256 = "bde70c71660fce29610d7931461d8db6181dba874514a1866b63cf16a81cec4a"
EXPECTED_KRT_PAIRS = 240
EXPECTED_NLS_PAIRS = 292
SCENARIO_ORDER = ("H0A", "H1", "H2", "H3", "H0B", "H0C", "H4", "H5", "H6", "H7")
SCENARIO_LABELS = {
    "H0A": "ouvriers-employés × abstention",
    "H1": "ouvriers-employés × gauche",
    "H2": "ouvriers × gauche",
    "H3": "employés × gauche",
    "H0B": "ouvriers-employés × vote exprimé",
    "H0C": "ouvriers-employés × abstention séparée",
    "H4": "ouvriers-employés × droite",
    "H5": "ouvriers-employés × centre",
    "H6": "ouvriers-employés × FN-RN",
    "H7": "groupe alternatif × FN-RN",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _copy(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return json.loads(frame.replace({np.nan: None}).to_json(orient="records", force_ascii=False))


def _table_description(table: str, column: str) -> str:
    exact = {
        "panel_id": "Identifiant du panel longitudinal fixe.",
        "election_id": "Identifiant stable du scrutin.",
        "scenario_id": "Identifiant de l'hypothèse et du tableau 2×2/RxC.",
        "unit_id": "Code communal harmonisé utilisé comme clé de jointure.",
        "run_id": "Identifiant unique du run source.",
        "estimand": "Paramètre agrégé : b_1, b_2 ou b_1_minus_b_2.",
        "mean": "Moyenne postérieure KRT de l'estimand.",
        "median": "Médiane postérieure KRT de l'estimand.",
        "q025": "Quantile postérieur 2,5 %.",
        "q975": "Quantile postérieur 97,5 %.",
        "estimate": "Estimation ponctuelle NLS ; aucun pseudo-intervalle postérieur.",
        "mcmc_status": "Diagnostic de convergence MCMC, séparé de l'identification.",
        "identification_status": "Diagnostic d'identification écologique, séparé de la MCMC.",
        "selection_status": "Statut provisoire de sélection dans cet instantané partiel.",
        "foreign_share": "Part d'étrangers normalisée dans [0,1], caractéristique jointe.",
        "revenue_ratio": "Ratio de revenu documenté, caractéristique jointe au résultat.",
        "capital_ratio": "Ratio de capital documenté, caractéristique jointe au résultat.",
    }
    if column in exact:
        return exact[column]
    if column.startswith(("b1_", "b2_")):
        return "Résumé communal ou poids du paramètre écologique correspondant."
    if column.endswith("_reference_year"):
        return "Année de référence documentée de la variable jointe."
    if column.endswith("_status"):
        return "Statut de provenance ou de diagnostic documenté."
    if column.endswith("_source_column"):
        return "Nom de la colonne source effectivement utilisée."
    return f"Champ technique de la table {table}; voir DATA_DICTIONARY.csv."


def _write_dictionary(tables: dict[str, pd.DataFrame], path: Path) -> None:
    rows: list[dict[str, str]] = []
    for table, frame in tables.items():
        for column, dtype in frame.dtypes.items():
            rows.append({
                "table": table,
                "column": str(column),
                "dtype": str(dtype),
                "description": _table_description(table, str(column)),
            })
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def _coverage_figure(coverage: pd.DataFrame, path: Path) -> None:
    frame = coverage.loc[coverage["scenario_id"].isin(SCENARIO_ORDER)].copy()
    frame["scenario_id"] = pd.Categorical(frame["scenario_id"], SCENARIO_ORDER, ordered=True)
    frame = frame.sort_values("scenario_id")
    x = np.arange(len(frame))
    fig, ax = plt.subplots(figsize=(11, 5.8))
    ax.bar(x, frame["krt_expected_pairs"], color="#D9E2EC", label="attendus")
    ax.bar(x, frame["krt_successful_pairs"], color="#2563EB", label="terminés")
    ax.set_xticks(x, frame["scenario_id"].astype(str))
    ax.set_ylabel("Couples élection × hypothèse")
    ax.set_title("Couverture KRT de l'instantané partiel")
    ax.legend(frameon=False, ncol=2)
    ax.grid(axis="y", alpha=.2)
    for index, value in enumerate(frame["krt_successful_pairs"].astype(int)):
        ax.text(index, value + .35, str(value), ha="center", va="bottom", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def _diagnostic_figure(selection: pd.DataFrame, path: Path) -> None:
    counts = (
        selection.groupby(["scenario_id", "mcmc_status"]).size().unstack(fill_value=0)
        .reindex(SCENARIO_ORDER, fill_value=0)
    )
    for status in ("pass", "caveat", "fail"):
        if status not in counts:
            counts[status] = 0
    fig, ax = plt.subplots(figsize=(11, 5.8))
    bottom = np.zeros(len(counts))
    colors = {"pass": "#059669", "caveat": "#D97706", "fail": "#DC2626"}
    for status in ("pass", "caveat", "fail"):
        values = counts[status].to_numpy()
        ax.bar(counts.index, values, bottom=bottom, label=status, color=colors[status])
        bottom += values
    ax.set_ylabel("Runs terminés")
    ax.set_title("Diagnostic MCMC des runs retenus dans l'instantané")
    ax.legend(frameon=False, ncol=3)
    ax.grid(axis="y", alpha=.2)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def _trajectory_figure(aggregate: pd.DataFrame, path: Path) -> None:
    contrast = aggregate.loc[aggregate["estimand"].eq("b_1_minus_b_2")].copy()
    contrast["family"] = np.where(contrast["election_id"].astype(str).str.startswith("leg_"), "Législatives", "Présidentielles")
    scenarios = [value for value in SCENARIO_ORDER if value in set(contrast["scenario_id"])]
    fig, axes = plt.subplots(5, 2, figsize=(14, 18), sharey=True)
    palette = {"Législatives": "#2563EB", "Présidentielles": "#DB2777"}
    for ax, scenario in zip(axes.ravel(), SCENARIO_ORDER):
        subset = contrast.loc[contrast["scenario_id"].eq(scenario)]
        if subset.empty:
            ax.text(.5, .5, "aucun run terminé", ha="center", va="center", transform=ax.transAxes)
        for family, values in subset.groupby("family"):
            values = values.sort_values("year")
            ax.errorbar(
                values["year"], values["mean"],
                yerr=[values["mean"] - values["q025"], values["q975"] - values["mean"]],
                color=palette[family], marker="o", linewidth=1.3, capsize=2, label=family,
            )
        ax.axhline(0, color="#64748B", linewidth=.8, linestyle="--")
        ax.set_title(f"{scenario} — {SCENARIO_LABELS.get(scenario, scenario)}", fontsize=10)
        ax.grid(alpha=.15)
    handles, labels = axes.ravel()[0].get_legend_handles_labels()
    if not handles:
        for ax in axes.ravel():
            handles, labels = ax.get_legend_handles_labels()
            if handles:
                break
    fig.suptitle(
        "Contrastes KRT disponibles — instantané partiel, familles de scrutin séparées",
        y=.997,
    )
    fig.legend(
        handles, labels, loc="upper center", bbox_to_anchor=(.5, .983),
        ncol=2, frameon=False,
    )
    fig.tight_layout(rect=(0, 0, 1, .955))
    fig.savefig(path, dpi=170)
    plt.close(fig)


def _img_data(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _write_html_report(
    stage: Path,
    coverage: pd.DataFrame,
    selection: pd.DataFrame,
    commune: pd.DataFrame,
    aggregate: pd.DataFrame,
    nls: pd.DataFrame,
    snapshot: dict[str, Any],
) -> None:
    coverage_rows = coverage.loc[coverage["scenario_id"].isin(SCENARIO_ORDER), [
        "scenario_id", "krt_expected_pairs", "krt_successful_pairs", "krt_pass_pairs", "krt_caveat_pairs", "krt_fail_pairs"
    ]]
    body_rows = "".join(
        "<tr>" + "".join(f"<td>{escape(str(value))}</td>" for value in row) + "</tr>"
        for row in coverage_rows.itertuples(index=False, name=None)
    )
    figures = []
    for filename, title in (
        ("coverage_by_scenario.png", "Couverture par hypothèse"),
        ("mcmc_status_by_scenario.png", "Convergence MCMC"),
        ("current_contrast_trajectories.png", "Contrastes actuellement disponibles"),
    ):
        figures.append(
            f"<section><h2>{title}</h2><img alt='{escape(title)}' src='data:image/png;base64,{_img_data(stage / 'figures' / filename)}'></section>"
        )
    html = f"""<!doctype html><html lang='fr'><head><meta charset='utf-8'><title>Audit d'avancement longitudinal</title>
<style>body{{font:15px/1.5 system-ui;color:#172033;max-width:1120px;margin:36px auto;padding:0 24px}}h1{{font-size:32px}}h2{{margin-top:34px}}.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.kpi{{background:#f2f6fb;border-radius:10px;padding:16px}}.kpi b{{display:block;font-size:24px;color:#174ea6}}.warn{{background:#fff7ed;border-left:4px solid #d97706;padding:14px}}table{{border-collapse:collapse;width:100%}}th,td{{padding:7px;border-bottom:1px solid #d8dee9;text-align:right}}th:first-child,td:first-child{{text-align:left}}img{{width:100%;height:auto;border:1px solid #e2e8f0;border-radius:8px}}code{{background:#eef2f7;padding:2px 4px}}</style></head><body>
<h1>Audit d'avancement — estimations longitudinales</h1><p>Instantané figé le {escape(snapshot['created_at_utc'])}. Ce document est un rapport de progression, pas une release scientifique finale.</p>
<div class='warn'><b>Conclusion technique.</b> Les 292 couples NLS sont présents. {snapshot['krt_successful_pairs']} couples KRT sur {EXPECTED_KRT_PAIRS} sont terminés et consolidés; le calcul Python continue en arrière-plan. Les statuts MCMC, l'identification écologique et les alertes KRT–NLS sont trois diagnostics distincts.</div>
<div class='kpis'><div class='kpi'><b>{snapshot['krt_successful_pairs']}/{EXPECTED_KRT_PAIRS}</b>KRT terminés</div><div class='kpi'><b>{len(commune):,}</b>lignes communales</div><div class='kpi'><b>{len(aggregate):,}</b>agrégats KRT</div><div class='kpi'><b>{snapshot['nls_pairs']}/{EXPECTED_NLS_PAIRS}</b>NLS terminés</div></div>
<h2>Périmètre et qualité</h2><p>Chaque run KRT retenu porte exactement 2 000 communes et trois estimands agrégés. Le panel a le SHA-256 attendu <code>{EXPECTED_PANEL_SHA256}</code>. Les huit champs d'incertitude communale b1/b2 sont présents.</p>
<table><thead><tr><th>Hypothèse</th><th>Attendus</th><th>Terminés</th><th>Pass</th><th>Caveat</th><th>Fail</th></tr></thead><tbody>{body_rows}</tbody></table>
{''.join(figures)}
<h2>Méthodologie</h2><p>KRT Python : modèle bêta-binomiale King99 non ajusté, paramétrisation <code>king99_beta_binomial_independent_beta_random_effects_v1</code>, quatre chaînes, 1 000 warmup, 1 000 tirages, target_accept 0,99, profondeur 14 et king_lambda 0,5. Les runs fragiles font l'objet d'une relance préenregistrée plus longue. NLS : estimations ponctuelles, sans pseudo-intervalles postérieurs.</p>
<h2>Limites et robustesse</h2><p>Les lignes marquées <code>fail</code> dans cet instantané peuvent résulter d'un ESS ou d'un BFMI sous seuil malgré zéro divergence; elles ne sont pas supprimées et restent provisoires jusqu'à la relance ciblée. Une alerte d'écart KRT–NLS est une sensibilité de méthode et ne doit pas être appelée échec MCMC. Les hypothèses partielles ne doivent pas encore être interprétées comme des trajectoires complètes.</p>
<h2>Étapes suivantes</h2><ol><li>Terminer les {EXPECTED_KRT_PAIRS - snapshot['krt_successful_pairs']} fits initiaux restants.</li><li>Exécuter une seule relance renforcée pour les caveats sévères/fails.</li><li>Lancer la réplication R exacte NIMBLE sur le même plan.</li><li>Comparer Python/R et sélectionner les runs canoniques avant la release professeur.</li></ol>
<h2>Questions ouvertes</h2><p>Quels fails disparaissent après allongement des chaînes ? Les écarts KRT–NLS persistants sont-ils associés à une identification écologique faible ? La réplication R confirme-t-elle les mêmes contrastes agrégés ?</p>
</body></html>"""
    report_dir = stage / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "PROGRESS_REPORT.html").write_text(html, encoding="utf-8")


def _write_artifact(stage: Path, coverage: pd.DataFrame, snapshot: dict[str, Any]) -> None:
    view = coverage.loc[coverage["scenario_id"].isin(SCENARIO_ORDER)].copy()
    view["krt_remaining_pairs"] = (
        view["krt_expected_pairs"].astype(int) - view["krt_successful_pairs"].astype(int)
    )
    sources = [
        {"id": "coverage", "label": "Couverture courante", "path": "diagnostics/current_estimation_coverage.csv", "query": {"engine": "local_csv", "language": "sql", "sql": "SELECT * FROM read_csv('diagnostics/current_estimation_coverage.csv') WHERE model_family = '2x2'"}},
        {"id": "krt_aggregate", "label": "Agrégats KRT partiels", "path": "tables/longitudinal_krt_aggregate_partial.parquet", "query": {"engine": "local_parquet", "language": "sql", "sql": "SELECT * FROM read_parquet('tables/longitudinal_krt_aggregate_partial.parquet')"}},
        {"id": "krt_commune", "label": "Résumés communaux KRT partiels", "path": "tables/longitudinal_krt_commune_partial.parquet", "query": {"engine": "local_parquet", "language": "sql", "sql": "SELECT * FROM read_parquet('tables/longitudinal_krt_commune_partial.parquet')"}},
        {"id": "nls", "label": "Estimations NLS candidates", "path": "tables/longitudinal_nls_292_candidate.parquet", "query": {"engine": "local_parquet", "language": "sql", "sql": "SELECT * FROM read_parquet('tables/longitudinal_nls_292_candidate.parquet')"}},
    ]
    artifact = {
        "surface": "report",
        "manifest": {
            "version": 1,
            "surface": "report",
            "title": "Audit d'avancement longitudinal",
            "description": "Instantané partiel vérifié des estimations KRT et NLS.",
            "generatedAt": snapshot["created_at_utc"],
            "cards": [
                {"id": "krt", "dataset": "headline", "sourceId": "coverage", "description": "Couples KRT consolidés.", "metrics": [{"label": "KRT terminés", "field": "krt_successful_pairs", "format": "number"}]},
                {"id": "nls", "dataset": "headline", "sourceId": "nls", "description": "Couples NLS disponibles.", "metrics": [{"label": "NLS terminés", "field": "nls_pairs", "format": "number"}]},
            ],
            "charts": [{
                "id": "coverage_chart",
                "title": "Couverture KRT par hypothèse",
                "subtitle": "Runs terminés et restant à produire dans le plan de 240 couples",
                "intent": "composition",
                "question": "Quelle part de chaque hypothèse est déjà estimée ?",
                "rationale": "Une barre empilée conserve le dénominateur attendu propre à chaque hypothèse.",
                "comparisonContext": {"grain": "élection × hypothèse", "unit": "nombre de runs"},
                "type": "stackedBar",
                "dataset": "coverage",
                "sourceId": "coverage",
                "xAxisTitle": "Hypothèse",
                "yAxisTitle": "Nombre de runs",
                "encodings": {
                    "x": {"field": "scenario_id", "type": "nominal", "label": "Hypothèse"},
                    "y": {"fields": ["krt_successful_pairs", "krt_remaining_pairs"], "type": "quantitative", "label": "Runs"},
                },
                "valueFormat": "number",
                "layout": "full",
                "surface": {"viewMode": "both", "showControls": True},
            }],
            "tables": [{
                "id": "coverage_table", "title": "Couverture par hypothèse", "dataset": "coverage", "sourceId": "coverage", "layout": "full",
                "columns": [
                    {"field": "scenario_id", "label": "Hypothèse", "type": "text"},
                    {"field": "krt_expected_pairs", "label": "Attendus", "type": "number"},
                    {"field": "krt_successful_pairs", "label": "Terminés", "type": "number"},
                    {"field": "krt_pass_pairs", "label": "Pass", "type": "number"},
                    {"field": "krt_caveat_pairs", "label": "Caveat", "type": "number"},
                    {"field": "krt_fail_pairs", "label": "Fail", "type": "number"},
                ],
            }],
            "sources": sources,
            "blocks": [
                {"id": "summary", "type": "markdown", "body": f"# Audit d'avancement\n\n{snapshot['krt_successful_pairs']} couples KRT sur {EXPECTED_KRT_PAIRS}; {snapshot['nls_pairs']} couples NLS sur {EXPECTED_NLS_PAIRS}. Instantané partiel, non validé pour une release scientifique."},
                {"id": "coverage_chart_block", "type": "chart", "chartId": "coverage_chart", "layout": "full"},
                {"id": "limits", "type": "markdown", "body": "## Limites\n\nLes diagnostics MCMC, l'identification écologique et les alertes KRT–NLS sont séparés. Les runs fail restent audités et doivent suivre la règle de relance préenregistrée."},
                {"id": "next", "type": "markdown", "body": "## Suite\n\nTerminer Python KRT, exécuter les relances ciblées, lancer la réplication R exacte puis comparer les deux implémentations."},
            ],
        },
        "snapshot": {
            "version": 1,
            "generatedAt": snapshot["created_at_utc"],
            "status": "partial",
            "datasets": {
                "headline": [{"krt_successful_pairs": snapshot["krt_successful_pairs"], "nls_pairs": snapshot["nls_pairs"]}],
                "coverage": _records(view),
            },
        },
        "sources": sources,
    }
    write_json(stage / "report" / "artifact.json", artifact)


def _write_docs(stage: Path, snapshot: dict[str, Any], selection: pd.DataFrame) -> None:
    readme = f"""# Instantané d'audit des estimations longitudinales

Ce dossier fige l'avancement au {snapshot['created_at_utc']}. Il ne remplace pas une release validée.

- KRT Python consolidés : **{snapshot['krt_successful_pairs']}/{EXPECTED_KRT_PAIRS}** couples.
- NLS : **{snapshot['nls_pairs']}/{EXPECTED_NLS_PAIRS}** couples.
- Panel : **2 000 communes**, SHA-256 `{EXPECTED_PANEL_SHA256}`.
- Calcul actif au moment du snapshot : `{snapshot.get('active_run', 'non déterminé')}`.

Commencer par `report/PROGRESS_REPORT.html`, puis consulter les trois Parquet dans `tables/`. La sélection courante est provisoire : les runs MCMC fragiles seront relancés une fois avec les réglages renforcés avant sélection canonique finale.

Les trois diagnostics restent distincts : convergence MCMC, identification écologique et sensibilité KRT–NLS. Un écart KRT–NLS ne constitue pas à lui seul un échec MCMC.

Le ZIP technique séparé ajoute le code de production, les configurations, les tests et les diagnostics individuels, sans NetCDF.
"""
    (stage / "README.md").write_text(readme, encoding="utf-8")
    (stage / "PIPELINE_MAP.md").write_text(
        """# Carte de la pipeline

```text
sources électorales + référentiel géographique + variables sociales
                              │
                              ▼
                    audit et harmonisation
                              │
                              ▼
             panel longitudinal fixe de 2 000 communes
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
       matrices model_ready              registre 292 couples
              │                               │
       ┌──────┴──────┐                  NLS Python/R
       ▼             ▼
 KRT Python      KRT R exact NIMBLE
       │             │
       └──────┬──────┘
              ▼
 diagnostics MCMC │ identification │ sensibilité KRT–NLS
              │
              ▼
 sélection canonique → Parquet → figures → rapport → ZIP
```
""",
        encoding="utf-8",
    )
    (stage / "REPRODUCTION_LEVELS.md").write_text(
        """# Notice de reproduction en trois niveaux

## Niveau 1 — Audit sans recalcul

Lire les Parquet, figures, manifestes et hashes contenus dans le ZIP léger. Python avec pandas/pyarrow suffit.

## Niveau 2 — Consolidation et figures

Utiliser le ZIP technique, recréer l'environnement Python, puis exécuter les tests et les scripts de consolidation. Les résumés de runs contenus suffisent; les traces NetCDF ne sont ni requises ni livrées.

## Niveau 3 — Réestimation complète

Nécessite le dépôt parent, les archives sources non redistribuées, Python/PyEI/PyMC/NumPyro et R/NIMBLE. Vérifier d'abord le hash du panel, puis reprendre uniquement les runs absents. Les chemins locaux de cette machine ne font pas partie de l'interface livrée.
""",
        encoding="utf-8",
    )
    (stage / "PLAN_AND_NEXT_STEPS.md").write_text(
        f"""# Plan exécuté et suite

## Déjà fait

- panel fixe de 2 000 communes contrôlé et hashé;
- 292 couples NLS disponibles;
- {snapshot['krt_successful_pairs']} couples KRT Python terminés dans cet instantané;
- sorties communales, agrégées, quantiles et diagnostics conservés;
- consolidation corrigée pour lire le contraste durable sans trace;
- paramétrisation KRT et pilotes déplacés dans les scopes de release;
- alerte KRT–NLS séparée du diagnostic MCMC;
- README racine actuel et README historique déplacé dans `legacy/`.

## À continuer

1. terminer les {EXPECTED_KRT_PAIRS - snapshot['krt_successful_pairs']} fits initiaux KRT Python restants;
2. relancer une fois les caveats sévères/fails avec 2 000 warmup + 2 000 draws;
3. figer exactement un run canonique par couple;
4. exécuter les 240 réplications KRT exactes R/NIMBLE;
5. produire la comparaison Python–R et la prochaine release professeur.
""",
        encoding="utf-8",
    )
    model_cards = """# Fiches modèles

## KRT Python — King99 bêta-binomiale

- Modèle : `krt_beta_binomial`.
- Paramétrisation : `king99_beta_binomial_independent_beta_random_effects_v1`.
- Likelihood : `Y_i ~ Binomial(N_i, x_i*b1_i + (1-x_i)*b2_i)`.
- Hyperpriors : `c1,d1,c2,d2 iid Exponential(rate=king_lambda)`.
- Priors communaux : `b1_i ~ Beta(c1,d1)`, `b2_i ~ Beta(c2,d2)`.
- Réglages initiaux : 4 chaînes, 1 000 warmup, 1 000 draws, target_accept 0,99, profondeur 14, king_lambda 0,5.
- Sorties : huit champs d'incertitude communale, trois agrégats et diagnostics distincts.

## NLS Python/R — Rosen 2×2 et RxC admissibles

- Estimations ponctuelles seulement.
- Python : `scipy.optimize.least_squares`, TRF, 20 départs, tolérance 1e-9, maximum 5 000 évaluations.
- La réplication R est comparée numériquement; aucun pseudo-intervalle postérieur.

## KRT R exact — NIMBLE

- Même likelihood et mêmes hypothèses que le KRT Python.
- Plan de 240 couples déjà matérialisé.
- Statut dans cet instantané : en attente de la fin des fits Python et des relances ciblées.

## Interprétation

H2 et H3 sont deux modèles séparés avec des compléments différents. Leur comparaison est descriptive et n'est ni une décomposition formelle de H1 ni une différence postérieure jointe.
"""
    (stage / "MODEL_CARDS.md").write_text(model_cards, encoding="utf-8")
    scenarios = pd.DataFrame([
        {"scenario_id": scenario, "description": SCENARIO_LABELS[scenario], "status_in_snapshot": "complete" if int(selection["scenario_id"].eq(scenario).sum()) == (16 if scenario in {"H6", "H7"} else 26) else "partial"}
        for scenario in SCENARIO_ORDER
    ])
    scenarios.to_csv(stage / "MODEL_SCENARIOS.csv", index=False, encoding="utf-8-sig")


def _write_lineage(stage: Path) -> None:
    rows = [
        ("panel/longitudinal_2000_v1.parquet", "audit + harmonisation + tirage équilibré", "unit_id", "panel longitudinal fixe"),
        ("tables/longitudinal_krt_commune_partial.parquet", "model_ready + résumés communaux des runs sélectionnés", "election_id × scenario_id × unit_id", "partiel"),
        ("tables/longitudinal_krt_aggregate_partial.parquet", "aggregate_comparison_v2.csv durable de chaque run", "election_id × scenario_id × estimand", "partiel"),
        ("tables/longitudinal_nls_292_candidate.parquet", "registre + model_ready + solveur NLS", "election_id × scenario_id × estimand", "complet candidat"),
        ("diagnostics/CURRENT_RUN_SELECTION_PROVISIONAL.csv", "manifestes de runs KRT terminés", "election_id × scenario_id", "provisoire"),
        ("figures/*.png", "tables et diagnostics de cet instantané", "figure", "dérivé"),
    ]
    pd.DataFrame(rows, columns=["artifact", "upstream_and_transformation", "grain_or_key", "status"]).to_csv(
        stage / "DATA_LINEAGE.csv", index=False, encoding="utf-8-sig"
    )


def _snapshot_inputs() -> tuple[dict[str, Path], dict[str, pd.DataFrame]]:
    paths = {
        "commune": ROOT / "outputs" / "longitudinal_2000_v1" / "production" / "all_2x2_candidate" / "longitudinal_krt_commune_240_candidate.parquet",
        "aggregate": ROOT / "outputs" / "longitudinal_2000_v1" / "production" / "all_2x2_candidate" / "longitudinal_krt_aggregate_240_candidate.parquet",
        "selection": ROOT / "outputs" / "longitudinal_2000_v1" / "production" / "all_2x2_candidate" / "krt_240_candidate_selection.csv",
        "coverage": ROOT / "outputs" / "longitudinal_2000_v1" / "production" / "current_estimation_coverage.csv",
        "coverage_json": ROOT / "outputs" / "longitudinal_2000_v1" / "production" / "current_estimation_coverage.json",
        "nls": ROOT / "outputs" / "longitudinal_2000_v1" / "production" / "rxc_nls_panel_extension_v11" / "longitudinal_nls_292_candidate.parquet",
        "panel": PANEL_PATH,
    }
    frames = {
        "longitudinal_krt_commune_partial": pd.read_parquet(paths["commune"]),
        "longitudinal_krt_aggregate_partial": pd.read_parquet(paths["aggregate"]),
        "longitudinal_nls_292_candidate": pd.read_parquet(paths["nls"]),
        "selection": pd.read_csv(paths["selection"]),
        "coverage": pd.read_csv(paths["coverage"]),
    }
    return paths, frames


def _validate(paths: dict[str, Path], frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
    commune = frames["longitudinal_krt_commune_partial"]
    aggregate = frames["longitudinal_krt_aggregate_partial"]
    nls = frames["longitudinal_nls_292_candidate"]
    selection = frames["selection"]
    pairs = selection[["election_id", "scenario_id"]].drop_duplicates()
    if len(pairs) != len(selection):
        raise AssertionError("current KRT selection contains duplicate pairs")
    if len(commune) != len(selection) * 2000:
        raise AssertionError("KRT commune row count is inconsistent with 2,000 communes per selected run")
    if commune[["election_id", "scenario_id", "unit_id"]].duplicated().any():
        raise AssertionError("KRT commune keys are not unique")
    if len(aggregate) != len(selection) * 3:
        raise AssertionError("KRT aggregate row count is inconsistent with three estimands per selected run")
    required_uncertainty = {
        "b1_sd", "b1_q025", "b1_q50", "b1_q975",
        "b2_sd", "b2_q025", "b2_q50", "b2_q975",
    }
    if not required_uncertainty.issubset(commune.columns):
        raise AssertionError("eight communal uncertainty fields are incomplete")
    nls_pairs = len(nls[["election_id", "scenario_id"]].drop_duplicates())
    if nls_pairs != EXPECTED_NLS_PAIRS:
        raise AssertionError(f"NLS pair count is {nls_pairs}; expected {EXPECTED_NLS_PAIRS}")
    panel_hash = file_sha256(paths["panel"])
    if panel_hash != EXPECTED_PANEL_SHA256:
        raise AssertionError("panel hash mismatch")
    running: list[str] = []
    for manifest_path in RUNS_DIR.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("status") == "running":
            parameters = manifest.get("parameters", {})
            running.append(f"{parameters.get('election_id','?')} × {parameters.get('scenario_id','?')} ({manifest.get('run_id', manifest_path.parent.name)})")
    return {
        "created_at_utc": _utc_now(),
        "status": "partial_snapshot",
        "ready": False,
        "panel_sha256": panel_hash,
        "panel_size": 2000,
        "krt_successful_pairs": len(selection),
        "krt_expected_pairs": EXPECTED_KRT_PAIRS,
        "krt_commune_rows": len(commune),
        "krt_aggregate_rows": len(aggregate),
        "nls_pairs": nls_pairs,
        "nls_expected_pairs": EXPECTED_NLS_PAIRS,
        "running_manifests": running,
        "active_run": running[-1] if running else "aucun manifeste running",
        "validation_checks": {
            "panel_hash": "pass",
            "krt_pair_uniqueness": "pass",
            "krt_2000_rows_per_pair": "pass",
            "krt_three_aggregates_per_pair": "pass",
            "eight_uncertainty_fields": "pass",
            "nls_292_pairs": "pass",
        },
    }


def create_stage() -> Path:
    paths, frames = _snapshot_inputs()
    snapshot = _validate(paths, frames)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stage = ROOT / "work" / f"current_progress_snapshot_{stamp}"
    if stage.exists():
        raise FileExistsError(stage)
    stage.mkdir(parents=True)
    _copy(paths["commune"], stage / "tables" / "longitudinal_krt_commune_partial.parquet")
    _copy(paths["aggregate"], stage / "tables" / "longitudinal_krt_aggregate_partial.parquet")
    _copy(paths["nls"], stage / "tables" / "longitudinal_nls_292_candidate.parquet")
    _copy(paths["panel"], stage / "panel" / "longitudinal_2000_v1.parquet")
    _copy(paths["selection"], stage / "diagnostics" / "CURRENT_RUN_SELECTION_PROVISIONAL.csv")
    _copy(paths["coverage"], stage / "diagnostics" / "current_estimation_coverage.csv")
    _copy(paths["coverage_json"], stage / "diagnostics" / "current_estimation_coverage.json")
    write_json(stage / "AUDIT_STATUS.json", snapshot)
    _write_dictionary(
        {key: frames[key] for key in (
            "longitudinal_krt_commune_partial",
            "longitudinal_krt_aggregate_partial",
            "longitudinal_nls_292_candidate",
        )},
        stage / "DATA_DICTIONARY.csv",
    )
    _write_lineage(stage)
    _write_docs(stage, snapshot, frames["selection"])
    (stage / "figures").mkdir()
    _coverage_figure(frames["coverage"], stage / "figures" / "coverage_by_scenario.png")
    _diagnostic_figure(frames["selection"], stage / "figures" / "mcmc_status_by_scenario.png")
    _trajectory_figure(frames["longitudinal_krt_aggregate_partial"], stage / "figures" / "current_contrast_trajectories.png")
    _write_html_report(
        stage, frames["coverage"], frames["selection"],
        frames["longitudinal_krt_commune_partial"],
        frames["longitudinal_krt_aggregate_partial"],
        frames["longitudinal_nls_292_candidate"], snapshot,
    )
    _write_artifact(stage, frames["coverage"], snapshot)
    return stage


def _copy_technical(stage: Path, technical: Path) -> None:
    shutil.copytree(stage, technical)
    code_files = (
        "consolidation_core.py", "release_scope.py", "run_2x2_batch.py",
        "run_longitudinal_production.py", "h23_pilot_gate.py", "h23_supervisor.py",
        "run_all_2x2_python_and_r.py", "run_r_krt_exact_all_2x2.py",
        "package_current_progress_snapshot.py",
    )
    for filename in code_files:
        source = ROOT / "code_longitudinal" / filename
        if source.is_file():
            _copy(source, technical / "technical" / "code_longitudinal" / filename)
    for config in (ROOT / "config" / "releases").glob("*.json"):
        _copy(config, technical / "technical" / "config" / "releases" / config.name)
    for test in (
        "test_consolidation_core.py", "test_release_scope.py", "test_h23_pilot_gate.py",
        "test_v11_release_tools.py", "test_r_krt_exact_pipeline.py",
    ):
        source = ROOT / "tests" / test
        if source.is_file():
            _copy(source, technical / "technical" / "tests" / test)
    selection = pd.read_csv(stage / "diagnostics" / "CURRENT_RUN_SELECTION_PROVISIONAL.csv")
    for run_id in selection["run_id"].astype(str):
        run_dir = RUNS_DIR / run_id
        for filename in (
            "manifest.json", "aggregate_comparison_v2.csv", "mcmc_diagnostics_v2.json",
            "identification_diagnostics.json", "resource_ladder_gate.json",
        ):
            source = run_dir / filename
            if source.is_file():
                _copy(source, technical / "technical" / "run_diagnostics" / run_id / filename)
    legacy = ROOT / "legacy" / "README_pre_longitudinal_2000_v1.md"
    if legacy.is_file():
        _copy(legacy, technical / "technical" / "legacy" / legacy.name)


def _file_manifest(folder: Path) -> None:
    rows = []
    for path in sorted(value for value in folder.rglob("*") if value.is_file() and value.name != "FILE_MANIFEST.csv"):
        rows.append({
            "delivery_path": path.relative_to(folder).as_posix(),
            "sha256": file_sha256(path),
            "size_bytes": path.stat().st_size,
        })
    pd.DataFrame(rows).to_csv(folder / "FILE_MANIFEST.csv", index=False, encoding="utf-8-sig")


def _zip_folder(folder: Path, destination: Path) -> dict[str, Any]:
    _file_manifest(folder)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(value for value in folder.rglob("*") if value.is_file()):
            archive.write(path, path.relative_to(folder).as_posix())
    with zipfile.ZipFile(destination) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise AssertionError(f"CRC failure: {bad}")
        names = archive.namelist()
        if any(Path(name).is_absolute() or ".." in Path(name).parts for name in names):
            raise AssertionError("unsafe or absolute ZIP member")
        if any(name.lower().endswith(".nc") for name in names):
            raise AssertionError("NetCDF must not be delivered")
    digest = file_sha256(destination)
    destination.with_suffix(destination.suffix + ".sha256").write_text(
        f"{digest}  {destination.name}\n", encoding="ascii"
    )
    return {"path": str(destination), "sha256": digest, "size_bytes": destination.stat().st_size}


def finalize_stage(stage: Path) -> dict[str, Any]:
    if not (stage / "AUDIT_STATUS.json").is_file():
        raise ValueError("not a current progress snapshot stage")
    technical = stage.parent / f"{stage.name}_technical"
    if technical.exists():
        raise FileExistsError(technical)
    _copy_technical(stage, technical)
    deliverables = ROOT / "deliverables"
    light_zip = deliverables / f"{stage.name}_audit.zip"
    technical_zip = deliverables / f"{stage.name}_technique.zip"
    result = {
        "stage": str(stage),
        "light": _zip_folder(stage, light_zip),
        "technical": _zip_folder(technical, technical_zip),
        "created_at_utc": _utc_now(),
    }
    write_json(deliverables / f"{stage.name}_delivery.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a verified partial audit snapshot without stopping active fits.")
    parser.add_argument("--stage-only", action="store_true")
    parser.add_argument("--finalize-stage", type=Path)
    args = parser.parse_args()
    if args.finalize_stage:
        print(json.dumps(finalize_stage(args.finalize_stage.resolve()), ensure_ascii=False, indent=2))
        return
    stage = create_stage()
    if args.stage_only:
        print(json.dumps({"stage": str(stage)}, ensure_ascii=False))
        return
    print(json.dumps(finalize_stage(stage), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
