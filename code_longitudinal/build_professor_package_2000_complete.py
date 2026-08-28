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
DATE_TAG = "20260816"
PACKAGE_NAME = f"longitudinal_2000_v1_H0A_H1_complet_{DATE_TAG}"
PACKAGE_DIR = ROOT / "deliverables" / PACKAGE_NAME
ZIP_PATH = ROOT / "deliverables" / f"{PACKAGE_NAME}.zip"

FINAL_DIR = ROOT / "outputs" / "longitudinal_2000_v1" / "final"
AUDIT_DIR = ROOT / "outputs" / "longitudinal_2000_v1" / "audit"
REPLICATION_DIR = ROOT / "outputs" / "longitudinal_2000_v1" / "r_replication"
RUNS_DIR = ROOT / "outputs" / "runs"
PANEL_DIR = ROOT / "panel"
FIGURE_DIR = ROOT / "figures" / "longitudinal_2000_v1"


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
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
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


def _record_rows(frame: pd.DataFrame) -> list[dict]:
    return [_json_ready(row) for row in frame.to_dict(orient="records")]


def _portable_manifest_value(value):
    """Remove machine-local roots from copied run manifests.

    Historical manifests are preserved in the working outputs.  The professor
    package contains a portable copy whose paths are relative to the project.
    """
    if isinstance(value, dict):
        return {
            str(_portable_manifest_value(key)): _portable_manifest_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_portable_manifest_value(item) for item in value]
    if isinstance(value, tuple):
        return [_portable_manifest_value(item) for item in value]
    if not isinstance(value, str):
        return value
    text = value.replace(str(ROOT), ".").replace(ROOT.as_posix(), ".")
    return text.replace(".\\", "").replace("./", "")


def _scenario_table() -> pd.DataFrame:
    return pd.DataFrame(
        [
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
            for item in SCENARIOS
        ]
    )


def _load_krt_diagnostics(krt_aggregate: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
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
    return pd.DataFrame(rows).sort_values(["scenario_id", "election_id"]).reset_index(drop=True)


def _build_tables() -> dict[str, pd.DataFrame]:
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
    contrast["election_type"] = np.where(
        contrast["election_id"].str.startswith("leg_"), "legislative", "presidential"
    )
    contrast["election_family"] = contrast["election_type"].map(
        {"legislative": "Législatives", "presidential": "Présidentielles"}
    )
    contrast["election_label"] = contrast["election_id"].str.replace("_r1", "", regex=False)
    contrast["line_style"] = contrast["election_type"].map(
        {"legislative": "solid", "presidential": "dashed"}
    )
    trajectory_columns = [
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
    trajectory = contrast[trajectory_columns].sort_values(["scenario_id", "election_type", "year"])

    krt_status = (
        krt_diag.groupby(["scenario_id", "mcmc_status"], observed=True)
        .size()
        .rename("n_fits")
        .reset_index()
    )
    krt_complete = pd.MultiIndex.from_product(
        [["H0A", "H1"], ["pass", "caveat"]], names=["scenario_id", "mcmc_status"]
    )
    krt_status = (
        krt_status.set_index(["scenario_id", "mcmc_status"])
        .reindex(krt_complete, fill_value=0)
        .reset_index()
    )
    krt_status["diagnostic_label"] = krt_status["mcmc_status"].map(
        {"pass": "MCMC pass", "caveat": "MCMC avec réserve"}
    )

    nls_by_scenario = (
        nls_fits.groupby(["scenario_id", "diagnostic_status"], observed=True)
        .size()
        .rename("n_fits")
        .reset_index()
    )
    nls_complete = pd.MultiIndex.from_product(
        [sorted(run_plan["scenario_id"].unique()), ["pass", "fail"]],
        names=["scenario_id", "diagnostic_status"],
    )
    nls_by_scenario = (
        nls_by_scenario.set_index(["scenario_id", "diagnostic_status"])
        .reindex(nls_complete, fill_value=0)
        .reset_index()
    )
    nls_by_scenario["diagnostic_label"] = nls_by_scenario["diagnostic_status"].map(
        {"pass": "Diagnostic pass", "fail": "Diagnostic à revoir"}
    )

    diagnostics_wide = krt_diag.pivot(
        index="election_id",
        columns="scenario_id",
        values=[
            "mcmc_status",
            "identification_status",
            "max_rhat",
            "min_ess_bulk",
            "divergences",
            "max_treedepth_hits",
        ],
    )
    diagnostics_wide.columns = [f"{metric}_{scenario.lower()}" for metric, scenario in diagnostics_wide.columns]
    diagnostics_wide = diagnostics_wide.reset_index()
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
        diagnostics_wide, on="election_id", how="left", validate="one_to_one"
    ).sort_values(["year", "election_type"])

    model_coverage = pd.DataFrame(
        [
            {"component": "Audit des scrutins", "completed": 26, "expected": 26},
            {"component": "Panel fixe par scrutin", "completed": 26, "expected": 26},
            {"component": "NLS admissibles", "completed": 270, "expected": 270},
            {"component": "KRT Python H0A", "completed": 26, "expected": 26},
            {"component": "KRT Python H1", "completed": 26, "expected": 26},
            {"component": "King R H0A", "completed": 26, "expected": 26},
        ]
    )
    model_coverage["completion_rate"] = model_coverage["completed"] / model_coverage["expected"]
    model_coverage["status"] = "terminé"

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
    comparison_top = comparison.sort_values("absolute_difference", ascending=False).head(15).copy()

    previous_current = pd.DataFrame(
        [
            {
                "element": "KRT H0A",
                "rendu_20260811": "26/26",
                "rendu_20260816": "26/26",
                "evolution": "inchangé, validé",
            },
            {
                "element": "KRT H1",
                "rendu_20260811": "0/26 inclus",
                "rendu_20260816": "26/26",
                "evolution": "production achevée",
            },
            {
                "element": "Lignes KRT communales",
                "rendu_20260811": "52 000",
                "rendu_20260816": "104 000",
                "evolution": "+52 000 lignes H1",
            },
            {
                "element": "Agrégats KRT",
                "rendu_20260811": "78",
                "rendu_20260816": "156",
                "evolution": "+78 agrégats H1",
            },
            {
                "element": "Validation finale",
                "rendu_20260811": "intermédiaire H0A",
                "rendu_20260816": "ready=true",
                "evolution": "périmètre v1 complet",
            },
            {
                "element": "Figures",
                "rendu_20260811": "H0A",
                "rendu_20260816": "H0A + H1",
                "evolution": "trajectoire et audit 2022 H1 ajoutés",
            },
        ]
    )

    return {
        "inventory": inventory,
        "run_plan": run_plan,
        "panel_quality": panel_quality,
        "nls": nls,
        "nls_fits": nls_fits,
        "nls_by_scenario": nls_by_scenario,
        "krt_aggregate": krt_aggregate,
        "krt_diagnostics": krt_diag,
        "krt_status": krt_status,
        "trajectory": trajectory,
        "trajectory_h0a": trajectory.loc[trajectory["scenario_id"].eq("H0A")].copy(),
        "trajectory_h1": trajectory.loc[trajectory["scenario_id"].eq("H1")].copy(),
        "election_status": election_status,
        "model_coverage": model_coverage,
        "comparison": comparison,
        "comparison_top": comparison_top,
        "commune_comparison": commune_comparison,
        "hypotheses": _scenario_table(),
        "previous_current": previous_current,
    }


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
            "id": "krt_results",
            "label": "Consolidation KRT Python H0A et H1",
            "path": "01_resultats_python/longitudinal_krt_aggregate.parquet",
            "query": {
                "engine": "duckdb",
                "language": "SQL",
                "sql": "SELECT * FROM read_parquet('01_resultats_python/longitudinal_krt_aggregate.parquet')",
                "description": "Charge les 156 agrégats KRT consolidés.",
                "tables_used": ["01_resultats_python/longitudinal_krt_aggregate.parquet"],
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
                "description": "Charge les 270 couples NLS admissibles.",
                "tables_used": ["01_resultats_python/longitudinal_nls.parquet"],
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
                "description": "Charge les 78 comparaisons agrégées King Python–R H0A.",
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
                "description": "Charge la classification exhaustive des 292 couples enregistrés.",
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
                "description": "Charge le verdict de validation de la release v1.",
                "tables_used": ["01_resultats_python/release_manifest.json"],
            },
        },
        {
            "id": "election_status_summary",
            "label": "Synthèse des diagnostics par scrutin",
            "path": "02_syntheses/etat_modeles_par_election.csv",
            "query": {
                "engine": "duckdb",
                "language": "SQL",
                "sql": "SELECT * FROM read_csv_auto('02_syntheses/etat_modeles_par_election.csv', header=true)",
                "description": "Charge la synthèse dérivée des résultats KRT, NLS et de l'inventaire électoral.",
                "tables_used": [
                    "02_syntheses/etat_modeles_par_election.csv",
                    "01_resultats_python/longitudinal_krt_aggregate.parquet",
                    "01_resultats_python/longitudinal_nls.parquet",
                    "03_panel_et_audit/all_elections_inventory.parquet",
                ],
            },
        },
    ]


def _build_artifact(tables: dict[str, pd.DataFrame], validation: dict) -> dict:
    king_manifest = json.loads(
        (REPLICATION_DIR / "king_python_r_comparison_manifest.json").read_text(encoding="utf-8")
    )
    krt_diag = tables["krt_diagnostics"]
    nls_fits = tables["nls_fits"]
    headline = pd.DataFrame(
        [
            {
                "panel_communes": validation["panel_primary_rows"],
                "elections": validation["elections"],
                "krt_pairs": validation["krt_pairs"],
                "nls_pairs": validation["nls_pairs"],
                "krt_pass": int(krt_diag["mcmc_status"].eq("pass").sum()),
                "krt_caveat": int(krt_diag["mcmc_status"].eq("caveat").sum()),
                "king_r_elections": king_manifest["elections"],
                "king_r_median_abs_diff": king_manifest["aggregate_median_absolute_difference"],
            }
        ]
    )
    sources = _sources()
    generated = datetime.now(timezone.utc).isoformat()
    title = "Résultats longitudinaux 2000 — KRT H0A et H1 complets"

    cards = [
        {
            "id": "panel_card",
            "description": "Même ensemble de codes harmonisés dans chaque scrutin.",
            "dataset": "headline",
            "sourceId": "panel_validation",
            "metrics": [
                {"label": "Communes fixes", "field": "panel_communes", "format": "number"},
                {"label": "Scrutins", "field": "elections", "format": "number"},
            ],
        },
        {
            "id": "krt_card",
            "description": "H0A et H1 sur 26 scrutins chacun.",
            "dataset": "headline",
            "sourceId": "krt_results",
            "metrics": [
                {"label": "Couples KRT validés", "field": "krt_pairs", "format": "number"},
                {"label": "MCMC pass", "field": "krt_pass", "format": "number"},
                {"label": "MCMC avec réserve", "field": "krt_caveat", "format": "number"},
            ],
        },
        {
            "id": "nls_card",
            "description": "Tous les couples admissibles sont conservés avec leur diagnostic.",
            "dataset": "headline",
            "sourceId": "nls_results",
            "metrics": [
                {"label": "Couples NLS", "field": "nls_pairs", "format": "number"},
            ],
        },
        {
            "id": "r_card",
            "description": "Sensibilité H0A avec la formulation King native du paquet R ei.",
            "dataset": "headline",
            "sourceId": "king_r_comparison",
            "metrics": [
                {"label": "Scrutins comparés en R", "field": "king_r_elections", "format": "number"},
                {"label": "Écart agrégé médian", "field": "king_r_median_abs_diff", "format": "percent"},
            ],
        },
    ]

    charts = [
        {
            "id": "krt_diagnostics_chart",
            "title": "Diagnostics MCMC KRT par hypothèse",
            "subtitle": "52 ajustements : les réserves restent admissibles mais doivent accompagner l’interprétation.",
            "type": "bar",
            "dataset": "krt_status",
            "sourceId": "krt_results",
            "encodings": {
                "x": {"field": "scenario_id", "type": "nominal", "label": "Hypothèse"},
                "y": {"field": "n_fits", "type": "quantitative", "label": "Nombre d’ajustements"},
                "color": {"field": "diagnostic_label", "type": "nominal", "label": "Diagnostic"},
                "tooltip": [
                    {"field": "scenario_id", "type": "nominal", "label": "Hypothèse"},
                    {"field": "n_fits", "type": "quantitative", "label": "Ajustements"},
                    {"field": "diagnostic_label", "type": "nominal", "label": "Statut"},
                ],
            },
            "layout": "full",
        },
        {
            "id": "trajectory_h0a_chart",
            "title": "Contraste KRT H0A par scrutin",
            "subtitle": "β1−β2 pour l’abstention parmi les inscrits; législatives et présidentielles séparées.",
            "type": "line",
            "dataset": "trajectory_h0a",
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
            "id": "trajectory_h1_chart",
            "title": "Contraste KRT H1 par scrutin",
            "subtitle": "β1−β2 pour le vote à gauche parmi les exprimés; échelle distincte de H0A.",
            "type": "line",
            "dataset": "trajectory_h1",
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
            "id": "nls_diagnostics_chart",
            "title": "Diagnostics NLS par hypothèse",
            "subtitle": "270 couples admissibles; les 17 réserves portent sur le rang, le conditionnement ou les frontières.",
            "type": "bar",
            "dataset": "nls_by_scenario",
            "sourceId": "nls_results",
            "encodings": {
                "x": {"field": "scenario_id", "type": "nominal", "label": "Hypothèse"},
                "y": {"field": "n_fits", "type": "quantitative", "label": "Nombre d’ajustements"},
                "color": {"field": "diagnostic_label", "type": "nominal", "label": "Diagnostic"},
            },
            "layout": "full",
        },
        {
            "id": "king_comparison_chart",
            "title": "Agrégats H0A — King Python et King R",
            "subtitle": "78 estimands sur les mêmes marges et communes, avec deux formulations probabilistes distinctes.",
            "type": "scatter",
            "dataset": "king_comparison",
            "sourceId": "king_r_comparison",
            "encodings": {
                "x": {"field": "mean_python_krt", "type": "quantitative", "label": "Python KRT", "format": "percent"},
                "y": {"field": "mean_r_ei", "type": "quantitative", "label": "R ei", "format": "percent"},
                "color": {"field": "estimand_display", "type": "nominal", "label": "Estimand"},
                "tooltip": [
                    {"field": "election_label", "type": "text", "label": "Scrutin"},
                    {"field": "absolute_difference", "type": "quantitative", "label": "Écart absolu", "format": "percent"},
                    {"field": "interval_overlap_label", "type": "nominal", "label": "Intervalles se chevauchent"},
                ],
            },
            "layout": "full",
        },
    ]

    tables_manifest = [
        {
            "id": "election_table",
            "title": "Diagnostics KRT et couverture NLS par scrutin",
            "subtitle": "Chaque ligne correspond à un scrutin sur les mêmes 2 000 communes.",
            "dataset": "election_status",
            "sourceId": "election_status_summary",
            "defaultSort": {"field": "year", "direction": "asc"},
            "density": "dense",
            "columns": [
                {"field": "election_id", "label": "Scrutin", "type": "text"},
                {"field": "year", "label": "Année", "format": "number"},
                {"field": "election_type", "label": "Type", "type": "text"},
                {"field": "nls_fits", "label": "NLS", "format": "number"},
                {"field": "nls_diagnostic_fail", "label": "NLS à revoir", "format": "number"},
                {"field": "mcmc_status_h0a", "label": "H0A MCMC", "type": "text"},
                {"field": "identification_status_h0a", "label": "H0A identification", "type": "text"},
                {"field": "mcmc_status_h1", "label": "H1 MCMC", "type": "text"},
                {"field": "identification_status_h1", "label": "H1 identification", "type": "text"},
            ],
        },
        {
            "id": "comparison_table",
            "title": "Plus grands écarts agrégés entre Python et R",
            "subtitle": "Contrôle H0A uniquement; classement par écart absolu.",
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
    ]

    h0a_pass = int(((krt_diag["scenario_id"] == "H0A") & (krt_diag["mcmc_status"] == "pass")).sum())
    h0a_caveat = 26 - h0a_pass
    h1_pass = int(((krt_diag["scenario_id"] == "H1") & (krt_diag["mcmc_status"] == "pass")).sum())
    h1_caveat = 26 - h1_pass
    nls_pass = int(nls_fits["diagnostic_status"].eq("pass").sum())
    nls_fail = int(nls_fits["diagnostic_status"].eq("fail").sum())

    blocks = [
        {"id": "title", "type": "markdown", "body": f"# {title}"},
        {
            "id": "technical_summary",
            "type": "markdown",
            "body": "## Résumé technique\n\nLe périmètre `longitudinal_2000_v1` est achevé : **26/26 KRT H0A**, **26/26 KRT H1** et **270/270 NLS admissibles** sont consolidés sur un panel invariant de **2 000 communes**. Le manifeste final est `ready=true`. Les résultats décrivent des associations écologiques communales et ne permettent pas d’inférer directement des comportements individuels.",
            "sourceId": "release_manifest",
        },
        {"id": "metrics", "type": "metric-strip", "cardIds": ["panel_card", "krt_card", "nls_card", "r_card"]},
        {
            "id": "panel_section",
            "type": "markdown",
            "body": f"## Un panel strictement invariant sur les 26 scrutins\n\nLes mêmes **2 000 `unit_id`** sont présents et admissibles dans chaque scrutin, soit **52 000 couples commune–élection**. Les contrôles de marges électorales, de non-négativité et de jointure passent. La porte d’équilibre reste sous les seuils annoncés : SMD absolu maximal **{validation['max_abs_smd']:.4f}** et écart catégoriel maximal **{validation['max_abs_category_gap']:.4f}**.",
            "sourceId": "panel_validation",
        },
        {
            "id": "model_definition",
            "type": "markdown",
            "body": "## Deux hypothèses KRT principales, deux dénominateurs différents\n\n**H0A** compare l’abstention des ouvriers et employés à celle des autres CSP parmi les inscrits. **H1** compare leur vote à gauche à celui des autres CSP parmi les suffrages exprimés. Les contrastes β1−β2 sont donc présentés dans deux graphiques distincts et leurs niveaux ne doivent pas être comparés directement.",
        },
        {
            "id": "krt_diag_text",
            "type": "markdown",
            "body": f"## Les 52 KRT sont calculés, avec des réserves diagnostiques explicites\n\nH0A compte **{h0a_pass} pass** et **{h0a_caveat} caveat** MCMC; H1 compte **{h1_pass} pass** et **{h1_caveat} caveat**. Aucun `fail` inexpliqué n’entre dans la release. Tous les runs utilisent 4 chaînes, 1 000 warmup, 1 000 draws, `target_accept=0,99`, `max_treedepth=14` et `king_lambda=0,5`.",
            "sourceId": "krt_results",
        },
        {"id": "krt_diag_chart_block", "type": "chart", "chartId": "krt_diagnostics_chart"},
        {
            "id": "h0a_interpretation",
            "type": "markdown",
            "body": "## H0A — trajectoire de l’abstention\n\nLa figure suit le contraste postérieur entre groupes sociaux au fil des scrutins. Les séries législatives et présidentielles sont séparées afin de ne pas relier artificiellement deux élections différentes tenues la même année. Les intervalles à 95 % sont disponibles dans les données et les infobulles.",
            "sourceId": "krt_results",
        },
        {"id": "h0a_chart_block", "type": "chart", "chartId": "trajectory_h0a_chart"},
        {
            "id": "h1_interpretation",
            "type": "markdown",
            "body": "## H1 — trajectoire du vote à gauche\n\nLa trajectoire H1 porte exclusivement sur les suffrages exprimés. Les 26 estimations sont disponibles, mais leur identification écologique est classée `caveat` dans les 26 cas : les distributions communales sont produites, tandis que toute conclusion individuelle doit rester prudente.",
            "sourceId": "krt_results",
        },
        {"id": "h1_chart_block", "type": "chart", "chartId": "trajectory_h1_chart"},
        {
            "id": "uncertainty_note",
            "type": "markdown",
            "body": "## Incertitude communale conservée de bout en bout\n\nLa table communale contient **104 000 lignes**, soit 2 hypothèses × 26 scrutins × 2 000 communes. Les huit champs exigés (`sd`, `q025`, `q50`, `q975` pour β1 et β2) sont complets. La table agrégée contient 156 lignes : β1, β2 et leur contraste pour chacun des 52 ajustements.",
            "sourceId": "krt_results",
        },
        {
            "id": "nls_text",
            "type": "markdown",
            "body": f"## Le NLS couvre toutes les spécifications admissibles\n\nLes **270/270** couples admissibles ont été exécutés avec 20 départs. **{nls_pass}** diagnostics sont `pass` et **{nls_fail}** sont `fail` au sens diagnostique, principalement pour le rang, le conditionnement ou les solutions en frontière. Ces lignes restent disponibles pour audit et ne sont pas présentées comme des résultats robustes sans réserve.",
            "sourceId": "nls_results",
        },
        {"id": "nls_chart_block", "type": "chart", "chartId": "nls_diagnostics_chart"},
        {
            "id": "r_text",
            "type": "markdown",
            "body": f"## Le contrôle King Python–R est favorable mais non identique\n\nLa comparaison R porte sur H0A, les mêmes 26 scrutins et les mêmes 2 000 communes. Les **78/78** intervalles agrégés se chevauchent; l’écart absolu médian vaut **{king_manifest['aggregate_median_absolute_difference']:.5f}** et le maximum **{king_manifest['aggregate_max_absolute_difference']:.5f}**. R utilise King 1997 avec normale bivariée tronquée; Python utilise KRT 1999 beta-binomial. Il s’agit donc d’une sensibilité inter-formulations, pas d’une identité de code.",
            "sourceId": "king_r_comparison",
        },
        {"id": "r_chart_block", "type": "chart", "chartId": "king_comparison_chart"},
        {"id": "comparison_table_block", "type": "table", "tableId": "comparison_table"},
        {
            "id": "limitations",
            "type": "markdown",
            "body": "## Limites et robustesse\n\n- Les résultats sont des inférences écologiques, non des transitions individuelles observées.\n- Les `caveat` d’identification signalent notamment des bornes de tomographie larges; H1 est concernée sur les 26 scrutins.\n- Le contrôle R King est disponible pour H0A seulement et repose sur une formulation différente.\n- H0B–H0C et H2–H7 sont disponibles en NLS, mais n’ont pas été estimées en KRT dans le périmètre v1.\n- Les NetCDF, RDS, caches et runs interrompus sont exclus du ZIP; les diagnostics et résumés consolidés sont conservés.",
        },
        {"id": "election_table_block", "type": "table", "tableId": "election_table"},
        {
            "id": "next_steps",
            "type": "markdown",
            "body": "## Étapes recommandées\n\n1. Utiliser cette archive comme rendu complet de `longitudinal_2000_v1`.\n2. Discuter avec le professeur de la lecture substantive des contrastes H0A et H1 ainsi que des réserves d’identification.\n3. Si nécessaire, ouvrir une extension `longitudinal_2000_v2` pour les 188 KRT supplémentaires H0B–H7, sans recalculer H0A/H1.\n4. Ajouter une réplication R de H1 uniquement si le contrôle inter-formulations est jugé prioritaire.",
        },
        {
            "id": "questions",
            "type": "markdown",
            "body": "## Questions pour la discussion\n\n- Les trajectoires principales doivent-elles privilégier la moyenne postérieure agrégée ou les distributions communales ?\n- Les 17 diagnostics NLS fragiles doivent-ils rester en annexe ou être exclus des graphiques ?\n- L’extension KRT doit-elle commencer par H2/H3, qui décomposent H1, ou par H4, qui ajoute un autre clivage social ?",
        },
    ]

    manifest = {
        "version": 1,
        "surface": "report",
        "title": title,
        "description": "Rapport technique auditable des estimations longitudinales sur 26 scrutins et 2 000 communes.",
        "generatedAt": generated,
        "cards": cards,
        "charts": charts,
        "tables": tables_manifest,
        "sources": sources,
        "blocks": blocks,
    }
    snapshot = {
        "version": 1,
        "generatedAt": generated,
        "status": "ready",
        "datasets": {
            "headline": _record_rows(headline),
            "krt_status": _record_rows(tables["krt_status"]),
            "trajectory_h0a": _record_rows(tables["trajectory_h0a"]),
            "trajectory_h1": _record_rows(tables["trajectory_h1"]),
            "nls_by_scenario": _record_rows(tables["nls_by_scenario"]),
            "king_comparison": _record_rows(tables["comparison"]),
            "comparison_top": _record_rows(tables["comparison_top"]),
            "election_status": _record_rows(tables["election_status"]),
        },
        "accessIssues": [],
    }
    return {
        "surface": "report",
        "manifest": manifest,
        "snapshot": snapshot,
        "sources": sources,
        "package_info": {"delivery": "portable_html", "release_status": "complete_h0a_h1"},
    }


def _copy_payload(tables: dict[str, pd.DataFrame]) -> None:
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
        "king_ei_progress.parquet",
        "nls_r_progress.parquet",
    ]
    for name in replication_files:
        _copy(REPLICATION_DIR / name, f"02_comparaison_python_r/{name}")

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
        "longitudinal_2000_v1.parquet",
        "longitudinal_2000_v1_manifest.json",
        "longitudinal_2000_v1_balance.parquet",
        "longitudinal_2000_v1_balance_by_election.parquet",
        "longitudinal_2000_v1_attempts.parquet",
    ]
    for name in panel_files:
        _copy(PANEL_DIR / name, f"03_panel_et_audit/{name}")

    panel = pd.read_parquet(PANEL_DIR / "longitudinal_2000_v1.parquet")
    primary = panel.loc[panel["included_primary_2000"].fillna(False)].sort_values("master_draw_order")
    primary.to_csv(
        PACKAGE_DIR / "03_panel_et_audit" / "panel_primaire_2000.csv",
        index=False,
        encoding="utf-8-sig",
    )

    for path in sorted(FIGURE_DIR.rglob("*")):
        if path.is_file():
            _copy(path, f"04_figures/{path.relative_to(FIGURE_DIR).as_posix()}")

    docs = [
        "RELEASE_README.md",
        "LONGITUDINAL_AUDIT.md",
        "BALANCE_TESTS.md",
        "OUTPUT_SCHEMA.md",
        "SCRIPT_GUIDE.md",
        "METHODOLOGY_CODE_MAP.md",
        "FIGURE_CATALOG.md",
    ]
    for name in docs:
        source = ROOT / "docs" / name
        if source.is_file():
            _copy(source, f"05_methodologie_et_code/docs/{name}")

    code_files = [
        "audit_longitudinal.py",
        "audit_panel_2000_integrity.py",
        "balance_checks.py",
        "build_longitudinal_panel.py",
        "data_io.py",
        "finalize_longitudinal.py",
        "paths.py",
        "postprocess_aggregates_v2.py",
        "prepare_inputs.py",
        "resume_krt_h1_with_timeout.py",
        "run_2x2_batch.py",
        "run_longitudinal_production.py",
        "run_nls_batch.py",
        "run_pipeline.py",
        "run_r_king_ei_replication.py",
        "run_r_nls_replication.py",
        "spec_registry.py",
        "utils.py",
    ]
    for name in code_files:
        _copy(ROOT / "code_longitudinal" / name, f"05_methodologie_et_code/code_longitudinal/{name}")
    _copy(ROOT / "config" / "run_settings.json", "05_methodologie_et_code/config/run_settings.json")
    for name in ["run_king_ei_replication.R", "run_nls_replication.R"]:
        source = ROOT / "r_replication" / name
        if source.is_file():
            _copy(source, f"05_methodologie_et_code/r_replication/{name}")

    selected_runs = pd.concat(
        [
            tables["krt_diagnostics"][["run_id", "election_id", "scenario_id"]].assign(model="krt"),
            tables["nls_fits"][["run_id", "election_id", "scenario_id"]].assign(model="nls"),
        ],
        ignore_index=True,
    ).drop_duplicates("run_id")
    selected_runs.to_csv(
        PACKAGE_DIR / "06_diagnostics_runs" / "index_runs_livres.csv",
        index=False,
        encoding="utf-8-sig",
    )
    for item in selected_runs.itertuples(index=False):
        source_dir = RUNS_DIR / str(item.run_id)
        target_prefix = f"06_diagnostics_runs/{item.model}/{item.run_id}"
        names = ["manifest.json", "model_diagnostics.csv", "longitudinal_estimates.csv"]
        if item.model == "krt":
            names.extend(
                [
                    "aggregate_comparison_v2.csv",
                    "identification_diagnostics.csv",
                    "identification_diagnostics.json",
                    "mcmc_diagnostics_v2.json",
                    "mcmc_block_metrics_v2.csv",
                    "mcmc_variable_metrics_v2.csv",
                    "resource_ladder_gate.csv",
                ]
            )
        else:
            names.extend(["nls_coefficients.csv", "nls_start_diagnostics.csv"])
        for name in names:
            source = source_dir / name
            if source.is_file():
                if name == "manifest.json":
                    payload = json.loads(source.read_text(encoding="utf-8"))
                    _write_json(
                        PACKAGE_DIR / target_prefix / name,
                        _portable_manifest_value(payload),
                    )
                else:
                    _copy(source, f"{target_prefix}/{name}")


def _validate(tables: dict[str, pd.DataFrame]) -> dict:
    panel_validation = json.loads((AUDIT_DIR / "panel_exact_validation.json").read_text(encoding="utf-8"))
    final_manifest = json.loads((FINAL_DIR / "release_manifest.json").read_text(encoding="utf-8"))
    krt_commune = pd.read_parquet(FINAL_DIR / "longitudinal_krt_commune.parquet")
    krt_aggregate = tables["krt_aggregate"]
    nls = tables["nls"]
    uncertainty = [
        "b1_sd",
        "b1_q025",
        "b1_q50",
        "b1_q975",
        "b2_sd",
        "b2_q025",
        "b2_q50",
        "b2_q975",
    ]
    fit_statuses = tables["krt_diagnostics"]["mcmc_status"].value_counts().to_dict()
    checks = {
        "schema_version": "professor_package_validation_v2",
        "as_of_date": "2026-08-16",
        "ready": False,
        "panel_id": panel_validation["panel_id"],
        "panel_sha256": panel_validation["panel_sha256"],
        "panel_primary_rows": panel_validation["primary_panel_rows"],
        "panel_primary_unique_unit_id": panel_validation["primary_unique_unit_id"],
        "elections": panel_validation["elections"],
        "same_codes_all_elections": panel_validation["exact_same_code_set_all_elections"],
        "margin_and_admissibility_checks_pass": panel_validation[
            "all_margin_join_and_admissibility_checks_pass"
        ],
        "max_abs_smd": panel_validation["max_abs_smd_all_elections"],
        "max_abs_category_gap": panel_validation["max_abs_category_gap_all_elections"],
        "registered_pairs": int(len(tables["run_plan"])),
        "nls_pairs": int(nls[["election_id", "scenario_id"]].drop_duplicates().shape[0]),
        "krt_pairs": int(krt_aggregate[["election_id", "scenario_id"]].drop_duplicates().shape[0]),
        "krt_pairs_by_scenario": krt_aggregate.groupby("scenario_id")["election_id"].nunique().to_dict(),
        "krt_commune_rows": int(len(krt_commune)),
        "krt_communes_per_pair_min": int(
            krt_commune.groupby(["election_id", "scenario_id"])["unit_id"].nunique().min()
        ),
        "krt_communes_per_pair_max": int(
            krt_commune.groupby(["election_id", "scenario_id"])["unit_id"].nunique().max()
        ),
        "krt_commune_unique_key": bool(
            ~krt_commune.duplicated(["panel_id", "election_id", "scenario_id", "unit_id"]).any()
        ),
        "uncertainty_fields_present": bool(set(uncertainty).issubset(krt_commune.columns)),
        "uncertainty_fields_complete": bool(krt_commune[uncertainty].notna().all().all()),
        "krt_aggregate_rows": int(len(krt_aggregate)),
        "krt_aggregate_unique_key": bool(
            ~krt_aggregate.duplicated(["panel_id", "election_id", "scenario_id", "estimand"]).any()
        ),
        "krt_mcmc_status_counts": fit_statuses,
        "krt_unexplained_failures": int(tables["krt_diagnostics"]["mcmc_status"].eq("fail").sum()),
        "finalizer_ready": bool(final_manifest["validation"]["ready"]),
        "contains_netcdf_or_rds": False,
    }
    required = [
        checks["panel_primary_rows"] == 2000,
        checks["panel_primary_unique_unit_id"] == 2000,
        checks["elections"] == 26,
        checks["same_codes_all_elections"],
        checks["margin_and_admissibility_checks_pass"],
        checks["registered_pairs"] == 292,
        checks["nls_pairs"] == 270,
        checks["krt_pairs"] == 52,
        checks["krt_pairs_by_scenario"] == {"H0A": 26, "H1": 26},
        checks["krt_commune_rows"] == 104000,
        checks["krt_communes_per_pair_min"] == 2000,
        checks["krt_communes_per_pair_max"] == 2000,
        checks["krt_commune_unique_key"],
        checks["uncertainty_fields_present"],
        checks["uncertainty_fields_complete"],
        checks["krt_aggregate_rows"] == 156,
        checks["krt_aggregate_unique_key"],
        checks["krt_unexplained_failures"] == 0,
        checks["finalizer_ready"],
    ]
    checks["ready"] = bool(all(required))
    if not checks["ready"]:
        raise RuntimeError("Professor package validation failed")
    return checks


def _write_supporting_docs(tables: dict[str, pd.DataFrame], validation: dict) -> None:
    readme = """# Livraison `longitudinal_2000_v1` — H0A et H1

Commencer par ouvrir **`RAPPORT_TECHNIQUE_LONGITUDINAL_2000_H0A_H1.html`**.

Cette archive contient l'état complet du périmètre v1 au 16 août 2026 : panel fixe de 2 000 communes, audit des 26 scrutins, NLS sur les 270 couples admissibles, KRT Python H0A et H1 sur les 26 scrutins, figures, diagnostics de runs et comparaison King Python–R H0A.

Les quatre Parquet destinés au professeur sont dans `01_resultats_python/`. Les traces NetCDF, objets RDS, caches et runs interrompus sont exclus. Le fichier `package_manifest.json` donne la taille et le SHA-256 de chaque fichier livré.
"""
    (PACKAGE_DIR / "README.md").write_text(readme, encoding="utf-8")

    comparison_note = """# Comparaison avec le rendu du 11 août 2026

Le rendu précédent était un point intermédiaire H0A. Le présent paquet le remplace pour le périmètre `longitudinal_2000_v1` : H1 est désormais terminé sur les 26 scrutins, les tables KRT passent de 52 000 à 104 000 lignes communales et le manifeste final est `ready=true`.

Le tableau `02_syntheses/comparaison_rendu_20260811_20260816.csv` fournit le détail exact des changements. L'ancien ZIP n'est pas imbriqué dans la nouvelle archive afin d'éviter la duplication; son existence et son statut restent documentés.
"""
    (PACKAGE_DIR / "COMPARAISON_AVEC_RENDU_PRECEDENT.md").write_text(
        comparison_note, encoding="utf-8"
    )

    mail = """# Projet de mail au professeur

**Objet : Avancement — estimations longitudinales sur un panel fixe de 2 000 communes**

Bonjour Professeur,

Je vous transmets une nouvelle livraison du travail longitudinal réalisé à partir des données Cagé–Piketty.

Depuis le précédent rendu, j'ai achevé les estimations KRT des hypothèses H0A et H1 sur les 26 scrutins, en conservant exactement le même panel de 2 000 communes et les mêmes codes harmonisés à chaque date. Cela représente 52 ajustements KRT complets. Les résultats communaux conservent les moyennes, écarts-types, médianes et intervalles à 95 % pour les deux paramètres.

Le NLS couvre parallèlement les 270 couples admissibles du registre. Le paquet comprend également les audits de présence et de marges, les contrôles d'équilibre du panel, les diagnostics MCMC et d'identification, les trajectoires H0A/H1, l'audit de densité 2022 et la comparaison King Python–R disponible pour H0A.

Le manifeste de consolidation est désormais validé (`ready=true`). Les fichiers de chaînes NetCDF ne sont pas inclus dans la livraison; seuls les résultats consolidés et les diagnostics nécessaires à l'audit sont fournis.

Les principales réserves concernent l'interprétation écologique — qui ne permet pas de conclure directement sur les comportements individuels — et des diagnostics d'identification parfois larges, en particulier pour H1. Ces limites sont détaillées dans le rapport technique joint.

Bien cordialement,
Pierre
"""
    (PACKAGE_DIR / "MAIL_RECAPITULATIF_PROFESSEUR.md").write_text(mail, encoding="utf-8")

    validation_report = f"""# Rapport de validation

## Évaluation globale : prêt à partager avec réserves méthodologiques

Le périmètre annoncé est complet et reproductible : 26 élections, 2 000 communes identiques, 52 KRT H0A/H1 et 270 couples NLS admissibles. Les clés finales sont uniques, les huit champs d'incertitude communale sont complets et aucun `fail` KRT inexpliqué n'entre dans la livraison.

## Contrôles vérifiés

- Panel primaire : {validation['panel_primary_rows']} lignes et {validation['panel_primary_unique_unit_id']} `unit_id` uniques.
- Ensemble exact de codes communs aux 26 élections : {validation['same_codes_all_elections']}.
- Contrôles de marges et d'admissibilité : {validation['margin_and_admissibility_checks_pass']}.
- KRT : {validation['krt_pairs']} couples et {validation['krt_commune_rows']} lignes communales.
- Communes par ajustement KRT : {validation['krt_communes_per_pair_min']} à {validation['krt_communes_per_pair_max']}.
- Champs d'incertitude complets : {validation['uncertainty_fields_complete']}.
- NLS : {validation['nls_pairs']} couples admissibles.
- Manifeste final : `ready={validation['finalizer_ready']}`.

## Réserves obligatoires

- L'inférence est écologique et ne prouve pas des comportements individuels.
- Les statuts d'identification `caveat`, notamment pour H1, doivent rester visibles.
- Le contrôle King R H0A n'est pas mathématiquement identique au KRT Python.
- Les hypothèses H0B–H7 ne sont pas estimées en KRT dans cette version.
"""
    (PACKAGE_DIR / "RAPPORT_VALIDATION.md").write_text(validation_report, encoding="utf-8")

    chart_map = """# Carte des visualisations

| Segment | Question | Forme | Données | Lecture |
|---|---|---|---|---|
| Diagnostics KRT | Combien de pass/caveat par hypothèse ? | Barres groupées | 52 fits | Statuts H0A/H1, sans masquer les réserves |
| Trajectoire H0A | Comment évolue le contraste d'abstention ? | Courbes par type de scrutin | 26 scrutins | H0A seulement, zéro comme référence |
| Trajectoire H1 | Comment évolue le contraste de vote à gauche ? | Courbes par type de scrutin | 26 scrutins | H1 seulement, échelle distincte de H0A |
| Diagnostics NLS | Où se situent les diagnostics fragiles ? | Barres empilées | 270 fits | Pass/fail par hypothèse |
| Python–R | Les agrégats H0A sont-ils proches ? | Nuage de points | 78 estimands | Sensibilité inter-formulations, pas identité |
"""
    notes_dir = PACKAGE_DIR / "02_syntheses"
    (notes_dir / "CARTE_VISUALISATIONS.md").write_text(chart_map, encoding="utf-8")


def prepare() -> None:
    if PACKAGE_DIR.exists():
        raise FileExistsError(f"Package directory already exists: {PACKAGE_DIR}")
    PACKAGE_DIR.mkdir(parents=True)
    (PACKAGE_DIR / "02_syntheses").mkdir(parents=True)
    (PACKAGE_DIR / "06_diagnostics_runs").mkdir(parents=True)

    tables = _build_tables()
    validation = _validate(tables)
    _copy_payload(tables)

    table_targets = {
        "model_coverage": "avancement_pipeline.csv",
        "election_status": "etat_modeles_par_election.csv",
        "trajectory": "trajectoires_krt_h0a_h1.csv",
        "krt_diagnostics": "diagnostics_krt_h0a_h1_par_election.csv",
        "krt_status": "diagnostics_krt_resume.csv",
        "nls_by_scenario": "nls_diagnostics_par_hypothese.csv",
        "comparison": "comparaison_king_python_r_agregee_h0a.csv",
        "commune_comparison": "comparaison_king_python_r_communale_resume_h0a.csv",
        "hypotheses": "definitions_hypotheses.csv",
        "previous_current": "comparaison_rendu_20260811_20260816.csv",
    }
    for key, name in table_targets.items():
        tables[key].to_csv(
            PACKAGE_DIR / "02_syntheses" / name,
            index=False,
            encoding="utf-8-sig",
        )

    _write_json(PACKAGE_DIR / "validation_report.json", validation)
    _write_supporting_docs(tables, validation)
    _write_json(PACKAGE_DIR / "artifact.json", _build_artifact(tables, validation))
    print(PACKAGE_DIR)


def finalize() -> None:
    report_path = PACKAGE_DIR / "RAPPORT_TECHNIQUE_LONGITUDINAL_2000_H0A_H1.html"
    if not report_path.is_file():
        raise FileNotFoundError(report_path)
    forbidden = [
        path
        for path in PACKAGE_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() in {".nc", ".rds"}
    ]
    if forbidden:
        raise RuntimeError(f"Forbidden chain files in package: {forbidden}")

    files = sorted(
        (
            path
            for path in PACKAGE_DIR.rglob("*")
            if path.is_file() and path.name != "package_manifest.json"
        ),
        key=lambda path: path.relative_to(PACKAGE_DIR).as_posix(),
    )
    manifest = {
        "schema_version": "professor_complete_package_v1",
        "package_name": PACKAGE_NAME,
        "release_status": "complete_h0a_h1",
        "h0a_included": True,
        "h1_included": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "file_count_excluding_manifest": len(files),
        "files": [
            {
                "path": path.relative_to(PACKAGE_DIR).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in files
        ],
        "exclusions": [
            "NetCDF traces",
            "RDS fits",
            "incomplete Stan chains",
            "cache directories",
            "failed or interrupted runs",
            "previous ZIP binary (superseded and documented instead)",
        ],
    }
    _write_json(PACKAGE_DIR / "package_manifest.json", manifest)

    zip_files = sorted(
        (path for path in PACKAGE_DIR.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(PACKAGE_DIR.parent).as_posix(),
    )
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in zip_files:
            arcname = path.relative_to(PACKAGE_DIR.parent).as_posix()
            info = zipfile.ZipInfo(arcname, date_time=(2026, 8, 16, 12, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(
                info,
                path.read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )

    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        corrupt = archive.testzip()
        if corrupt is not None:
            raise RuntimeError(f"ZIP CRC failure: {corrupt}")
        members = archive.namelist()
        forbidden_members = [name for name in members if Path(name).suffix.lower() in {".nc", ".rds"}]
        if forbidden_members:
            raise RuntimeError(f"Forbidden members found in ZIP: {forbidden_members}")

    sidecar = ZIP_PATH.with_suffix(ZIP_PATH.suffix + ".sha256")
    sidecar.write_text(f"{_sha256(ZIP_PATH)}  {ZIP_PATH.name}\n", encoding="ascii")
    receipt = {
        "zip_path": ZIP_PATH.relative_to(ROOT).as_posix(),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": _sha256(ZIP_PATH),
        "zip_members": len(members),
        "zip_crc_check": "passed",
        "contains_netcdf_or_rds": False,
        "report_path": report_path.relative_to(ROOT).as_posix(),
        "report_sha256": _sha256(report_path),
    }
    _write_json(ZIP_PATH.with_suffix(ZIP_PATH.suffix + ".receipt.json"), receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the complete longitudinal 2000 H0A/H1 package")
    parser.add_argument("mode", choices=("prepare", "finalize"))
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare()
    else:
        finalize()


if __name__ == "__main__":
    main()
