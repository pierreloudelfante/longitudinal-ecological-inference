from __future__ import annotations

"""Build a small, independently verifiable reproducibility kit."""

import hashlib
import json
import os
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reproducibility"
CANDIDATE = ROOT / "work" / "longitudinal_2000_reproductibilite_candidate"
OUTPUT = ROOT / "deliverables" / "longitudinal_2000_reproductibilite.zip"
TEXT_SUFFIXES = {".csv", ".json", ".md", ".txt", ".py", ".r", ".R", ".ps1", ".mjs"}
ABSOLUTE_PATH_RE = re.compile(r"(?i)(?:(?<![a-z0-9])[a-z]:[\\/](?![\\/])|/users/|/home/)")


def build_time() -> datetime:
    value = os.environ.get("SOURCE_DATE_EPOCH")
    return datetime.fromtimestamp(int(value), timezone.utc) if value else datetime.now(timezone.utc)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_portable(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix in TEXT_SUFFIXES:
        text = source.read_text(encoding="utf-8", errors="replace")
        for value in (str(ROOT), str(ROOT).replace("\\", "/")):
            text = text.replace(value, "<PROJECT_ROOT>")
        destination.write_text(text, encoding="utf-8", newline="\n")
    else:
        shutil.copy2(source, destination)


def main() -> None:
    if CANDIDATE.exists():
        shutil.rmtree(CANDIDATE)
    CANDIDATE.mkdir(parents=True)

    for source in sorted(path for path in SOURCE.rglob("*") if path.is_file()):
        if "__pycache__" in source.parts or source.suffix.lower() in {".pyc", ".tmp"}:
            continue
        relative = source.relative_to(SOURCE)
        if relative.as_posix() == "qa/latest_verification.json" or (
            relative.parts[:1] == ("qa",) and relative.name.startswith("verification_")
        ):
            continue
        copy_portable(source, CANDIDATE / "KIT" / relative)

    for source in sorted((ROOT / "config").rglob("*")):
        if source.is_file():
            copy_portable(source, CANDIDATE / "CONFIG" / source.relative_to(ROOT / "config"))

    for name in (
        "README.md",
        "R_REQUIREMENTS.md",
        "requirements-production-v101.txt",
        "requirements-handoff-v1.1.txt",
    ):
        source = ROOT / name
        if source.is_file():
            copy_portable(source, CANDIDATE / "CONTRAT_PROJET" / name)

    audit_files = {
        ROOT / "panel" / "longitudinal_2000_v1_manifest.json": "panel_manifest.json",
        ROOT
        / "outputs"
        / "longitudinal_2000_v1"
        / "production"
        / "all_2x2_candidate"
        / "krt_240_candidate_selection.csv": "python_selection_initial_only_240.csv",
        ROOT
        / "outputs"
        / "longitudinal_2000_v1"
        / "r_replication"
        / "king_ei_all_2x2_status.json": "r_ei_240_status.json",
    }
    for source, name in audit_files.items():
        if source.is_file():
            copy_portable(source, CANDIDATE / "AUDIT" / name)

    members = []
    for path in sorted(candidate for candidate in CANDIDATE.rglob("*") if candidate.is_file()):
        relative = path.relative_to(CANDIDATE).as_posix()
        if path.suffix in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8", errors="replace")
            scan = "\n".join(
                line
                for line in text.splitlines()
                if "ABSOLUTE_PATH_RE =" not in line
            )
            if ABSOLUTE_PATH_RE.search(scan):
                raise RuntimeError(f"absolute local path in {relative}")
        members.append(
            {"path": relative, "bytes": path.stat().st_size, "sha256": sha256(path)}
        )
    manifest = {
        "schema_version": "longitudinal_reproducibility_bundle_v1",
        "status": "complete",
        "created_at_utc": build_time().isoformat(),
        "raw_data_included": False,
        "raw_data_validation": "27 names and SHA-256 in KIT/generated/inputs.manifest.json",
        "members": members,
    }
    manifest_path = CANDIDATE / "BUNDLE_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    temporary = OUTPUT.with_suffix(".zip.tmp")
    if temporary.exists():
        temporary.unlink()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    timestamp = build_time()
    zip_datetime = (timestamp.year, timestamp.month, timestamp.day, timestamp.hour, timestamp.minute, timestamp.second)
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        for path in sorted(candidate for candidate in CANDIDATE.rglob("*") if candidate.is_file()):
            info = zipfile.ZipInfo(path.relative_to(CANDIDATE).as_posix(), date_time=zip_datetime)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (0o100644 & 0xFFFF) << 16
            with path.open("rb") as source, archive.open(info, "w", force_zip64=True) as destination:
                shutil.copyfileobj(source, destination, length=1024 * 1024)
    temporary.replace(OUTPUT)
    with zipfile.ZipFile(OUTPUT) as archive:
        bad_crc = archive.testzip()
        member_count = len(archive.namelist())
    if bad_crc is not None:
        raise RuntimeError(f"CRC failure: {bad_crc}")
    digest = sha256(OUTPUT)
    OUTPUT.with_suffix(".zip.sha256").write_text(f"{digest}  {OUTPUT.name}\n", encoding="utf-8")
    receipt = {
        "schema_version": "longitudinal_reproducibility_bundle_receipt_v1",
        "status": "complete",
        "zip_name": OUTPUT.name,
        "zip_bytes": OUTPUT.stat().st_size,
        "zip_sha256": digest,
        "zip_members": member_count,
        "crc_test": "pass",
        "absolute_local_paths": 0,
        "created_at_utc": build_time().isoformat(),
    }
    OUTPUT.with_suffix(".zip.receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
