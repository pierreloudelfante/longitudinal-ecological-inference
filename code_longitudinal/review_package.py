from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from .paths import DOCS_DIR, FIGURE_DIR, OUTPUT_DIR, PANEL_DIR, REVIEW_DIR, ensure_runtime_dirs


def _copy(source: Path, destination: Path) -> bool:
    if not source.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def build_review_package() -> dict[str, object]:
    ensure_runtime_dirs()
    copied: list[str] = []
    for source in (
        PANEL_DIR / "panel_3000.csv",
        PANEL_DIR / "panel_2000.csv",
        PANEL_DIR / "panel_balance_checks.csv",
        PANEL_DIR / "panel_balance_attempts.csv",
        PANEL_DIR / "panel_manifest.json",
        PANEL_DIR / "panel_election_presence.csv",
    ):
        destination = REVIEW_DIR / "panel" / source.name
        if _copy(source, destination):
            copied.append(str(destination))
    for source in (
        DOCS_DIR / "BALANCE_TESTS.md",
        DOCS_DIR / "SCRIPT_GUIDE.md",
        DOCS_DIR / "METHODOLOGY_CODE_MAP.md",
        DOCS_DIR / "RESULTS_TRANSPARENCY.md",
        DOCS_DIR / "OUTPUT_SCHEMA.md",
        DOCS_DIR / "LONGITUDINAL_AUDIT.md",
        DOCS_DIR / "VALIDATION_REPORT.md",
        DOCS_DIR / "IMPLEMENTATION_MANIFEST.md",
        DOCS_DIR / "ELECTION_2022_PRODUCTION_REPORT.md",
        DOCS_DIR / "ALL_ELECTION_PARTITIONS_REPORT.md",
        DOCS_DIR / "PILOT_1962_1986_2022_REPORT.md",
        DOCS_DIR / "FIGURE_CATALOG.md",
    ):
        destination = REVIEW_DIR / source.name
        if _copy(source, destination):
            copied.append(str(destination))

    # Keep the illustrated report under docs/ so its ../figures relative links
    # work both in the project and in the professor package without rewriting.
    illustrated = DOCS_DIR / "RESULTS_ILLUSTRATED_1962_1986_2022.md"
    stale_illustrated = REVIEW_DIR / illustrated.name
    if stale_illustrated.exists():
        stale_illustrated.unlink()
    illustrated_destination = REVIEW_DIR / "docs" / illustrated.name
    if _copy(illustrated, illustrated_destination):
        copied.append(str(illustrated_destination))

    professor_recap = DOCS_DIR / "PROFESSOR_GLOBAL_RECAP_1962_1986_2022.md"
    professor_recap_destination = REVIEW_DIR / "docs" / professor_recap.name
    if _copy(professor_recap, professor_recap_destination):
        copied.append(str(professor_recap_destination))

    extracts_dir = REVIEW_DIR / "table_extracts"
    extracts_dir.mkdir(parents=True, exist_ok=True)
    table_names = (
        "longitudinal_estimates",
        "model_diagnostics",
        "commune_latent_summaries",
        "commune_beta_estimates",
        "beta_trace_index",
        "beta_density_data",
        "nls_coefficients",
        "nls_start_diagnostics",
        "density_marginal_data",
        "density_joint_data",
        "rxc_runtime_benchmark",
        "resource_ladder_preflight",
        "resource_ladder_gates",
        "excluded_units",
        "run_registry",
        "validation_checks",
        "election_2022_input_integrity",
        "election_2022_fit_quality",
        "all_elections_partition_integrity",
        "pilot_model_coverage",
        "pilot_density_selection",
        "illustrated_report_estimates",
        "professor_canonical_comparisons",
    )
    table_status: dict[str, int] = {}
    for name in table_names:
        source = OUTPUT_DIR / f"{name}.csv"
        if not source.exists():
            table_status[name] = 0
            continue
        try:
            frame = pd.read_csv(source, low_memory=False)
        except pd.errors.EmptyDataError:
            frame = pd.DataFrame()
        frame.head(50).to_csv(extracts_dir / f"{name}__first50.csv", index=False, encoding="utf-8-sig")
        table_status[name] = int(len(frame))

    figure_destination = REVIEW_DIR / "figures"
    if figure_destination.exists():
        shutil.rmtree(figure_destination)
    if FIGURE_DIR.exists():
        shutil.copytree(FIGURE_DIR, figure_destination)

    registry_path = OUTPUT_DIR / "run_registry.csv"
    registry = pd.read_csv(registry_path, dtype="string") if registry_path.exists() else pd.DataFrame()
    successful = int(registry["status"].eq("success").sum()) if not registry.empty else 0
    failed = int(registry["status"].eq("failed").sum()) if not registry.empty else 0
    model_status = (
        registry.groupby("model_key")["status"].value_counts().unstack(fill_value=0).to_dict("index")
        if not registry.empty
        else {}
    )
    joint_path = OUTPUT_DIR / "density_joint_data.csv"
    joint = pd.read_csv(joint_path, low_memory=False) if joint_path.exists() else pd.DataFrame()
    common = joint.loc[joint.get("comparison_scope", pd.Series(dtype=str)).eq("common_intersection")]
    largest_common_value = pd.to_numeric(common.get("n_communes_requested"), errors="coerce").max() if not common.empty else 0
    largest_common = int(largest_common_value) if pd.notna(largest_common_value) else 0
    coverage_path = OUTPUT_DIR / "pilot_model_coverage.csv"
    coverage = pd.read_csv(coverage_path, low_memory=False) if coverage_path.exists() else pd.DataFrame()
    reached_n3000 = int(coverage.get("coverage_status", pd.Series(dtype=str)).eq("reached_n3000").sum())
    resource_limited = coverage.loc[
        coverage.get("coverage_status", pd.Series(dtype=str)).eq("partial_resource_block")
    ]
    blocked_summary = (
        resource_limited[
            [
                "election_id",
                "scenario_id",
                "model_key",
                "largest_successful_n_requested",
                "target_n",
                "limitation",
            ]
        ].to_dict("records")
        if not resource_limited.empty
        else []
    )
    readme = [
        "# Paquet de revue longitudinale 01",
        "",
        "Ce paquet est un point de contrôle avant généralisation des calculs 1962–2022.",
        "Les résultats d'inférence écologique sont descriptifs et ne constituent pas des relations individuelles observées.",
        "",
        "## État",
        "",
        f"- Runs réussis : {successful}",
        f"- Runs échoués conservés : {failed}",
        f"- État par modèle : `{model_status}`",
        f"- Plus grand palier commun King/KRT disponible : `{largest_common}` communes demandées.",
        f"- Couples pilotes ayant atteint le palier demandé 3 000 : `{reached_n3000}/{len(coverage)}`.",
        "- Le panel principal reste fixé à 3 000 communes ; toutes les calibrations PyEI 20/20/1 sont explicitement non substantielles, même à ce palier.",
        "- Les communes absentes ou filtrées ne sont jamais remplacées et sont listées dans les tables dédiées.",
        "",
        "## Contenu",
        "",
        "- `panel/` : panel, balance checks, tentatives, présence longitudinale et manifeste.",
        "- `table_extracts/` : 50 premières lignes de chaque table disponible.",
        "- `figures/` : balance, densités, figures longitudinales et diagnostic mono-élection 2022.",
        "- `BALANCE_TESTS.md` : critères, résultats et limites de la balance.",
        "- `SCRIPT_GUIDE.md` : rôle, entrées, sorties et importance de chaque script.",
        "- `METHODOLOGY_CODE_MAP.md` : équations reliées aux fonctions et lignes de code.",
        "- `RESULTS_TRANSPARENCY.md` : statut substantiel et guide de lecture.",
        "- `OUTPUT_SCHEMA.md` et `LONGITUDINAL_AUDIT.md` : contrats et provenance.",
        "- `ELECTION_2022_PRODUCTION_REPORT.md` : périmètre effectivement calculé à 3 000 communes et verdict d'intégrité.",
        "- `ALL_ELECTION_PARTITIONS_REPORT.md` : 292 partitions auditées, 270 valides et 22 RXC refusées.",
        "- `PILOT_1962_1986_2022_REPORT.md` : paliers atteints, NLS, mémoire et densités.",
        "- `FIGURE_CATALOG.md` : catalogue exhaustif des figures, de leur portée et de leurs tables sources.",
        "- `docs/RESULTS_ILLUSTRATED_1962_1986_2022.md` : 18 figures intégrées, valeurs exactes et comparaisons interannuelles.",
        "- `docs/PROFESSOR_GLOBAL_RECAP_1962_1986_2022.md` : synthèse globale, inventaire des sorties, exemples graphiques et huit comparaisons canoniques.",
        "",
        "## Lignes disponibles dans les tables consolidées",
        "",
        *[f"- `{name}` : {count}" for name, count in table_status.items()],
        "",
        "## Limite de calcul",
        "",
        "Les modèles PyEI sont soumis au passage par paliers. Une figure issue d'une calibration ou portant un diagnostic `warning`/`fail` ne doit pas être interprétée comme un résultat substantiel.",
        f"Blocages courants du pilote, après prise en compte des retries réussis : `{blocked_summary}`.",
    ]
    (REVIEW_DIR / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")
    return {"review_dir": str(REVIEW_DIR), "copied_files": len(copied), "table_rows": table_status}
