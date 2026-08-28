from __future__ import annotations

import csv
import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DELIVERABLES = ROOT / "deliverables"
PACKAGE = DELIVERABLES / "appoint_professeur_structure_bases_longitudinales"
ZIP_PATH = DELIVERABLES / f"{PACKAGE.name}.zip"
WORKBOOK_DATA = ROOT / "work_professor_structure_20260805" / "workbook_data.json"
CURRENT = ROOT / "outputs" / "v2" / "priority_3000_final"
RAW_ROOT = ROOT.parent / "pour_moi_avec_data" / "data" / "raw"
RAW_ARCHIVE_NAMES = (
    "political_leg_1962_csv.zip",
    "political_leg_1986_csv.zip",
    "political_leg_2022_csv.zip",
    "socio_csp_csv.zip",
)
USED_CODE_FILES = (
    "code_longitudinal/__init__.py",
    "code_longitudinal/balance_checks.py",
    "code_longitudinal/build_common_panel_v2.py",
    "code_longitudinal/build_panel.py",
    "code_longitudinal/data_io.py",
    "code_longitudinal/paths.py",
    "code_longitudinal/prepare_inputs.py",
    "code_longitudinal/prepare_priority_v2.py",
    "code_longitudinal/spec_registry.py",
    "code_longitudinal/utils.py",
    "config/run_settings.json",
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str] | None = None) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    data = json.loads(WORKBOOK_DATA.read_text(encoding="utf-8"))
    bases = PACKAGE / "bases_actuelles"
    future = PACKAGE / "schema_futur"
    panel_dir = PACKAGE / "panel"
    inputs_dir = PACKAGE / "analysis_inputs"
    raw_dir = PACKAGE / "sources_brutes_cage_piketty"
    code_dir = PACKAGE / "code_utilise"
    bases.mkdir(parents=True, exist_ok=True)
    future.mkdir(parents=True, exist_ok=True)
    panel_dir.mkdir(parents=True, exist_ok=True)
    inputs_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    code_dir.mkdir(parents=True, exist_ok=True)

    for name in RAW_ARCHIVE_NAMES:
        shutil.copy2(RAW_ROOT / "archives" / name, raw_dir / name)
    shutil.copy2(RAW_ROOT / "README.md", raw_dir / "README_SOURCE_ORIGINALE.md")

    source_manifest = read_csv(RAW_ROOT / "metadata" / "download_manifest.csv")
    selected_sources = [
        row for row in source_manifest if row.get("dataset_id") in set(name.removesuffix(".zip") for name in RAW_ARCHIVE_NAMES)
    ]
    write_csv(raw_dir / "provenance_sources.csv", selected_sources)

    for relative_name in USED_CODE_FILES:
        source = ROOT / relative_name
        destination = code_dir / relative_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    workbook_source = (
        DELIVERABLES
        / "professeur_structure_sorties_longitudinales_3000"
        / "TABLES_EXEMPLES_STRUCTURE_SORTIES.xlsx"
    )
    shutil.copy2(workbook_source, PACKAGE / workbook_source.name)

    obsolete_panel_extract = bases / "panel_v2_extrait_20_communes.csv"
    if obsolete_panel_extract.exists():
        obsolete_panel_extract.unlink()

    for name in [
        "panel_3000_common_1962_1986_2022_v2.csv",
        "panel_3000_common_1962_1986_2022_v2_balance.csv",
        "panel_3000_common_1962_1986_2022_v2_attempts.csv",
        "panel_3000_common_1962_1986_2022_v2_manifest.json",
    ]:
        shutil.copy2(ROOT / "panel" / name, panel_dir / name)

    for year in [1962, 1986, 2022]:
        for hypothesis in ["H0A", "H1", "H2", "H4"]:
            stem = (
                f"leg_{year}_r1__{hypothesis}__"
                "panel_3000_common_1962_1986_2022_seed_20260802_v2__n3000"
            )
            for suffix in [".csv", "__manifest.json"]:
                source = ROOT / "outputs" / "model_ready" / f"{stem}{suffix}"
                shutil.copy2(source, inputs_dir / source.name)

    for source_name, destination_name in [
        ("aggregate_drawwise_corrected_3000_v1.csv", "resultats_krt_agreges.csv"),
        ("within_period_contrasts_3000_v1.csv", "contrastes_krt.csv"),
        ("nls_contrasts_3000_v1.csv", "contrastes_nls.csv"),
        ("nls_krt_comparison_3000_v1.csv", "comparaison_krt_nls.csv"),
    ]:
        shutil.copy2(CURRENT / source_name, bases / destination_name)

    krt_diagnostics = read_csv(CURRENT / "canonical_mcmc_diagnostics_3000_v1.csv")
    krt_fields = [
        "run_id",
        "election_id",
        "year",
        "scenario_id",
        "fit_status",
        "mcmc_assessment_label",
        "beta_diagnostic_status",
        "non_beta_parameter_status",
        "identification_status",
        "saved_chains",
        "saved_draws_per_chain",
        "max_rhat",
        "min_ess_bulk",
        "min_ess_tail",
        "divergences",
    ]
    write_csv(bases / "diagnostics_krt_simplifies.csv", krt_diagnostics, krt_fields)

    nls_diagnostics = read_csv(CURRENT / "nls_model_diagnostics_3000_v1.csv")
    nls_fields = [
        "election_id",
        "scenario_id",
        "year",
        "n_communes",
        "elapsed_seconds",
        "optimizer_success",
        "diagnostic_status",
        "n_starts",
        "n_successful_starts",
        "sandwich_condition_info",
        "max_abs_prediction_difference_from_best",
    ]
    write_csv(bases / "diagnostics_nls_simplifies.csv", nls_diagnostics, nls_fields)
    write_csv(bases / "resultats_communaux_krt_extrait.csv", data["commune_results"])

    write_csv(PACKAGE / "inventaire_tables.csv", data["schema_tables"])
    write_csv(future / "resultats_long_exemple.csv", data["long_results"])
    write_csv(future / "diagnostics_unifies_exemple.csv", data["diagnostics"])
    write_csv(future / "dictionnaire_variables.csv", data["dictionary"])

    manifest = {
        "package": PACKAGE.name,
        "purpose": "supplement for reviewing raw sources, the exact V2 data-preparation code, and current/proposed longitudinal database structures",
        "estimated_panel_version": "v2",
        "future_panel_version": "v3",
        "files": [],
    }
    manifest_path = PACKAGE / "manifest.json"
    for path in sorted(PACKAGE.rglob("*")):
        if path.is_file() and path != manifest_path:
            manifest["files"].append(
                {
                    "path": path.relative_to(PACKAGE).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=7) as archive:
        for path in sorted(PACKAGE.rglob("*")):
            if path.is_file():
                archive.write(path, (Path(PACKAGE.name) / path.relative_to(PACKAGE)).as_posix())
    ZIP_PATH.with_suffix(ZIP_PATH.suffix + ".sha256").write_text(
        f"{sha256(ZIP_PATH)}  {ZIP_PATH.name}\n",
        encoding="ascii",
    )


if __name__ == "__main__":
    main()
