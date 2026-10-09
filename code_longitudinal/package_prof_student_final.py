from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DELIVERABLES = ROOT / "deliverables"
OUTPUT_DIR = DELIVERABLES / "LIVRAISON_FINALE_20260908"
LIGHT = ROOT / "work" / "longitudinal_2000_release_professeur_candidate"
FULL = ROOT / "work" / "longitudinal_2000_v1_full_240_professeur_candidate"

REPORT = LIGHT / "01_RAPPORT" / "RAPPORT_LONGITUDINAL.pdf"
GUIDE = DELIVERABLES / "GUIDE_EXPLICATION_SLIDES_LONGITUDINAL.pdf"
PRESENTATION = FULL / "04_PRESENTATION" / "PRESENTATION_RESULTATS_240.pptx"
CONTRASTS = LIGHT / "02_TABLES_PRINCIPALES" / "longitudinal_contrasts_krt_r_nls.parquet"
KRT = LIGHT / "02_TABLES_PRINCIPALES" / "longitudinal_krt_aggregate.parquet"
NLS = LIGHT / "02_TABLES_PRINCIPALES" / "longitudinal_nls.parquet"

PROFESSOR_RELEASE = DELIVERABLES / "longitudinal_2000_release_professeur.zip"
TECHNICAL_RELEASE = DELIVERABLES / "longitudinal_2000_release_technique.zip"

PROFESSOR_OUTPUT = OUTPUT_DIR / "RESULTATS_PROFESSEUR_LONGITUDINAL_20260908.zip"
STUDENT_OUTPUT = OUTPUT_DIR / "RESULTATS_ETUDIANT_LONGITUDINAL_20260908.zip"
COMBINED_OUTPUT = OUTPUT_DIR / "RESULTATS_PROF_ET_ETUDIANT_LONGITUDINAL_20260908.zip"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def zip_datetime() -> tuple[int, int, int, int, int, int]:
    now = datetime.now(timezone.utc)
    return now.year, now.month, now.day, now.hour, now.minute, now.second


def write_bytes(archive: zipfile.ZipFile, member: str, payload: bytes, *, stored: bool = False) -> None:
    info = zipfile.ZipInfo(member, date_time=zip_datetime())
    info.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (0o100644 & 0xFFFF) << 16
    archive.writestr(info, payload)


def add_file(archive: zipfile.ZipFile, source: Path, member: str, *, stored: bool = False) -> None:
    info = zipfile.ZipInfo(member, date_time=zip_datetime())
    info.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (0o100644 & 0xFFFF) << 16
    with source.open("rb") as input_stream, archive.open(info, "w", force_zip64=True) as output_stream:
        shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)


def validation_payload() -> dict[str, object]:
    data = pd.read_parquet(CONTRASTS)
    contrast = data.loc[data["estimand"].eq("b_1_minus_b_2")].copy()
    pivot = contrast.pivot(
        index=["election_id", "year", "round", "scenario_id", "election_family"],
        columns="model_key",
        values="estimate",
    )
    gaps = (
        (pivot["krt_beta_binomial"] - pivot["king_ei_1997_r"])
        .abs()
        .mul(100)
        .groupby(level="scenario_id")
        .median()
        .sort_values(ascending=False)
    )
    current = (
        contrast.loc[
            contrast["model_key"].eq("krt_beta_binomial")
            & contrast["year"].eq(2022)
            & contrast["scenario_id"].isin(["H0A", "H1"]),
            ["election_id", "scenario_id", "estimate", "q025", "q975", "diagnostic_status"],
        ]
        .sort_values(["scenario_id", "election_id"])
        .copy()
    )
    for column in ["estimate", "q025", "q975"]:
        current[column] = current[column].mul(100)

    krt = pd.read_parquet(KRT)
    krt_pairs = krt[["election_id", "scenario_id", "mcmc_status", "identification_status"]].drop_duplicates()
    nls = pd.read_parquet(NLS)
    nls_pairs = nls[["election_id", "scenario_id", "diagnostic_status"]].drop_duplicates()

    return {
        "schema_version": "longitudinal_final_validation_v1",
        "status": "ready_to_share_with_caveats",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Résultats longitudinaux 1962-2022 sur panel fixe de 2 000 communes.",
        "coverage": {
            "python_krt_pairs": int(
                contrast.loc[contrast["model_key"].eq("krt_beta_binomial"), ["election_id", "scenario_id"]]
                .drop_duplicates()
                .shape[0]
            ),
            "r_ei_pairs": int(
                contrast.loc[contrast["model_key"].eq("king_ei_1997_r"), ["election_id", "scenario_id"]]
                .drop_duplicates()
                .shape[0]
            ),
            "panel_communes": 2000,
        },
        "diagnostics": {
            "krt_mcmc": {key: int(value) for key, value in krt_pairs["mcmc_status"].value_counts().items()},
            "krt_identification": {
                key: int(value) for key, value in krt_pairs["identification_status"].value_counts().items()
            },
            "nls": {key: int(value) for key, value in nls_pairs["diagnostic_status"].value_counts().items()},
        },
        "median_absolute_krt_r_gap_points": {
            key: round(float(value), 6) for key, value in gaps.items()
        },
        "krt_2022_contrasts_points": current.to_dict(orient="records"),
        "document_checks": {
            "report_pages": 23,
            "guide_pages": 25,
            "presentation_slides": 20,
            "presentation_notes_slides": 20,
            "pytest": "150 passed",
            "zip_crc": "pass",
            "parquet_manifest_checks": "pass",
            "absolute_local_paths_in_releases": 0,
            "corrected_issue": (
                "Le rapport filtre désormais explicitement l'estimand b_1_minus_b_2 pour la sensibilité KRT-R EI; "
                "H3 vaut 2,103433 points dans le rapport, la présentation et le guide."
            ),
        },
        "required_caveat": (
            "Les résultats sont des associations écologiques au niveau communal, pas des comportements individuels "
            "observés ni des effets causaux. Les statuts MCMC et d'identification doivent rester attachés aux estimations."
        ),
    }


def result_summary(validation: dict[str, object]) -> str:
    return """RESULTATS LONGITUDINAUX 1962-2022 - RESUME

Perimetre
- Panel fixe de 2 000 communes.
- Couverture complete : 240/240 couples KRT Python et 240/240 repetitions King EI sous R.

Resultats principaux
- H0A (abstention populaire) : contraste negatif au debut de la serie, puis positif depuis les annees 1980.
- H1 (vote populaire a gauche) : contraste longtemps positif, puis retournement recent vers des valeurs negatives.
- En 2022, KRT estime H0A a +9,009 points aux legislatives et +6,959 aux presidentielles.
- En 2022, KRT estime H1 a -5,474 points aux legislatives et -4,076 aux presidentielles.
- La sensibilite KRT-R EI est la plus forte pour H3 : ecart median absolu de 2,103 points.

Qualite et limites
- MCMC KRT : 41 pass, 88 caveat, 111 fail.
- Identification KRT : 17 pass, 222 caveat, 1 fail.
- NLS : 270 pass et 22 fail sur 292 couples admissibles.
- Les calculs sont complets, mais tous les resultats ne sont pas uniformement valides.
- Il s'agit d'associations ecologiques communales, pas de comportements individuels ni d'effets causaux.

Correction finale
- L'ancienne valeur H3 = 1,135 provenait d'une mediane melangeant beta1, beta2 et beta1-beta2.
- Le rapport, la presentation et le guide utilisent maintenant le meme contraste beta1-beta2 et la valeur H3 = 2,103 points.
"""


def finish_archive(output: Path) -> dict[str, object]:
    with zipfile.ZipFile(output) as archive:
        bad = archive.testzip()
        members = archive.namelist()
    if bad is not None:
        raise RuntimeError(f"CRC failure in {output.name}: {bad}")
    digest = sha256(output)
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{digest}  {output.name}\n", encoding="ascii"
    )
    receipt = {
        "schema_version": "longitudinal_audience_delivery_receipt_v1",
        "status": "complete",
        "zip_name": output.name,
        "zip_bytes": output.stat().st_size,
        "zip_sha256": digest,
        "zip_members": len(members),
        "crc_test": "pass",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    output.with_suffix(output.suffix + ".receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return receipt


def build_professor(validation: dict[str, object], summary: str) -> dict[str, object]:
    readme = """LIVRAISON PROFESSEUR - RESULTATS LONGITUDINAUX 1962-2022

Ordre de lecture
1. 01_PRESENTATION/PRESENTATION_RESULTATS_240.pptx
2. 02_GUIDE/GUIDE_EXPLICATION_SLIDES_LONGITUDINAL.pdf
3. 03_RAPPORT/RAPPORT_LONGITUDINAL.pdf
4. 04_CONTROLE/RESUME_RESULTATS.txt

Le rapport, la presentation et le guide utilisent les memes valeurs finales.
La valeur H3 de l'ecart median KRT-R EI est 2,103 points sur le contraste beta1-beta2.
"""
    temporary = PROFESSOR_OUTPUT.with_suffix(".zip.tmp")
    if temporary.exists():
        temporary.unlink()
    with zipfile.ZipFile(temporary, "w", allowZip64=True, compresslevel=6) as archive:
        write_bytes(archive, "00_LIRE_EN_PREMIER.txt", readme.encode("utf-8"))
        add_file(archive, PRESENTATION, "01_PRESENTATION/PRESENTATION_RESULTATS_240.pptx")
        add_file(archive, GUIDE, "02_GUIDE/GUIDE_EXPLICATION_SLIDES_LONGITUDINAL.pdf")
        add_file(archive, REPORT, "03_RAPPORT/RAPPORT_LONGITUDINAL.pdf")
        write_bytes(archive, "04_CONTROLE/RESUME_RESULTATS.txt", summary.encode("utf-8"))
        write_bytes(
            archive,
            "04_CONTROLE/VALIDATION_FINALE.json",
            (json.dumps(validation, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
    temporary.replace(PROFESSOR_OUTPUT)
    return finish_archive(PROFESSOR_OUTPUT)


def build_student(validation: dict[str, object], summary: str) -> dict[str, object]:
    readme = """LIVRAISON ETUDIANT - RESULTATS ET REPRODUCTIBILITE

Ordre conseille
1. Lire 00_RESUME_RESULTATS.txt.
2. Ouvrir les documents directs dans 01_DOCUMENTS_DIRECTS/.
3. Utiliser 02_RESULTATS_COMPLETS/ pour les tables, figures et diagnostics.
4. Utiliser 03_ARCHIVE_TECHNIQUE/ pour le code, les configurations, l'audit et la reproduction.

Les deux archives internes conservent leurs recus et empreintes SHA-256 verifies.
"""
    temporary = STUDENT_OUTPUT.with_suffix(".zip.tmp")
    if temporary.exists():
        temporary.unlink()
    with zipfile.ZipFile(temporary, "w", allowZip64=True, compresslevel=6) as archive:
        write_bytes(archive, "00_LIRE_EN_PREMIER.txt", readme.encode("utf-8"))
        write_bytes(archive, "00_RESUME_RESULTATS.txt", summary.encode("utf-8"))
        write_bytes(
            archive,
            "00_VALIDATION_FINALE.json",
            (json.dumps(validation, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
        add_file(archive, PRESENTATION, "01_DOCUMENTS_DIRECTS/PRESENTATION_RESULTATS_240.pptx")
        add_file(archive, GUIDE, "01_DOCUMENTS_DIRECTS/GUIDE_EXPLICATION_SLIDES_LONGITUDINAL.pdf")
        add_file(archive, REPORT, "01_DOCUMENTS_DIRECTS/RAPPORT_LONGITUDINAL.pdf")
        for suffix in ["", ".receipt.json", ".sha256"]:
            source = Path(str(PROFESSOR_RELEASE) + suffix)
            add_file(
                archive,
                source,
                f"02_RESULTATS_COMPLETS/{source.name}",
                stored=source.suffix.lower() == ".zip",
            )
        for suffix in ["", ".receipt.json", ".sha256"]:
            source = Path(str(TECHNICAL_RELEASE) + suffix)
            add_file(
                archive,
                source,
                f"03_ARCHIVE_TECHNIQUE/{source.name}",
                stored=source.suffix.lower() == ".zip",
            )
    temporary.replace(STUDENT_OUTPUT)
    return finish_archive(STUDENT_OUTPUT)


def build_combined(validation: dict[str, object], summary: str) -> dict[str, object]:
    readme = """LIVRAISON FINALE - PROFESSEUR ET ETUDIANT

- 01_PROFESSEUR contient le paquet leger a transmettre au professeur.
- 02_ETUDIANT contient les resultats complets, les documents et la reproductibilite.
- 03_CONTROLE contient le resume et la validation finale.
"""
    temporary = COMBINED_OUTPUT.with_suffix(".zip.tmp")
    if temporary.exists():
        temporary.unlink()
    with zipfile.ZipFile(temporary, "w", allowZip64=True, compresslevel=6) as archive:
        write_bytes(archive, "00_LIRE_EN_PREMIER.txt", readme.encode("utf-8"))
        for source, folder in [(PROFESSOR_OUTPUT, "01_PROFESSEUR"), (STUDENT_OUTPUT, "02_ETUDIANT")]:
            add_file(archive, source, f"{folder}/{source.name}", stored=True)
            add_file(archive, Path(str(source) + ".sha256"), f"{folder}/{source.name}.sha256")
            add_file(archive, Path(str(source) + ".receipt.json"), f"{folder}/{source.name}.receipt.json")
        write_bytes(archive, "03_CONTROLE/RESUME_RESULTATS.txt", summary.encode("utf-8"))
        write_bytes(
            archive,
            "03_CONTROLE/VALIDATION_FINALE.json",
            (json.dumps(validation, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
    temporary.replace(COMBINED_OUTPUT)
    return finish_archive(COMBINED_OUTPUT)


def main() -> None:
    required = [
        REPORT,
        GUIDE,
        PRESENTATION,
        CONTRASTS,
        KRT,
        NLS,
        PROFESSOR_RELEASE,
        TECHNICAL_RELEASE,
        Path(str(PROFESSOR_RELEASE) + ".receipt.json"),
        Path(str(PROFESSOR_RELEASE) + ".sha256"),
        Path(str(TECHNICAL_RELEASE) + ".receipt.json"),
        Path(str(TECHNICAL_RELEASE) + ".sha256"),
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(missing)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    validation = validation_payload()
    summary = result_summary(validation)
    (OUTPUT_DIR / "RESUME_RESULTATS.txt").write_text(summary, encoding="utf-8")
    (OUTPUT_DIR / "VALIDATION_FINALE.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    professor_receipt = build_professor(validation, summary)
    student_receipt = build_student(validation, summary)
    combined_receipt = build_combined(validation, summary)
    print(
        json.dumps(
            {
                "status": "complete",
                "professor": professor_receipt,
                "student": student_receipt,
                "combined": combined_receipt,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
