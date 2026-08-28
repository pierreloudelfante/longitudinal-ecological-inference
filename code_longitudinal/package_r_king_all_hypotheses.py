from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
R_OUTPUT = ROOT / "outputs" / "longitudinal_2000_v1" / "r_replication"
DENSITY_OUTPUT = (
    ROOT / "work" / "r_density_cross_validation_H0A_H1_H0B_H0C_H6_H7_20260827"
)
ZIP_PATH = (
    ROOT / "deliverables" / "R_King_EI_2000_H0A_H1_H0B_H0C_H6_H7_20260827.zip"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def required_files() -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    consolidated = (
        "longitudinal_king_ei_r_commune_retained6.parquet",
        "longitudinal_king_ei_r_aggregate_retained6.parquet",
        "king_ei_retained6_run_audit.csv",
        "king_ei_retained6_consolidation_manifest.json",
        "king_ei_all_2x2_status.json",
        "king_ei_r_runtime_by_run.parquet",
        "king_ei_r_runtime_by_hypothesis.parquet",
        "king_ei_r_runtime_by_run.csv",
        "king_ei_r_runtime_by_hypothesis.csv",
        "king_ei_r_runtime_manifest.json",
        "longitudinal_nls_r.parquet",
        "nls_r_manifest.json",
    )
    for name in consolidated:
        path = R_OUTPUT / name
        if not path.is_file():
            raise FileNotFoundError(path)
        files.append((path, f"01_resultats_R/{name}"))

    code_files = (
        ROOT / "r_replication" / "run_king_ei_replication.R",
        ROOT / "r_replication" / "run_nls_replication.R",
        ROOT / "r_replication" / "generate_king_ei_density_figures.R",
    )
    for path in code_files:
        if not path.is_file():
            raise FileNotFoundError(path)
        files.append((path, f"02_code_R/{path.name}"))

    if not DENSITY_OUTPUT.is_dir():
        raise FileNotFoundError(DENSITY_OUTPUT)
    density_files = sorted(
        path
        for path in DENSITY_OUTPUT.rglob("*")
        if path.is_file() and path.suffix.lower() in {".parquet", ".csv", ".json", ".png", ".svg"}
    )
    if not density_files:
        raise RuntimeError("No R density outputs were found")
    for path in density_files:
        relative = path.relative_to(DENSITY_OUTPUT).as_posix()
        files.append((path, f"03_densites_R_toutes_annees/{relative}"))
    return files


def main() -> None:
    files = required_files()
    runtime = json.loads((R_OUTPUT / "king_ei_r_runtime_manifest.json").read_text(encoding="utf-8"))
    consolidation = json.loads(
        (R_OUTPUT / "king_ei_retained6_consolidation_manifest.json").read_text(encoding="utf-8-sig")
    )
    created_at = datetime.now(timezone.utc).isoformat()
    entries = [
        {
            "archive_path": archive_path,
            "source_path": path.relative_to(ROOT).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path, archive_path in files
    ]
    manifest = {
        "schema_version": "r_king_ei_2000_retained6_package_v1",
        "created_at_utc": created_at,
        "scope": "R-only code and results for H0A, H1, H0B, H0C, H6 and H7 on the 2,000-commune longitudinal panel",
        "model": "King 1997 truncated bivariate-normal EI through R ei/eiPack",
        "mathematical_identity_with_python_krt": False,
        "consolidation": consolidation,
        "runtime_summary": runtime,
        "files": entries,
    }
    readme = (
        "# Estimations R — panel longitudinal de 2 000 communes\n\n"
        "Ce paquet contient uniquement le code et les résultats R des six hypothèses "
        "prioritaires H0A, H1, H0B, H0C, H6 et H7 : estimations King EI consolidées, "
        "benchmark NLS R, durées observées et densités pour toutes les années.\n\n"
        "Le modèle R est le King EI classique à normale bivariée tronquée (`ei`/`eiPack`). "
        "Il sert de validation croisée descriptive et n'est pas mathématiquement identique "
        "au modèle KRT bêta-binomial Python.\n"
    )

    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = ZIP_PATH.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("README.md", readme.encode("utf-8"))
        archive.writestr("MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
        for path, archive_path in files:
            archive.write(path, archive_path)
    temporary.replace(ZIP_PATH)
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        corrupt = archive.testzip()
        entries_count = len(archive.infolist())
    if corrupt is not None:
        raise RuntimeError(f"Corrupt ZIP entry: {corrupt}")
    result = {
        "zip_path": str(ZIP_PATH),
        "bytes": ZIP_PATH.stat().st_size,
        "sha256": sha256(ZIP_PATH),
        "archive_entries": entries_count,
        "integrity_test": "ok",
        "created_at_utc": created_at,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
