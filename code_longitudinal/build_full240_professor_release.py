from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .paths import OUTPUT_DIR, ROOT
from .spec_registry import SCENARIOS, SPEC_VERSION
from .utils import file_sha256
from reproducibility.replication_scope import get_scope


RELEASE_BASENAME = "longitudinal_2000_v1_full_240_professeur"
CANDIDATE = ROOT / "work" / f"{RELEASE_BASENAME}_candidate"
DELIVERABLES = ROOT / "deliverables"
ZIP_PATH = DELIVERABLES / f"{RELEASE_BASENAME}.zip"
PPTX_PATH = CANDIDATE / "04_PRESENTATION" / "PRESENTATION_RESULTATS_240.pptx"
PRESENTATION_QA_PATH = CANDIDATE / "04_PRESENTATION" / "PRESENTATION_QA.json"

PRODUCTION = OUTPUT_DIR / SPEC_VERSION / "production"
PYTHON_DIR = PRODUCTION / "all_2x2_candidate"
R_DIR = OUTPUT_DIR / SPEC_VERSION / "r_replication"
NLS_DIR = PRODUCTION / "rxc_nls_panel_extension_v11"

PYTHON_AGGREGATE = PYTHON_DIR / "longitudinal_krt_aggregate_240_candidate.parquet"
PYTHON_COMMUNE = PYTHON_DIR / "longitudinal_krt_commune_240_candidate.parquet"
PYTHON_SELECTION = PYTHON_DIR / "krt_240_candidate_selection.csv"
PYTHON_MANIFEST = PYTHON_DIR / "krt_240_candidate_manifest.json"
R_AGGREGATE = R_DIR / "longitudinal_king_ei_r_aggregate_all_2x2.parquet"
R_COMMUNE = R_DIR / "longitudinal_king_ei_r_commune_all_2x2.parquet"
R_AUDIT = R_DIR / "king_ei_all_2x2_run_audit.csv"
R_MANIFEST = R_DIR / "king_ei_all_2x2_consolidation_manifest.json"
COMPARISON_AGGREGATE = R_DIR / "king_python_r_full_240_aggregate_comparison.parquet"
COMPARISON_COMMUNE = R_DIR / "king_python_r_full_240_commune_summary.parquet"
COMPARISON_MANIFEST = R_DIR / "king_python_r_full_240_comparison_manifest.json"
NLS_RESULTS = NLS_DIR / "longitudinal_nls_292_candidate.parquet"
PANEL = ROOT / "panel" / "longitudinal_2000_v1.parquet"
COVERAGE_JSON = PRODUCTION / "current_estimation_coverage.json"
COVERAGE_CSV = PRODUCTION / "current_estimation_coverage.csv"

EXPECTED_PAIRS = get_scope().pair_count
EXPECTED_AGGREGATE_ROWS = EXPECTED_PAIRS * 3
EXPECTED_COMMUNE_ROWS = EXPECTED_PAIRS * 2000
MODEL_LABELS = {
    "krt_beta_binomial": "Python NumPyro — KRT bêta-binomial",
    "king_ei_1997_r": "R ei/eiPack — King normale tronquée",
    "rosen_nls": "NLS déterministe",
}
PALETTE = {
    "krt_beta_binomial": "#2457A7",
    "king_ei_1997_r": "#D97706",
    "accent": "#B78B20",
    "ink": "#20242A",
    "grid": "#D8DDE5",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _safe_reset_candidate() -> None:
    resolved = CANDIDATE.resolve()
    expected_parent = (ROOT / "work").resolve()
    if resolved.parent != expected_parent or not resolved.name.endswith("_candidate"):
        raise ValueError(f"refusing to reset unexpected path: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True)


def _copy(source: Path, relative_target: str) -> Path:
    if not source.is_file():
        raise FileNotFoundError(source)
    target = CANDIDATE / relative_target
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def _pair_count(frame: pd.DataFrame) -> int:
    return int(frame[["election_id", "scenario_id"]].drop_duplicates().shape[0])


def _validate_source_tables() -> dict[str, object]:
    required = (
        PYTHON_AGGREGATE,
        PYTHON_COMMUNE,
        PYTHON_SELECTION,
        PYTHON_MANIFEST,
        R_AGGREGATE,
        R_COMMUNE,
        R_AUDIT,
        R_MANIFEST,
        COMPARISON_AGGREGATE,
        COMPARISON_COMMUNE,
        COMPARISON_MANIFEST,
        NLS_RESULTS,
        PANEL,
        COVERAGE_JSON,
        COVERAGE_CSV,
    )
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing final-release inputs: {missing}")

    python_aggregate = pd.read_parquet(PYTHON_AGGREGATE)
    python_commune = pd.read_parquet(PYTHON_COMMUNE)
    r_aggregate = pd.read_parquet(R_AGGREGATE)
    r_commune = pd.read_parquet(R_COMMUNE)
    comparison = pd.read_parquet(COMPARISON_AGGREGATE)
    selection = pd.read_csv(PYTHON_SELECTION)
    r_audit = pd.read_csv(R_AUDIT)
    scope = get_scope()
    for label, frame in (("KRT aggregate", python_aggregate), ("KRT commune", python_commune),
                         ("R aggregate", r_aggregate), ("R commune", r_commune),
                         ("comparison", comparison), ("selection", selection), ("R audit", r_audit)):
        if set(map(tuple, frame[["election_id", "scenario_id"]].astype(str).values)) != scope.pairs:
            raise AssertionError(f"{label}: pairs differ from the selected replication scope")
    nls = pd.read_parquet(NLS_RESULTS)
    if set(map(tuple, nls[["election_id", "scenario_id"]].astype(str).values)) != scope.nls_pairs:
        raise AssertionError("NLS pairs differ from the selected replication scope")

    checks = {
        "python_pairs_240": _pair_count(python_aggregate) == EXPECTED_PAIRS,
        "python_aggregate_rows_720": len(python_aggregate) == EXPECTED_AGGREGATE_ROWS,
        "python_commune_rows_480000": len(python_commune) == EXPECTED_COMMUNE_ROWS,
        "python_communes_2000_per_pair": bool(
            python_commune.groupby(["election_id", "scenario_id"])["unit_id"].nunique().eq(2000).all()
        ),
        "python_selection_240": len(selection) == EXPECTED_PAIRS,
        "r_pairs_240": _pair_count(r_aggregate) == EXPECTED_PAIRS,
        "r_aggregate_rows_720": len(r_aggregate) == EXPECTED_AGGREGATE_ROWS,
        "r_commune_rows_480000": len(r_commune) == EXPECTED_COMMUNE_ROWS,
        "r_communes_2000_per_pair": bool(
            r_commune.groupby(["election_id", "scenario_id"])["unit_id"].nunique().eq(2000).all()
        ),
        "r_audit_240": len(r_audit) == EXPECTED_PAIRS,
        "python_r_comparison_pairs_240": _pair_count(comparison) == EXPECTED_PAIRS,
        "python_r_comparison_rows_720": len(comparison) == EXPECTED_AGGREGATE_ROWS,
        "no_duplicate_python_aggregate_key": not python_aggregate[
            ["election_id", "scenario_id", "estimand"]
        ].duplicated().any(),
        "no_duplicate_r_aggregate_key": not r_aggregate[
            ["election_id", "scenario_id", "estimand"]
        ].duplicated().any(),
    }
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise AssertionError(f"full-240 release checks failed: {failed}")
    return {
        "schema_version": "full_240_release_input_validation_v1",
        "created_at_utc": _utc_now(),
        "status": "pass",
        "checks": checks,
        "replication_scope": scope.as_dict(),
        "input_sha256": {str(path.relative_to(ROOT)).replace("\\", "/"): file_sha256(path) for path in required},
    }


def _normalize_results() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    python = pd.read_parquet(PYTHON_AGGREGATE)
    r_ei = pd.read_parquet(R_AGGREGATE)
    nls = pd.read_parquet(NLS_RESULTS)

    python_base = pd.DataFrame(
        {
            "panel_id": python["panel_id"],
            "engine": "Python_NumPyro",
            "model_key": "krt_beta_binomial",
            "model_label": MODEL_LABELS["krt_beta_binomial"],
            "election_id": python["election_id"],
            "year": python["year"].astype(int),
            "round": python["round"].astype(int),
            "election_family": np.where(python["election_id"].str.startswith("leg_"), "legislative", "presidential"),
            "scenario_id": python["scenario_id"],
            "estimand": python["estimand"],
            "estimate": python["mean"],
            "sd": np.nan,
            "q025": python["q025"],
            "q50": python["median"],
            "q975": python["q975"],
            "n_draws": python["n_posterior_draws"],
            "n_communes": python["n_communes"],
            "run_id": python["run_id"],
            "diagnostic_status": python["mcmc_status"],
            "identification_status": python["identification_status"],
            "source_table": str(PYTHON_AGGREGATE.relative_to(ROOT)).replace("\\", "/"),
        }
    )

    election_metadata = python[["election_id", "year", "round"]].drop_duplicates()
    r_ei = r_ei.merge(election_metadata, on="election_id", how="left", validate="many_to_one")
    r_estimand = {
        "beta1_aggregate": "b_1",
        "beta2_aggregate": "b_2",
        "contrast_aggregate": "b_1_minus_b_2",
    }
    r_base = pd.DataFrame(
        {
            "panel_id": r_ei["panel_id"],
            "engine": "R_ei_eiPack",
            "model_key": "king_ei_1997_r",
            "model_label": MODEL_LABELS["king_ei_1997_r"],
            "election_id": r_ei["election_id"],
            "year": r_ei["year"].astype(int),
            "round": r_ei["round"].astype(int),
            "election_family": np.where(r_ei["election_id"].str.startswith("leg_"), "legislative", "presidential"),
            "scenario_id": r_ei["scenario_id"],
            "estimand": r_ei["estimand"].map(r_estimand),
            "estimate": r_ei["mean"],
            "sd": r_ei["sd"],
            "q025": r_ei["q025"],
            "q50": r_ei["q50"],
            "q975": r_ei["q975"],
            "n_draws": r_ei["n_posterior_draws"],
            "n_communes": 2000,
            "run_id": "",
            "diagnostic_status": "native_ei_importance_resampling",
            "identification_status": "not_directly_comparable_to_krt_diagnostic",
            "source_table": str(R_AGGREGATE.relative_to(ROOT)).replace("\\", "/"),
        }
    )
    base = pd.concat([python_base, r_base], ignore_index=True).sort_values(
        ["election_family", "year", "round", "scenario_id", "model_key", "estimand"]
    )

    comparison = pd.read_parquet(COMPARISON_AGGREGATE).sort_values(
        ["scenario_id", "year", "round", "estimand"]
    )
    coverage = python[
        [
            "panel_id",
            "election_id",
            "year",
            "round",
            "scenario_id",
            "run_id",
            "mcmc_status",
            "identification_status",
            "selection_status",
        ]
    ].drop_duplicates()
    r_pairs = r_ei[["election_id", "scenario_id"]].drop_duplicates().assign(r_ei_status="success")
    coverage = coverage.merge(r_pairs, on=["election_id", "scenario_id"], how="left", validate="one_to_one")
    coverage["python_status"] = "success"
    coverage["complete_python_and_r"] = coverage["r_ei_status"].eq("success")
    coverage["election_family"] = np.where(
        coverage["election_id"].str.startswith("leg_"), "legislative", "presidential"
    )

    nls = nls.copy()
    nls["election_family"] = np.where(nls["election_id"].str.startswith("leg_"), "legislative", "presidential")
    nls["model_label"] = MODEL_LABELS["rosen_nls"]
    return base.reset_index(drop=True), comparison.reset_index(drop=True), coverage.reset_index(drop=True), nls


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
            "font.size": 10,
            "axes.titleweight": "bold",
        }
    )


def _save_figure(fig: plt.Figure, base: Path) -> list[Path]:
    base.parent.mkdir(parents=True, exist_ok=True)
    png = base.with_suffix(".png")
    svg = base.with_suffix(".svg")
    fig.savefig(png, dpi=220, bbox_inches="tight", facecolor="white")
    fig.savefig(svg, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return [png, svg]


def _build_figures(base: pd.DataFrame, comparison: pd.DataFrame, coverage: pd.DataFrame) -> pd.DataFrame:
    _configure_plotting()
    figure_root = CANDIDATE / "03_FIGURES"
    records: list[dict[str, object]] = []
    contrast = base.loc[base["estimand"].eq("b_1_minus_b_2")].copy()
    for scenario_id in sorted(contrast["scenario_id"].unique()):
        for family in ("legislative", "presidential"):
            part = contrast.loc[
                contrast["scenario_id"].eq(scenario_id) & contrast["election_family"].eq(family)
            ]
            if part["year"].nunique() < 4:
                continue
            fig, ax = plt.subplots(figsize=(10.5, 5.6))
            for model_key in ("krt_beta_binomial", "king_ei_1997_r"):
                model = part.loc[part["model_key"].eq(model_key)].sort_values(["year", "round"])
                ax.plot(
                    model["year"],
                    model["estimate"],
                    marker="o" if model_key == "krt_beta_binomial" else "s",
                    linewidth=2.1,
                    markersize=5.5,
                    color=PALETTE[model_key],
                    label=MODEL_LABELS[model_key],
                )
            ax.axhline(0, color=PALETTE["ink"], linewidth=1.0, alpha=0.7)
            ax.grid(axis="y", color=PALETTE["grid"], linewidth=0.8)
            ax.set_title(f"Contraste agrégé {scenario_id} — {family}s")
            ax.set_xlabel("Année électorale")
            ax.set_ylabel("β₁ − β₂")
            ax.legend(frameon=False, loc="best")
            fig.tight_layout()
            relative_base = Path("interannuelles") / family / f"contraste_{scenario_id}_{family}"
            paths = _save_figure(fig, figure_root / relative_base)
            records.append(
                {
                    "figure_id": f"contrast_{scenario_id}_{family}",
                    "question": f"Comment le contraste {scenario_id} varie-t-il entre les années de {family}s ?",
                    "chart_family": "trend",
                    "chart_type": "highlighted multi-series line",
                    "source_table": "02_BASE_TRANSPARENTE/base_resultats_long.parquet",
                    "takeaway_scope": "description interannuelle; aucune causalité",
                    "png": paths[0].relative_to(CANDIDATE).as_posix(),
                    "svg": paths[1].relative_to(CANDIDATE).as_posix(),
                }
            )

    agreement = comparison.loc[comparison["estimand"].eq("b_1_minus_b_2")].copy()
    fig, ax = plt.subplots(figsize=(7.2, 7.0))
    ax.scatter(
        agreement["mean_python_krt"],
        agreement["mean_r_ei"],
        s=28,
        alpha=0.72,
        color=PALETTE["krt_beta_binomial"],
        edgecolor="white",
        linewidth=0.35,
    )
    low = float(min(agreement["mean_python_krt"].min(), agreement["mean_r_ei"].min()))
    high = float(max(agreement["mean_python_krt"].max(), agreement["mean_r_ei"].max()))
    pad = max((high - low) * 0.06, 0.02)
    ax.plot([low - pad, high + pad], [low - pad, high + pad], color=PALETTE["ink"], linestyle="--")
    ax.set_xlim(low - pad, high + pad)
    ax.set_ylim(low - pad, high + pad)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(color=PALETTE["grid"], linewidth=0.8)
    ax.set_title("Contrastes agrégés : Python KRT et R ei")
    ax.set_xlabel("Python NumPyro — KRT bêta-binomial")
    ax.set_ylabel("R ei/eiPack — normale tronquée")
    fig.tight_layout()
    paths = _save_figure(fig, figure_root / "comparaison_modeles" / "accord_contrastes_python_r")
    records.append(
        {
            "figure_id": "agreement_contrasts_python_r",
            "question": "Les deux formulations d'inférence écologique donnent-elles des contrastes proches ?",
            "chart_family": "relationship",
            "chart_type": "scatter with identity reference",
            "source_table": "01_DONNEES_CANONIQUES/03_COMPARAISON_PYTHON_R/python_r_aggregate.parquet",
            "takeaway_scope": "sensibilité inter-modèle; formulations non identiques",
            "png": paths[0].relative_to(CANDIDATE).as_posix(),
            "svg": paths[1].relative_to(CANDIDATE).as_posix(),
        }
    )

    scenario_gap = (
        agreement.groupby("scenario_id", as_index=False)["absolute_difference"].median()
        .sort_values("absolute_difference")
    )
    fig, ax = plt.subplots(figsize=(9.2, 5.8))
    ax.barh(scenario_gap["scenario_id"], scenario_gap["absolute_difference"], color=PALETTE["accent"])
    ax.grid(axis="x", color=PALETTE["grid"], linewidth=0.8)
    ax.set_title("Écart médian absolu entre Python KRT et R ei")
    ax.set_xlabel("|contraste R − contraste Python|")
    ax.set_ylabel("Hypothèse")
    fig.tight_layout()
    paths = _save_figure(fig, figure_root / "comparaison_modeles" / "ecart_median_par_hypothese")
    records.append(
        {
            "figure_id": "median_model_gap_by_scenario",
            "question": "Quelles hypothèses sont les plus sensibles au choix du modèle ?",
            "chart_family": "comparison",
            "chart_type": "ranked horizontal bar",
            "source_table": "01_DONNEES_CANONIQUES/03_COMPARAISON_PYTHON_R/python_r_aggregate.parquet",
            "takeaway_scope": "médiane sur les scrutins admissibles",
            "png": paths[0].relative_to(CANDIDATE).as_posix(),
            "svg": paths[1].relative_to(CANDIDATE).as_posix(),
        }
    )

    diagnostic = coverage["mcmc_status"].value_counts().rename_axis("status").reset_index(name="pairs")
    fig, ax = plt.subplots(figsize=(7.8, 4.8))
    ax.bar(diagnostic["status"], diagnostic["pairs"], color=PALETTE["krt_beta_binomial"])
    ax.grid(axis="y", color=PALETTE["grid"], linewidth=0.8)
    ax.set_title(f"Diagnostics MCMC des {EXPECTED_PAIRS} ajustements Python")
    ax.set_xlabel("Statut")
    ax.set_ylabel("Nombre de couples")
    for index, value in enumerate(diagnostic["pairs"]):
        ax.text(index, value, str(int(value)), ha="center", va="bottom")
    fig.tight_layout()
    paths = _save_figure(fig, figure_root / "diagnostics" / "statuts_mcmc_240")
    records.append(
        {
            "figure_id": "mcmc_status_240",
            "question": f"Quelle est la qualité numérique des {EXPECTED_PAIRS} ajustements Python ?",
            "chart_family": "comparison",
            "chart_type": "categorical bar",
            "source_table": "02_BASE_TRANSPARENTE/couverture_240.parquet",
            "takeaway_scope": "statut numérique distinct de l'identification écologique",
            "png": paths[0].relative_to(CANDIDATE).as_posix(),
            "svg": paths[1].relative_to(CANDIDATE).as_posix(),
        }
    )
    return pd.DataFrame(records)


def _write_documents(
    base: pd.DataFrame,
    comparison: pd.DataFrame,
    coverage: pd.DataFrame,
    figure_catalog: pd.DataFrame,
    validation: dict[str, object],
) -> None:
    counts = coverage["mcmc_status"].value_counts().to_dict()
    contrasts = comparison.loc[comparison["estimand"].eq("b_1_minus_b_2")]
    gap_by_scenario = contrasts.groupby("scenario_id")["absolute_difference"].median().sort_values(ascending=False)
    most_sensitive = gap_by_scenario.index[0]
    least_sensitive = gap_by_scenario.index[-1]
    readme = f"""# Livraison finale — panel longitudinal de 2 000 communes

Cette arborescence regroupe les **{EXPECTED_PAIRS} couples élection × hypothèse** du périmètre `{get_scope().name}`, estimés en Python et en R `ei`/`eiPack`, les résultats NLS, les comparaisons interannuelles, les figures et les éléments de reproduction.

## Ordre de lecture

1. `00_LIRE_D_ABORD/RESULTATS_ET_COMPARAISONS.md`
2. `04_PRESENTATION/PRESENTATION_RESULTATS_240.pptx`
3. `02_BASE_TRANSPARENTE/base_resultats_long.parquet`
4. `07_AUDIT_ET_MANIFESTES/DELIVERY_MANIFEST.csv`

## Couverture

- Python KRT : {EXPECTED_PAIRS}/{EXPECTED_PAIRS} couples, réglages historiques individuels conservés dans les manifestes sélectionnés.
- R King EI : {EXPECTED_PAIRS}/{EXPECTED_PAIRS} couples sur le même panel de 2 000 communes.
- Comparaison Python–R : {EXPECTED_PAIRS}/{EXPECTED_PAIRS} couples ; les modèles sont volontairement distincts.
- Diagnostics Python : {', '.join(f'{key}={value}' for key, value in sorted(counts.items()))}.

Les traces NetCDF et les objets RDS ne sont pas inclus dans le ZIP principal. Les tables Parquet, les manifestes, les graines, les versions et les empreintes SHA-256 permettent l'audit sans gonfler artificiellement l'archive.
"""
    results = f"""# Résultats et comparaisons interannuelles

## Ce que contient la comparaison

Les législatives et les présidentielles sont présentées séparément. Les trajectoires portent sur le contraste agrégé `β₁ − β₂`. Elles décrivent des variations entre scrutins ; elles ne mesurent ni comportements individuels observés ni effets causaux.

La sensibilité au choix du modèle est la plus forte, en médiane, pour **{most_sensitive}** et la plus faible pour **{least_sensitive}**. Cette comparaison oppose le KRT bêta-binomial Python au King EI à normale tronquée en R : un écart ne doit donc pas être interprété comme une erreur de traduction bit-à-bit.

## Règles de lecture demandées par le professeur

- séparer législatives et présidentielles ;
- conserver les diagnostics MCMC et d'identification près des estimations ;
- distinguer dispersion entre communes, incertitude postérieure et comparaison inter-modèle ;
- ne pas présenter l'inférence écologique comme une observation individuelle ou une causalité ;
- traiter H6/H7 sur leur période admissible seulement.

Le détail exact se trouve dans `base_resultats_long.parquet`, `comparaison_python_r.parquet` et les figures vectorielles SVG.
"""
    methodology = """# Méthodologie, limites et reproductibilité

## Modèles

- **Python NumPyro — KRT bêta-binomial** : modèle hiérarchique de production, quatre chaînes, diagnostics R-hat/ESS/divergences et identification conservés.
- **R `ei`/`eiPack` — King 1997** : normale bivariée tronquée par les contraintes de tomographie ; ce n'est pas une troncature des données.
- **NLS** : benchmark déterministe distinct, sans intervalles postérieurs bayésiens.

## Limites

Le panel fixe rétrospectif suit des communes présentes dans l'univers de référence. Les estimations reposent sur des marges agrégées et sur les hypothèses des modèles. Les niveaux H0A/H0B/H0C n'ont pas le même dénominateur que H1–H7. Les résultats R et Python testent la robustesse à deux formulations différentes.

## Reproduction

Les tables canoniques sont en Parquet. Chaque fichier livré est indexé par chemin, taille, rôle et SHA-256. Les chemins locaux absolus sont exclus de la livraison. Les commandes minimales sont fournies dans `06_REPRODUCTIBILITE/COMMANDES.md`.
"""
    commands = """# Commandes de reconstruction

Depuis `part2/longitudinal_2022`, avec l'environnement Python du projet :

```powershell
& '..\\pour_moi_avec_data\\.venv-ei\\Scripts\\python.exe' -m code_longitudinal.consolidate_current_krt_all_2x2
& '..\\pour_moi_avec_data\\.venv-ei\\Scripts\\python.exe' -m code_longitudinal.consolidate_r_ei_all_2x2 --scenarios H0A H0B H0C H1 H2 H3 H4 H5 H6 H7 --output-scope all_2x2
& '..\\pour_moi_avec_data\\.venv-ei\\Scripts\\python.exe' -m code_longitudinal.compare_python_r_ei_full_240
& '..\\pour_moi_avec_data\\.venv-ei\\Scripts\\python.exe' -m code_longitudinal.build_full240_professor_release prepare
```

La création de la présentation doit ensuite suivre la vérification visuelle décrite dans `04_PRESENTATION/PRESENTATION_BRIEF.json`, avant le mode `finalize`.
"""
    (CANDIDATE / "00_LIRE_D_ABORD").mkdir(parents=True, exist_ok=True)
    (CANDIDATE / "00_LIRE_D_ABORD" / "README.md").write_text(readme, encoding="utf-8")
    (CANDIDATE / "00_LIRE_D_ABORD" / "RESULTATS_ET_COMPARAISONS.md").write_text(results, encoding="utf-8")
    (CANDIDATE / "05_METHODE_ET_LIMITES").mkdir(parents=True, exist_ok=True)
    (CANDIDATE / "05_METHODE_ET_LIMITES" / "METHODOLOGIE_ET_LIMITES.md").write_text(methodology, encoding="utf-8")
    (CANDIDATE / "06_REPRODUCTIBILITE").mkdir(parents=True, exist_ok=True)
    (CANDIDATE / "06_REPRODUCTIBILITE" / "COMMANDES.md").write_text(commands, encoding="utf-8")

    scenario_rows = []
    for scenario in SCENARIOS:
        if scenario.scenario_id not in get_scope().scenario_ids:
            continue
        if scenario.scenario_id not in set(base["scenario_id"]):
            continue
        scenario_rows.append(
            {
                "scenario_id": scenario.scenario_id,
                "vote_categories": " / ".join(scenario.vote_categories),
                "social_groups": "; ".join(
                    f"{name}={' + '.join(parts)}" for name, parts in scenario.social_groups.items()
                ),
                "denominator": scenario.denominator,
                "first_year": scenario.min_year,
            }
        )
    pd.DataFrame(scenario_rows).to_csv(
        CANDIDATE / "05_METHODE_ET_LIMITES" / "DEFINITIONS_HYPOTHESES.csv",
        index=False,
        encoding="utf-8-sig",
    )
    _copy(ROOT / "docs" / "PROFESSOR_GLOBAL_RECAP_1962_1986_2022.md", "05_METHODE_ET_LIMITES/PLAN_PROFESSEUR_REFERENCE.md")
    _copy(ROOT / "docs" / "OUTPUT_SCHEMA.md", "05_METHODE_ET_LIMITES/SCHEMA_SORTIES_HISTORIQUE.md")

    presentation_brief = {
        "schema_version": "full_240_presentation_brief_v1",
        "audience": "professeur encadrant et jury académique",
        "purpose": "présenter la couverture complète, les évolutions interannuelles, la sensibilité Python-R et les limites",
        "communication_job": f"À la fin, le professeur doit comprendre ce que montrent les {EXPECTED_PAIRS} estimations du périmètre {get_scope().name}, leur robustesse inter-modèle et leurs limites écologiques.",
        "language": "français",
        "recommended_slide_count": 12,
        "required_sections": [
            "question de recherche et panel",
            "méthode et hypothèses",
            f"couverture {EXPECTED_PAIRS}/{EXPECTED_PAIRS} dans le périmètre {get_scope().name}",
            "résultats législatifs",
            "résultats présidentiels",
            "comparaisons canoniques 1962-1986-2022",
            "accord et sensibilité Python-R",
            "diagnostics",
            "limites et conclusion",
        ],
        "figure_catalog": "../03_FIGURES/FIGURE_CATALOG.csv",
        "source_notes": "PRESENTATION_SOURCE_NOTES.txt",
        "qa_requirements": [
            "render every slide",
            "inspect every slide at full size",
            "zero unintended overlaps or clipping",
            "verify every numeric claim against delivered Parquet",
            "write PRESENTATION_QA.json with status=pass",
        ],
        "input_validation": validation,
        "figure_count": len(figure_catalog),
    }
    _write_json(CANDIDATE / "04_PRESENTATION" / "PRESENTATION_BRIEF.json", presentation_brief)
    (CANDIDATE / "04_PRESENTATION" / "PRESENTATION_SOURCE_NOTES.txt").write_text(
        "Toutes les affirmations chiffrées proviennent des Parquet livrés dans 01_DONNEES_CANONIQUES et 02_BASE_TRANSPARENTE.\n"
        "Le plan de restitution suit docs/PROFESSOR_GLOBAL_RECAP_1962_1986_2022.md et les règles de séparation des familles électorales.\n",
        encoding="utf-8",
    )


def _copy_canonical_sources() -> None:
    mappings = {
        PYTHON_AGGREGATE: "01_DONNEES_CANONIQUES/01_PYTHON_NUMPYRO/krt_aggregate_240.parquet",
        PYTHON_COMMUNE: "01_DONNEES_CANONIQUES/01_PYTHON_NUMPYRO/krt_commune_240.parquet",
        PYTHON_SELECTION: "01_DONNEES_CANONIQUES/01_PYTHON_NUMPYRO/selection_240.csv",
        PYTHON_MANIFEST: "01_DONNEES_CANONIQUES/01_PYTHON_NUMPYRO/manifest.json",
        R_AGGREGATE: "01_DONNEES_CANONIQUES/02_R_EI_EIPACK/king_ei_aggregate_240.parquet",
        R_COMMUNE: "01_DONNEES_CANONIQUES/02_R_EI_EIPACK/king_ei_commune_240.parquet",
        R_AUDIT: "01_DONNEES_CANONIQUES/02_R_EI_EIPACK/run_audit_240.csv",
        R_MANIFEST: "01_DONNEES_CANONIQUES/02_R_EI_EIPACK/manifest.json",
        COMPARISON_AGGREGATE: "01_DONNEES_CANONIQUES/03_COMPARAISON_PYTHON_R/python_r_aggregate.parquet",
        COMPARISON_COMMUNE: "01_DONNEES_CANONIQUES/03_COMPARAISON_PYTHON_R/python_r_commune_summary.parquet",
        COMPARISON_MANIFEST: "01_DONNEES_CANONIQUES/03_COMPARAISON_PYTHON_R/manifest.json",
        NLS_RESULTS: "01_DONNEES_CANONIQUES/04_NLS/longitudinal_nls.parquet",
        PANEL: "01_DONNEES_CANONIQUES/05_PANEL/panel_2000.parquet",
        COVERAGE_JSON: "07_AUDIT_ET_MANIFESTES/current_estimation_coverage.json",
        COVERAGE_CSV: "07_AUDIT_ET_MANIFESTES/current_estimation_coverage.csv",
    }
    for source, destination in mappings.items():
        _copy(source, destination)

    code_files = (
        ROOT / "code_longitudinal" / "consolidate_current_krt_all_2x2.py",
        ROOT / "code_longitudinal" / "consolidate_r_ei_all_2x2.py",
        ROOT / "code_longitudinal" / "compare_python_r_ei_full_240.py",
        ROOT / "code_longitudinal" / "build_full240_professor_release.py",
        ROOT / "r_replication" / "run_king_ei_replication.R",
        ROOT / "continue_r_ei_after_numpyro.ps1",
        ROOT / "run_finalize_professor_release_after_240.ps1",
    )
    for source in code_files:
        _copy(source, f"06_REPRODUCTIBILITE/code/{source.name}")


def _write_tree() -> None:
    tree = """longitudinal_2000_v1_full_240_professeur/
├── 00_LIRE_D_ABORD/                 résumé et résultats
├── 01_DONNEES_CANONIQUES/           sorties Python, R, NLS et panel
├── 02_BASE_TRANSPARENTE/             tables longues, couverture et dictionnaire
├── 03_FIGURES/                       PNG + SVG et catalogue des graphiques
├── 04_PRESENTATION/                  PowerPoint, sources et contrôle visuel
├── 05_METHODE_ET_LIMITES/            définitions, méthode et plan professeur
├── 06_REPRODUCTIBILITE/              commandes et code minimal
└── 07_AUDIT_ET_MANIFESTES/           contrôles, empreintes et inventaires
"""
    (CANDIDATE / "00_LIRE_D_ABORD" / "ARBORESCENCE.txt").write_text(tree, encoding="utf-8")


def prepare() -> dict[str, object]:
    validation = _validate_source_tables()
    _safe_reset_candidate()
    _copy_canonical_sources()
    base, comparison, coverage, nls = _normalize_results()
    transparent = CANDIDATE / "02_BASE_TRANSPARENTE"
    transparent.mkdir(parents=True, exist_ok=True)
    base.to_parquet(transparent / "base_resultats_long.parquet", index=False)
    base.to_csv(transparent / "base_resultats_long.csv", index=False, encoding="utf-8-sig")
    comparison.to_parquet(transparent / "comparaison_python_r.parquet", index=False)
    comparison.to_csv(transparent / "comparaison_python_r.csv", index=False, encoding="utf-8-sig")
    coverage.to_parquet(transparent / "couverture_240.parquet", index=False)
    nls.to_parquet(transparent / "resultats_nls_long.parquet", index=False)
    coverage.to_csv(transparent / "couverture_240.csv", index=False, encoding="utf-8-sig")
    dictionary_descriptions = {
        "panel_id": "Identifiant immuable du panel longitudinal",
        "engine": "Moteur logiciel ayant produit l'estimation",
        "model_key": "Identifiant stable du modèle",
        "model_label": "Libellé lisible du modèle",
        "election_id": "Identifiant du scrutin et du tour",
        "year": "Année du scrutin",
        "round": "Tour électoral",
        "election_family": "Famille législative ou présidentielle",
        "scenario_id": "Hypothèse H0A à H7",
        "estimand": "Paramètre agrégé b_1, b_2 ou b_1_minus_b_2",
        "estimate": "Moyenne de l'estimand",
        "sd": "Écart-type disponible pour R ei",
        "q025": "Quantile inférieur 2,5 %",
        "q50": "Médiane",
        "q975": "Quantile supérieur 97,5 %",
        "n_draws": "Nombre de tirages ou rééchantillonnages natifs",
        "n_communes": "Nombre de communes utilisées",
        "run_id": "Identifiant du run Python lorsqu'il existe",
        "diagnostic_status": "Statut numérique du modèle",
        "identification_status": "Statut d'identification écologique",
        "source_table": "Table canonique d'origine",
    }
    pd.DataFrame(
        [
            {
                "column": column,
                "dtype": str(base[column].dtype),
                "description": dictionary_descriptions.get(column, "Voir la méthodologie et la table source"),
            }
            for column in base.columns
        ]
    ).to_csv(transparent / "DICTIONNAIRE_BASE_RESULTATS.csv", index=False, encoding="utf-8-sig")
    figure_catalog = _build_figures(base, comparison, coverage)
    figure_catalog.to_csv(CANDIDATE / "03_FIGURES" / "FIGURE_CATALOG.csv", index=False, encoding="utf-8-sig")
    _write_documents(base, comparison, coverage, figure_catalog, validation)
    _write_tree()
    _write_json(CANDIDATE / "07_AUDIT_ET_MANIFESTES" / "PREPARE_VALIDATION.json", validation)
    result = {
        "schema_version": "full_240_professor_release_prepare_v1",
        "created_at_utc": _utc_now(),
        "status": "waiting_for_presentation_qa",
        "candidate": str(CANDIDATE),
        "presentation_path": str(PPTX_PATH),
        "presentation_qa_path": str(PRESENTATION_QA_PATH),
        "transparent_rows": len(base),
        "comparison_rows": len(comparison),
        "coverage_rows": len(coverage),
        "nls_rows": len(nls),
        "figure_count": len(figure_catalog),
    }
    _write_json(CANDIDATE / "07_AUDIT_ET_MANIFESTES" / "PREPARE_RECEIPT.json", result)
    return result


def _file_role(relative: str) -> str:
    prefix = relative.split("/", 1)[0]
    return {
        "00_LIRE_D_ABORD": "orientation",
        "01_DONNEES_CANONIQUES": "canonical_data",
        "02_BASE_TRANSPARENTE": "transparent_analysis_base",
        "03_FIGURES": "figure",
        "04_PRESENTATION": "presentation",
        "05_METHODE_ET_LIMITES": "methodology",
        "06_REPRODUCTIBILITE": "reproduction",
        "07_AUDIT_ET_MANIFESTES": "audit",
    }.get(prefix, "other")


def _write_delivery_manifest() -> pd.DataFrame:
    manifest_names = {"DELIVERY_MANIFEST.csv", "DELIVERY_MANIFEST.json"}
    catalogue_names = {"CATALOGUE_SORTIES.csv", "CATALOGUE_SORTIES.parquet"}

    def inventory(excluded_names: set[str]) -> pd.DataFrame:
        rows = []
        for path in sorted(item for item in CANDIDATE.rglob("*") if item.is_file()):
            relative = path.relative_to(CANDIDATE).as_posix()
            if path.name in excluded_names:
                continue
            rows.append(
                {
                    "delivery_path": relative,
                    "role": _file_role(relative),
                    "bytes": path.stat().st_size,
                    "sha256": file_sha256(path),
                }
            )
        return pd.DataFrame(rows)

    catalogue = inventory(manifest_names | catalogue_names)
    catalogue.to_csv(
        CANDIDATE / "02_BASE_TRANSPARENTE" / "CATALOGUE_SORTIES.csv",
        index=False,
        encoding="utf-8-sig",
    )
    catalogue.to_parquet(
        CANDIDATE / "02_BASE_TRANSPARENTE" / "CATALOGUE_SORTIES.parquet",
        index=False,
    )
    frame = inventory(manifest_names)
    target = CANDIDATE / "07_AUDIT_ET_MANIFESTES" / "DELIVERY_MANIFEST.csv"
    frame.to_csv(target, index=False, encoding="utf-8-sig")
    _write_json(
        CANDIDATE / "07_AUDIT_ET_MANIFESTES" / "DELIVERY_MANIFEST.json",
        {
            "schema_version": "full_240_delivery_manifest_v1",
            "created_at_utc": _utc_now(),
            "release": RELEASE_BASENAME,
            "file_count_excluding_manifests": len(frame),
            "files": frame.to_dict("records"),
        },
    )
    return frame


def finalize() -> dict[str, object]:
    if not CANDIDATE.is_dir():
        raise FileNotFoundError(CANDIDATE)
    if not PPTX_PATH.is_file():
        raise FileNotFoundError(f"presentation is missing: {PPTX_PATH}")
    if not PRESENTATION_QA_PATH.is_file():
        raise FileNotFoundError(f"presentation QA is missing: {PRESENTATION_QA_PATH}")
    qa = json.loads(PRESENTATION_QA_PATH.read_text(encoding="utf-8"))
    required_qa = {
        "status": "pass",
        "all_slides_rendered": True,
        "visual_inspection_complete": True,
        "overflow_test": "pass",
        "unintended_overlaps": 0,
    }
    failures = {key: value for key, value in required_qa.items() if qa.get(key) != value}
    if failures:
        raise AssertionError(f"presentation QA is incomplete: {failures}")
    with zipfile.ZipFile(PPTX_PATH) as presentation_archive:
        if presentation_archive.testzip() is not None:
            raise AssertionError("the PowerPoint file is corrupt")

    forbidden = [
        path for path in CANDIDATE.rglob("*") if path.is_file() and path.suffix.lower() in {".nc", ".rds"}
    ]
    if forbidden:
        raise AssertionError(f"forbidden heavy runtime files in delivery: {forbidden[:5]}")
    manifest = _write_delivery_manifest()

    DELIVERABLES.mkdir(parents=True, exist_ok=True)
    temporary_zip = ZIP_PATH.with_suffix(".zip.tmp")
    if temporary_zip.exists():
        temporary_zip.unlink()
    with zipfile.ZipFile(temporary_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        for path in sorted(item for item in CANDIDATE.rglob("*") if item.is_file()):
            archive.write(path, path.relative_to(CANDIDATE).as_posix())
    temporary_zip.replace(ZIP_PATH)

    with zipfile.ZipFile(ZIP_PATH) as archive:
        bad_crc = archive.testzip()
        if bad_crc is not None:
            raise AssertionError(f"ZIP CRC failure: {bad_crc}")
        members = archive.namelist()
        unsafe = [name for name in members if Path(name).is_absolute() or ".." in Path(name).parts]
        if unsafe:
            raise AssertionError(f"unsafe ZIP members: {unsafe[:5]}")
        with tempfile.TemporaryDirectory(prefix="full240_release_verify_", dir=ROOT / "work") as temp_dir:
            archive.extractall(temp_dir)
            extracted = Path(temp_dir)
            mismatches = []
            for row in manifest.itertuples(index=False):
                path = extracted / str(row.delivery_path)
                if not path.is_file() or file_sha256(path) != str(row.sha256):
                    mismatches.append(str(row.delivery_path))
            if mismatches:
                raise AssertionError(f"re-extracted SHA-256 mismatch: {mismatches[:5]}")

    digest = file_sha256(ZIP_PATH)
    ZIP_PATH.with_suffix(".zip.sha256").write_text(f"{digest}  {ZIP_PATH.name}\n", encoding="ascii")
    receipt = {
        "schema_version": "full_240_professor_release_receipt_v1",
        "created_at_utc": _utc_now(),
        "status": "complete",
        "zip_path": str(ZIP_PATH),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": digest,
        "zip_members": len(members),
        "crc_check": "pass",
        "reextract_hash_check": "pass",
        "python_pairs": EXPECTED_PAIRS,
        "r_pairs": EXPECTED_PAIRS,
        "presentation_qa": qa,
    }
    _write_json(ZIP_PATH.with_suffix(".zip.receipt.json"), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the complete professor release for all 240 2x2 pairs.")
    parser.add_argument("mode", choices=("prepare", "finalize"))
    args = parser.parse_args()
    result = prepare() if args.mode == "prepare" else finalize()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
