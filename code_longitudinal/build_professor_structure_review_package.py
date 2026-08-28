from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DELIVERABLES = ROOT / "deliverables"
PACKAGE_DIR = DELIVERABLES / "professeur_structure_sorties_longitudinales_3000"
WORK_DIR = ROOT / "work_professor_structure_20260805"
FINAL_OUTPUT = ROOT / "outputs" / "v2" / "priority_3000_final"
PANEL_VERSION = "panel_3000_common_1962_1986_2022_v2"

KRT_RUNS = [
    "20260804T135238Z__a1d85f03a9f8",
    "20260804T140822Z__cc8c7aa063b5",
    "20260804T144933Z__4830d0298ccd",
    "20260804T150252Z__2df1cacde040",
    "20260804T161211Z__6719825c1e9a",
    "20260804T163742Z__1cc94b3f41d5",
]

HYPOTHESES = {
    "H0A": {
        "event": "abstention",
        "event_label": "abstention parmi les inscrits",
        "group_1": "ouvriers + employés",
        "group_2": "autres CSP",
    },
    "H1": {
        "event": "gauche",
        "event_label": "vote à gauche parmi les exprimés",
        "group_1": "ouvriers + employés",
        "group_2": "autres CSP",
    },
    "H2": {
        "event": "gauche",
        "event_label": "vote à gauche parmi les exprimés",
        "group_1": "ouvriers",
        "group_2": "autres CSP",
    },
    "H4": {
        "event": "droite",
        "event_label": "vote à droite parmi les exprimés",
        "group_1": "agriculteurs + indépendants",
        "group_2": "salariés",
    },
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def number(value: str | None, *, integer: bool = False) -> int | float | None:
    if value is None or value == "":
        return None
    return int(float(value)) if integer else float(value)


def boolean(value: str | None) -> bool | None:
    if value is None or value == "":
        return None
    return value.strip().lower() in {"true", "1", "yes"}


def krt_estimation_key(run_id: str) -> str:
    return f"krt|{run_id}"


def nls_estimation_key(election_id: str, scenario_id: str) -> str:
    return f"nls|{election_id}|{scenario_id}|rosen_nls_2x2_unadjusted"


def build_long_results() -> list[dict[str, Any]]:
    aggregate = read_csv(FINAL_OUTPUT / "aggregate_drawwise_corrected_3000_v1.csv")
    contrasts = read_csv(FINAL_OUTPUT / "within_period_contrasts_3000_v1.csv")
    nls = read_csv(FINAL_OUTPUT / "nls_contrasts_3000_v1.csv")
    rows: list[dict[str, Any]] = []

    for row in aggregate:
        hypothesis = row["scenario_id"]
        meta = HYPOTHESES[hypothesis]
        beta = "beta_1" if row["beta_parameter"] == "b_1" else "beta_2"
        group_label = meta["group_1"] if beta == "beta_1" else meta["group_2"]
        rows.append(
            {
                "estimation_id": krt_estimation_key(row["run_id"]),
                "run_id_source": row["run_id"],
                "election_id": row["election_id"],
                "year": number(row["year"], integer=True),
                "hypothesis": hypothesis,
                "method": "KRT",
                "model_key": "krt_beta_binomial",
                "event": meta["event"],
                "estimand": beta,
                "estimand_label": group_label,
                "mean": number(row["mean"]),
                "q025": number(row["q025"]),
                "q50": number(row["q50"]),
                "q975": number(row["q975"]),
                "n_communes": 3000,
                "n_posterior_draws": number(row["n_posterior_draws"], integer=True),
                "panel_version": PANEL_VERSION,
                "uncertainty_available": True,
                "source_file": "aggregate_drawwise_corrected_3000_v1.csv",
            }
        )

    for row in contrasts:
        hypothesis = row["scenario_id"]
        meta = HYPOTHESES[hypothesis]
        rows.append(
            {
                "estimation_id": krt_estimation_key(row["run_id"]),
                "run_id_source": row["run_id"],
                "election_id": row["election_id"],
                "year": number(row["year"], integer=True),
                "hypothesis": hypothesis,
                "method": "KRT",
                "model_key": "krt_beta_binomial",
                "event": meta["event"],
                "estimand": "beta_1_minus_beta_2",
                "estimand_label": f"{meta['group_1']} - {meta['group_2']}",
                "mean": number(row["estimate"]),
                "q025": number(row["lower"]),
                "q50": number(row["median"]),
                "q975": number(row["upper"]),
                "n_communes": 3000,
                "n_posterior_draws": number(row["n_posterior_draws"], integer=True),
                "panel_version": PANEL_VERSION,
                "uncertainty_available": True,
                "source_file": "within_period_contrasts_3000_v1.csv",
            }
        )

    for row in nls:
        hypothesis = row["scenario_id"]
        meta = HYPOTHESES[hypothesis]
        common = {
            "estimation_id": nls_estimation_key(f"leg_{row['year']}_r1", hypothesis),
            "run_id_source": None,
            "election_id": f"leg_{row['year']}_r1",
            "year": number(row["year"], integer=True),
            "hypothesis": hypothesis,
            "method": "NLS",
            "model_key": "rosen_nls_2x2_unadjusted",
            "event": row["event"],
            "n_communes": number(row["n_communes"], integer=True),
            "n_posterior_draws": None,
            "panel_version": PANEL_VERSION,
            "uncertainty_available": False,
            "source_file": "nls_contrasts_3000_v1.csv",
        }
        for estimand, label, value in [
            ("group_1", row["group_1_label"], row["group_1_estimate"]),
            ("group_2", row["group_2_label"], row["group_2_estimate"]),
            ("group_1_minus_group_2", f"{meta['group_1']} - {meta['group_2']}", row["contrast_group_1_minus_group_2"]),
        ]:
            rows.append(
                {
                    **common,
                    "estimand": estimand,
                    "estimand_label": label,
                    "mean": number(value),
                    "q025": None,
                    "q50": None,
                    "q975": None,
                }
            )

    return sorted(rows, key=lambda r: (r["method"], r["hypothesis"], r["year"], r["estimand"]))


def build_commune_results() -> list[dict[str, Any]]:
    joint = read_csv(FINAL_OUTPUT / "joint_latent_3000_v1.csv")
    election_by_run = {
        row["run_id"]: row["election_id"]
        for row in read_csv(FINAL_OUTPUT / "within_period_contrasts_3000_v1.csv")
    }
    rows: list[dict[str, Any]] = []
    for row in joint:
        if int(row["sample_rank"]) > 10:
            continue
        hypothesis = row["scenario_id"]
        meta = HYPOTHESES[hypothesis]
        beta_1_weight = number(row["b1_weight"])
        beta_2_weight = number(row["b2_weight"])
        beta_1_mean = number(row["b1_mean"])
        beta_2_mean = number(row["b2_mean"])
        rows.append(
            {
                "estimation_id": krt_estimation_key(row["run_id"]),
                "run_id_source": row["run_id"],
                "election_id": election_by_run[row["run_id"]],
                "year": number(row["year"], integer=True),
                "hypothesis": hypothesis,
                "method": "KRT",
                "model_key": "krt_beta_binomial",
                "unit_id": row["unit_id"].zfill(5),
                "sample_rank": number(row["sample_rank"], integer=True),
                "beta_1_group": meta["group_1"],
                "beta_2_group": meta["group_2"],
                "beta_1_weight": beta_1_weight,
                "beta_2_weight": beta_2_weight,
                "N_total": beta_1_weight + beta_2_weight,
                "beta_1_mean": beta_1_mean,
                "beta_2_mean": beta_2_mean,
                "contrast_mean": beta_1_mean - beta_2_mean,
                "panel_version": PANEL_VERSION,
                "source_file": "joint_latent_3000_v1.csv",
            }
        )
    return sorted(rows, key=lambda r: (r["hypothesis"], r["year"], r["sample_rank"]))


def build_diagnostics() -> list[dict[str, Any]]:
    krt = read_csv(FINAL_OUTPUT / "canonical_mcmc_diagnostics_3000_v1.csv")
    nls = read_csv(FINAL_OUTPUT / "nls_model_diagnostics_3000_v1.csv")
    rows: list[dict[str, Any]] = []
    for row in krt:
        rows.append(
            {
                "estimation_id": krt_estimation_key(row["run_id"]),
                "run_id_source": row["run_id"],
                "election_id": row["election_id"],
                "year": number(row["year"], integer=True),
                "hypothesis": row["scenario_id"],
                "method": "KRT",
                "model_key": "krt_beta_binomial",
                "fit_status": row["fit_status"],
                "assessment_label": row["mcmc_assessment_label"],
                "beta_status": row["beta_diagnostic_status"],
                "non_beta_status": row["non_beta_parameter_status"],
                "identification_status": row["identification_status"],
                "chains": number(row["saved_chains"], integer=True),
                "tune_per_chain": 1000,
                "draws_per_chain": number(row["saved_draws_per_chain"], integer=True),
                "target_accept": 0.99,
                "max_treedepth": number(row["configured_max_treedepth"], integer=True),
                "max_rhat_beta": number(row["max_rhat"]),
                "min_ess_bulk_beta": number(row["min_ess_bulk"]),
                "min_ess_tail_beta": number(row["min_ess_tail"]),
                "divergences": number(row["divergences"], integer=True),
                "solver": None,
                "n_starts": None,
                "n_successful_starts": None,
                "optimizer_success": None,
                "condition_information": None,
                "panel_version": PANEL_VERSION,
                "source_file": "canonical_mcmc_diagnostics_3000_v1.csv",
            }
        )
    for row in nls:
        rows.append(
            {
                "estimation_id": nls_estimation_key(row["election_id"], row["scenario_id"]),
                "run_id_source": None,
                "election_id": row["election_id"],
                "year": number(row["year"], integer=True),
                "hypothesis": row["scenario_id"],
                "method": "NLS",
                "model_key": "rosen_nls_2x2_unadjusted",
                "fit_status": "success" if boolean(row["optimizer_success"]) else "failure",
                "assessment_label": "satisfaisant" if row["diagnostic_status"] == "pass" else "à contrôler",
                "beta_status": None,
                "non_beta_status": None,
                "identification_status": None,
                "chains": None,
                "tune_per_chain": None,
                "draws_per_chain": None,
                "target_accept": None,
                "max_treedepth": None,
                "max_rhat_beta": None,
                "min_ess_bulk_beta": None,
                "min_ess_tail_beta": None,
                "divergences": None,
                "solver": "scipy.optimize.least_squares (TRF)",
                "n_starts": number(row["n_starts"], integer=True),
                "n_successful_starts": number(row["n_successful_starts"], integer=True),
                "optimizer_success": boolean(row["optimizer_success"]),
                "condition_information": number(row["sandwich_condition_info"]),
                "panel_version": PANEL_VERSION,
                "source_file": "nls_model_diagnostics_3000_v1.csv",
            }
        )
    return sorted(rows, key=lambda r: (r["method"], r["hypothesis"], r["year"]))


def build_schema_rows() -> list[dict[str, Any]]:
    return [
        {"table": "panel_membership", "grain": "panel_version × commune", "primary_key": "panel_version + unit_id", "current_source": "panel CSV V2", "current_rows": 3000, "proposed_status": "conserver et versionner"},
        {"table": "estimations", "grain": "une estimation", "primary_key": "estimation_id", "current_source": "manifestes KRT et tables NLS", "current_rows": 18, "proposed_status": "créer une table commune"},
        {"table": "group_estimates", "grain": "estimation × grandeur de groupe", "primary_key": "estimation_id + estimand", "current_source": "agrégats KRT et estimations NLS", "current_rows": 36, "proposed_status": "unifier les noms et unités"},
        {"table": "contrasts", "grain": "estimation × contraste", "primary_key": "estimation_id + contrast_id", "current_source": "contrastes KRT et NLS", "current_rows": 18, "proposed_status": "unifier avec incertitude nullable"},
        {"table": "commune_estimates", "grain": "estimation × commune", "primary_key": "estimation_id + unit_id", "current_source": "Parquet KRT et joint_latent", "current_rows": 18000, "proposed_status": "conserver en Parquet"},
        {"table": "diagnostics", "grain": "une estimation", "primary_key": "estimation_id", "current_source": "diagnostics KRT et NLS", "current_rows": 18, "proposed_status": "table commune avec champs méthode"},
        {"table": "period_changes", "grain": "hypothèse × paire de périodes", "primary_key": "hypothesis + year_from + year_to", "current_source": "between_period_contrast_changes", "current_rows": 6, "proposed_status": "conserver comme résultat dérivé"},
        {"table": "posterior_draws", "grain": "estimation × chaîne × tirage × grandeur", "primary_key": "estimation_id + chain + draw + estimand", "current_source": "traces NetCDF KRT", "current_rows": None, "proposed_status": "stockage séparé"},
        {"table": "data_quality_events", "grain": "source × unité × règle", "primary_key": "source_id + unit_id + rule_id", "current_source": "source_data_anomalies", "current_rows": 9, "proposed_status": "journaliser séparément"},
    ]


def build_inventory() -> list[dict[str, Any]]:
    files = [
        (ROOT / "panel" / "panel_3000_common_1962_1986_2022_v2.csv", "panel", "CSV", "panel × commune"),
        (FINAL_OUTPUT / "aggregate_drawwise_corrected_3000_v1.csv", "KRT", "CSV", "estimation × beta"),
        (FINAL_OUTPUT / "within_period_contrasts_3000_v1.csv", "KRT", "CSV", "estimation"),
        (FINAL_OUTPUT / "between_period_contrast_changes_3000_v1.csv", "KRT", "CSV", "hypothèse × paire de périodes"),
        (FINAL_OUTPUT / "joint_latent_3000_v1.csv", "KRT", "CSV", "estimation × commune"),
        (FINAL_OUTPUT / "canonical_mcmc_diagnostics_3000_v1.csv", "KRT", "CSV", "estimation"),
        (FINAL_OUTPUT / "estimand_mcmc_diagnostics_3000_v1.csv", "KRT", "CSV", "estimation × grandeur"),
        (FINAL_OUTPUT / "identification_separate_3000_v1.csv", "KRT", "CSV", "estimation"),
        (FINAL_OUTPUT / "nls_estimates_3000_v1.csv", "NLS", "CSV", "estimation × groupe × événement"),
        (FINAL_OUTPUT / "nls_contrasts_3000_v1.csv", "NLS", "CSV", "estimation"),
        (FINAL_OUTPUT / "nls_model_diagnostics_3000_v1.csv", "NLS", "CSV", "estimation"),
        (FINAL_OUTPUT / "nls_krt_comparison_3000_v1.csv", "comparaison", "CSV", "hypothèse × année"),
    ]
    rows: list[dict[str, Any]] = []
    for path, block, file_format, grain in files:
        row_count = len(read_csv(path)) if file_format == "CSV" else None
        rows.append(
            {
                "file": path.name,
                "block": block,
                "format": file_format,
                "grain": grain,
                "rows": row_count,
                "size_kib": round(path.stat().st_size / 1024, 1),
                "included_in_package": True,
            }
        )
    rows.append({"file": "commune_latent_summaries.parquet × 6", "block": "KRT", "format": "Parquet", "grain": "estimation × commune", "rows": 18000, "size_kib": None, "included_in_package": True})
    rows.append({"file": "trace.nc × 6", "block": "KRT", "format": "NetCDF", "grain": "chaîne × tirage × paramètre", "rows": None, "size_kib": None, "included_in_package": False})
    return rows


def build_dictionary(data: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    definitions = {
        "estimation_id": ("texte", "non", "identifiant", "Identifiant stable proposé pour relier les tables."),
        "run_id_source": ("texte", "oui", "identifiant", "Identifiant technique natif de l'exécution source."),
        "election_id": ("texte", "non", "identifiant", "Identifiant de l'élection et du tour."),
        "year": ("entier", "non", "année", "Année de l'élection."),
        "hypothesis": ("texte", "non", "H0A/H1/H2/H4", "Hypothèse ou partition sociale étudiée."),
        "method": ("texte", "non", "KRT/NLS", "Méthode d'estimation."),
        "model_key": ("texte", "non", "identifiant", "Spécification du modèle."),
        "event": ("texte", "non", "catégorie", "Événement électoral modélisé."),
        "estimand": ("texte", "non", "identifiant", "Grandeur estimée ou contraste."),
        "estimand_label": ("texte", "non", "libellé", "Libellé substantiel de la grandeur."),
        "mean": ("réel", "non", "proportion", "Moyenne postérieure KRT ou estimation ponctuelle NLS."),
        "q025": ("réel", "oui", "proportion", "Quantile postérieur à 2,5 %."),
        "q50": ("réel", "oui", "proportion", "Médiane postérieure."),
        "q975": ("réel", "oui", "proportion", "Quantile postérieur à 97,5 %."),
        "n_communes": ("entier", "non", "communes", "Nombre de communes utilisées."),
        "n_posterior_draws": ("entier", "oui", "tirages", "Nombre total de tirages postérieurs agrégés."),
        "panel_version": ("texte", "non", "identifiant", "Version du panel utilisée pour l'estimation."),
        "uncertainty_available": ("booléen", "non", "vrai/faux", "Indique si un intervalle d'incertitude est exporté."),
        "source_file": ("texte", "non", "chemin relatif", "Fichier source du résultat présenté."),
        "unit_id": ("texte", "non", "code commune", "Identifiant communal conservé avec ses zéros initiaux."),
        "sample_rank": ("entier", "non", "rang", "Rang de la commune dans le panel."),
        "beta_1_group": ("texte", "non", "libellé", "Groupe social associé à beta_1."),
        "beta_2_group": ("texte", "non", "libellé", "Groupe social associé à beta_2."),
        "beta_1_weight": ("réel", "non", "effectif", "Poids communal du groupe associé à beta_1."),
        "beta_2_weight": ("réel", "non", "effectif", "Poids communal du groupe associé à beta_2."),
        "N_total": ("réel", "non", "effectif", "Dénominateur communal ou agrégé de l'estimation."),
        "beta_1_mean": ("réel", "non", "proportion", "Moyenne postérieure communale de beta_1."),
        "beta_2_mean": ("réel", "non", "proportion", "Moyenne postérieure communale de beta_2."),
        "contrast_mean": ("réel", "non", "proportion", "Différence communale beta_1 moins beta_2."),
        "fit_status": ("texte", "non", "statut", "Statut technique de l'ajustement."),
        "assessment_label": ("texte", "non", "statut", "Bilan synthétique publié."),
        "beta_status": ("texte", "oui", "statut", "Diagnostic du bloc des paramètres beta."),
        "non_beta_status": ("texte", "oui", "statut", "Réserve éventuelle sur les paramètres hors beta."),
        "identification_status": ("texte", "oui", "statut", "Bilan séparé d'identification écologique."),
        "chains": ("entier", "oui", "chaînes", "Nombre de chaînes MCMC sauvegardées."),
        "tune_per_chain": ("entier", "oui", "itérations", "Itérations de réglage par chaîne."),
        "draws_per_chain": ("entier", "oui", "tirages", "Tirages conservés par chaîne."),
        "target_accept": ("réel", "oui", "probabilité", "Valeur cible d'acceptation NUTS."),
        "max_treedepth": ("entier", "oui", "niveau", "Profondeur maximale configurée pour NUTS."),
        "max_rhat_beta": ("réel", "oui", "diagnostic", "Pire R-hat parmi les paramètres beta communaux."),
        "min_ess_bulk_beta": ("réel", "oui", "tirages effectifs", "Plus faible ESS bulk parmi les beta communaux."),
        "min_ess_tail_beta": ("réel", "oui", "tirages effectifs", "Plus faible ESS tail parmi les beta communaux."),
        "divergences": ("entier", "oui", "événements", "Nombre de divergences MCMC."),
        "solver": ("texte", "oui", "méthode", "Solveur utilisé pour NLS."),
        "n_starts": ("entier", "oui", "démarrages", "Nombre de points de départ NLS."),
        "n_successful_starts": ("entier", "oui", "démarrages", "Nombre de points de départ NLS convergents."),
        "optimizer_success": ("booléen", "oui", "vrai/faux", "Indicateur de succès de l'optimiseur."),
        "condition_information": ("réel", "oui", "diagnostic", "Conditionnement de la matrice d'information NLS."),
    }
    rows: list[dict[str, Any]] = []
    for table_name in ["long_results", "commune_results", "diagnostics"]:
        if not data[table_name]:
            continue
        for column in data[table_name][0].keys():
            dtype, nullable, domain, definition = definitions.get(column, ("texte", "oui", "", "Champ de la table proposée."))
            rows.append(
                {
                    "table": table_name,
                    "column": column,
                    "type": dtype,
                    "nullable": nullable,
                    "unit_or_domain": domain,
                    "definition": definition,
                    "status": "déjà disponible" if column != "estimation_id" else "clé proposée",
                }
            )
    return rows


def write_workbook_data() -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "readme": [
            {"item": "Objet", "value": "Exemple de structure des sorties longitudinales", "note": "Aucune estimation n'est modifiée."},
            {"item": "Panel estimé", "value": PANEL_VERSION, "note": "3 000 communes communes aux trois dates."},
            {"item": "KRT", "value": "6 estimations", "note": "H0A et H1 en 1962, 1986 et 2022."},
            {"item": "NLS", "value": "12 estimations", "note": "H0A, H1, H2 et H4 sur les trois dates."},
            {"item": "Table proposée", "value": "format long", "note": "Une ligne par estimation et grandeur publiée."},
            {"item": "Clé proposée", "value": "estimation_id", "note": "Relie résultats, communes, diagnostics et tirages."},
            {"item": "V3", "value": "prochaines estimations", "note": "Ne pas attribuer les résultats actuels au panel V3."},
        ],
        "schema_tables": build_schema_rows(),
        "long_results": build_long_results(),
        "commune_results": build_commune_results(),
        "diagnostics": build_diagnostics(),
        "inventory": build_inventory(),
    }
    data["dictionary"] = build_dictionary(data)
    with (WORK_DIR / "workbook_data.json").open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def create_code_snapshot() -> None:
    destination = PACKAGE_DIR / "code" / "code_et_configuration_20260805.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    included_roots = [ROOT / "code_longitudinal", ROOT / "config", ROOT / "tests"]
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=7) as archive:
        for source_root in included_roots:
            for path in sorted(source_root.rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(ROOT)
                if "__pycache__" in relative.parts or ".pytest_cache" in relative.parts or path.suffix in {".pyc", ".pyo"}:
                    continue
                archive.write(path, relative.as_posix())
        for name in ["README.md", "requirements-dev.txt"]:
            path = ROOT / name
            if path.exists():
                archive.write(path, name)


def prepare_package() -> None:
    write_workbook_data()
    if not PACKAGE_DIR.exists():
        raise FileNotFoundError(f"The documentation directory must exist before preparation: {PACKAGE_DIR}")

    report_zip = DELIVERABLES / "premiers_resultats_KRT_NLS_panel3000_1962_1986_2022.zip"
    report_dir = PACKAGE_DIR / "rapport_premiers_resultats"
    report_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(report_zip, "r") as archive:
        archive.extractall(report_dir)

    sources = PACKAGE_DIR / "sources_structure_actuelle"
    selected = [
        FINAL_OUTPUT / "README.md",
        FINAL_OUTPUT / "release_manifest_3000_v1.json",
        FINAL_OUTPUT / "aggregate_drawwise_corrected_3000_v1.csv",
        FINAL_OUTPUT / "within_period_contrasts_3000_v1.csv",
        FINAL_OUTPUT / "between_period_contrast_changes_3000_v1.csv",
        FINAL_OUTPUT / "joint_latent_3000_v1.csv",
        FINAL_OUTPUT / "canonical_mcmc_diagnostics_3000_v1.csv",
        FINAL_OUTPUT / "estimand_mcmc_diagnostics_3000_v1.csv",
        FINAL_OUTPUT / "identification_separate_3000_v1.csv",
        FINAL_OUTPUT / "density_bandwidths_3000_v1.csv",
        FINAL_OUTPUT / "source_data_anomalies_3000_v1.csv",
        FINAL_OUTPUT / "nls_estimates_3000_v1.csv",
        FINAL_OUTPUT / "nls_contrasts_3000_v1.csv",
        FINAL_OUTPUT / "nls_model_diagnostics_3000_v1.csv",
        FINAL_OUTPUT / "nls_krt_comparison_3000_v1.csv",
        FINAL_OUTPUT / "nls_summary_manifest_3000_v1.json",
        ROOT / "panel" / "panel_3000_common_1962_1986_2022_v2.csv",
        ROOT / "panel" / "panel_3000_common_1962_1986_2022_v2_balance.csv",
        ROOT / "panel" / "panel_3000_common_1962_1986_2022_v2_manifest.json",
    ]
    for path in selected:
        section = "panel" if path.parent.name == "panel" else "tables_consolidees"
        copy_file(path, sources / section / path.name)

    for run_id in KRT_RUNS:
        run_dir = ROOT / "outputs" / "runs" / run_id
        destination = sources / "sorties_communales_krt" / run_id
        for name in ["manifest.json", "commune_latent_summaries.parquet", "aggregate_comparison_v2.csv", "longitudinal_estimates.csv"]:
            path = run_dir / name
            if path.exists():
                copy_file(path, destination / name)

    create_code_snapshot()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finalize_package() -> None:
    workbook = PACKAGE_DIR / "TABLES_EXEMPLES_STRUCTURE_SORTIES.xlsx"
    if not workbook.exists():
        raise FileNotFoundError(f"Workbook missing: {workbook}")
    manifest_path = PACKAGE_DIR / "package_manifest.json"
    files = []
    for path in sorted(PACKAGE_DIR.rglob("*")):
        if path.is_file() and path != manifest_path:
            files.append(
                {
                    "path": path.relative_to(PACKAGE_DIR).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    manifest = {
        "package": PACKAGE_DIR.name,
        "created_for": "validation of longitudinal output structure",
        "estimated_panel_version": "v2",
        "future_panel_version": "v3",
        "files": files,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    zip_path = DELIVERABLES / f"{PACKAGE_DIR.name}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=7) as archive:
        for path in sorted(PACKAGE_DIR.rglob("*")):
            if path.is_file():
                archive.write(path, (Path(PACKAGE_DIR.name) / path.relative_to(PACKAGE_DIR)).as_posix())
    checksum_path = zip_path.with_suffix(zip_path.suffix + ".sha256")
    checksum_path.write_text(f"{sha256(zip_path)}  {zip_path.name}\n", encoding="ascii")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["prepare", "finalize"])
    args = parser.parse_args()
    if args.phase == "prepare":
        prepare_package()
    else:
        finalize_package()


if __name__ == "__main__":
    main()
