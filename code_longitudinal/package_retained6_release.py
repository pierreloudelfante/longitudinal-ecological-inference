from __future__ import annotations

import ast
import csv
import hashlib
import json
import shutil
import tempfile
import zipfile
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from .paths import OUTPUT_DIR, ROOT, RUNS_DIR
from .utils import file_sha256


RELEASE_BASENAME = "longitudinal_2000_v1.5_H0A_H1_H0B_H0C_H2_H3"
CANDIDATE = ROOT / "work" / f"{RELEASE_BASENAME}_candidate"
DELIVERABLES = ROOT / "deliverables"
PROFESSOR_STAGE = ROOT / "work" / f"package_staging_{RELEASE_BASENAME}_professeur"
TECHNICAL_STAGE = ROOT / "work" / f"package_staging_{RELEASE_BASENAME}_technique"
PROFESSOR_ZIP = DELIVERABLES / f"{RELEASE_BASENAME}_professeur.zip"
TECHNICAL_ZIP = DELIVERABLES / f"{RELEASE_BASENAME}_technique.zip"

ENTRYPOINTS = (
    "run_longitudinal_production",
    "h23_supervisor",
    "run_r_ei_all_2x2",
    "consolidate_r_ei_all_2x2",
    "compare_python_r_ei_all_2x2",
    "build_retained6_selection",
    "scoped_finalizer",
    "materialize_retained6_release",
    "plot_python_r_retained6",
    "plot_2022_retained6_diagnostics",
    "build_retained6_documentation",
    "build_retained6_report",
    "package_retained6_release",
)


def _copy(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _sanitize_delivery_value(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(_sanitize_delivery_value(key)): _sanitize_delivery_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_delivery_value(item) for item in value]
    if not isinstance(value, str):
        return value
    text = value.replace(str(ROOT), ".").replace(str(ROOT).replace("\\", "/"), ".")
    user_home = str(Path.home())
    text = text.replace(user_home, "<USER_HOME>").replace(user_home.replace("\\", "/"), "<USER_HOME>")
    return text


def _write_sanitized_json(source: Path, destination: Path) -> None:
    payload = json.loads(source.read_text(encoding="utf-8"))
    sanitized = _sanitize_delivery_value(payload)
    if isinstance(sanitized, dict):
        sanitized["delivery_manifest_sanitized"] = True
        sanitized["source_runtime_manifest_sha256"] = file_sha256(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(sanitized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _safe_reset(path: Path, expected: Path) -> None:
    resolved = path.resolve()
    expected_resolved = expected.resolve()
    if resolved != expected_resolved or resolved.parent != (ROOT / "work").resolve():
        raise ValueError(f"refusing to replace unexpected staging directory: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True)


def _relative_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    dependencies: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module:
                dependencies.add(node.module.split(".", 1)[0])
            else:
                dependencies.update(alias.name for alias in node.names)
    return {
        item
        for item in dependencies
        if (ROOT / "code_longitudinal" / f"{item}.py").is_file()
    }


def _code_closure() -> set[str]:
    selected = {"__init__"}
    queue = deque(ENTRYPOINTS)
    while queue:
        module = queue.popleft()
        if module in selected:
            continue
        path = ROOT / "code_longitudinal" / f"{module}.py"
        if not path.is_file():
            raise FileNotFoundError(path)
        selected.add(module)
        queue.extend(sorted(_relative_imports(path) - selected))
    return selected


def _copy_candidate_file(stage: Path, relative: str, destination: str | None = None) -> None:
    _copy(CANDIDATE / relative, stage / (destination or relative))


def _build_professor_stage() -> None:
    _safe_reset(PROFESSOR_STAGE, PROFESSOR_STAGE)
    for relative in ("README.md", "PIPELINE_MAP.md", "DATA_LINEAGE.csv", "RAPPORT_PROFESSEUR.pdf", "RAPPORT_PROFESSEUR.html", "VALIDATION_RETAINED6.json", "MATERIALIZATION_RETAINED6.json"):
        _copy_candidate_file(PROFESSOR_STAGE, relative)

    mappings = {
        "01_entrees/README.md": "01_ENTREES/README.md",
        "01_entrees/MODEL_READY_INDEX.csv": "01_ENTREES/MODEL_READY_INDEX.csv",
        "03_panel_et_audit/panel_primaire_2000.csv": "01_ENTREES/panel_2000.csv",
        "01_resultats_python/README.md": "02_RESULTATS_PYTHON/README.md",
        "01_resultats_python/longitudinal_krt_commune.parquet": "02_RESULTATS_PYTHON/longitudinal_krt_commune.parquet",
        "01_resultats_python/longitudinal_krt_aggregate.parquet": "02_RESULTATS_PYTHON/longitudinal_krt_aggregate.parquet",
        "01_resultats_python/longitudinal_nls.parquet": "02_RESULTATS_PYTHON/longitudinal_nls.parquet",
        "01_resultats_python/release_manifest.json": "02_RESULTATS_PYTHON/release_manifest.json",
        "03_resultats_r_eipack/README.md": "03_RESULTATS_R_EIPACK/README.md",
        "03_resultats_r_eipack/longitudinal_king_ei_r_commune_retained6.parquet": "03_RESULTATS_R_EIPACK/longitudinal_king_ei_r_commune.parquet",
        "03_resultats_r_eipack/longitudinal_king_ei_r_aggregate_retained6.parquet": "03_RESULTATS_R_EIPACK/longitudinal_king_ei_r_aggregate.parquet",
        "03_resultats_r_eipack/king_ei_retained6_run_audit.csv": "03_RESULTATS_R_EIPACK/run_audit.csv",
        "03_resultats_r_eipack/king_ei_retained6_consolidation_manifest.json": "03_RESULTATS_R_EIPACK/consolidation_manifest.json",
        "04_comparaison_python_r/README.md": "04_COMPARAISONS/README.md",
        "04_comparaison_python_r/king_python_r_retained6_aggregate_comparison.parquet": "04_COMPARAISONS/python_r_aggregate.parquet",
        "04_comparaison_python_r/king_python_r_retained6_commune_summary.parquet": "04_COMPARAISONS/python_r_commune_summary.parquet",
        "04_comparaison_python_r/king_python_r_retained6_python_selection.csv": "04_COMPARAISONS/python_run_selection.csv",
        "04_comparaison_python_r/king_python_r_retained6_comparison_manifest.json": "04_COMPARAISONS/python_r_manifest.json",
        "02_syntheses/krt_nls_comparison_h0a_h1_h0b_h0c_h2_h3.csv": "04_COMPARAISONS/krt_nls_comparison.csv",
        "02_syntheses/canonical_run_selection.csv": "06_AUDIT/canonical_run_selection.csv",
        "02_syntheses/diagnostics_krt_par_election.csv": "06_AUDIT/diagnostics_krt_par_election.csv",
        "02_syntheses/diagnostics_krt_resume.csv": "06_AUDIT/diagnostics_krt_resume.csv",
        "02_syntheses/etat_modeles_par_election.csv": "06_AUDIT/etat_modeles_par_election.csv",
        "02_syntheses/definitions_hypotheses.csv": "06_AUDIT/definitions_hypotheses.csv",
        "03_panel_et_audit/DATA_DICTIONARY.csv": "06_AUDIT/DATA_DICTIONARY.csv",
        "03_panel_et_audit/COVARIATE_PROVENANCE.csv": "06_AUDIT/COVARIATE_PROVENANCE.csv",
        "03_panel_et_audit/HARMONISATION_POLITIQUE.csv": "06_AUDIT/HARMONISATION_POLITIQUE.csv",
        "03_panel_et_audit/coverage_by_election_department.csv": "06_AUDIT/coverage_by_election_department.csv",
        "03_panel_et_audit/panel_exact_validation.json": "06_AUDIT/panel_exact_validation.json",
        "05_methodologie_et_code/MODEL_CARDS.md": "07_REPRODUCTION/MODEL_CARDS.md",
        "05_methodologie_et_code/REPRODUCTION.md": "07_REPRODUCTION/REPRODUCTION.md",
        "05_methodologie_et_code/DEPENDENCIES.md": "07_REPRODUCTION/DEPENDENCIES.md",
        "05_methodologie_et_code/release_config_retained6.json": "07_REPRODUCTION/release_config.json",
        "05_methodologie_et_code/SCOPE_DECISION_20260826.md": "07_REPRODUCTION/SCOPE_DECISION_20260826.md",
    }
    for source, destination in mappings.items():
        _copy_candidate_file(PROFESSOR_STAGE, source, destination)
    figure_source = CANDIDATE / "04_figures_essentielles"
    for path in sorted(figure_source.glob("*.png")):
        _copy(path, PROFESSOR_STAGE / "05_FIGURES" / path.name)
    for name in ("README.md", "CHART_MAP.csv", "python_r_figures_manifest.json"):
        path = figure_source / name
        if path.is_file():
            _copy(path, PROFESSOR_STAGE / "05_FIGURES" / name)


def _copy_technical_inputs() -> None:
    index = pd.read_csv(CANDIDATE / "01_entrees" / "MODEL_READY_INDEX.csv")
    if len(index) != 156:
        raise AssertionError("technical model-ready index must contain 156 rows")
    for row in index.itertuples(index=False):
        source = ROOT / str(row.runtime_path)
        destination = TECHNICAL_STAGE / str(row.technical_delivery_path)
        if file_sha256(source) != str(row.sha256):
            raise AssertionError(f"model-ready hash changed: {source}")
        _copy(source, destination)
    _copy(ROOT / "panel" / "longitudinal_2000_v1.parquet", TECHNICAL_STAGE / "01_entrees" / "panel_2000.parquet")
    _copy(ROOT / "panel" / "longitudinal_2000_v1_manifest.json", TECHNICAL_STAGE / "01_entrees" / "panel_manifest.json")


def _copy_minimal_code() -> None:
    modules = _code_closure()
    rows: list[dict[str, object]] = []
    for module in sorted(modules):
        source = ROOT / "code_longitudinal" / f"{module}.py"
        destination = TECHNICAL_STAGE / "08_CODE_MINIMAL" / "code_longitudinal" / source.name
        _copy(source, destination)
        rows.append(
            {
                "module": module,
                "role": "entrypoint" if module in ENTRYPOINTS else "dependency",
                "sha256": file_sha256(source),
                "bundle_path": destination.relative_to(TECHNICAL_STAGE).as_posix(),
            }
        )
    _copy(ROOT / "r_replication" / "run_king_ei_replication.R", TECHNICAL_STAGE / "08_CODE_MINIMAL" / "r_replication" / "run_king_ei_replication.R")
    _copy(ROOT / "config" / "releases" / "v1.5_retained6.json", TECHNICAL_STAGE / "08_CODE_MINIMAL" / "config" / "releases" / "v1.5_retained6.json")
    pd.DataFrame(rows).to_csv(TECHNICAL_STAGE / "08_CODE_MINIMAL" / "CODE_INVENTORY.csv", index=False, encoding="utf-8-sig")
    (TECHNICAL_STAGE / "08_CODE_MINIMAL" / "README.md").write_text(
        "# Code minimal\n\nCe dossier est la fermeture des imports des seuls points d'entrée de la chaîne retenue. Aucun script NIMBLE, Stan, historique V2/V3 ou cache n'est inclus.\n",
        encoding="utf-8",
    )


def _copy_run_diagnostics() -> None:
    selection = pd.read_csv(CANDIDATE / "02_syntheses" / "canonical_run_selection.csv", dtype="string")
    for row in selection.itertuples(index=False):
        source_dir = RUNS_DIR / str(row.run_id)
        destination = TECHNICAL_STAGE / "09_DIAGNOSTICS_RUNS" / str(row.run_id)
        for name in (
            "manifest.json",
            "mcmc_diagnostics_v2.json",
            "identification_diagnostics_v2.json",
            "aggregate_comparison_v2.csv",
        ):
            source = source_dir / name
            if source.is_file():
                if source.suffix == ".json":
                    _write_sanitized_json(source, destination / name)
                else:
                    _copy(source, destination / name)
    r_runs = OUTPUT_DIR / "longitudinal_2000_v1" / "r_replication" / "king_ei_runs"
    for run_dir in sorted(r_runs.iterdir()):
        if not run_dir.is_dir():
            continue
        manifest = run_dir / "manifest_r.json"
        if not manifest.is_file():
            continue
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        if str(payload.get("scenario_id")) not in {"H0A", "H1", "H0B", "H0C", "H2", "H3"}:
            continue
        destination = TECHNICAL_STAGE / "09_DIAGNOSTICS_RUNS_R" / run_dir.name
        _write_sanitized_json(manifest, destination / "manifest_r.json")


def _build_technical_stage() -> None:
    _safe_reset(TECHNICAL_STAGE, TECHNICAL_STAGE)
    shutil.copytree(PROFESSOR_STAGE, TECHNICAL_STAGE, dirs_exist_ok=True)
    _copy_technical_inputs()
    _copy_minimal_code()
    _copy_run_diagnostics()
    _copy_candidate_file(TECHNICAL_STAGE, "03_panel_et_audit/DATA_DICTIONARY_TECHNICAL.csv", "06_AUDIT/DATA_DICTIONARY_TECHNICAL.csv")
    _copy_candidate_file(TECHNICAL_STAGE, "03_panel_et_audit/longitudinal_audit.parquet", "06_AUDIT/longitudinal_audit.parquet")
    _copy_candidate_file(TECHNICAL_STAGE, "03_panel_et_audit/rxc_ineligible_audit.csv", "06_AUDIT/rxc_ineligible_audit.csv")


def _write_manifest(stage: Path) -> Path:
    rows = []
    for path in sorted(item for item in stage.rglob("*") if item.is_file() and item.name != "DELIVERY_MANIFEST.csv"):
        relative = path.relative_to(stage).as_posix()
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise AssertionError(f"unsafe delivery path: {relative}")
        rows.append({"delivery_path": relative, "bytes": path.stat().st_size, "sha256": file_sha256(path)})
    manifest = stage / "DELIVERY_MANIFEST.csv"
    pd.DataFrame(rows).to_csv(manifest, index=False, encoding="utf-8-sig")
    return manifest


def _assert_no_local_absolute_paths(stage: Path) -> None:
    needles = (str(Path.home()).encode("utf-8"), str(Path.home()).replace("\\", "/").encode("utf-8"))
    violations: list[str] = []
    for path in stage.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".json", ".csv", ".md", ".txt", ".html", ".log", ".py", ".r"}:
            continue
        raw = path.read_bytes()
        if any(needle in raw for needle in needles):
            violations.append(path.relative_to(stage).as_posix())
    if violations:
        raise AssertionError(f"local absolute paths remain in delivery text: {violations[:10]}")


def _write_zip(stage: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        for path in sorted(item for item in stage.rglob("*") if item.is_file()):
            archive.write(path, path.relative_to(stage).as_posix())
    temporary.replace(destination)


def _verify_zip(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        unsafe = [name for name in names if Path(name).is_absolute() or ".." in Path(name).parts or ":" in Path(name).drive]
        bad_crc = archive.testzip()
        if unsafe or bad_crc:
            raise AssertionError(f"invalid ZIP {path.name}: unsafe={unsafe[:3]}, bad_crc={bad_crc}")
        with tempfile.TemporaryDirectory(prefix="retained6_zip_verify_", dir=ROOT / "work") as temporary:
            archive.extractall(temporary)
            manifest = pd.read_csv(Path(temporary) / "DELIVERY_MANIFEST.csv")
            mismatches = []
            for row in manifest.itertuples(index=False):
                extracted = Path(temporary) / str(row.delivery_path)
                if not extracted.is_file() or file_sha256(extracted) != str(row.sha256):
                    mismatches.append(str(row.delivery_path))
            if mismatches:
                raise AssertionError(f"re-extracted hashes failed: {mismatches[:5]}")
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": file_sha256(path), "members": len(names), "crc": "pass", "reextract_hashes": "pass"}


def package() -> dict[str, object]:
    validation = json.loads((CANDIDATE / "VALIDATION_RETAINED6.json").read_text(encoding="utf-8"))
    if not validation.get("structural_ready"):
        raise RuntimeError("candidate is not structurally ready")
    _build_professor_stage()
    _assert_no_local_absolute_paths(PROFESSOR_STAGE)
    _write_manifest(PROFESSOR_STAGE)
    _build_technical_stage()
    _assert_no_local_absolute_paths(TECHNICAL_STAGE)
    _write_manifest(TECHNICAL_STAGE)
    for stage in (PROFESSOR_STAGE, TECHNICAL_STAGE):
        forbidden = [path for path in stage.rglob("*") if path.is_file() and path.suffix.lower() in {".nc", ".rds"}]
        if forbidden:
            raise AssertionError(f"forbidden heavy runtime artifacts: {forbidden[:5]}")
    _write_zip(PROFESSOR_STAGE, PROFESSOR_ZIP)
    _write_zip(TECHNICAL_STAGE, TECHNICAL_ZIP)
    results = [_verify_zip(PROFESSOR_ZIP), _verify_zip(TECHNICAL_ZIP)]
    for item in results:
        Path(str(item["path"]) + ".sha256").write_text(f"{item['sha256']}  {Path(str(item['path'])).name}\n", encoding="ascii")
    receipt = {
        "schema_version": "retained6_package_receipt_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "release": RELEASE_BASENAME,
        "structural_ready": True,
        "scientific_ready": bool(validation.get("scientific_ready")),
        "archives": results,
        "netcdf_included": False,
        "rds_included": False,
    }
    (DELIVERABLES / f"{RELEASE_BASENAME}_PACKAGE_RECEIPT.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return receipt


def main() -> None:
    print(json.dumps(package(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
