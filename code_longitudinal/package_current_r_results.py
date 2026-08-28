from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
R_OUTPUT = ROOT / "outputs" / "longitudinal_2000_v1" / "r_replication"
METHOD_DELIVERABLE = (
    ROOT / "deliverables" / "h0a_h1_king_nls_r_eipack_2000_20260827"
)
ZIP_PATH = (
    ROOT
    / "deliverables"
    / "R_code_et_resultats_panel2000_20260827.zip"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def add_file(files: list[tuple[Path, str]], source: Path, archive_path: str) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    files.append((source, archive_path.replace("\\", "/")))


def build_file_list() -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []

    king_files = [
        "longitudinal_king_ei_r_aggregate_all_2x2.parquet",
        "longitudinal_king_ei_r_commune_all_2x2.parquet",
        "king_ei_all_2x2_run_audit.csv",
        "king_ei_all_2x2_consolidation_manifest.json",
        "king_ei_all_2x2_status.json",
    ]
    for name in king_files:
        add_file(files, R_OUTPUT / name, f"01_king_ei_r_consolide/{name}")

    nls_files = [
        "longitudinal_nls_r.parquet",
        "nls_r_manifest.json",
    ]
    for name in nls_files:
        add_file(files, R_OUTPUT / name, f"02_nls_r/{name}")

    density_dir = METHOD_DELIVERABLE / "figures" / "densites_professeur" / "r_eipack"
    density_files = sorted(path for path in density_dir.iterdir() if path.is_file())
    if len(density_files) != 6:
        raise RuntimeError(f"Expected 6 R density figures, found {len(density_files)}")
    for source in density_files:
        add_file(files, source, f"03_figures_densite_r_eipack/{source.name}")
    code_files = [
        ROOT / "r_replication" / "run_king_ei_replication.R",
        ROOT / "r_replication" / "run_nls_replication.R",
    ]
    for source in code_files:
        add_file(files, source, f"04_code_R/{source.name}")

    archive_paths = [archive_path for _, archive_path in files]
    if len(archive_paths) != len(set(archive_paths)):
        raise RuntimeError("Duplicate archive paths")
    return files


README = """# Résultats R — panel longitudinal de 2 000 communes

État figé au 27 août 2026.

## Ce qui est effectivement calculé

- King EI classique dans R (`ei::ei`, dépendant de `eiPack`) : H0A est complet pour les 26 scrutins.
- Les deux tables Parquet consolidées (agrégée et communale), l'audit des 26 scrutins et le manifest de consolidation sont inclus.
- NLS dans R (`stats::optim`, méthode BFGS) : les 270 couples scrutin × hypothèse sont calculés, dont H0A et H1 complets.

## Densités demandées par le professeur

Les six fichiers PNG/SVG de `03_figures_densite_r_eipack` sont les densités H0A pour 1962, 1986 et 2022, produites à partir des estimations communales R-eiPack.

## Limites à lire avant utilisation

- H1 n'est pas encore calculé avec le King EI classique R : la file d'attente attend que la mémoire soit suffisante. Le fichier d'état est inclus.
- NLS produit des estimations ponctuelles, pas une distribution communale : il n'y a donc pas de densité NLS analogue sans bootstrap ou autre schéma d'incertitude.

## Temps observés

- King EI R H0A : 1 639.86 s cumulées, soit 27.33 min ; médiane 62.34 s par scrutin. La fenêtre murale complète a été d'environ 31 min 21 s.
- NLS R H0A + H1 : 5.10 s d'optimisation cumulée pour 52 ajustements, soit environ 0.098 s par ajustement (hors démarrage R et entrées/sorties).

`MANIFEST.json` donne la provenance, la taille et le SHA-256 de chaque fichier archivé.
"""


def main() -> None:
    files = build_file_list()
    created_at = datetime.now(timezone.utc).isoformat()
    manifest_entries = [
        {
            "archive_path": archive_path,
            "source_path": source.relative_to(ROOT).as_posix(),
            "bytes": source.stat().st_size,
            "sha256": sha256(source),
        }
        for source, archive_path in files
    ]
    manifest = {
        "created_at_utc": created_at,
        "scope": "R results currently available for the 2,000-commune longitudinal panel",
        "king_ei_r": {"H0A_complete": 26, "H1_complete": 0},
        "nls_r": {"all_scenarios_pairs": 270, "H0A_H1_pairs": 52},
        "file_count_excluding_readme_and_manifest": len(files),
        "files": manifest_entries,
    }

    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_zip = ZIP_PATH.with_suffix(".zip.tmp")
    with zipfile.ZipFile(
        temporary_zip,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        archive.writestr("README.md", README.encode("utf-8"))
        archive.writestr(
            "MANIFEST.json",
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        for source, archive_path in files:
            archive.write(source, archive_path)
    temporary_zip.replace(ZIP_PATH)

    with zipfile.ZipFile(ZIP_PATH, mode="r") as archive:
        bad_file = archive.testzip()
        archive_count = len(archive.infolist())
    if bad_file is not None:
        raise RuntimeError(f"Corrupt ZIP entry: {bad_file}")
    if archive_count != len(files) + 2:
        raise RuntimeError(
            f"ZIP entry count mismatch: expected {len(files) + 2}, got {archive_count}"
        )

    result = {
        "zip_path": str(ZIP_PATH),
        "bytes": ZIP_PATH.stat().st_size,
        "sha256": sha256(ZIP_PATH),
        "archive_entries": archive_count,
        "integrity_test": "ok",
        "created_at_utc": created_at,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
