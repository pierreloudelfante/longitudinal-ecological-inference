from __future__ import annotations

import csv
import hashlib
import json
import shutil
import struct
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from reproducibility.replication_scope import get_scope


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "deliverables" / "longitudinal_2000_densites_completes"
ZIP_PATH = ROOT / "deliverables" / "longitudinal_2000_densites_completes.zip"
CATALOG = BUNDLE / "03_CATALOGUE_DENSITES.csv"
R_MANIFEST = BUNDLE / "04_DENSITY_MANIFEST.json"
INPUT_COVERAGE = ROOT / "work" / "density_all_pairs" / "data" / "beta_coverage_by_pair.csv"
QA_PATH = BUNDLE / "05_QA_DENSITES.json"
DELIVERY_MANIFEST = BUNDLE / "06_DELIVERY_MANIFEST.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def write_json(path: Path, payload: object) -> None:
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"invalid PNG: {path}")
    return struct.unpack(">II", header[16:24])


def read_catalog() -> list[dict[str, str]]:
    with CATALOG.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def coverage_summary(rows: list[dict[str, str]]) -> dict[str, object]:
    by_method: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_method.setdefault(row["method"], []).append(row)
    result: dict[str, object] = {}
    for method, method_rows in sorted(by_method.items()):
        b1 = [int(row["finite_b1"]) for row in method_rows]
        b2 = [int(row["finite_b2"]) for row in method_rows]
        both = [int(row["finite_both"]) for row in method_rows]
        result[method] = {
            "pairs": len(method_rows),
            "pairs_with_2000_finite_b1": sum(value == 2000 for value in b1),
            "pairs_with_2000_finite_b2": sum(value == 2000 for value in b2),
            "pairs_with_2000_finite_both": sum(value == 2000 for value in both),
            "minimum_finite_b1": min(b1),
            "minimum_finite_b2": min(b2),
            "minimum_finite_both": min(both),
            "pairs_with_any_nonfinite_beta": sum(
                int(row["finite_b1"]) < int(row["total_rows"])
                or int(row["finite_b2"]) < int(row["total_rows"])
                for row in method_rows
            ),
        }
    return result


def main() -> None:
    if not CATALOG.is_file() or not R_MANIFEST.is_file():
        raise FileNotFoundError("density generation outputs are incomplete")
    rows = read_catalog()
    scope = get_scope()
    expected = {(method, election, scenario) for method in ("krt_python", "r_eipack") for election, scenario in scope.pairs}
    actual = {(row["method"], row["election_id"], row["scenario_id"]) for row in rows}
    if len(rows) != scope.density_count or actual != expected:
        raise RuntimeError(f"expected exactly {scope.density_count} scoped catalog rows, found {len(rows)}")
    if any(row["status"] != "complete" for row in rows):
        raise RuntimeError("at least one density pair is incomplete")

    coverage_target = BUNDLE / "03_COUVERTURE_BETA_PAR_COUPLE.csv"
    shutil.copy2(INPUT_COVERAGE, coverage_target)
    reproduction = BUNDLE / "07_REPRODUCTION"
    reproduction.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "code_longitudinal" / "export_density_pair_inputs.py", reproduction / "export_density_pair_inputs.py")
    shutil.copy2(ROOT / "r_replication" / "generate_all_pair_density_figures.R", reproduction / "generate_all_pair_density_figures.R")

    errors: list[str] = []
    sizes: list[int] = []
    for row in rows:
        png = BUNDLE / row["png"]
        svg = BUNDLE / row["svg"]
        for path in (png, svg):
            if not path.is_file() or path.stat().st_size < 1_000:
                errors.append(f"missing or too small: {path.relative_to(BUNDLE).as_posix()}")
            else:
                sizes.append(path.stat().st_size)
        if png.is_file():
            try:
                if png_dimensions(png) != (2100, 760):
                    errors.append(f"unexpected PNG dimensions: {png.relative_to(BUNDLE).as_posix()}")
            except ValueError as error:
                errors.append(str(error))
        if svg.is_file():
            text = svg.read_text(encoding="utf-8", errors="replace")
            if "<svg" not in text[:2_000]:
                errors.append(f"invalid SVG: {svg.relative_to(BUNDLE).as_posix()}")

    summary = coverage_summary(rows)
    qa = {
        "schema_version": "density_bundle_qa_v1",
        "status": "pass" if not errors else "fail",
        "catalog_rows": len(rows),
        "expected_catalog_rows": scope.density_count,
        "replication_scope": scope.as_dict(),
        "png_files_validated": sum(1 for row in rows if (BUNDLE / row["png"]).is_file()),
        "svg_files_validated": sum(1 for row in rows if (BUNDLE / row["svg"]).is_file()),
        "png_dimensions": [2100, 760],
        "visual_samples_inspected": 0,
        "visual_samples": [],
        "visual_inspection_complete_for_samples": False,
        "axes_fixed_to_unit_interval": True,
        "shared_bandwidth_within_series": True,
        "coverage": summary,
        "errors": errors,
        "checked_at_utc": utc_now(),
    }
    write_json(QA_PATH, qa)
    if errors:
        raise RuntimeError(f"density QA failed: {errors[:10]}")

    write_text(
        BUNDLE / "00_README_DENSITES.md",
        f"""# Densités complètes — panel longitudinal de 2 000 communes

Cette archive contient une planche pour chacun des **{scope.pair_count} couples élection × hypothèse** du périmètre `{scope.name}` et pour chacune des deux méthodes : **KRT Python** et **King EI R/eiPack**, soit **{scope.density_count} planches** disponibles en PNG et SVG.

Chaque planche comporte :

- la densité jointe des moyennes postérieures communales β₁–β₂, avec diagonale β₁=β₂ ;
- la densité marginale de β₁, pondérée par l'effectif du groupe cible ;
- la densité marginale de β₂, pondérée par l'effectif du groupe complémentaire ;
- le nombre de β₁, β₂ et couples β₁–β₂ finis réellement utilisés.

## Disponibilité des β

- Python/KRT : {scope.pair_count * 2000:,} lignes communales, {scope.pair_count}/{scope.pair_count} couples ; la couverture finie exacte figure dans le catalogue.
- R/eiPack : {scope.pair_count * 2000:,} lignes et {scope.pair_count}/{scope.pair_count} couples disponibles. Certaines moyennes communales sont non finies et sont exclues explicitement du lissage. Le catalogue conserve les effectifs par couple; le minimum est {summary['r_eipack']['minimum_finite_both']} couples communaux β₁–β₂ finis parmi les couples de ce périmètre.

Les valeurs non finies R ne sont ni imputées ni remplacées. Elles restent visibles dans `03_CATALOGUE_DENSITES.csv` et `03_COUVERTURE_BETA_PAR_COUPLE.csv`.

## Lecture

Les axes β₁ et β₂ sont fixés à [0,1]. Les bandes passantes sont communes à chaque série méthode × hypothèse × type de scrutin, afin de préserver la comparabilité temporelle. Ces densités portent sur les **moyennes postérieures communales** : elles ne sont pas des densités de draws MCMC ni des régions crédibles agrégées.
""",
    )

    files = []
    for path in sorted(p for p in BUNDLE.rglob("*") if p.is_file() and p != DELIVERY_MANIFEST):
        files.append(
            {
                "path": path.relative_to(BUNDLE).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    manifest = {
        "schema_version": "density_delivery_manifest_v1",
        "status": "complete",
        "created_at_utc": utc_now(),
        "figures": {"pair_plots": scope.density_count, "png": scope.density_count, "svg": scope.density_count},
        "replication_scope": scope.as_dict(),
        "coverage": summary,
        "file_count_excluding_manifest": len(files),
        "files": files,
    }
    write_json(DELIVERY_MANIFEST, manifest)

    temporary = ZIP_PATH.with_suffix(".zip.tmp")
    if temporary.exists():
        temporary.unlink()
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        for path in sorted(p for p in BUNDLE.rglob("*") if p.is_file()):
            archive.write(path, path.relative_to(BUNDLE).as_posix())
    temporary.replace(ZIP_PATH)
    with zipfile.ZipFile(ZIP_PATH) as archive:
        bad_crc = archive.testzip()
        members = archive.namelist()
    if bad_crc is not None:
        raise RuntimeError(f"CRC failure: {bad_crc}")
    digest = sha256(ZIP_PATH)
    write_text(ZIP_PATH.with_suffix(".zip.sha256"), f"{digest}  {ZIP_PATH.name}\n")
    receipt = {
        "schema_version": "density_delivery_receipt_v1",
        "status": "complete",
        "zip_name": ZIP_PATH.name,
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": digest,
        "zip_members": len(members),
        "crc_test": "pass",
        "manifest_verified": True,
        "qa_status": qa["status"],
        "created_at_utc": utc_now(),
    }
    write_json(ZIP_PATH.with_suffix(".zip.receipt.json"), receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
