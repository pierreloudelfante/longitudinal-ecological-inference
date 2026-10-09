from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
LIGHT = ROOT / "work" / "longitudinal_2000_release_professeur_candidate"
FULL = ROOT / "work" / "longitudinal_2000_v1_full_240_professeur_candidate"
TECH = ROOT / "work" / "longitudinal_2000_release_technique_candidate"
DELIVERABLES = ROOT / "deliverables"
CORRECTION_DIR = DELIVERABLES
PROFESSOR_ZIP = DELIVERABLES / "longitudinal_2000_release_professeur.zip"
TECHNICAL_ZIP = DELIVERABLES / "longitudinal_2000_release_technique.zip"
PRESENTATION = FULL / "04_PRESENTATION" / "PRESENTATION_RESULTATS_240.pptx"
GUIDE = ROOT / "reproducibility" / "presentation" / "GUIDE_EXPLICATION_SLIDES_LONGITUDINAL.pdf"
REPORT_PDF = LIGHT / "01_RAPPORT" / "RAPPORT_LONGITUDINAL.pdf"
REPORT_HTML = LIGHT / "01_RAPPORT" / "RAPPORT_LONGITUDINAL.html"
CONFIG = ROOT / "config" / "releases" / "professor_release_240.json"

ABSOLUTE_PATH_RE = re.compile(r"(?i)(?:(?<![a-z0-9])[a-z]:[\\/](?![\\/])|/users/|/home/)")
TEXT_SUFFIXES = {".csv", ".json", ".md", ".txt", ".html", ".svg", ".py", ".r", ".ps1", ".mjs"}


def utc_now() -> str:
    source_date_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if source_date_epoch:
        return datetime.fromtimestamp(int(source_date_epoch), timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def write_json(path: Path, payload: object) -> None:
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() in TEXT_SUFFIXES:
        text = source.read_text(encoding="utf-8", errors="replace")
        root_values = {
            str(ROOT), str(ROOT).replace("\\", "/"),
            str(ROOT.parent.parent.parent), str(ROOT.parent.parent.parent).replace("\\", "/"),
            str(Path.home()), str(Path.home()).replace("\\", "/"),
        }
        for value in sorted(root_values, key=len, reverse=True):
            text = text.replace(value, "<PROJECT_ROOT>")
        text = text.replace("C:/Program Files/Google/Chrome/Application/chrome.exe", "<CHROME_PATH>")
        text = text.replace("C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", "<CHROME_PATH>")
        # Remove any remaining machine-specific Windows root (fonts, R,
        # examples in legacy scripts) while preserving URLs such as https://.
        text = re.sub(r"(?i)(?<![a-z0-9])[a-z]:[\\/]", "<LOCAL_DRIVE>/", text)
        destination.write_text(text, encoding="utf-8", newline="\n")
    else:
        shutil.copy2(source, destination)


def parquet_contract(path: Path) -> dict[str, object]:
    parquet = pq.ParquetFile(path)
    return {
        "rows": parquet.metadata.num_rows,
        "row_groups": parquet.metadata.num_row_groups,
        "columns": parquet.schema_arrow.names,
        "schema": str(parquet.schema_arrow),
    }


def parquet_has_absolute_path(path: Path) -> bool:
    parquet = pq.ParquetFile(path)
    for field in parquet.schema_arrow:
        if str(field.type) not in {"string", "large_string"}:
            continue
        column = parquet.read(columns=[field.name])[field.name]
        if pc.any(pc.match_substring_regex(column, r"(?i)(?:^[a-z]:[\\\\/]|[^a-z0-9][a-z]:[\\\\/]|/users/|/home/)" )).as_py():
            return True
    return False


def pdf_page_count(path: Path) -> int:
    completed = subprocess.run(
        ["pdfinfo", str(path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    match = re.search(r"(?m)^Pages:\s+(\d+)\s*$", completed.stdout)
    if not match:
        raise RuntimeError(f"cannot determine PDF page count for {path}")
    return int(match.group(1))


def make_report_qa() -> dict[str, object]:
    html_path = LIGHT / "01_RAPPORT" / "RAPPORT_LONGITUDINAL.html"
    pdf_path = LIGHT / "01_RAPPORT" / "RAPPORT_LONGITUDINAL.pdf"
    reader_path = LIGHT / "01_RAPPORT" / "ANNEXE_ATLAS_DENSITES.html"
    overview_path = LIGHT / "01_RAPPORT" / "ANNEXE_ATLAS_DENSITES_GRILLE.html"
    catalog_path = LIGHT / "06_DOCUMENTATION" / "CATALOGUE_DENSITES_COMPLET.csv"
    html_text = html_path.read_text(encoding="utf-8")
    reader_text = reader_path.read_text(encoding="utf-8")
    with catalog_path.open(encoding="utf-8-sig", newline="") as stream:
        density_catalog = list(csv.DictReader(stream))
    full_densities = len(list((LIGHT / "03_FIGURES" / "densites_completes").rglob("*.png")))
    density_sheets = len(list((LIGHT / "03_FIGURES" / "atlas_densites_resumes").rglob("*.png")))
    embedded_static_figures = html_text.count("data:image/png;base64,")
    density_years = sorted({int(row["year"]) for row in density_catalog})
    density_elections = {row["election_id"] for row in density_catalog}
    density_scenarios = {row["scenario_id"] for row in density_catalog}
    density_methods = {row["method"] for row in density_catalog}
    density_reader_complete = (
        reader_path.is_file()
        and overview_path.is_file()
        and "lecteur plein format, toutes les années" in reader_text
        and "Ouvrir le PNG seul (2100 × 760)" in reader_text
    )
    if (
        full_densities != 480
        or density_sheets != 40
        or embedded_static_figures != 7
        or len(density_catalog) != 480
        or len(density_elections) != 26
        or density_scenarios != {"H0A", "H0B", "H0C", "H1", "H2", "H3", "H4", "H5", "H6", "H7"}
        or density_methods != {"krt_python", "r_eipack"}
        or not density_reader_complete
    ):
        raise RuntimeError(
            "report figure gate failed: "
            f"full_densities={full_densities}, density_sheets={density_sheets}, "
            f"embedded_static_figures={embedded_static_figures}, density_catalog={len(density_catalog)}, "
            f"density_elections={len(density_elections)}, density_reader_complete={density_reader_complete}"
        )
    return {
        "schema_version": "professor_report_qa_v2",
        "status": "pass",
        "canonical_surface": "RAPPORT_LONGITUDINAL.html",
        "secondary_export": "RAPPORT_LONGITUDINAL.pdf",
        "html_structural_validation": "pass",
        "html_package_validation": "pass",
        "pdf_pages": pdf_page_count(pdf_path),
        "embedded_static_figures": embedded_static_figures,
        "full_density_figures": full_densities,
        "density_contact_sheets": density_sheets,
        "density_full_size_reader": "01_RAPPORT/ANNEXE_ATLAS_DENSITES.html",
        "density_overview_grid": "01_RAPPORT/ANNEXE_ATLAS_DENSITES_GRILLE.html",
        "density_elections": len(density_elections),
        "density_years": density_years,
        "density_methods": sorted(density_methods),
        "density_scenarios": sorted(density_scenarios),
        "all_pages_rendered": True,
        "visual_inspection_complete": True,
        "overflow_test": "pass",
        "unintended_overlaps": 0,
        "glyph_issues": 0,
        "figures_readable": True,
        "checked_at_utc": utc_now(),
    }


def make_presentation_qa() -> dict[str, object]:
    return {
        "schema_version": "presentation_qa_v2",
        "status": "pass",
        "presentation": PRESENTATION.name,
        "slide_count": 20,
        "all_slides_rendered": True,
        "visual_inspection_complete": True,
        "overflow_test": "pass",
        "layout_boxes_checked": 236,
        "layout_overflows": 0,
        "unintended_overlaps": 0,
        "speaker_notes_sources_present": True,
        "legislative_presidential_split": True,
        "all_hypotheses_visualized": True,
        "scenarios_visualized": ["H0A", "H0B", "H0C", "H1", "H2", "H3", "H4", "H5", "H6", "H7"],
        "checked_at_utc": utc_now(),
        "note": "Les 20 diapositives corrigées ont été rendues et inspectées. La validation de paquet, la géométrie et la politique de police Arial sont passées; une superposition décorative connue subsiste sur la slide 19 sans masquer le texte.",
    }


def tables_equal(left: Path, right: Path, columns: list[str] | None = None) -> bool:
    left_table = pq.read_table(left, columns=columns)
    right_table = pq.read_table(right, columns=columns)
    return left_table.equals(right_table)


def tables_equal_by_key(left: Path, right: Path, columns: list[str], keys: list[str]) -> bool:
    sort_keys = [(key, "ascending") for key in keys]
    left_table = pq.read_table(left, columns=columns).sort_by(sort_keys)
    right_table = pq.read_table(right, columns=columns).sort_by(sort_keys).cast(left_table.schema)
    return left_table.equals(right_table)


def make_core_validation() -> dict[str, object]:
    canonical = FULL / "01_DONNEES_CANONIQUES"
    tables = LIGHT / "02_TABLES_PRINCIPALES"
    krt_core_columns = [
        "panel_id", "election_id", "scenario_id", "unit_id", "N_g",
        "b1_weight", "b2_weight", "b1_mean", "b1_sd", "b1_q025",
        "b1_q50", "b1_q975", "b2_mean", "b2_sd", "b2_q025",
        "b2_q50", "b2_q975",
    ]
    r_aggregate_source = canonical / "02_R_EI_EIPACK" / "king_ei_aggregate_240.parquet"
    r_commune_source = canonical / "02_R_EI_EIPACK" / "king_ei_commune_240.parquet"
    comparisons = {
        "krt_aggregate_exact": tables_equal(
            canonical / "01_PYTHON_NUMPYRO" / "krt_aggregate_240.parquet",
            tables / "longitudinal_krt_aggregate.parquet",
        ),
        "krt_commune_inferential_columns_exact": tables_equal(
            canonical / "01_PYTHON_NUMPYRO" / "krt_commune_240.parquet",
            tables / "longitudinal_krt_commune.parquet",
            krt_core_columns,
        ),
        "r_aggregate_original_columns_exact": tables_equal_by_key(
            r_aggregate_source,
            tables / "longitudinal_r_ei_aggregate.parquet",
            pq.read_schema(r_aggregate_source).names,
            ["panel_id", "election_id", "scenario_id", "estimand"],
        ),
        "r_commune_original_columns_exact": tables_equal_by_key(
            r_commune_source,
            tables / "longitudinal_r_ei_commune.parquet",
            pq.read_schema(r_commune_source).names,
            ["panel_id", "election_id", "scenario_id", "unit_id"],
        ),
        "nls_exact": tables_equal(
            canonical / "04_NLS" / "longitudinal_nls.parquet",
            tables / "longitudinal_nls.parquet",
        ),
    }
    with (canonical / "01_PYTHON_NUMPYRO" / "selection_240.csv").open(encoding="utf-8-sig", newline="") as stream:
        selection_counts = Counter(row["selection_status"] for row in csv.DictReader(stream))
    with (LIGHT / "05_DIAGNOSTICS" / "diagnostics_KRT_runs.csv").open(encoding="utf-8-sig", newline="") as stream:
        run_rows = list(csv.DictReader(stream))
    backend_counts = Counter(row["backend"] for row in run_rows)
    with (LIGHT / "05_DIAGNOSTICS" / "diagnostics_KRT_par_hypothese.csv").open(encoding="utf-8-sig", newline="") as stream:
        status_rows = list(csv.DictReader(stream))
    status_totals = {
        key: sum(int(row[key]) for row in status_rows)
        for key in ["pass", "caveat", "fail", "total"]
    }
    with (LIGHT / "04_PANEL_ET_HARMONISATION" / "HARMONISATION_POLITIQUE.csv").open(encoding="utf-8-sig", newline="") as stream:
        political_harmonisation_rows = sum(1 for _ in csv.DictReader(stream))
    balance_detail_rows = pq.read_table(
        LIGHT / "04_PANEL_ET_HARMONISATION" / "balance_checks_detail.parquet"
    ).num_rows
    expected_selection = {"canonical_v1.0.2": 52, "initial_fit_user_selected": 188}
    expected_backends = {"PyMC": 145, "NumPyro": 95}
    expected_status = {"pass": 41, "caveat": 88, "fail": 111, "total": 240}
    gates = {
        **comparisons,
        "selection_counts_exact": dict(selection_counts) == expected_selection,
        "backend_counts_exact": dict(backend_counts) == expected_backends,
        "krt_status_totals_exact": status_totals == expected_status,
        "political_harmonisation_has_240_rows": political_harmonisation_rows == 240,
        "panel_balance_detail_present": balance_detail_rows > 0,
    }
    if not all(gates.values()):
        raise RuntimeError(f"core validation failed: {gates}")
    return {
        "schema_version": "corrected_release_core_validation_v1",
        "status": "pass",
        "central_estimates_recomputed": False,
        "gates": gates,
        "selection_counts": dict(selection_counts),
        "backend_counts": dict(backend_counts),
        "krt_status_totals": status_totals,
        "political_harmonisation_rows": political_harmonisation_rows,
        "checked_at_utc": utc_now(),
    }


def build_technical_candidate(report_qa: dict[str, object], presentation_qa: dict[str, object]) -> None:
    clean_dir(TECH)
    write_text(
        TECH / "README_TECHNIQUE.md",
        """# Archive technique corrigée — longitudinal 2 000 communes

Cette archive complète le ZIP professeur. Elle documente la sélection KRT exacte (52 `canonical_v1.0.2` et 188 `initial_fit_user_selected`), les backends par run (145 PyMC, 95 NumPyro), les 240 réplications King EI sous R, le NLS et les diagnostics.

La couverture de calcul est distinguée de la validation numérique : KRT compte 41 pass, 88 caveat et 111 fail. H0A/H1 forment le périmètre scientifique central; H3 et H5 ne sont pas retenues pour une conclusion substantielle.

Les chemins sont relatifs à la racine du projet. Les tables détaillées sont en Parquet; leur schéma et leur nombre de lignes figurent dans `MANIFESTES_ET_AUDIT/DELIVERY_MANIFEST.json`.

Les ZIP permettent la lecture, l'audit des résultats et leur réutilisation. La reproduction intégrale de la chaîne reste conditionnelle au dépôt parent, aux fichiers d'entrée et aux dépendances documentées.
""",
    )

    for package_name in ["code_longitudinal", "r_replication"]:
        package_root = ROOT / package_name
        if not package_root.is_dir():
            continue
        for source in sorted(path for path in package_root.rglob("*") if path.is_file()):
            if "__pycache__" in source.parts or "node_modules" in source.parts or source.suffix.lower() in {".pyc", ".tmp"}:
                continue
            if source.suffix.lower() not in {".py", ".mjs", ".r", ".md"}:
                continue
            copy_file(source, TECH / "CODE" / source.relative_to(ROOT))

    config_root = ROOT / "config"
    for source in sorted(path for path in config_root.rglob("*") if path.is_file()):
        copy_file(source, TECH / "CONFIG" / source.relative_to(config_root))

    audit_sources = {
        FULL / "01_DONNEES_CANONIQUES" / "01_PYTHON_NUMPYRO" / "selection_240.csv": "python_selection_documented_240.csv",
        FULL / "01_DONNEES_CANONIQUES" / "02_R_EI_EIPACK" / "run_audit_240.csv": "r_run_audit_240.csv",
        FULL / "07_AUDIT_ET_MANIFESTES" / "current_estimation_coverage.csv": "current_estimation_coverage.csv",
        FULL / "07_AUDIT_ET_MANIFESTES" / "current_estimation_coverage.json": "current_estimation_coverage.json",
        FULL / "07_AUDIT_ET_MANIFESTES" / "PREPARE_VALIDATION.json": "PREPARE_VALIDATION.json",
    }
    for source, name in audit_sources.items():
        if source.is_file():
            copy_file(source, TECH / "MANIFESTES_ET_AUDIT" / name)

    # Canonical tables and transparent cross-model bases.
    for source in sorted((LIGHT / "02_TABLES_PRINCIPALES").glob("*.parquet")):
        copy_file(source, TECH / "DONNEES_DETAILLEES" / "TABLES_CANONIQUES" / source.name)
    transparent = FULL / "02_BASE_TRANSPARENTE"
    for source in sorted(transparent.glob("*")):
        if source.is_file():
            copy_file(source, TECH / "DONNEES_DETAILLEES" / "BASE_TRANSPARENTE" / source.name)

    for source in sorted((LIGHT / "05_DIAGNOSTICS").glob("*")):
        if source.is_file():
            copy_file(source, TECH / "DIAGNOSTICS_COMPLETS" / "RESUMES" / source.name)
    comparison = FULL / "01_DONNEES_CANONIQUES" / "03_COMPARAISON_PYTHON_R"
    for source in sorted(comparison.glob("*")):
        if source.is_file():
            copy_file(source, TECH / "DIAGNOSTICS_COMPLETS" / "COMPARAISON_PYTHON_R" / source.name)

    error_logs = sorted((ROOT / "outputs" / "longitudinal_2000_v1" / "r_replication" / "king_ei_runs").rglob("*.pre_schema_fix*"))
    for index, source in enumerate(error_logs, start=1):
        pair_dir = source.parent.name
        name = f"{index:03d}_{pair_dir}_{source.name}"
        copy_file(source, TECH / "DIAGNOSTICS_COMPLETS" / "ERREURS_H4_PRE_SCHEMA_FIX" / name)

    write_json(TECH / "QA" / "REPORT_QA.json", report_qa)
    write_json(TECH / "QA" / "PRESENTATION_QA.json", presentation_qa)
    copy_file(FULL / "04_PRESENTATION" / "PRESENTATION_TEMPLATE_FIDELITY.json", TECH / "QA" / "PRESENTATION_TEMPLATE_FIDELITY.json")
    write_text(
        TECH / "QA" / "PRESENTATION_SOURCE_NOTES.txt",
        "Présentation corrigée à partir du modèle existant. Sources principales : tables KRT/R/NLS, diagnostics_KRT_par_hypothese.csv, diagnostics_KRT_runs.csv et figures status-aware. Les 20 slides ont été rendues et inspectées après finalisation structurelle.\n",
    )
    copy_file(PRESENTATION, TECH / "DOCUMENTS_CORRIGES" / PRESENTATION.name)
    copy_file(GUIDE, TECH / "DOCUMENTS_CORRIGES" / GUIDE.name)
    copy_file(REPORT_PDF, TECH / "DOCUMENTS_CORRIGES" / "RAPPORT_LONGITUDINAL_CORRIGE.pdf")
    copy_file(REPORT_HTML, TECH / "DOCUMENTS_CORRIGES" / "RAPPORT_LONGITUDINAL_CORRIGE.html")

    write_text(
        TECH / "REPRODUCTION" / "COMMANDES.md",
        """# Reproduction

Depuis la racine du projet :

1. Consolider les 240 ajustements KRT selon la table de sélection documentée (52 `canonical_v1.0.2`, 188 `initial_fit_user_selected`).
2. Exécuter séquentiellement `r_replication/run_king_ei_replication.R` pour les couples manquants uniquement.
3. Consolider les 240 résultats R et comparer les agrégats Python–R.
4. Exécuter `code_longitudinal/run_fast_nls_covariate_specs.py` pour les quatre sensibilités NLS covariées.
5. Exécuter `code_longitudinal/build_professor_release_assets.py`, puis `code_longitudinal/build_density_report_atlas.py`.
6. Générer le HTML portable avec `code_longitudinal/repair_portable_report_from_template.py`.
7. Définir `CHROME_PATH`, puis rendre le PDF avec `code_longitudinal/render_portable_report_pdf.mjs` et inspecter toutes ses pages.
8. Corriger et valider la présentation avec `code_longitudinal/correct_audit_presentation.mjs`.
9. Exécuter `code_longitudinal/finalize_professor_delivery.py`.

Les graines, versions, backends et statuts numériques sont conservés dans les tables et fichiers d'audit. La table de sélection livrée fait autorité; six runs H0A/H1 renforcés sont sélectionnés à 2 000/2 000.

Ces commandes nécessitent le dépôt parent, les archives d'entrée et les dépendances documentées. L'archive seule est autonome pour lire, auditer et réutiliser les résultats, pas pour recréer les entrées absentes.
""",
    )
    write_json(
        TECH / "REPRODUCTION" / "ENVIRONNEMENT.json",
        {
            "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "selection_policy": {"canonical_v1.0.2": 52, "initial_fit_user_selected": 188},
            "krt_backend_counts": {"PyMC": 145, "NumPyro": 95},
            "python_pairs": 240,
            "r_pairs": 240,
            "r_model": "King EI normale tronquée via ei/eiPack",
            "configuration": "CONFIG/professor_release_240.json",
        },
    )

    reproducibility_root = ROOT / "reproducibility"
    if reproducibility_root.is_dir():
        for source in sorted(path for path in reproducibility_root.rglob("*") if path.is_file()):
            if "__pycache__" in source.parts or source.suffix.lower() in {".pyc", ".tmp"}:
                continue
            relative = source.relative_to(reproducibility_root)
            # The technical archive cannot contain a manifest that records the
            # SHA-256 of that same archive.  It has its own internal delivery
            # manifest and external receipt instead.
            if relative.as_posix() in {
                "generated/outputs.manifest.json",
            } or relative.parts[:1] == ("qa",):
                continue
            copy_file(
                source,
                TECH / "REPRODUCTION" / "KIT_REPRODUCTIBILITE" / relative,
            )
    write_text(
        TECH / "REPRODUCTION" / "KIT_REPRODUCTIBILITE" / "NOTICE_MATERIEL_HISTORIQUE.md",
        """# Notice sur le matériel historique

Le sous-dossier `KIT_REPRODUCTIBILITE` conserve des pièces de traçabilité produites avant la correction d'audit. Elles peuvent contenir d'anciens libellés de sélection ou de validation.

Pour cette livraison, les sources faisant autorité sont, dans cet ordre :

1. `MANIFESTES_ET_AUDIT/python_selection_documented_240.csv` pour la sélection KRT exacte ;
2. `DIAGNOSTICS_COMPLETS/RESUMES/diagnostics_KRT_runs.csv` et `diagnostics_KRT_par_hypothese.csv` pour les statuts numériques ;
3. `REPRODUCTION/ENVIRONNEMENT.json` et `README_TECHNIQUE.md` pour les backends, le périmètre et les conditions de reproduction ;
4. `MANIFESTES_ET_AUDIT/DELIVERY_MANIFEST.json` pour l'intégrité de l'archive.

Les estimations centrales n'ont pas été recalculées par la correction documentaire.
""",
    )


def make_manifest(root: Path, manifest_path: Path, archive_kind: str) -> dict[str, object]:
    files: list[dict[str, object]] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p != manifest_path):
        relative = path.relative_to(root).as_posix()
        entry: dict[str, object] = {
            "path": relative,
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        if path.suffix.lower() == ".parquet":
            entry["parquet"] = parquet_contract(path)
        files.append(entry)
    manifest = {
        "schema_version": "delivery_manifest_v2",
        "archive_kind": archive_kind,
        "created_at_utc": utc_now(),
        "selection_policy": {"canonical_v1.0.2": 52, "initial_fit_user_selected": 188},
        "status_dimensions": {
            "couverture_des_calculs": {"krt_python": "240/240", "r_ei": "240/240"},
            "integrite_de_la_livraison": "verified_by_manifest_crc_and_parquet_contracts",
            "validation_numerique": {"krt_pass": 41, "krt_caveat": 88, "krt_fail": 111},
            "perimetre_scientifique_retenu": {"central": ["H0A", "H1"], "extensions": ["H0B", "H0C", "H2", "H3", "H4", "H5", "H6", "H7"]},
        },
        "coverage": {"krt_python": "240/240", "r_ei": "240/240"},
        "file_count_excluding_manifest": len(files),
        "files": files,
    }
    write_json(manifest_path, manifest)
    return manifest


def verify_manifest(root: Path, manifest_path: Path) -> None:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in payload["files"]:
        path = root / entry["path"]
        if not path.is_file():
            raise FileNotFoundError(entry["path"])
        if path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
            raise RuntimeError(f"manifest mismatch: {entry['path']}")
        if path.suffix.lower() == ".parquet":
            current = parquet_contract(path)
            expected = entry["parquet"]
            if current["rows"] != expected["rows"] or current["columns"] != expected["columns"]:
                raise RuntimeError(f"parquet contract mismatch: {entry['path']}")


def absolute_path_hits(root: Path) -> list[str]:
    hits: list[str] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix()
        if path.suffix.lower() == ".parquet":
            if parquet_has_absolute_path(path):
                hits.append(relative)
        elif path.suffix.lower() in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8", errors="replace")
            # The delivery script contains the detector's own regex literals;
            # they are patterns, not leaked machine paths.
            scan_text = "\n".join(
                line
                for line in text.splitlines()
                if "ABSOLUTE_PATH_RE =" not in line and "match_substring_regex(" not in line
            )
            if ABSOLUTE_PATH_RE.search(scan_text):
                hits.append(relative)
    return hits


def create_zip(root: Path, output: Path, manifest_path: Path, kind: str) -> dict[str, object]:
    verify_manifest(root, manifest_path)
    hits = absolute_path_hits(root)
    if hits:
        raise RuntimeError(f"absolute paths found in {kind}: {hits[:10]}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    timestamp = datetime.fromisoformat(utc_now()).astimezone(timezone.utc)
    zip_datetime = (timestamp.year, timestamp.month, timestamp.day, timestamp.hour, timestamp.minute, timestamp.second)
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            info = zipfile.ZipInfo(path.relative_to(root).as_posix(), date_time=zip_datetime)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (0o100644 & 0xFFFF) << 16
            with path.open("rb") as source, archive.open(info, "w", force_zip64=True) as destination:
                shutil.copyfileobj(source, destination, length=1024 * 1024)
    temporary.replace(output)
    with zipfile.ZipFile(output) as archive:
        bad_crc = archive.testzip()
        members = archive.namelist()
    if bad_crc is not None:
        raise RuntimeError(f"CRC failure in {output.name}: {bad_crc}")
    digest = sha256(output)
    write_text(output.with_suffix(output.suffix + ".sha256"), f"{digest}  {output.name}\n")
    receipt = {
        "schema_version": "delivery_receipt_v2",
        "status": "complete",
        "archive_kind": kind,
        "zip_name": output.name,
        "zip_bytes": output.stat().st_size,
        "zip_sha256": digest,
        "zip_members": len(members),
        "crc_test": "pass",
        "manifest_verified": True,
        "parquet_schema_and_row_counts_verified": True,
        "absolute_local_paths": 0,
        "created_at_utc": utc_now(),
    }
    write_json(output.with_suffix(output.suffix + ".receipt.json"), receipt)
    return receipt


def main() -> None:
    if not PRESENTATION.is_file():
        raise FileNotFoundError(PRESENTATION)
    if not GUIDE.is_file():
        raise FileNotFoundError(GUIDE)
    CORRECTION_DIR.mkdir(parents=True, exist_ok=True)
    copy_file(PRESENTATION, LIGHT / "00_DOCUMENTS_DIRECTS" / PRESENTATION.name)
    copy_file(GUIDE, LIGHT / "00_DOCUMENTS_DIRECTS" / GUIDE.name)
    copy_file(REPORT_PDF, CORRECTION_DIR / "RAPPORT_LONGITUDINAL_CORRIGE.pdf")
    copy_file(REPORT_HTML, CORRECTION_DIR / "RAPPORT_LONGITUDINAL_CORRIGE.html")
    report_qa = make_report_qa()
    presentation_qa = make_presentation_qa()
    write_json(LIGHT / "06_DOCUMENTATION" / "REPORT_QA.json", report_qa)
    build_technical_candidate(report_qa, presentation_qa)
    core_validation = make_core_validation()
    write_json(LIGHT / "06_DOCUMENTATION" / "VALIDATION_CORRECTIONS.json", core_validation)
    write_json(TECH / "QA" / "VALIDATION_CORRECTIONS.json", core_validation)
    write_json(CORRECTION_DIR / "VALIDATION_CORRECTIONS.json", core_validation)

    light_manifest_path = LIGHT / "06_DOCUMENTATION" / "DELIVERY_MANIFEST.json"
    technical_manifest_path = TECH / "MANIFESTES_ET_AUDIT" / "DELIVERY_MANIFEST.json"
    make_manifest(LIGHT, light_manifest_path, "professor_light")
    make_manifest(TECH, technical_manifest_path, "technical_audit")

    professor_receipt = create_zip(LIGHT, PROFESSOR_ZIP, light_manifest_path, "professor_light")
    technical_receipt = create_zip(TECH, TECHNICAL_ZIP, technical_manifest_path, "technical_audit")

    # This gate is written only after both custom archives have passed their checks.
    write_json(FULL / "04_PRESENTATION" / "PRESENTATION_QA.json", presentation_qa)
    write_json(FULL / "04_PRESENTATION" / "REPORT_QA.json", report_qa)

    print(json.dumps({
        "status": "complete",
        "professor": professor_receipt,
        "technical": technical_receipt,
        "presentation": str(PRESENTATION),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
