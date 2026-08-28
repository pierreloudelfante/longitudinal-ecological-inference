"""Build a review package below 500 MB from the complete 3,000-unit release.

The compact archive keeps every human-readable result and every small audit
artifact.  It retains two representative NetCDF traces: one canonical pass
and the most diagnostically fragile caveat.  The full release is never
modified.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .paths import DOCS_DIR, ROOT


FULL_ZIP = ROOT / "deliverables" / "longitudinal_priority_results_v2_3000_H0A_H1_complete.zip"
OUTPUT_ZIP = ROOT / "deliverables" / "longitudinal_priority_results_v2_3000_H0A_H1_compact_lt500mo.zip"
SHA_PATH = OUTPUT_ZIP.with_suffix(".zip.sha256")
PACKAGE_NOTE = DOCS_DIR / "README_PAQUET_CHATGPT_500MO.md"
SUMMARY_ZIP = ROOT / "deliverables" / "premiers_resultats_KRT_NLS_panel3000_1962_1986_2022.zip"
SUMMARY_PREFIX = "presentation_KRT_NLS/"
BUILDER_PATH = Path(__file__).resolve()
MAX_BYTES = 500_000_000

TRACE_METADATA = {
    "outputs/runs/20260804T135238Z__a1d85f03a9f8/trace.nc": {
        "scenario_id": "H0A", "year": 1962, "mcmc_status": "caveat",
    },
    "outputs/runs/20260804T140822Z__cc8c7aa063b5/trace.nc": {
        "scenario_id": "H0A", "year": 1986, "mcmc_status": "caveat",
    },
    "outputs/runs/20260804T144933Z__4830d0298ccd/trace.nc": {
        "scenario_id": "H0A", "year": 2022, "mcmc_status": "pass",
    },
    "outputs/runs/20260804T150252Z__2df1cacde040/trace.nc": {
        "scenario_id": "H1", "year": 1962, "mcmc_status": "caveat",
    },
    "outputs/runs/20260804T161211Z__6719825c1e9a/trace.nc": {
        "scenario_id": "H1", "year": 1986, "mcmc_status": "pass",
    },
    "outputs/runs/20260804T163742Z__1cc94b3f41d5/trace.nc": {
        "scenario_id": "H1", "year": 2022, "mcmc_status": "caveat",
    },
}

INCLUDED_TRACES = {
    "outputs/runs/20260804T144933Z__4830d0298ccd/trace.nc",
    "outputs/runs/20260804T150252Z__2df1cacde040/trace.nc",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_member(
    source: zipfile.ZipFile,
    target: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    destination: str | None = None,
) -> None:
    copied = zipfile.ZipInfo(destination or info.filename, date_time=info.date_time)
    copied.compress_type = zipfile.ZIP_DEFLATED
    copied.external_attr = info.external_attr
    copied.create_system = info.create_system
    with source.open(info, "r") as reader, target.open(copied, "w", force_zip64=True) as writer:
        shutil.copyfileobj(reader, writer, length=4 * 1024 * 1024)


def build_chatgpt_package() -> dict[str, object]:
    if not FULL_ZIP.exists():
        raise FileNotFoundError(f"archive complète absente: {FULL_ZIP}")
    if not PACKAGE_NOTE.exists():
        raise FileNotFoundError(f"note du paquet compact absente: {PACKAGE_NOTE}")
    if not SUMMARY_ZIP.exists():
        raise FileNotFoundError(f"paquet de présentation KRT/NLS absent: {SUMMARY_ZIP}")

    full_sha256 = _sha256(FULL_ZIP)
    summary_sha256 = _sha256(SUMMARY_ZIP)
    omitted_traces = sorted(set(TRACE_METADATA).difference(INCLUDED_TRACES))
    with zipfile.ZipFile(FULL_ZIP, "r") as source, zipfile.ZipFile(SUMMARY_ZIP, "r") as summary:
        if summary.testzip() is not None:
            raise AssertionError("échec du contrôle CRC du paquet de présentation KRT/NLS")
        summary_members = [info for info in summary.infolist() if not info.is_dir()]
        selected = [
            info for info in source.infolist()
            if info.filename != "README.md"
            and (not info.filename.endswith("/trace.nc") or info.filename in INCLUDED_TRACES)
        ]
        unknown_traces = [
            info.filename for info in source.infolist()
            if info.filename.endswith("/trace.nc") and info.filename not in TRACE_METADATA
        ]
        if unknown_traces:
            raise AssertionError(f"traces non documentées dans l'archive complète: {unknown_traces}")
        if {info.filename for info in source.infolist() if info.filename.endswith('/trace.nc')} != set(TRACE_METADATA):
            raise AssertionError("la liste des six traces de l'archive complète a changé")

        manifest = {
            "schema_version": "chatgpt_review_package_3000_v1.0",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "purpose": "review package below 500 MB; scientific results unchanged",
            "maximum_bytes": MAX_BYTES,
            "source_complete_zip": FULL_ZIP.name,
            "source_complete_zip_sha256": full_sha256,
            "embedded_summary_zip": SUMMARY_ZIP.name,
            "embedded_summary_zip_sha256": summary_sha256,
            "main_report": f"{SUMMARY_PREFIX}PREMIERS_RESULTATS_KRT_NLS_PANEL_3000.md",
            "included_traces": [
                {"path": path, **TRACE_METADATA[path]} for path in sorted(INCLUDED_TRACES)
            ],
            "omitted_traces": [
                {"path": path, **TRACE_METADATA[path], "reason": "500 MB upload limit"}
                for path in omitted_traces
            ],
            "all_six_small_results_retained": True,
            "package_note": "docs/README_PAQUET_CHATGPT_500MO.md",
            "project_guide_scope": (
                "docs/README_PRODUCTION_3000_H0A_H1.md describes the complete release; "
                "the compact-package note governs trace membership here"
            ),
            "member_count": len(selected) + len(summary_members) + 4,
        }

        OUTPUT_ZIP.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(OUTPUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as target:
            target.writestr(
                "README.md",
                "# Paquet ChatGPT — moins de 500 Mo\n\n"
                "Lire d'abord `presentation_KRT_NLS/PREMIERS_RESULTATS_KRT_NLS_PANEL_3000.md`. "
                "Cette présentation contient les résultats KRT et NLS, les diagnostics et les densités. "
                "La composition technique du paquet est décrite dans `docs/README_PAQUET_CHATGPT_500MO.md`. "
                "Tous les résultats des six fits sont présents, mais seules deux traces "
                "NetCDF représentatives sont incluses pour respecter la limite d'upload.\n",
            )
            for info in selected:
                if info.filename == "docs/README_PRODUCTION_3000_H0A_H1.md":
                    body = source.read(info).decode("utf-8")
                    banner = (
                        "> **Portée de cette copie compacte :** ce guide décrit la livraison complète. "
                        "Dans ce ZIP de revue, quatre traces NetCDF sont omises ; lire "
                        "`README_PAQUET_CHATGPT_500MO.md` pour la liste exacte.\n\n"
                    )
                    target.writestr(info.filename, banner + body)
                else:
                    _copy_member(source, target, info)
            for info in summary_members:
                _copy_member(
                    summary,
                    target,
                    info,
                    destination=f"{SUMMARY_PREFIX}{info.filename}",
                )
            target.write(PACKAGE_NOTE, "docs/README_PAQUET_CHATGPT_500MO.md")
            target.write(BUILDER_PATH, "code_longitudinal/build_chatgpt_package_3000.py")
            target.writestr(
                "chatgpt_package_manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )

    size = OUTPUT_ZIP.stat().st_size
    if size >= MAX_BYTES:
        raise AssertionError(f"paquet ChatGPT trop grand: {size} >= {MAX_BYTES}")
    with zipfile.ZipFile(OUTPUT_ZIP, "r") as archive:
        if archive.testzip() is not None:
            raise AssertionError("échec du contrôle CRC du paquet ChatGPT")
        names = archive.namelist()
        traces = {name for name in names if name.endswith("/trace.nc")}
        if traces != INCLUDED_TRACES or len(names) != manifest["member_count"]:
            raise AssertionError("contenu du paquet ChatGPT différent du manifeste")
        required = {
            "README.md",
            "docs/README_PAQUET_CHATGPT_500MO.md",
            "docs/README_PRODUCTION_3000_H0A_H1.md",
            "docs/PRIORITY_RESULTS_3000_FINAL.md",
            "docs/METHODE_ECHANTILLONNAGE_PANEL_3000.md",
            "docs/RESUME_TRAVAIL_ET_ANALYSES_3000.md",
            "docs/COMPARAISON_DENSITES_JOINTES_3_PERIODES.md",
            "docs/METHODOLOGIE_ET_CHOIX_SENSIBLES_3000.md",
            "docs/RESUME_GENERAL_PROFESSEUR_3000.md",
            "code_longitudinal/build_chatgpt_package_3000.py",
            "chatgpt_package_manifest.json",
            f"{SUMMARY_PREFIX}PREMIERS_RESULTATS_KRT_NLS_PANEL_3000.md",
            f"{SUMMARY_PREFIX}PREMIERS_RESULTATS_KRT_NLS_PANEL_3000.pdf",
            f"{SUMMARY_PREFIX}resultats/nls_estimates_3000_v1.csv",
            f"{SUMMARY_PREFIX}resultats/nls_model_diagnostics_3000_v1.csv",
            f"{SUMMARY_PREFIX}annexes/figures/joint_beta_H0A_common_bandwidth_equal_communes.png",
            f"{SUMMARY_PREFIX}annexes/figures/joint_beta_H1_common_bandwidth_equal_communes.png",
        }
        if not required.issubset(names):
            raise AssertionError(f"documents requis absents: {sorted(required.difference(names))}")
        if any(name.endswith("model_diagnostics.csv") or "diagnostic_audits/" in name for name in names):
            raise AssertionError("un ancien diagnostic concurrent est entré dans le paquet compact")

    digest = _sha256(OUTPUT_ZIP)
    SHA_PATH.write_text(f"{digest}  {OUTPUT_ZIP.name}\n", encoding="ascii")
    return {
        "zip": str(OUTPUT_ZIP),
        "sha256": digest,
        "size_bytes": size,
        "size_decimal_mb": round(size / 1_000_000, 1),
        "included_traces": sorted(INCLUDED_TRACES),
        "omitted_trace_count": len(omitted_traces),
        "member_count": manifest["member_count"],
    }


def main() -> None:
    print(json.dumps(build_chatgpt_package(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
