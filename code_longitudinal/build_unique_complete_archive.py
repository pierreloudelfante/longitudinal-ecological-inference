from __future__ import annotations

"""Bundle the final professor, technical, presentation, and density releases.

The component archives remain byte-identical and independently verifiable.
The master ZIP therefore uses stored entries for already-compressed artifacts
and adds a small relative-path manifest plus a reading guide.
"""

import hashlib
import json
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DELIVERABLES = ROOT / "deliverables"
PRESENTATION_DIR = ROOT / "work" / "longitudinal_2000_v1_full_240_professeur_candidate" / "04_PRESENTATION"
OUTPUT = DELIVERABLES / "longitudinal_2000_travail_complet_unique.zip"


def build_time() -> datetime:
    value = os.environ.get("SOURCE_DATE_EPOCH")
    return datetime.fromtimestamp(int(value), timezone.utc) if value else datetime.now(timezone.utc)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


COMPONENTS = [
    (DELIVERABLES / "longitudinal_2000_release_professeur.zip", "01_LIVRAISON_PROFESSEUR/longitudinal_2000_release_professeur.zip"),
    (DELIVERABLES / "longitudinal_2000_release_professeur.zip.receipt.json", "01_LIVRAISON_PROFESSEUR/longitudinal_2000_release_professeur.zip.receipt.json"),
    (DELIVERABLES / "longitudinal_2000_release_professeur.zip.sha256", "01_LIVRAISON_PROFESSEUR/longitudinal_2000_release_professeur.zip.sha256"),
    (DELIVERABLES / "longitudinal_2000_release_technique.zip", "02_ARCHIVE_TECHNIQUE/longitudinal_2000_release_technique.zip"),
    (DELIVERABLES / "longitudinal_2000_release_technique.zip.receipt.json", "02_ARCHIVE_TECHNIQUE/longitudinal_2000_release_technique.zip.receipt.json"),
    (DELIVERABLES / "longitudinal_2000_release_technique.zip.sha256", "02_ARCHIVE_TECHNIQUE/longitudinal_2000_release_technique.zip.sha256"),
    (PRESENTATION_DIR / "PRESENTATION_RESULTATS_240.pptx", "03_PRESENTATION/PRESENTATION_RESULTATS_240.pptx"),
    (PRESENTATION_DIR / "PRESENTATION_QA.json", "03_PRESENTATION/PRESENTATION_QA.json"),
    (PRESENTATION_DIR / "PRESENTATION_SOURCE_NOTES.txt", "03_PRESENTATION/PRESENTATION_SOURCE_NOTES.txt"),
    (PRESENTATION_DIR / "REPORT_QA.json", "03_PRESENTATION/REPORT_QA.json"),
    (DELIVERABLES / "longitudinal_2000_densites_completes.zip", "04_DENSITES_COMPLETES/longitudinal_2000_densites_completes.zip"),
    (DELIVERABLES / "longitudinal_2000_densites_completes.zip.receipt.json", "04_DENSITES_COMPLETES/longitudinal_2000_densites_completes.zip.receipt.json"),
    (DELIVERABLES / "longitudinal_2000_densites_completes.zip.sha256", "04_DENSITES_COMPLETES/longitudinal_2000_densites_completes.zip.sha256"),
    (DELIVERABLES / "longitudinal_2000_reproductibilite.zip", "05_REPRODUCTIBILITE/longitudinal_2000_reproductibilite.zip"),
    (DELIVERABLES / "longitudinal_2000_reproductibilite.zip.receipt.json", "05_REPRODUCTIBILITE/longitudinal_2000_reproductibilite.zip.receipt.json"),
    (DELIVERABLES / "longitudinal_2000_reproductibilite.zip.sha256", "05_REPRODUCTIBILITE/longitudinal_2000_reproductibilite.zip.sha256"),
]


README = """# Travail longitudinal 2 000 communes — archive unique

Cette archive regroupe les livrables finaux déjà produits, sans les anciens
snapshots intermédiaires devenus obsolètes.

- `01_LIVRAISON_PROFESSEUR/` : rapport HTML/PDF, tables Parquet, figures et documentation.
- `02_ARCHIVE_TECHNIQUE/` : code, configurations, tables détaillées, diagnostics et audit.
- `03_PRESENTATION/` : présentation PowerPoint et fichiers de contrôle qualité.
- `04_DENSITES_COMPLETES/` : 480 couples méthode × scrutin × hypothèse en PNG et SVG.
- `05_REPRODUCTIBILITE/` : environnements verrouillés, empreintes d'entrées, commande unique et contrôles.
- `06_MANIFESTE/MASTER_MANIFEST.json` : taille et SHA-256 de chaque composant.

Les ZIP professeur, technique et densités sont conservés tels quels afin que
leurs reçus et SHA-256 restent directement vérifiables.
"""


def main() -> None:
    missing = [str(source) for source, _ in COMPONENTS if not source.is_file()]
    if missing:
        raise FileNotFoundError(f"missing master-archive components: {missing}")

    for source, _ in COMPONENTS:
        if source.suffix.lower() == ".zip":
            with zipfile.ZipFile(source) as archive:
                if archive.testzip() is not None:
                    raise RuntimeError(f"CRC failure in component {source.name}")

    entries = [
        {"path": member, "bytes": source.stat().st_size, "sha256": sha256(source)}
        for source, member in COMPONENTS
    ]
    manifest = {
        "schema_version": "longitudinal_master_bundle_v1",
        "status": "complete",
        "created_at_utc": build_time().isoformat(),
        "scope": "final deliverables only; obsolete intermediate snapshots excluded",
        "coverage": {"python_numpyro": "240/240", "r_ei": "240/240"},
        "components": entries,
    }

    temporary = OUTPUT.with_suffix(".zip.tmp")
    if temporary.exists():
        temporary.unlink()
    timestamp = build_time()
    zip_datetime = (timestamp.year, timestamp.month, timestamp.day, timestamp.hour, timestamp.minute, timestamp.second)
    with zipfile.ZipFile(temporary, "w", allowZip64=True, compresslevel=9) as archive:
        readme_info = zipfile.ZipInfo("00_LIRE_EN_PREMIER.md", date_time=zip_datetime)
        readme_info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(readme_info, README.encode("utf-8"))
        for source, member in COMPONENTS:
            info = zipfile.ZipInfo(member, date_time=zip_datetime)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = (0o100644 & 0xFFFF) << 16
            with source.open("rb") as input_stream, archive.open(info, "w", force_zip64=True) as output_stream:
                shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
        manifest_info = zipfile.ZipInfo("06_MANIFESTE/MASTER_MANIFEST.json", date_time=zip_datetime)
        manifest_info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(manifest_info, (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    temporary.replace(OUTPUT)

    with zipfile.ZipFile(OUTPUT) as archive:
        bad_crc = archive.testzip()
        members = archive.namelist()
    if bad_crc is not None:
        raise RuntimeError(f"master CRC failure: {bad_crc}")
    if len(members) != len(COMPONENTS) + 2:
        raise RuntimeError(f"unexpected master member count: {len(members)}")

    digest = sha256(OUTPUT)
    OUTPUT.with_suffix(".zip.sha256").write_text(f"{digest}  {OUTPUT.name}\n", encoding="utf-8")
    receipt = {
        "schema_version": "longitudinal_master_bundle_receipt_v1",
        "status": "complete",
        "zip_name": OUTPUT.name,
        "zip_bytes": OUTPUT.stat().st_size,
        "zip_sha256": digest,
        "zip_members": len(members),
        "crc_test": "pass",
        "component_crc_tests": "pass",
        "component_hashes_recorded": True,
        "created_at_utc": build_time().isoformat(),
    }
    OUTPUT.with_suffix(".zip.receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
