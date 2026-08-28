from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .spec_registry import SCENARIOS


ROOT = Path(__file__).resolve().parents[1]
DATE_TAG = "20260811"
PACKAGE_NAME = f"longitudinal_2000_v1_point_intermediaire_H0A_{DATE_TAG}"
PACKAGE_DIR = ROOT / "deliverables" / PACKAGE_NAME
ZIP_PATH = ROOT / "deliverables" / f"{PACKAGE_NAME}.zip"

FINAL_DIR = ROOT / "outputs" / "longitudinal_2000_v1" / "final"
AUDIT_DIR = ROOT / "outputs" / "longitudinal_2000_v1" / "audit"
REPLICATION_DIR = ROOT / "outputs" / "longitudinal_2000_v1" / "r_replication"
RUNS_DIR = ROOT / "outputs" / "runs"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_ready(value):
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    return value


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_ready(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _copy(source: Path, relative_target: str) -> Path:
    if not source.is_file():
        raise FileNotFoundError(source)
    target = PACKAGE_DIR / relative_target
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def _scenario_table() -> pd.DataFrame:
    rows = []
    for item in SCENARIOS:
        rows.append(
            {
                "scenario_id": item.scenario_id,
                "model_family": item.model_family,
                "social_groups": "; ".join(
                    f"{name}={' + '.join(parts)}" for name, parts in item.social_groups.items()
                ),
                "vote_categories": " / ".join(item.vote_categories),
                "vote_definition": item.vote_definition,
                "denominator": item.denominator,
                "first_year": item.min_year,
                "allowed_models": "; ".join(item.models),
            }
        )
    return pd.DataFrame(rows)


def _load_krt_diagnostics(krt_aggregate: pd.DataFrame) -> pd.DataFrame:
    rows = []
    selected = krt_aggregate[["election_id", "scenario_id", "run_id"]].drop_duplicates()
    for item in selected.itertuples(index=False):
        manifest_path = RUNS_DIR / str(item.run_id) / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        diag = manifest["canonical_mcmc_diagnostic"]
        ident = manifest["identification_diagnostic"]
        rows.append(
            {
                "election_id": item.election_id,
                "scenario_id": item.scenario_id,
                "run_id": item.run_id,
                "mcmc_status": diag["mcmc_status"],
                "identification_status": diag["identification_status"],
                "max_rhat": diag["max_rhat"],
                "min_ess_bulk": diag["min_ess_bulk"],
                "min_ess_tail": diag["min_ess_tail"],
                "divergences": diag["divergences"],
                "max_treedepth_hits": diag["max_treedepth_hits"],
                "mean_acceptance_rate": diag["mean_acceptance_rate"],
                "design_rank": ident["design_rank"],
                "design_condition": ident["design_condition"],
                "median_max_bound_width": ident["median_max_bound_width"],
                "share_max_bound_width_gt_0_8": ident["share_max_bound_width_gt_0_8"],
            }
        )
    return pd.DataFrame(rows).sort_values(["election_id", "scenario_id"])


def _build_derived_tables() -> dict[str, pd.DataFrame]:
    inventory = pd.read_parquet(AUDIT_DIR / "all_elections_inventory.parquet")
    run_plan = pd.read_parquet(AUDIT_DIR / "longitudinal_run_plan.parquet")
    panel_quality = pd.read_parquet(AUDIT_DIR / "panel_election_quality.parquet")
    nls = pd.read_parquet(FINAL_DIR / "longitudinal_nls.parquet")
    krt_aggregate = pd.read_parquet(FINAL_DIR / "longitudinal_krt_aggregate.parquet")
    comparison = pd.read_parquet(REPLICATION_DIR / "king_python_r_aggregate_comparison.parquet")
    commune_comparison = pd.read_parquet(
        REPLICATION_DIR / "king_python_r_commune_comparison_summary.parquet"
    )

    nls_fits = nls[
        ["election_id", "scenario_id", "run_id", "diagnostic_status", "fit_status"]
    ].drop_duplicates()
    krt_diag = _load_krt_diagnostics(krt_aggregate)
    contrast = krt_aggregate.loc[krt_aggregate["estimand"].eq("b_1_minus_b_2")].copy()
    contrast = contrast.merge(
        inventory[["election_id", "election_type", "year", "round"]],
        on=["election_id", "year", "round"],
        how="left",
        validate="one_to_one",
    )
    contrast["election_family"] = contrast["election_type"].map(
        {"legislative": "Législatives", "presidential": "Présidentielles"}
    )
    contrast["election_label"] = contrast["election_id"].str.replace("_r1", "", regex=False)
    contrast["line_style"] = contrast["election_type"].map(
        {"legislative": "solid", "presidential": "dashed"}
    )
    trajectory = contrast[
        [
            "election_id",
            "election_label",
            "election_type",
            "election_family",
            "line_style",
            "year",
            "round",
            "scenario_id",
            "mean",
            "median",
            "q025",
            "q975",
            "n_communes",
            "mcmc_status",
            "identification_status",
        ]
    ].sort_values(["election_type", "year"])

    nls_by_scenario = (
        nls_fits.groupby(["scenario_id", "diagnostic_status"], observed=True)
        .size()
        .rename("n_fits")
        .reset_index()
    )
    all_scenarios = sorted(run_plan["scenario_id"].unique())
    all_statuses = ["pass", "fail"]
    complete_index = pd.MultiIndex.from_product(
        [all_scenarios, all_statuses], names=["scenario_id", "diagnostic_status"]
    )
    nls_by_scenario = (
        nls_by_scenario.set_index(["scenario_id", "diagnostic_status"])
        .reindex(complete_index, fill_value=0)
        .reset_index()
    )
    nls_by_scenario["diagnostic_label"] = nls_by_scenario["diagnostic_status"].map(
        {"pass": "Diagnostic pass", "fail": "Diagnostic à revoir"}
    )

    krt_status = krt_diag[[
        "election_id",
        "mcmc_status",
        "identification_status",
        "max_rhat",
        "min_ess_bulk",
        "min_ess_tail",
        "divergences",
        "max_treedepth_hits",
    ]]
    nls_election = (
        nls_fits.groupby("election_id", observed=True)
        .agg(
            nls_fits=("scenario_id", "size"),
            nls_diagnostic_pass=("diagnostic_status", lambda s: int((s == "pass").sum())),
            nls_diagnostic_fail=("diagnostic_status", lambda s: int((s == "fail").sum())),
        )
        .reset_index()
    )
    election_status = inventory[["election_id", "election_type", "year", "round"]].merge(
        nls_election, on="election_id", how="left", validate="one_to_one"
    )
    election_status = election_status.merge(
        krt_status, on="election_id", how="left", validate="one_to_one"
    )
    r_done = set(comparison["election_id"].unique())
    election_status["krt_h0a_python"] = np.where(
        election_status["mcmc_status"].notna(), "terminé", "absent"
    )
    election_status["king_h0a_r"] = np.where(
        election_status["election_id"].isin(r_done), "terminé", "absent"
    )
    election_status["krt_h1_python"] = "en cours / non inclus"
    election_status = election_status.sort_values(["year", "election_type"])

    model_coverage = pd.DataFrame(
        [
            {"component": "Audit élections", "completed": 26, "expected": 26, "status": "terminé"},
            {"component": "NLS admissibles", "completed": 270, "expected": 270, "status": "terminé"},
            {"component": "KRT Python H0A", "completed": 26, "expected": 26, "status": "terminé"},
            {"component": "King R H0A", "completed": 26, "expected": 26, "status": "terminé"},
            {"component": "KRT Python H1", "completed": 0, "expected": 26, "status": "en cours"},
        ]
    )
    model_coverage["completion_rate"] = model_coverage["completed"] / model_coverage["expected"]

    estimand_labels = {
        "beta1_aggregate": "β1",
        "beta2_aggregate": "β2",
        "contrast_aggregate": "β1−β2",
    }
    comparison = comparison.copy()
    comparison["estimand_display"] = comparison["estimand"].map(estimand_labels)
    comparison["election_label"] = comparison["election_id"].str.replace("_r1", "", regex=False)
    comparison["interval_overlap_label"] = np.where(
        comparison["credible_intervals_overlap"], "oui", "non"
    )
    comparison_top = comparison.sort_values("absolute_difference", ascending=False).head(12).copy()

    return {
        "inventory": inventory,
        "run_plan": run_plan,
        "panel_quality": panel_quality,
        "nls_fits": nls_fits,
        "nls_by_scenario": nls_by_scenario,
        "krt_diagnostics": krt_diag,
        "trajectory": trajectory,
        "election_status": election_status,
        "model_coverage": model_coverage,
        "comparison": comparison,
        "comparison_top": comparison_top,
        "commune_comparison": commune_comparison,
        "hypotheses": _scenario_table(),
    }


def _record_rows(frame: pd.DataFrame) -> list[dict]:
    return [_json_ready(row) for row in frame.to_dict(orient="records")]


def _sources() -> list[dict]:
    return [
        {
            "id": "panel_validation",
            "label": "Validation exacte du panel longitudinal 2 000",
            "path": "03_panel_et_audit/panel_exact_validation.json",
            "query": {
                "engine": "duckdb",
                "language": "SQL",
                "sql": "SELECT * FROM read_json_auto('03_panel_et_audit/panel_exact_validation.json')",
                "description": "Charge les contrôles validés du panel primaire.",
                "tables_used": ["03_panel_et_audit/panel_exact_validation.json"],
            },
        },
        {
            "id": "nls_results",
            "label": "Consolidation NLS longitudinale",
            "path": "01_resultats_python/longitudinal_nls.parquet",
            "query": {
                "engine": "duckdb",
                "language": "SQL",
                "sql": "SELECT * FROM read_parquet('01_resultats_python/longitudinal_nls.parquet')",
                "description": "Charge les résultats NLS consolidés.",
                "tables_used": ["01_resultats_python/longitudinal_nls.parquet"],
            },
        },
        {
            "id": "krt_results",
            "label": "Consolidation KRT Python H0A",
            "path": "01_resultats_python/longitudinal_krt_aggregate.parquet",
            "query": {
                "engine": "duckdb",
                "language": "SQL",
                "sql": "SELECT * FROM read_parquet('01_resultats_python/longitudinal_krt_aggregate.parquet')",
                "description": "Charge les agrégats KRT H0A consolidés.",
                "tables_used": ["01_resultats_python/longitudinal_krt_aggregate.parquet"],
            },
        },
        {
            "id": "king_r_comparison",
            "label": "Comparaison King Python–R H0A",
            "path": "02_comparaison_python_r_king/king_python_r_aggregate_comparison.parquet",
            "query": {
                "engine": "duckdb",
                "language": "SQL",
                "sql": "SELECT * FROM read_parquet('02_comparaison_python_r_king/king_python_r_aggregate_comparison.parquet')",
                "description": "Charge les comparaisons agrégées King Python–R.",
                "tables_used": ["02_comparaison_python_r_king/king_python_r_aggregate_comparison.parquet"],
            },
        },
        {
            "id": "run_plan",
            "label": "Plan de runs dérivé du registre",
            "path": "03_panel_et_audit/longitudinal_run_plan.parquet",
            "query": {
                "engine": "duckdb",
                "language": "SQL",
                "sql": "SELECT * FROM read_parquet('03_panel_et_audit/longitudinal_run_plan.parquet')",
                "description": "Charge la classification exhaustive des couples élection-hypothèse.",
                "tables_used": ["03_panel_et_audit/longitudinal_run_plan.parquet"],
            },
        },
        {
            "id": "release_manifest",
            "label": "Manifeste de consolidation longitudinale",
            "path": "01_resultats_python/release_manifest.json",
            "query": {
                "engine": "duckdb",
                "language": "SQL",
                "sql": "SELECT * FROM read_json_auto('01_resultats_python/release_manifest.json')",
                "description": "Charge le manifeste de consolidation et ses effectifs attendus.",
                "tables_used": ["01_resultats_python/release_manifest.json"],
            },
        },
    ]


def _build_artifact(tables: dict[str, pd.DataFrame]) -> dict:
    panel_validation = json.loads((AUDIT_DIR / "panel_exact_validation.json").read_text(encoding="utf-8"))
    king_manifest = json.loads(
        (REPLICATION_DIR / "king_python_r_comparison_manifest.json").read_text(encoding="utf-8")
    )
    nls_fits = tables["nls_fits"]
    krt_diag = tables["krt_diagnostics"]
    headline = pd.DataFrame(
        [
            {
                "panel_communes": panel_validation["primary_panel_rows"],
                "panel_elections": panel_validation["elections"],
                "nls_completed": int(len(nls_fits)),
                "nls_pass": int(nls_fits["diagnostic_status"].eq("pass").sum()),
                "krt_h0a_completed": int(len(krt_diag)),
                "krt_h0a_caveat": int(krt_diag["mcmc_status"].eq("caveat").sum()),
                "king_r_completed": king_manifest["elections"],
                "king_r_median_abs_diff": king_manifest["aggregate_median_absolute_difference"],
                "krt_h1_completed": 0,
                "krt_h1_expected": 26,
            }
        ]
    )

    sources = _sources()
    generated = datetime.now(timezone.utc).isoformat()
    title = "Point intermédiaire longitudinal 2000 — H0A complet"
    manifest = {
        "version": 1,
        "surface": "report",
        "title": title,
        "description": "État technique auditable des estimations sur 26 scrutins et un panel fixe de 2 000 communes.",
        "generatedAt": generated,
        "cards": [
            {
                "id": "panel_card",
                "description": "Même ensemble de codes harmonisés dans chaque scrutin.",
                "dataset": "headline",
                "sourceId": "panel_validation",
                "metrics": [
                    {"label": "Communes fixes", "field": "panel_communes", "format": "number"},
                    {"label": "Scrutins", "field": "panel_elections", "format": "number"},
                ],
            },
            {
                "id": "nls_card",
                "description": "Tous les couples admissibles ont un ajustement; les réserves restent visibles.",
                "dataset": "headline",
                "sourceId": "nls_results",
                "metrics": [
                    {"label": "NLS exécutés", "field": "nls_completed", "format": "number"},
                    {"label": "Diagnostics pass", "field": "nls_pass", "format": "number"},
                ],
            },
            {
                "id": "krt_card",
                "description": "KRT beta-binomial Python, H0A uniquement dans cette livraison.",
                "dataset": "headline",
                "sourceId": "krt_results",
                "metrics": [
                    {"label": "KRT H0A terminés", "field": "krt_h0a_completed", "format": "number"},
                    {"label": "Avec réserve MCMC", "field": "krt_h0a_caveat", "format": "number"},
                ],
            },
            {
                "id": "r_card",
                "description": "Sensibilité King R sur les mêmes marges, avec formulation latente différente.",
                "dataset": "headline",
                "sourceId": "king_r_comparison",
                "metrics": [
                    {"label": "King R terminés", "field": "king_r_completed", "format": "number"},
                    {"label": "Écart agrégé médian", "field": "king_r_median_abs_diff", "format": "number"},
                ],
            },
            {
                "id": "h1_card",
                "description": "La production H1 a été relancée mais aucun résultat H1 n'entre dans ce ZIP intermédiaire.",
                "dataset": "headline",
                "sourceId": "release_manifest",
                "metrics": [
                    {"label": "KRT H1 inclus", "field": "krt_h1_completed", "format": "number"},
                    {"label": "Attendus", "field": "krt_h1_expected", "format": "number"},
                ],
            },
        ],
        "charts": [
            {
                "id": "coverage_chart",
                "title": "Avancement des composantes du pipeline",
                "subtitle": "H0A et NLS sont consolidés; H1 reste en dehors de ce point intermédiaire.",
                "type": "bar",
                "dataset": "model_coverage",
                "sourceId": "release_manifest",
                "encodings": {
                    "x": {"field": "component", "type": "nominal", "label": "Composante"},
                    "y": {"field": "completion_rate", "type": "quantitative", "label": "Part achevée", "format": "percent"},
                    "tooltip": [
                        {"field": "completed", "type": "quantitative", "label": "Achevés"},
                        {"field": "expected", "type": "quantitative", "label": "Attendus"},
                        {"field": "status", "type": "nominal", "label": "Statut"},
                    ],
                },
                "valueFormat": "percent",
                "layout": "full",
            },
            {
                "id": "trajectory_chart",
                "title": "Contraste KRT H0A par scrutin",
                "subtitle": "Moyenne postérieure de β1−β2; séries séparées pour législatives et présidentielles.",
                "type": "line",
                "dataset": "trajectory",
                "sourceId": "krt_results",
                "encodings": {
                    "x": {"field": "year", "type": "quantitative", "label": "Année"},
                    "y": {"field": "mean", "type": "quantitative", "label": "β1−β2", "format": "percent"},
                    "color": {"field": "election_family", "type": "nominal", "label": "Type de scrutin"},
                    "lineStyle": {"field": "line_style", "type": "nominal"},
                    "tooltip": [
                        {"field": "election_label", "type": "text", "label": "Scrutin"},
                        {"field": "q025", "type": "quantitative", "label": "q2,5 %", "format": "percent"},
                        {"field": "q975", "type": "quantitative", "label": "q97,5 %", "format": "percent"},
                        {"field": "mcmc_status", "type": "nominal", "label": "MCMC"},
                    ],
                },
                "valueFormat": "percent",
                "referenceLines": [{"axis": "y", "value": 0, "label": "Égalité β1=β2"}],
                "layout": "full",
            },
            {
                "id": "nls_diagnostic_chart",
                "title": "Diagnostics NLS par hypothèse",
                "subtitle": "Les 17 réserves sont des diagnostics de rang, conditionnement ou frontière, pas des échecs d'exécution.",
                "type": "bar",
                "dataset": "nls_by_scenario",
                "sourceId": "nls_results",
                "encodings": {
                    "x": {"field": "scenario_id", "type": "nominal", "label": "Hypothèse"},
                    "y": {"field": "n_fits", "type": "quantitative", "label": "Nombre d'ajustements"},
                    "color": {"field": "diagnostic_label", "type": "nominal", "label": "Diagnostic"},
                },
                "layout": "full",
            },
            {
                "id": "king_comparison_chart",
                "title": "Agrégats H0A — King Python et King R",
                "subtitle": "78 estimands; mêmes marges et communes, mais deux formulations probabilistes King distinctes.",
                "type": "scatter",
                "dataset": "king_comparison",
                "sourceId": "king_r_comparison",
                "encodings": {
                    "x": {"field": "mean_python_krt", "type": "quantitative", "label": "Python KRT 1999", "format": "percent"},
                    "y": {"field": "mean_r_ei", "type": "quantitative", "label": "R ei King 1997", "format": "percent"},
                    "color": {"field": "estimand_display", "type": "nominal", "label": "Estimand"},
                    "tooltip": [
                        {"field": "election_label", "type": "text", "label": "Scrutin"},
                        {"field": "absolute_difference", "type": "quantitative", "label": "Écart absolu", "format": "percent"},
                        {"field": "interval_overlap_label", "type": "nominal", "label": "Intervalles se chevauchent"},
                    ],
                },
                "layout": "full",
            },
        ],
        "tables": [
            {
                "id": "election_table",
                "title": "État des modèles par scrutin",
                "subtitle": "26 scrutins, mêmes 2 000 codes; H1 est en cours et absent de cette livraison.",
                "dataset": "election_status",
                "sourceId": "release_manifest",
                "defaultSort": {"field": "year", "direction": "asc"},
                "density": "dense",
                "columns": [
                    {"field": "election_id", "label": "Scrutin", "type": "text"},
                    {"field": "year", "label": "Année", "format": "number"},
                    {"field": "election_type", "label": "Type", "type": "text"},
                    {"field": "nls_fits", "label": "NLS", "format": "number"},
                    {"field": "nls_diagnostic_fail", "label": "NLS à revoir", "format": "number"},
                    {"field": "mcmc_status", "label": "KRT H0A MCMC", "type": "text"},
                    {"field": "identification_status", "label": "Identification", "type": "text"},
                    {"field": "max_rhat", "label": "R-hat max", "format": "number"},
                    {"field": "min_ess_bulk", "label": "ESS bulk min", "format": "number"},
                    {"field": "king_h0a_r", "label": "King R", "type": "text"},
                    {"field": "krt_h1_python", "label": "KRT H1", "type": "text"},
                ],
            },
            {
                "id": "comparison_table",
                "title": "Plus grands écarts agrégés entre Python et R",
                "subtitle": "Classement par écart absolu; les intervalles 95 % se chevauchent dans les 78 comparaisons.",
                "dataset": "comparison_top",
                "sourceId": "king_r_comparison",
                "defaultSort": {"field": "absolute_difference", "direction": "desc"},
                "density": "dense",
                "columns": [
                    {"field": "election_id", "label": "Scrutin", "type": "text"},
                    {"field": "estimand_display", "label": "Estimand", "type": "text"},
                    {"field": "mean_python_krt", "label": "Python KRT", "format": "percent"},
                    {"field": "mean_r_ei", "label": "R ei", "format": "percent"},
                    {"field": "absolute_difference", "label": "Écart absolu", "format": "percent"},
                    {"field": "interval_overlap_label", "label": "Chevauchement", "type": "text"},
                ],
            },
        ],
        "sources": sources,
        "blocks": [
            {"id": "title", "type": "markdown", "body": f"# {title}"},
            {
                "id": "status_notice",
                "type": "markdown",
                "body": "**Statut : rapport intermédiaire.** La production H0A est complète et consolidée. La production H1 a été relancée, mais aucun résultat H1 n'est inclus ici; le manifeste final reste donc volontairement `ready=false`.",
                "sourceId": "release_manifest",
            },
            {
                "id": "technical_summary",
                "type": "markdown",
                "body": "## Résumé technique\n\nLe pipeline longitudinal repose désormais sur un panel communal invariant, un registre exhaustif des scrutins et hypothèses, des clés `unit_id` harmonisées et des runs indépendants reprenables. Ce point d'étape privilégie la traçabilité : toute réserve diagnostique ou composante encore absente reste visible.",
            },
            {"id": "metrics", "type": "metric-strip", "cardIds": ["panel_card", "nls_card", "krt_card", "r_card", "h1_card"]},
            {"id": "coverage", "type": "chart", "chartId": "coverage_chart"},
            {
                "id": "panel_section",
                "type": "markdown",
                "body": "## Panel et données\n\nLe panel primaire contient exactement **2 000 communes** et le même ensemble de `unit_id` est retrouvé dans chacun des **26 scrutins**, soit **52 000 couples commune–élection**. Aucun compte négatif ni aucune violation `exprimés ≤ votants ≤ inscrits` ne subsiste. La porte d'équilibre passe avec un SMD absolu maximal de **0,0669** et un écart catégoriel maximal de **0,01962**.",
                "sourceId": "panel_validation",
            },
            {
                "id": "model_scope",
                "type": "markdown",
                "body": "## Périmètre des modèles\n\nLe registre classe exactement **292 couples élection–hypothèse** : **270 admissibles** et exécutés en NLS, plus **22 inéligibles** conservés avec un motif explicite. Les KRT présentés dans ce rapport portent uniquement sur H0A : abstention parmi les inscrits, avec β1 pour les ouvriers et employés et β2 pour les autres catégories socioprofessionnelles.",
                "sourceId": "run_plan",
            },
            {"id": "trajectory", "type": "chart", "chartId": "trajectory_chart"},
            {
                "id": "krt_method",
                "type": "markdown",
                "body": "## KRT Python H0A\n\nLes **26/26** ajustements utilisent le modèle beta-binomial KRT/King99, `king_lambda=0,5`, quatre chaînes, 1 000 itérations de warmup, 1 000 tirages conservés, `target_accept=0,99` et `max_treedepth=14`. Bilan : **12 pass**, **14 caveat**, **0 fail**, aucune divergence; les réserves d'identification sont conservées séparément (**7 pass**, **19 caveat**).",
                "sourceId": "krt_results",
            },
            {
                "id": "uncertainty_note",
                "type": "markdown",
                "body": "Les intervalles de la figure sont accessibles dans la table agrégée et dans les infobulles. Au niveau communal, les huit champs demandés (`sd`, `q025`, `q50`, `q975` pour β1 et β2) sont présents sur les 52 000 lignes.",
                "sourceId": "krt_results",
            },
            {"id": "nls_diagnostics", "type": "chart", "chartId": "nls_diagnostic_chart"},
            {
                "id": "nls_section",
                "type": "markdown",
                "body": "## NLS sur toutes les hypothèses admissibles\n\nLes **270/270** couples admissibles ont convergé avec 20 départs réussis. **253** diagnostics sont `pass` et **17** sont `fail` au sens diagnostique, principalement pour H5/RXC1/RXC2 en raison du rang, du conditionnement ou de solutions en frontière. Ces 17 lignes restent dans les tables pour audit mais ne doivent pas être interprétées comme des estimations robustes sans examen complémentaire.",
                "sourceId": "nls_results",
            },
            {"id": "king_comparison", "type": "chart", "chartId": "king_comparison_chart"},
            {
                "id": "r_section",
                "type": "markdown",
                "body": "## Comparaison King Python–R\n\nLa réplication R native `ei::ei` est terminée pour H0A sur les **26 scrutins** et exactement les mêmes **2 000 communes**. Les signes des 26 contrastes agrégés concordent; les **78/78** intervalles se chevauchent. L'écart absolu médian est **0,00184** et le maximum **0,01342**. Il s'agit d'un test de sensibilité, pas d'une réplication mathématiquement identique : R utilise King 1997 à normale bivariée tronquée et 99 tirages d'importance, tandis que Python utilise KRT 1999 beta-binomial avec MCMC.",
                "sourceId": "king_r_comparison",
            },
            {"id": "comparison_detail", "type": "table", "tableId": "comparison_table"},
            {"id": "election_detail", "type": "table", "tableId": "election_table"},
            {
                "id": "limitations",
                "type": "markdown",
                "body": "## Limites et robustesse\n\n- Ce ZIP est un point intermédiaire H0A, pas la release H0A+H1.\n- Les `caveat` d'identification signalent des bornes de tomographie parfois larges : ils limitent l'interprétation individuelle des β.\n- Le modèle R `ei` n'est pas identique au modèle PyEI KRT; l'accord observé teste la robustesse à une autre formulation King.\n- La tentative Stan strictement identique n'a pas atteint un run validé et n'est ni mélangée aux résultats ni livrée.\n- Les NetCDF et RDS sont exclus; seuls les résumés consolidés et les diagnostics auditables sont remis.",
            },
            {
                "id": "next_steps",
                "type": "markdown",
                "body": "## Étapes suivantes\n\n1. Achever les 26 KRT H1 et relancer le finaliseur pour obtenir 52/52 couples KRT.\n2. Consolider les trajectoires H1 et les contrastes H0A/H1 sans comparer directement leurs niveaux, car événements et dénominateurs diffèrent.\n3. Ajouter l'audit de densité 2022 et les figures limitées aux élections charnières.\n4. Produire la release finale autonome uniquement après validation des quatre Parquet et absence de `fail` inexpliqué.",
            },
            {
                "id": "questions",
                "type": "markdown",
                "body": "## Questions pour la discussion\n\n- Les 17 diagnostics NLS fragiles doivent-ils être exclus des trajectoires principales ou conservés en annexe ?\n- Pour l'interprétation substantive, souhaite-t-on privilégier le contraste agrégé pondéré par population ou une synthèse des distributions communales ?\n- La sensibilité R `ei` suffit-elle comme contrôle externe, sachant que la formulation King n'est pas identique ?",
            },
        ],
    }
    snapshot = {
        "version": 1,
        "generatedAt": generated,
        "status": "partial",
        "datasets": {
            "headline": _record_rows(headline),
            "model_coverage": _record_rows(tables["model_coverage"]),
            "trajectory": _record_rows(tables["trajectory"]),
            "nls_by_scenario": _record_rows(tables["nls_by_scenario"]),
            "king_comparison": _record_rows(tables["comparison"]),
            "comparison_top": _record_rows(tables["comparison_top"]),
            "election_status": _record_rows(tables["election_status"]),
        },
        "accessIssues": [
            {
                "id": "krt_h1_pending",
                "scope": "KRT H1",
                "sourceId": "release_manifest",
                "message": "Les 26 estimations KRT H1 ne sont pas encore consolidées dans cette livraison intermédiaire.",
            }
        ],
    }
    return {
        "surface": "report",
        "manifest": manifest,
        "snapshot": snapshot,
        "sources": sources,
        "package_info": {"delivery": "portable_html", "release_status": "intermediate_h0a"},
    }


def _write_supporting_docs(tables: dict[str, pd.DataFrame]) -> None:
    readme = """# Point intermédiaire `longitudinal_2000_v1` — H0A

Commencer par ouvrir **`RAPPORT_INTERMEDIAIRE_LONGITUDINAL_2000_H0A.html`**.

Cette livraison contient l'état calculé à la date du 11 août 2026 : panel fixe de 2 000 communes validé sur 26 scrutins, NLS complet sur les 270 couples admissibles, KRT Python H0A complet sur 26 scrutins et comparaison King R H0A complète. Les KRT H1 sont en cours et ne figurent pas dans ce ZIP.

Les quatre Parquet professoraux actuels sont dans `01_resultats_python/`. La table KRT communale contient les huit champs d'incertitude demandés pour β1 et β2. Les fichiers NetCDF, RDS, caches et runs incomplets sont volontairement exclus.

Le fichier `package_manifest.json` fournit la taille et le SHA-256 de chaque fichier livré. Le ZIP est un **rendu intermédiaire**, pas la release finale H0A+H1.
"""
    (PACKAGE_DIR / "README.md").write_text(readme, encoding="utf-8")

    note = """# Note sur la comparaison King Python–R

Les deux calculs emploient exactement les mêmes 2 000 `unit_id` et les mêmes marges H0A pour les 26 scrutins, mais ils ne sont pas mathématiquement identiques.

- Python : PyEI, modèle King–Rosen–Tanner 1999 beta-binomial, quatre chaînes MCMC.
- R : `ei::ei`, modèle King 1997 à normale bivariée tronquée, 99 tirages d'importance produits par l'implémentation native.

La comparaison doit donc être lue comme un contrôle de sensibilité entre deux formulations de la famille King. Elle ne valide pas une identité ligne à ligne du code. Les 26 signes des contrastes agrégés concordent et les 78 intervalles agrégés se chevauchent; l'écart absolu médian vaut 0,00184 et le maximum 0,01342.

Une tentative Stan de réplication stricte du modèle Python a été compilée mais n'a pas produit de run validé dans un temps raisonnable en dimension 4 004. Ses chaînes partielles sont exclues de la livraison.
"""
    note_path = PACKAGE_DIR / "02_comparaison_python_r_king" / "NOTE_MODELES_NON_IDENTIQUES.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(note, encoding="utf-8")

    table_notes = """# Guide des tables

- `etat_modeles_par_election.csv` : couverture NLS, diagnostics KRT H0A, comparaison R et statut H1 pour chaque scrutin.
- `trajectoire_krt_h0a.csv` : β1−β2 avec moyenne, médiane et intervalle 95 % pour les 26 scrutins.
- `nls_diagnostics_par_hypothese.csv` : nombre de diagnostics pass/fail parmi les fits NLS exécutés.
- `comparaison_king_python_r_agregee.csv` : 78 comparaisons β1, β2 et contraste.
- `comparaison_king_python_r_communale_resume.csv` : écarts, corrélations et recouvrement au niveau communal par scrutin.
"""
    (PACKAGE_DIR / "02_syntheses" / "README.md").write_text(table_notes, encoding="utf-8")


def _copy_payload() -> None:
    final_files = [
        "longitudinal_krt_commune.parquet",
        "longitudinal_krt_aggregate.parquet",
        "longitudinal_nls.parquet",
        "longitudinal_audit.parquet",
        "benchmark_regression.parquet",
        "release_manifest.json",
    ]
    for name in final_files:
        _copy(FINAL_DIR / name, f"01_resultats_python/{name}")

    replication_files = [
        "longitudinal_king_ei_r_commune.parquet",
        "longitudinal_king_ei_r_aggregate.parquet",
        "king_python_r_aggregate_comparison.parquet",
        "king_python_r_commune_comparison.parquet",
        "king_python_r_commune_comparison_summary.parquet",
        "king_python_r_comparison_manifest.json",
        "longitudinal_nls_r.parquet",
        "nls_python_r_comparison.parquet",
        "nls_r_manifest.json",
    ]
    for name in replication_files:
        _copy(REPLICATION_DIR / name, f"02_comparaison_python_r_king/{name}")

    audit_files = [
        "all_elections_inventory.parquet",
        "all_elections_inventory.csv",
        "longitudinal_run_plan.parquet",
        "longitudinal_run_plan.csv",
        "panel_election_quality.parquet",
        "panel_exact_validation.json",
        "audit_manifest.json",
    ]
    for name in audit_files:
        _copy(AUDIT_DIR / name, f"03_panel_et_audit/{name}")

    panel_files = [
        "longitudinal_2000_v1_manifest.json",
        "longitudinal_2000_v1_balance.parquet",
        "longitudinal_2000_v1_balance_by_election.parquet",
        "longitudinal_2000_v1_attempts.parquet",
    ]
    for name in panel_files:
        _copy(ROOT / "panel" / name, f"03_panel_et_audit/{name}")

    code_files = [
        (ROOT / "config" / "run_settings.json", "05_methodologie_et_code/run_settings.json"),
        (ROOT / "code_longitudinal" / "spec_registry.py", "05_methodologie_et_code/spec_registry.py"),
        (ROOT / "code_longitudinal" / "finalize_longitudinal.py", "05_methodologie_et_code/finalize_longitudinal.py"),
        (ROOT / "code_longitudinal" / "run_pipeline.py", "05_methodologie_et_code/run_pipeline.py"),
        (ROOT / "code_longitudinal" / "run_longitudinal_production.py", "05_methodologie_et_code/run_longitudinal_production.py"),
        (ROOT / "code_longitudinal" / "run_r_king_ei_replication.py", "05_methodologie_et_code/run_r_king_ei_replication.py"),
        (ROOT / "r_replication" / "run_king_ei_replication.R", "05_methodologie_et_code/run_king_ei_replication.R"),
    ]
    for source, target in code_files:
        _copy(source, target)

    figure_files = [
        (
            ROOT / "figures" / "longitudinal_2000_v1" / "trajectories" / "h0a_contrast.png",
            "04_figures/h0a_contrast.png",
        ),
        (
            ROOT / "figures" / "longitudinal_2000_v1" / "trajectories" / "h0a_contrast.svg",
            "04_figures/h0a_contrast.svg",
        ),
        (
            ROOT / "figures" / "longitudinal_2000_v1" / "density_audit_2022" / "h0a_density_audit.png",
            "04_figures/h0a_density_audit_2022.png",
        ),
        (
            ROOT / "figures" / "longitudinal_2000_v1" / "density_audit_2022" / "h0a_density_audit.svg",
            "04_figures/h0a_density_audit_2022.svg",
        ),
        (
            ROOT / "figures" / "longitudinal_2000_v1" / "density_audit_2022" / "density_audit_metrics.parquet",
            "04_figures/density_audit_metrics.parquet",
        ),
    ]
    for source, target in figure_files:
        _copy(source, target)


def _validate_and_write(tables: dict[str, pd.DataFrame]) -> dict:
    panel = pd.read_parquet(ROOT / "panel" / "longitudinal_2000_v1.parquet")
    primary = panel.loc[panel["included_primary_2000"].fillna(False)].copy()
    primary = primary.sort_values("master_draw_order")
    target_dir = PACKAGE_DIR / "03_panel_et_audit"
    primary.to_parquet(target_dir / "panel_primaire_2000.parquet", index=False)
    primary.to_csv(target_dir / "panel_primaire_2000.csv", index=False, encoding="utf-8-sig")

    krt_commune = pd.read_parquet(FINAL_DIR / "longitudinal_krt_commune.parquet")
    krt_aggregate = pd.read_parquet(FINAL_DIR / "longitudinal_krt_aggregate.parquet")
    nls = pd.read_parquet(FINAL_DIR / "longitudinal_nls.parquet")
    panel_quality = tables["panel_quality"]
    comparison = tables["comparison"]
    uncertainty = [
        "b1_sd", "b1_q025", "b1_q50", "b1_q975",
        "b2_sd", "b2_q025", "b2_q50", "b2_q975",
    ]
    checks = {
        "panel_primary_rows": int(len(primary)),
        "panel_primary_unique_unit_id": int(primary["unit_id"].nunique()),
        "panel_same_code_set_26_elections": bool(panel_quality["exact_master_code_set"].all()),
        "panel_rows_each_election": sorted(panel_quality["n_rows"].unique().tolist()),
        "krt_commune_rows": int(len(krt_commune)),
        "krt_commune_unique_key": bool(
            ~krt_commune.duplicated(["panel_id", "election_id", "scenario_id", "unit_id"]).any()
        ),
        "krt_uncertainty_fields_present": bool(set(uncertainty).issubset(krt_commune.columns)),
        "krt_uncertainty_fields_complete": bool(krt_commune[uncertainty].notna().all().all()),
        "krt_aggregate_rows": int(len(krt_aggregate)),
        "krt_aggregate_unique_key": bool(
            ~krt_aggregate.duplicated(["panel_id", "election_id", "scenario_id", "estimand"]).any()
        ),
        "nls_rows": int(len(nls)),
        "nls_pairs": int(nls[["election_id", "scenario_id"]].drop_duplicates().shape[0]),
        "registered_pairs": int(len(tables["run_plan"])),
        "registered_pairs_all_classified": bool(tables["run_plan"]["preparation_status"].notna().all()),
        "r_aggregate_comparisons": int(len(comparison)),
        "r_same_26_elections": int(comparison["election_id"].nunique()),
        "r_interval_overlap_rate": float(comparison["credible_intervals_overlap"].mean()),
        "netcdf_or_rds_in_package": False,
    }
    required_truths = [
        checks["panel_primary_rows"] == 2000,
        checks["panel_primary_unique_unit_id"] == 2000,
        checks["panel_same_code_set_26_elections"],
        checks["panel_rows_each_election"] == [2000],
        checks["krt_commune_rows"] == 52000,
        checks["krt_commune_unique_key"],
        checks["krt_uncertainty_fields_present"],
        checks["krt_uncertainty_fields_complete"],
        checks["krt_aggregate_rows"] == 78,
        checks["krt_aggregate_unique_key"],
        checks["nls_pairs"] == 270,
        checks["registered_pairs"] == 292,
        checks["registered_pairs_all_classified"],
        checks["r_aggregate_comparisons"] == 78,
        checks["r_same_26_elections"] == 26,
    ]
    checks["ready_for_intermediate_delivery"] = bool(all(required_truths))
    _write_json(PACKAGE_DIR / "validation_report.json", checks)
    if not checks["ready_for_intermediate_delivery"]:
        raise RuntimeError("Intermediate package validation failed")
    return checks


def prepare() -> None:
    if PACKAGE_DIR.exists():
        raise FileExistsError(f"Package directory already exists: {PACKAGE_DIR}")
    PACKAGE_DIR.mkdir(parents=True)
    (PACKAGE_DIR / "02_syntheses").mkdir(parents=True)
    tables = _build_derived_tables()
    _copy_payload()

    table_targets = {
        "model_coverage": "avancement_pipeline.csv",
        "election_status": "etat_modeles_par_election.csv",
        "trajectory": "trajectoire_krt_h0a.csv",
        "nls_by_scenario": "nls_diagnostics_par_hypothese.csv",
        "krt_diagnostics": "diagnostics_krt_h0a_par_election.csv",
        "comparison": "comparaison_king_python_r_agregee.csv",
        "commune_comparison": "comparaison_king_python_r_communale_resume.csv",
        "hypotheses": "definitions_hypotheses.csv",
    }
    for key, name in table_targets.items():
        tables[key].to_csv(
            PACKAGE_DIR / "02_syntheses" / name,
            index=False,
            encoding="utf-8-sig",
        )
    _write_supporting_docs(tables)
    _validate_and_write(tables)
    _write_json(PACKAGE_DIR / "artifact.json", _build_artifact(tables))
    print(PACKAGE_DIR)


def finalize() -> None:
    report_path = PACKAGE_DIR / "RAPPORT_INTERMEDIAIRE_LONGITUDINAL_2000_H0A.html"
    if not report_path.is_file():
        raise FileNotFoundError(report_path)
    forbidden = [p for p in PACKAGE_DIR.rglob("*") if p.is_file() and p.suffix.lower() in {".nc", ".rds"}]
    if forbidden:
        raise RuntimeError(f"Forbidden chain files in package: {forbidden}")

    files = sorted(
        (p for p in PACKAGE_DIR.rglob("*") if p.is_file() and p.name != "package_manifest.json"),
        key=lambda p: p.relative_to(PACKAGE_DIR).as_posix(),
    )
    manifest = {
        "schema_version": "professor_intermediate_package_v1",
        "package_name": PACKAGE_NAME,
        "release_status": "intermediate_h0a",
        "h1_included": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "file_count_excluding_manifest": len(files),
        "files": [
            {
                "path": p.relative_to(PACKAGE_DIR).as_posix(),
                "bytes": p.stat().st_size,
                "sha256": _sha256(p),
            }
            for p in files
        ],
        "exclusions": [
            "NetCDF traces",
            "RDS fits",
            "incomplete Stan chains",
            "cache directories",
            "failed or interrupted runs",
        ],
    }
    _write_json(PACKAGE_DIR / "package_manifest.json", manifest)

    zip_files = sorted(
        (p for p in PACKAGE_DIR.rglob("*") if p.is_file()),
        key=lambda p: p.relative_to(PACKAGE_DIR.parent).as_posix(),
    )
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in zip_files:
            arcname = path.relative_to(PACKAGE_DIR.parent).as_posix()
            info = zipfile.ZipInfo(arcname, date_time=(2026, 8, 11, 12, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        corrupt = archive.testzip()
        if corrupt is not None:
            raise RuntimeError(f"ZIP CRC failure: {corrupt}")
        zip_members = archive.namelist()
    sidecar = ZIP_PATH.with_suffix(ZIP_PATH.suffix + ".sha256")
    sidecar.write_text(f"{_sha256(ZIP_PATH)}  {ZIP_PATH.name}\n", encoding="ascii")
    receipt = {
        "zip_path": ZIP_PATH.relative_to(ROOT).as_posix(),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": _sha256(ZIP_PATH),
        "zip_members": len(zip_members),
        "zip_crc_check": "passed",
        "report_path": report_path.relative_to(ROOT).as_posix(),
        "report_sha256": _sha256(report_path),
    }
    _write_json(ZIP_PATH.with_suffix(ZIP_PATH.suffix + ".receipt.json"), receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the longitudinal 2000 H0A professor package")
    parser.add_argument("mode", choices=("prepare", "finalize"))
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare()
    else:
        finalize()


if __name__ == "__main__":
    main()
