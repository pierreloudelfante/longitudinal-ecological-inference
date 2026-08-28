from __future__ import annotations

import csv
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from .paths import CONFIG_DIR, DOCS_DIR, FIGURE_DIR, OUTPUT_DIR, PANEL_DIR, ROOT, RUNS_DIR


RELEASE_NAME = "longitudinal_2022_release_01"
DELIVERABLE_DIR = ROOT / "deliverables"
RELEASE_DIR = DELIVERABLE_DIR / RELEASE_NAME
ZIP_PATH = DELIVERABLE_DIR / f"{RELEASE_NAME}.zip"
SHA256_PATH = DELIVERABLE_DIR / f"{RELEASE_NAME}.sha256"

EXCLUDED_ROOT_OUTPUTS = {
    "file_manifest.csv",  # replaced by PACKAGE_MANIFEST.csv inside the archive
    "run_registry_all.csv",  # duplicate of the public consolidated registry
    "beta_density_data.csv",  # large duplicate; Parquet retained
    "commune_latent_summaries.csv",  # large duplicate; Parquet retained
    "density_joint_data.csv",  # large duplicate; Parquet retained
    "density_marginal_data.csv",  # large duplicate; Parquet retained
}

RUN_FILES_TO_KEEP = {
    "manifest.json",
    "trace.nc",
    "resource_ladder_gate.json",
}

CONSOLIDATED_RUN_TABLES = (
    "longitudinal_estimates.csv",
    "model_diagnostics.csv",
    "beta_trace_index.csv",
    "nls_coefficients.csv",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _consolidated_run_dirs() -> list[Path]:
    """Return the immutable runs referenced by the consolidated snapshot."""
    run_ids: set[str] = set()
    for filename in CONSOLIDATED_RUN_TABLES:
        path = OUTPUT_DIR / filename
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8-sig") as stream:
            for row in csv.DictReader(stream):
                run_id = str(row.get("run_id", "")).strip()
                if run_id:
                    run_ids.add(run_id)
    if not run_ids:
        raise RuntimeError("No consolidated run_id found in analytical outputs")

    run_dirs: list[Path] = []
    for run_id in sorted(run_ids):
        if Path(run_id).name != run_id:
            raise RuntimeError(f"Unsafe consolidated run_id: {run_id}")
        run_dir = (RUNS_DIR / run_id).resolve()
        if run_dir.parent != RUNS_DIR.resolve() or not (run_dir / "manifest.json").is_file():
            raise RuntimeError(f"Missing consolidated run directory: {run_id}")
        run_dirs.append(run_dir)
    return run_dirs


def _safe_reset_release_dir() -> None:
    DELIVERABLE_DIR.mkdir(parents=True, exist_ok=True)
    if RELEASE_DIR.resolve().parent != DELIVERABLE_DIR.resolve():
        raise RuntimeError(f"Unsafe release path: {RELEASE_DIR}")
    if RELEASE_DIR.exists():
        shutil.rmtree(RELEASE_DIR)
    RELEASE_DIR.mkdir(parents=True)


def _copy_file(source: Path, relative_destination: Path) -> None:
    destination = RELEASE_DIR / relative_destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _copy_tree_files(source: Path, destination: Path, *, suffixes: set[str] | None = None) -> None:
    if not source.exists():
        return
    for path in sorted(source.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or ".cache" in path.parts:
            continue
        if suffixes is not None and path.suffix.lower() not in suffixes:
            continue
        _copy_file(path, destination / path.relative_to(source))


def _write_package_manifest() -> tuple[int, int]:
    rows: list[dict[str, str | int]] = []
    for path in sorted(RELEASE_DIR.rglob("*")):
        if not path.is_file() or path.name == "PACKAGE_MANIFEST.csv":
            continue
        rows.append(
            {
                "relative_path": path.relative_to(RELEASE_DIR).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    manifest_path = RELEASE_DIR / "PACKAGE_MANIFEST.csv"
    with manifest_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=["relative_path", "size_bytes", "sha256"])
        writer.writeheader()
        writer.writerows(rows)
    return len(rows), sum(int(row["size_bytes"]) for row in rows)


def _write_zip() -> None:
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(RELEASE_DIR.rglob("*")):
            if not path.is_file():
                continue
            archive_name = (Path(RELEASE_NAME) / path.relative_to(RELEASE_DIR)).as_posix()
            info = zipfile.ZipInfo(archive_name, date_time=(2026, 8, 2, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    SHA256_PATH.write_text(f"{_sha256(ZIP_PATH)}  {ZIP_PATH.name}\n", encoding="ascii")


def verify_release() -> dict[str, object]:
    required = {
        "README.md",
        "PACKAGE_MANIFEST.csv",
        "docs/BALANCE_TESTS.md",
        "docs/SCRIPT_GUIDE.md",
        "docs/METHODOLOGY_CODE_MAP.md",
        "docs/RESULTS_TRANSPARENCY.md",
        "docs/ELECTION_2022_PRODUCTION_REPORT.md",
        "docs/ALL_ELECTION_PARTITIONS_REPORT.md",
        "docs/PILOT_1962_1986_2022_REPORT.md",
        "docs/FIGURE_CATALOG.md",
        "docs/RESULTS_ILLUSTRATED_1962_1986_2022.md",
        "docs/PROFESSOR_GLOBAL_RECAP_1962_1986_2022.md",
        "outputs/commune_beta_estimates.csv",
        "outputs/beta_density_data.parquet",
        "outputs/beta_trace_index.csv",
        "outputs/validation_summary.json",
        "outputs/election_2022_input_integrity.csv",
        "outputs/election_2022_fit_quality.csv",
        "outputs/all_elections_partition_integrity.csv",
        "outputs/pilot_model_coverage.csv",
        "outputs/pilot_density_selection.csv",
        "outputs/illustrated_report_estimates.csv",
        "outputs/professor_canonical_comparisons.csv",
        "figures/election_2022/README.md",
        "figures/densities/README.md",
        "figures/illustrated_report/README.md",
        "figures/illustrated_report/comparison_interannuelle__H0A.svg",
        "figures/illustrated_report/comparison_interannuelle__H1.svg",
        "figures/illustrated_report/comparison_interannuelle__H5.svg",
        "figures/illustrated_report/comparison_interannuelle__H6.svg",
        "figures/illustrated_report/comparison_interannuelle__H7.svg",
        "figures/professor_recap/README.md",
        *{
            f"figures/professor_recap/comparison_interannuelle__{scenario_id}.svg"
            for scenario_id in ("H0A", "H0B", "H0C", "H1", "H2", "H3", "H4", "H5")
        },
    }
    missing = sorted(item for item in required if not (RELEASE_DIR / item).is_file())
    if missing:
        raise RuntimeError(f"Missing required release files: {missing}")

    with (RELEASE_DIR / "PACKAGE_MANIFEST.csv").open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        path = RELEASE_DIR / row["relative_path"]
        if not path.is_file():
            raise RuntimeError(f"Manifest path is missing: {row['relative_path']}")
        if path.stat().st_size != int(row["size_bytes"]) or _sha256(path) != row["sha256"]:
            raise RuntimeError(f"Manifest mismatch: {row['relative_path']}")

    with (RELEASE_DIR / "outputs" / "beta_trace_index.csv").open(newline="", encoding="utf-8-sig") as stream:
        trace_rows = list(csv.DictReader(stream))
    for row in trace_rows:
        trace = RELEASE_DIR / Path(row["trace_path"])
        if not trace.is_file() or _sha256(trace) != row["trace_sha256"]:
            raise RuntimeError(f"Missing or altered indexed trace: {row['trace_path']}")

    with zipfile.ZipFile(ZIP_PATH) as archive:
        bad_member = archive.testzip()
        names = archive.namelist()
    if bad_member is not None:
        raise RuntimeError(f"Corrupt ZIP member: {bad_member}")
    banned = [name for name in names if "__pycache__" in name or "/.cache/" in name or name.endswith(".pyc")]
    if banned:
        raise RuntimeError(f"Cache files found in ZIP: {banned[:5]}")
    return {
        "manifest_rows_verified": len(rows),
        "indexed_traces_verified": len(trace_rows),
        "zip_members_verified": len(names),
        "cache_files_in_zip": 0,
    }


def build_release() -> dict[str, object]:
    _safe_reset_release_dir()

    _copy_file(DOCS_DIR / "RELEASE_README.md", Path("README.md"))
    _copy_file(ROOT / "requirements-dev.txt", Path("requirements-dev.txt"))

    for document in sorted(DOCS_DIR.glob("*.md")):
        if document.name != "RELEASE_README.md":
            _copy_file(document, Path("docs") / document.name)

    _copy_tree_files(ROOT / "code_longitudinal", Path("code_longitudinal"), suffixes={".py", ".md"})
    _copy_tree_files(CONFIG_DIR, Path("config"))
    _copy_tree_files(ROOT / "tests", Path("tests"), suffixes={".py", ".md"})
    _copy_tree_files(PANEL_DIR, Path("panel"))
    _copy_tree_files(FIGURE_DIR, Path("figures"), suffixes={".svg", ".md"})

    for output in sorted(OUTPUT_DIR.iterdir()):
        if output.is_file() and output.name not in EXCLUDED_ROOT_OUTPUTS:
            _copy_file(output, Path("outputs") / output.name)
    for model_ready_file in sorted((OUTPUT_DIR / "model_ready").glob("*")):
        if not model_ready_file.is_file():
            continue
        if model_ready_file.suffix.lower() == ".csv" and not model_ready_file.name.endswith("__excluded.csv"):
            continue
        _copy_file(model_ready_file, Path("outputs") / "model_ready" / model_ready_file.name)
    if (OUTPUT_DIR / "runs" / "README.md").exists():
        _copy_file(OUTPUT_DIR / "runs" / "README.md", Path("outputs") / "runs" / "README.md")
    selected_run_dirs = _consolidated_run_dirs()
    release_run_dirs = set(selected_run_dirs)
    trace_index_path = OUTPUT_DIR / "beta_trace_index.csv"
    if trace_index_path.exists():
        with trace_index_path.open(newline="", encoding="utf-8-sig") as stream:
            for row in csv.DictReader(stream):
                trace_path = (ROOT / Path(row["trace_path"])).resolve()
                if trace_path.parent.parent != RUNS_DIR.resolve():
                    raise RuntimeError(f"Indexed trace is outside outputs/runs: {trace_path}")
                if not trace_path.is_file() or _sha256(trace_path) != row["trace_sha256"]:
                    raise RuntimeError(f"Missing or altered source trace: {row['trace_path']}")
                release_run_dirs.add(trace_path.parent)

    for run_dir in sorted(release_run_dirs):
        for run_file in sorted(run_dir.iterdir()):
            if run_file.is_file() and run_file.name in RUN_FILES_TO_KEEP:
                _copy_file(run_file, Path("outputs") / "runs" / run_dir.name / run_file.name)

    file_count, payload_bytes = _write_package_manifest()
    _write_zip()
    verification = verify_release()

    shutil.rmtree(RELEASE_DIR)

    result = {
        "zip_path": str(ZIP_PATH),
        "zip_sha256": _sha256(ZIP_PATH),
        "zip_size_bytes": ZIP_PATH.stat().st_size,
        "manifested_files": file_count,
        "payload_bytes": payload_bytes,
        "selected_successful_runs": len(selected_run_dirs),
        "released_run_directories": len(release_run_dirs),
        "staging_directory_removed": not RELEASE_DIR.exists(),
        "verification": verification,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    build_release()
