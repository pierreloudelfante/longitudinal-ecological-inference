from __future__ import annotations

"""Capture and verify the reproducibility contract of the 2,000-commune study.

This module intentionally separates three reproducibility levels:

* ``audit`` verifies the published artifacts without raw data or fitting tools;
* ``consolidation`` additionally verifies the 240 Python and 240 R run records;
* ``full`` also verifies the 27 raw source archives and the locked environments.

The fitting pipeline is resume-aware.  This verifier never starts an estimation.
"""

import argparse
import csv
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
REPRO = ROOT / "reproducibility"
GENERATED = REPRO / "generated"
QA_DIR = REPRO / "qa"
DEFAULT_RAW_DIR = ROOT.parent / "pour_moi_avec_data" / "data" / "raw" / "archives"
PANEL_ID = "longitudinal_2000_v1__strict_nested_3000__seed_20260803"
PANEL_SHA256 = "bde70c71660fce29610d7931461d8db6181dba874514a1866b63cf16a81cec4a"
SCENARIO_COUNTS = {
    "H0A": 26,
    "H0B": 26,
    "H0C": 26,
    "H1": 26,
    "H2": 26,
    "H3": 26,
    "H4": 26,
    "H5": 26,
    "H6": 16,
    "H7": 16,
}
EXPECTED_PAIRS = sum(SCENARIO_COUNTS.values())
CRITICAL_PYTHON_PACKAGES = {
    "arviz",
    "jax",
    "jaxlib",
    "numpy",
    "numpyro",
    "pandas",
    "pyarrow",
    "pyei",
    "pymc",
    "scipy",
    "statsmodels",
}
CRITICAL_R_PACKAGES = {"coda", "ei", "eiPack", "jsonlite", "MASS"}
EXPECTED_TABLE_ROWS = {
    "longitudinal_contrasts_krt_r_nls.parquet": 720,
    "longitudinal_krt_aggregate.parquet": 720,
    "longitudinal_krt_commune.parquet": 480_000,
    "longitudinal_nls.parquet": 2_370,
    "longitudinal_nls_covariate_coefficients.parquet": 6_720,
    "longitudinal_nls_covariates.parquet": 2_880,
    "longitudinal_r_ei_aggregate.parquet": 720,
    "longitudinal_r_ei_commune.parquet": 480_000,
}
TABLE_KEYS = {
    "longitudinal_krt_commune.parquet": ["election_id", "scenario_id", "unit_id"],
    "longitudinal_krt_aggregate.parquet": ["election_id", "scenario_id", "estimand"],
    "longitudinal_r_ei_commune.parquet": ["election_id", "scenario_id", "unit_id"],
    "longitudinal_r_ei_aggregate.parquet": ["election_id", "scenario_id", "estimand"],
    "longitudinal_nls.parquet": [
        "election_id",
        "scenario_id",
        "model_key",
        "estimand_type",
        "social_group",
        "vote_category",
    ],
    "longitudinal_contrasts_krt_r_nls.parquet": ["election_id", "scenario_id", "model_key"],
    "longitudinal_nls_covariates.parquet": ["election_id", "scenario_id", "spec_id", "estimand"],
    "longitudinal_nls_covariate_coefficients.parquet": [
        "election_id",
        "scenario_id",
        "spec_id",
        "social_group",
        "term",
    ],
}
PYTHON_PLAN_CONFIG = {
    "H0A": "config/releases/v1.0.2.json",
    "H1": "config/releases/v1.0.2.json",
    "H2": "config/releases/v1.1.json",
    "H3": "config/releases/v1.1.json",
    "H4": "config/releases/v1.4_numpyro_h4_h5_continuation.json",
    "H5": "config/releases/v1.4_numpyro_h4_h5_continuation.json",
    "H0B": "config/releases/v1.3_pymc_h0b_h0c.json",
    "H0C": "config/releases/v1.3_pymc_h0b_h0c.json",
    "H6": "config/releases/v1.2_pymc_h6_h7.json",
    "H7": "config/releases/v1.2_pymc_h6_h7.json",
}


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


def json_load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def portable(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def normalized_package_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def python_packages() -> dict[str, str]:
    packages: dict[str, str] = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if name:
            packages[normalized_package_name(name)] = distribution.version
    return dict(sorted(packages.items()))


def parse_r_description(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    current = ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line[:1].isspace() and current:
            fields[current] = f"{fields[current]} {line.strip()}".strip()
            continue
        if ":" not in line:
            continue
        current, value = line.split(":", 1)
        current = current.strip()
        fields[current] = value.strip()
    return fields


def tree_fingerprint(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    files = 0
    total_bytes = 0
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        relative = item.relative_to(path).as_posix().encode("utf-8")
        item_sha = sha256(item).encode("ascii")
        digest.update(relative + b"\0" + item_sha + b"\n")
        files += 1
        total_bytes += item.stat().st_size
    return {"files": files, "bytes": total_bytes, "tree_sha256": digest.hexdigest()}


def r_packages(library: Path) -> list[dict[str, Any]]:
    packages: list[dict[str, Any]] = []
    if not library.is_dir():
        return packages
    for directory in sorted(item for item in library.iterdir() if item.is_dir()):
        description = directory / "DESCRIPTION"
        if not description.is_file():
            continue
        fields = parse_r_description(description)
        fingerprint = tree_fingerprint(directory)
        packages.append(
            {
                "package": fields.get("Package", directory.name),
                "version": fields.get("Version", ""),
                "repository": fields.get("Repository", ""),
                "built": fields.get("Built", ""),
                "depends": fields.get("Depends", ""),
                "imports": fields.get("Imports", ""),
                "linking_to": fields.get("LinkingTo", ""),
                **fingerprint,
            }
        )
    return packages


def discover_rscript() -> Path | None:
    configured = os.environ.get("LONGITUDINAL_RSCRIPT")
    candidates = [Path(configured)] if configured else []
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        r_root = Path(program_files) / "R"
        candidates.extend(sorted(r_root.glob("R-*/bin/Rscript.exe"), reverse=True))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def r_runtime_info(rscript: Path | None) -> dict[str, Any]:
    if rscript is None:
        return {"available": False}
    command = [
        str(rscript),
        "--vanilla",
        "-e",
        "cat(R.version$major, R.version$minor, R.version$platform, sep='|')",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    output = completed.stdout.strip().split("|")
    return {
        "available": completed.returncode == 0 and len(output) == 3,
        "version": f"{output[0]}.{output[1]}" if len(output) == 3 else "",
        "platform": output[2] if len(output) == 3 else "",
    }


def canonical_model_manifests() -> list[tuple[Path, dict[str, Any]]]:
    result: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted((ROOT / "outputs" / "model_ready").glob("*__manifest.json")):
        payload = json_load(path)
        if (
            payload.get("scenario_id") in SCENARIO_COUNTS
            and payload.get("sample_id") == PANEL_ID
            and int(payload.get("n_communes_used", -1)) == 2000
        ):
            result.append((path, payload))
    return result


def capture_python_lock() -> dict[str, Any]:
    packages = python_packages()
    lock_path = REPRO / "requirements-python312.lock.txt"
    lock_path.write_text(
        "".join(f"{name}=={version}\n" for name, version in packages.items()),
        encoding="utf-8",
        newline="\n",
    )
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "packages": packages,
        "lock_path": portable(lock_path),
        "lock_sha256": sha256(lock_path),
    }


def capture_r_lock() -> dict[str, Any]:
    library = ROOT / ".cache" / "R" / "library"
    packages = r_packages(library)
    runtime = r_runtime_info(discover_rscript())
    payload = {
        "schema_version": "longitudinal_r_packages_lock_v1",
        "captured_at_utc": utc_now(),
        "runtime": runtime,
        "library_contract": "Windows x86_64, project-local binary library",
        "package_count": len(packages),
        "critical_packages": sorted(CRITICAL_R_PACKAGES),
        "packages": packages,
    }
    write_json(REPRO / "r-packages.lock.json", payload)
    return payload


def capture_inputs(raw_dir: Path) -> dict[str, Any]:
    manifests = canonical_model_manifests()
    pair_counts = Counter(payload["scenario_id"] for _, payload in manifests)
    sources: dict[str, str] = {}
    model_ready: list[dict[str, Any]] = []
    for manifest_path, payload in manifests:
        for name, digest in payload.get("source_sha256", {}).items():
            previous = sources.setdefault(name, digest)
            if previous != digest:
                raise RuntimeError(f"conflicting source digest for {name}")
        stem = manifest_path.name.removesuffix("__manifest.json")
        files: list[dict[str, Any]] = []
        for suffix in (".parquet", ".csv"):
            path = manifest_path.with_name(stem + suffix)
            if path.is_file():
                files.append(
                    {"path": portable(path), "bytes": path.stat().st_size, "sha256": sha256(path)}
                )
        model_ready.append(
            {
                "election_id": payload["election_id"],
                "scenario_id": payload["scenario_id"],
                "manifest_path": portable(manifest_path),
                "manifest_sha256": sha256(manifest_path),
                "files": files,
            }
        )
    raw_sources: list[dict[str, Any]] = []
    for name, expected in sorted(sources.items()):
        path = raw_dir / name
        current = sha256(path) if path.is_file() else ""
        raw_sources.append(
            {
                "name": name,
                "required_sha256": expected,
                "bytes": path.stat().st_size if path.is_file() else None,
                "present_at_capture": path.is_file(),
                "verified_at_capture": current == expected,
            }
        )
    panel_path = ROOT / "panel" / "longitudinal_2000_v1.parquet"
    panel_manifest_path = ROOT / "panel" / "longitudinal_2000_v1_manifest.json"
    payload = {
        "schema_version": "longitudinal_reproducibility_inputs_v1",
        "captured_at_utc": utc_now(),
        "raw_location_contract": "Set LONGITUDINAL_RAW_ARCHIVES or pass --raw-dir; paths are not embedded.",
        "raw_sources": raw_sources,
        "panel": {
            "panel_id": PANEL_ID,
            "path": portable(panel_path),
            "sha256": sha256(panel_path),
            "expected_sha256": PANEL_SHA256,
            "manifest_path": portable(panel_manifest_path),
            "manifest_sha256": sha256(panel_manifest_path),
        },
        "canonical_model_ready": {
            "pairs": len(model_ready),
            "pairs_by_scenario": dict(sorted(pair_counts.items())),
            "entries": model_ready,
        },
    }
    write_json(GENERATED / "inputs.manifest.json", payload)
    return payload


def source_files() -> Iterable[Path]:
    for directory, suffixes in (
        (ROOT / "code_longitudinal", {".py", ".mjs"}),
        (ROOT / "r_replication", {".R", ".r", ".stan"}),
        (ROOT / "config", {".json", ".md"}),
        (ROOT / "tests", {".py", ".md"}),
        (REPRO, {".py", ".ps1", ".R", ".r", ".mjs", ".md", ".txt", ".json"}),
    ):
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix not in suffixes:
                continue
            if GENERATED in path.parents or QA_DIR in path.parents:
                continue
            yield path
    for path in sorted(ROOT.glob("*.ps1")):
        yield path
    for name in ("README.md", "R_REQUIREMENTS.md"):
        path = ROOT / name
        if path.is_file():
            yield path


def capture_code() -> dict[str, Any]:
    entries = [
        {"path": portable(path), "bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in source_files()
    ]
    payload = {
        "schema_version": "longitudinal_reproducibility_code_v1",
        "captured_at_utc": utc_now(),
        "files": entries,
    }
    write_json(GENERATED / "code.manifest.json", payload)
    return payload


def parquet_contract(path: Path) -> dict[str, Any]:
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    return {
        "rows": parquet.metadata.num_rows,
        "columns": parquet.schema_arrow.names,
        "schema": str(parquet.schema_arrow),
    }


def capture_outputs() -> dict[str, Any]:
    tables_root = (
        ROOT / "work" / "longitudinal_2000_release_professeur_candidate" / "02_TABLES_PRINCIPALES"
    )
    tables = []
    for path in sorted(tables_root.glob("*.parquet")):
        tables.append(
            {
                "path": portable(path),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
                "parquet": parquet_contract(path),
            }
        )
    artifacts = []
    artifact_paths = [
        ROOT / "deliverables" / "longitudinal_2000_release_professeur.zip",
        ROOT / "deliverables" / "longitudinal_2000_densites_completes.zip",
        ROOT
        / "work"
        / "longitudinal_2000_release_professeur_candidate"
        / "01_RAPPORT"
        / "RAPPORT_LONGITUDINAL.html",
        ROOT
        / "work"
        / "longitudinal_2000_release_professeur_candidate"
        / "01_RAPPORT"
        / "RAPPORT_LONGITUDINAL.pdf",
        ROOT
        / "work"
        / "longitudinal_2000_v1_full_240_professeur_candidate"
        / "04_PRESENTATION"
        / "PRESENTATION_RESULTATS_240.pptx",
    ]
    for path in artifact_paths:
        if path.is_file():
            artifacts.append(
                {"path": portable(path), "bytes": path.stat().st_size, "sha256": sha256(path)}
            )
    selection = (
        ROOT
        / "outputs"
        / "longitudinal_2000_v1"
        / "production"
        / "all_2x2_candidate"
        / "krt_240_candidate_selection.csv"
    )
    payload = {
        "schema_version": "longitudinal_reproducibility_outputs_v1",
        "captured_at_utc": utc_now(),
        "coverage": {"python_krt": "240/240", "r_ei": "240/240"},
        "selection_policy": "initial_only",
        "selection_path": portable(selection),
        "selection_sha256": sha256(selection),
        "tables": tables,
        "artifacts": artifacts,
    }
    write_json(GENERATED / "outputs.manifest.json", payload)
    return payload


def capture_presentation_source() -> dict[str, Any]:
    presentation_root = (
        ROOT / "work" / "longitudinal_2000_v1_full_240_professeur_candidate" / "04_PRESENTATION"
    )
    source_root = REPRO / "presentation"
    source_root.mkdir(parents=True, exist_ok=True)
    mapping = {
        "PRESENTATION_RESULTATS_240.pptx": "PRESENTATION_RESULTATS_240.source.pptx",
        "PRESENTATION_BRIEF.json": "PRESENTATION_BRIEF.json",
        "PRESENTATION_SOURCE_NOTES.txt": "PRESENTATION_SOURCE_NOTES.txt",
    }
    entries: list[dict[str, Any]] = []
    for input_name, output_name in mapping.items():
        source = presentation_root / input_name
        destination = source_root / output_name
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copy2(source, destination)
        entries.append(
            {
                "source_role": input_name,
                "path": destination.relative_to(REPRO).as_posix(),
                "bytes": destination.stat().st_size,
                "sha256": sha256(destination),
            }
        )
    pptx_entry = next(entry for entry in entries if entry["path"].endswith(".pptx"))
    payload = {
        "schema_version": "longitudinal_presentation_source_v1",
        "captured_at_utc": utc_now(),
        "source_sha256": pptx_entry["sha256"],
        "source_bytes": pptx_entry["bytes"],
        "rendering_policy": "frozen QA-approved binary source; analytical sources rebuilt first",
        "entries": entries,
    }
    write_json(source_root / "PRESENTATION_SOURCE_MANIFEST.json", payload)
    return payload


def capture_report_source() -> dict[str, Any]:
    report_root = ROOT / "work" / "longitudinal_2000_release_professeur_candidate" / "01_RAPPORT"
    source_root = REPRO / "report"
    source_root.mkdir(parents=True, exist_ok=True)
    source = report_root / "RAPPORT_LONGITUDINAL.pdf"
    destination = source_root / "RAPPORT_LONGITUDINAL.source.pdf"
    if not source.is_file():
        raise FileNotFoundError(source)
    shutil.copy2(source, destination)
    payload = {
        "schema_version": "longitudinal_report_pdf_source_v1",
        "captured_at_utc": utc_now(),
        "source_sha256": sha256(destination),
        "source_bytes": destination.stat().st_size,
        "path": destination.relative_to(REPRO).as_posix(),
        "rendering_policy": (
            "portable HTML is rebuilt from data; QA-approved secondary PDF is frozen "
            "to avoid browser, font and pagination drift"
        ),
    }
    write_json(source_root / "REPORT_SOURCE_MANIFEST.json", payload)
    return payload


def capture(raw_dir: Path) -> dict[str, Any]:
    GENERATED.mkdir(parents=True, exist_ok=True)
    python_lock = capture_python_lock()
    r_lock = capture_r_lock()
    inputs = capture_inputs(raw_dir)
    code = capture_code()
    outputs = capture_outputs()
    presentation = capture_presentation_source()
    report = capture_report_source()
    environment = {
        "schema_version": "longitudinal_environment_observed_v1",
        "captured_at_utc": utc_now(),
        "python": python_lock,
        "r": r_lock["runtime"],
        "os_contract": "Windows x86_64; CPU execution for JAX/NumPyro",
        "statistical_reproducibility": {
            "seeds_fixed": True,
            "bitwise_identity_guaranteed_across_hardware": False,
            "reason": "JAX/XLA and MCMC floating-point reductions can differ across CPU, OS and library builds.",
            "validation_rule": "Exact schemas/counts/hashes for frozen artifacts; numerical tolerances for refits.",
        },
    }
    write_json(GENERATED / "environment.observed.json", environment)
    receipt = {
        "schema_version": "longitudinal_reproducibility_capture_v1",
        "status": "complete",
        "captured_at_utc": utc_now(),
        "python_packages": len(python_lock["packages"]),
        "r_packages": r_lock["package_count"],
        "raw_sources": len(inputs["raw_sources"]),
        "raw_sources_verified": sum(item["verified_at_capture"] for item in inputs["raw_sources"]),
        "model_ready_pairs": inputs["canonical_model_ready"]["pairs"],
        "code_files": len(code["files"]),
        "output_tables": len(outputs["tables"]),
        "presentation_source_sha256": presentation["source_sha256"],
        "report_pdf_source_sha256": report["source_sha256"],
    }
    write_json(GENERATED / "CAPTURE_RECEIPT.json", receipt)
    return receipt


class Verification:
    def __init__(self, level: str) -> None:
        self.level = level
        self.checks: list[dict[str, Any]] = []

    def add(self, name: str, passed: bool, detail: str, **evidence: Any) -> None:
        self.checks.append(
            {"name": name, "status": "pass" if passed else "fail", "detail": detail, **evidence}
        )

    @property
    def passed(self) -> bool:
        return all(check["status"] == "pass" for check in self.checks)


def verify_zip(path: Path, receipt_path: Path, verification: Verification) -> None:
    if not path.is_file() or not receipt_path.is_file():
        verification.add(f"zip:{path.name}", False, "archive or receipt missing")
        return
    receipt = json_load(receipt_path)
    digest = sha256(path)
    expected = receipt.get("zip_sha256")
    with zipfile.ZipFile(path) as archive:
        bad_crc = archive.testzip()
    verification.add(
        f"zip:{path.name}",
        bad_crc is None and digest == expected and receipt.get("status") == "complete",
        "CRC, receipt status and SHA-256",
        expected_sha256=expected,
        observed_sha256=digest,
        crc="pass" if bad_crc is None else bad_crc,
    )


def verify_embedded_manifest(
    archive_path: Path,
    manifest_member: str,
    entries_key: str,
    verification: Verification,
) -> None:
    errors: list[str] = []
    checked = 0
    try:
        with zipfile.ZipFile(archive_path) as archive:
            manifest = json.loads(archive.read(manifest_member).decode("utf-8-sig"))
            for entry in manifest.get(entries_key, []):
                member = entry["path"]
                try:
                    info = archive.getinfo(member)
                    digest = hashlib.sha256()
                    with archive.open(info) as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(chunk)
                    if info.file_size != entry["bytes"] or digest.hexdigest() != entry["sha256"]:
                        errors.append(member)
                    checked += 1
                except KeyError:
                    errors.append(member)
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    verification.add(
        f"embedded-manifest:{archive_path.name}",
        not errors and checked > 0,
        "every declared member size and SHA-256",
        members_checked=checked,
        errors=errors,
    )


def verify_tables(verification: Verification) -> None:
    import pyarrow.parquet as pq

    root = ROOT / "work" / "longitudinal_2000_release_professeur_candidate" / "02_TABLES_PRINCIPALES"
    for name, expected_rows in EXPECTED_TABLE_ROWS.items():
        path = root / name
        if not path.is_file():
            verification.add(f"table:{name}", False, "missing")
            continue
        table = pq.read_table(path)
        rows_ok = table.num_rows == expected_rows
        keys = [key for key in TABLE_KEYS.get(name, []) if key in table.column_names]
        duplicates = 0
        if keys:
            frame = table.select(keys).to_pandas()
            duplicates = int(frame.duplicated(keys).sum())
        verification.add(
            f"table:{name}",
            rows_ok and duplicates == 0,
            "row count and declared grain",
            observed_rows=table.num_rows,
            expected_rows=expected_rows,
            key_columns=keys,
            duplicate_keys=duplicates,
        )


def verify_frozen_outputs(verification: Verification) -> None:
    manifest_path = GENERATED / "outputs.manifest.json"
    if not manifest_path.is_file():
        verification.add("frozen-output-manifest", False, "run capture first")
        return
    payload = json_load(manifest_path)
    for entry in payload.get("tables", []) + payload.get("artifacts", []):
        path = ROOT / entry["path"]
        observed = sha256(path) if path.is_file() else ""
        verification.add(
            f"frozen:{entry['path']}",
            observed == entry["sha256"],
            "frozen artifact SHA-256",
            expected_sha256=entry["sha256"],
            observed_sha256=observed,
        )


def verify_audit(verification: Verification) -> None:
    deliverables = ROOT / "deliverables"
    for name in (
        "longitudinal_2000_release_professeur.zip",
        "longitudinal_2000_release_technique.zip",
        "longitudinal_2000_densites_completes.zip",
        "longitudinal_2000_reproductibilite.zip",
        "longitudinal_2000_travail_complet_unique.zip",
    ):
        verify_zip(deliverables / name, deliverables / f"{name}.receipt.json", verification)
    verify_embedded_manifest(
        deliverables / "longitudinal_2000_reproductibilite.zip",
        "BUNDLE_MANIFEST.json",
        "members",
        verification,
    )
    verify_embedded_manifest(
        deliverables / "longitudinal_2000_travail_complet_unique.zip",
        "06_MANIFESTE/MASTER_MANIFEST.json",
        "components",
        verification,
    )
    verify_tables(verification)
    density_root = (
        ROOT / "work" / "longitudinal_2000_release_professeur_candidate" / "03_FIGURES" / "densites_completes"
    )
    density_png = len(list(density_root.rglob("*.png"))) if density_root.is_dir() else 0
    verification.add("density-figures", density_png == 480, "one PNG per method/election/scenario pair", observed=density_png)
    presentation_root = (
        ROOT / "work" / "longitudinal_2000_v1_full_240_professeur_candidate" / "04_PRESENTATION"
    )
    qa_path = presentation_root / "PRESENTATION_QA.json"
    qa = json_load(qa_path) if qa_path.is_file() else {}
    verification.add(
        "presentation-qa",
        qa.get("status") == "pass" and qa.get("all_slides_rendered") is True,
        "presentation rendered and visually inspected",
        slide_count=qa.get("slide_count"),
    )
    report_qa_path = presentation_root / "REPORT_QA.json"
    report_qa = json_load(report_qa_path) if report_qa_path.is_file() else {}
    verification.add(
        "report-qa",
        report_qa.get("status") == "pass" and report_qa.get("all_pages_rendered") is True,
        "report rendered and visually inspected",
        pages=report_qa.get("pdf_pages"),
    )
    verify_frozen_outputs(verification)


def selected_python_pairs() -> tuple[set[tuple[str, str]], list[str]]:
    selection_path = (
        ROOT
        / "outputs"
        / "longitudinal_2000_v1"
        / "production"
        / "all_2x2_candidate"
        / "krt_240_candidate_selection.csv"
    )
    pairs: set[tuple[str, str]] = set()
    errors: list[str] = []
    with selection_path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            pair = (row["election_id"], row["scenario_id"])
            run_manifest = ROOT / "outputs" / "runs" / row["run_id"] / "manifest.json"
            if pair in pairs:
                errors.append(f"duplicate selection {pair}")
            pairs.add(pair)
            if not run_manifest.is_file():
                errors.append(f"missing run {row['run_id']}")
                continue
            payload = json_load(run_manifest)
            parameters = payload.get("parameters", {})
            if payload.get("status") != "success" or parameters.get("model_key") != "krt_beta_binomial":
                errors.append(f"invalid run {row['run_id']}")
            if (parameters.get("election_id"), parameters.get("scenario_id")) != pair:
                errors.append(f"pair mismatch {row['run_id']}")
    return pairs, errors


def successful_r_pairs() -> tuple[set[tuple[str, str]], list[str]]:
    root = ROOT / "outputs" / "longitudinal_2000_v1" / "r_replication" / "king_ei_runs"
    pairs: set[tuple[str, str]] = set()
    errors: list[str] = []
    for path in sorted(root.rglob("manifest_r.json")):
        try:
            payload = json_load(path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"unreadable {portable(path)}: {exc}")
            continue
        if payload.get("status") != "success" or int(payload.get("n_communes", -1)) != 2000:
            continue
        pair = (str(payload.get("election_id")), str(payload.get("scenario_id")))
        if pair in pairs:
            errors.append(f"duplicate successful R pair {pair}")
        pairs.add(pair)
    return pairs, errors


def verify_consolidation(verification: Verification) -> None:
    manifests = canonical_model_manifests()
    counts = Counter(payload["scenario_id"] for _, payload in manifests)
    verification.add(
        "model-ready-240",
        len(manifests) == EXPECTED_PAIRS and dict(counts) == SCENARIO_COUNTS,
        "canonical model-ready matrices",
        observed=len(manifests),
        by_scenario=dict(sorted(counts.items())),
    )
    python_pairs, python_errors = selected_python_pairs()
    verification.add(
        "python-krt-240",
        len(python_pairs) == EXPECTED_PAIRS and not python_errors,
        "240 unique initial/canonical successful run manifests",
        observed=len(python_pairs),
        errors=python_errors,
    )
    r_pairs, r_errors = successful_r_pairs()
    verification.add(
        "r-ei-240",
        len(r_pairs) == EXPECTED_PAIRS and not r_errors,
        "240 unique successful R EI manifests",
        observed=len(r_pairs),
        errors=r_errors,
    )
    verification.add(
        "python-r-pair-alignment",
        python_pairs == r_pairs,
        "same election/scenario keys in Python and R",
        python_only=sorted(python_pairs - r_pairs),
        r_only=sorted(r_pairs - python_pairs),
    )
    panel = ROOT / "panel" / "longitudinal_2000_v1.parquet"
    observed_panel = sha256(panel) if panel.is_file() else ""
    verification.add(
        "panel-sha256",
        observed_panel == PANEL_SHA256,
        "fixed outcome-blind 2,000-commune panel",
        expected=PANEL_SHA256,
        observed=observed_panel,
    )


def verify_environment(verification: Verification) -> None:
    observed_python = python_packages()
    lock_path = REPRO / "requirements-python312.lock.txt"
    expected_python: dict[str, str] = {}
    if lock_path.is_file():
        for line in lock_path.read_text(encoding="utf-8").splitlines():
            if "==" in line:
                name, version = line.split("==", 1)
                expected_python[normalized_package_name(name)] = version
    mismatches = {
        name: {"expected": expected_python.get(name), "observed": observed_python.get(name)}
        for name in sorted(CRITICAL_PYTHON_PACKAGES)
        if expected_python.get(name) != observed_python.get(name)
    }
    verification.add(
        "python-environment",
        platform.python_version() == "3.12.10" and not mismatches,
        "Python 3.12.10 and exact critical package versions",
        observed_python=platform.python_version(),
        mismatches=mismatches,
    )
    r_lock_path = REPRO / "r-packages.lock.json"
    expected_r_payload = json_load(r_lock_path) if r_lock_path.is_file() else {}
    expected_r = {
        row["package"]: row["version"] for row in expected_r_payload.get("packages", [])
    }
    observed_r = {
        row["package"]: row["version"] for row in r_packages(ROOT / ".cache" / "R" / "library")
    }
    r_mismatches = {
        name: {"expected": expected_r.get(name), "observed": observed_r.get(name)}
        for name in sorted(CRITICAL_R_PACKAGES)
        if expected_r.get(name) != observed_r.get(name)
    }
    runtime = r_runtime_info(discover_rscript())
    verification.add(
        "r-environment",
        runtime.get("version") == "4.6.0" and not r_mismatches,
        "R 4.6.0 and exact critical package versions",
        runtime=runtime,
        mismatches=r_mismatches,
    )


def verify_raw_inputs(raw_dir: Path, verification: Verification) -> None:
    inputs_path = GENERATED / "inputs.manifest.json"
    if not inputs_path.is_file():
        verification.add("raw-inputs", False, "inputs.manifest.json missing; run capture")
        return
    payload = json_load(inputs_path)
    missing: list[str] = []
    mismatched: list[str] = []
    for entry in payload.get("raw_sources", []):
        path = raw_dir / entry["name"]
        if not path.is_file():
            missing.append(entry["name"])
        elif sha256(path) != entry["required_sha256"]:
            mismatched.append(entry["name"])
    verification.add(
        "raw-inputs",
        not missing and not mismatched and len(payload.get("raw_sources", [])) == 27,
        "27 source archives located by name and SHA-256",
        raw_source_count=len(payload.get("raw_sources", [])),
        missing=missing,
        mismatched=mismatched,
    )


def verify(level: str, raw_dir: Path) -> dict[str, Any]:
    verification = Verification(level)
    verify_audit(verification)
    if level in {"consolidation", "full"}:
        verify_consolidation(verification)
    if level == "full":
        verify_environment(verification)
        verify_raw_inputs(raw_dir, verification)
    payload = {
        "schema_version": "longitudinal_reproducibility_verification_v1",
        "status": "pass" if verification.passed else "fail",
        "level": level,
        "checked_at_utc": utc_now(),
        "checks_passed": sum(check["status"] == "pass" for check in verification.checks),
        "checks_failed": sum(check["status"] == "fail" for check in verification.checks),
        "checks": verification.checks,
    }
    QA_DIR.mkdir(parents=True, exist_ok=True)
    write_json(QA_DIR / f"verification_{level}.json", payload)
    write_json(QA_DIR / "latest_verification.json", payload)
    return payload


def build_plan() -> dict[str, Any]:
    manifests = canonical_model_manifests()
    rows = []
    for _, payload in manifests:
        scenario = payload["scenario_id"]
        rows.append(
            {
                "election_id": payload["election_id"],
                "scenario_id": scenario,
                "release_config": PYTHON_PLAN_CONFIG[scenario],
                "panel_id": PANEL_ID,
            }
        )
    rows.sort(key=lambda row: (row["scenario_id"], row["election_id"]))
    if len(rows) != EXPECTED_PAIRS:
        raise RuntimeError(f"expected {EXPECTED_PAIRS} plan rows, found {len(rows)}")
    payload = {
        "schema_version": "longitudinal_initial_only_execution_plan_v1",
        "selection_policy": "initial_only",
        "targeted_reruns": False,
        "pairs": len(rows),
        "rows": rows,
    }
    write_json(GENERATED / "execution_plan_240.json", payload)
    with (GENERATED / "execution_plan_240.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture_parser = subparsers.add_parser("capture", help="freeze inputs, code, environments and outputs")
    capture_parser.add_argument("--raw-dir", type=Path, default=Path(os.environ.get("LONGITUDINAL_RAW_ARCHIVES", DEFAULT_RAW_DIR)))
    verify_parser = subparsers.add_parser("verify", help="verify without starting any fit")
    verify_parser.add_argument("--level", choices=("audit", "consolidation", "full"), default="audit")
    verify_parser.add_argument("--raw-dir", type=Path, default=Path(os.environ.get("LONGITUDINAL_RAW_ARCHIVES", DEFAULT_RAW_DIR)))
    subparsers.add_parser("plan", help="write the exact 240-pair initial-only execution plan")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "capture":
        result = capture(args.raw_dir.resolve())
    elif args.command == "verify":
        result = verify(args.level, args.raw_dir.resolve())
        if result["status"] != "pass":
            print(json.dumps(result, ensure_ascii=False, indent=2))
            raise SystemExit(1)
    else:
        result = build_plan()
    printable = (
        {key: value for key, value in result.items() if key != "rows"}
        if args.command == "plan"
        else result
    )
    print(json.dumps(printable, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
