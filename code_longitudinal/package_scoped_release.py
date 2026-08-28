from __future__ import annotations

import ast
import json
import re
import shutil
import zipfile
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from .paths import ROOT, RUNS_DIR
from .release_scope import ReleaseScope, load_release_scope
from .scoped_finalizer import _selected_nls_runs
from .utils import file_sha256


SOURCE_ARCHIVES = {
    "longitudinal_2000_v1_H0A_H1_complet_20260816.zip": "ed80a7dfb14653ec0be943c811317c6786651fa8d97e12870f366dde1df74446",
    "longitudinal_2000_v1.0.1_H0A_H1_validated_professeur.zip": "bae38ffe56159dd6ff5fe7476015a4702ee503bc7e151b314487229654733038",
    "longitudinal_2000_v1.0.1_H0A_H1_validated_technique.zip": "087678a5dc5dd37238f00e848cf977c8bc38d457f73aa5d6d1703c30e302f67b",
}
TEXT_SUFFIXES = {".txt", ".md", ".json", ".csv", ".py", ".r", ".toml", ".yaml", ".yml"}
ABSOLUTE_WINDOWS_PATH = re.compile(r"(?i)(?:^|[\s\"'])[A-Z]:[\\/]")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_clean_staging(path: Path, expected_name: str) -> None:
    work = (ROOT / "work").resolve()
    resolved = path.resolve()
    if resolved.parent != work or resolved.name != expected_name:
        raise ValueError(f"refusing to replace unexpected staging directory: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True)


def _copy(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def _verify_immutable_sources() -> dict[str, str]:
    observed: dict[str, str] = {}
    for filename, expected in SOURCE_ARCHIVES.items():
        path = ROOT / "deliverables" / filename
        digest = file_sha256(path)
        if digest != expected:
            raise AssertionError(f"immutable source hash changed: {filename}")
        observed[filename] = digest
    return observed


def _write_release_documents(release_root: Path, scope: ReleaseScope) -> None:
    nls_summary = pd.read_csv(release_root / "02_syntheses" / "nls_python_r_replication_summary.csv").iloc[0]
    _write_text(
        release_root / "README_PROFESSEUR.md",
        f"""# {scope.release_id}

Cette release corrective porte uniquement sur le perimetre `{scope.ready_scope}`. Elle conserve exactement les estimations canoniques de la v1.0.1 et corrige l'interface publique, les syntheses, les dictionnaires, les figures et le packaging.

Commencer par `RAPPORT_TECHNIQUE_v1.0.2.pdf`. Les trois Parquet publics se trouvent dans `01_resultats_python/`.

`ready=true` signifie uniquement que le perimetre `{scope.ready_scope}` est valide. H2/H3 appartiennent a la release v1.1 separee.
""",
    )
    _write_text(
        release_root / "DEPENDENCIES_AND_REPRODUCTION.md",
        """# Dependances et reproduction

La lecture des trois Parquet publics ne requiert que Python, pandas et pyarrow (ou un autre lecteur Parquet).

La reproduction complete des modeles exige le depot parent, les archives brutes documentees, Python 3.12 et les versions listees dans le bundle technique. Les archives brutes et les matrices `model_ready` ne sont pas livrees.

Les KRT utilisent PyEI/PyMC avec quatre chaines, 1 000 iterations de chauffe, 1 000 tirages, `target_accept=0.99`, `max_treedepth=14` et `king_lambda=0.5`. Les NetCDF sont exclus des deux archives.

La replication NLS utilise R et Python. Rscript doit etre disponible dans `PATH` ou par la variable `LONGITUDINAL_RSCRIPT`.
""",
    )
    _write_text(
        release_root / "CHANGELOG_v1.0.2.md",
        f"""# Changelog v1.0.2

## Corrections

- configuration de release unique et effectifs derives du perimetre ;
- schema public `{scope.public_schema_version}` ;
- `revenue` renomme `revenue_ratio` et `capital` renomme `capital_ratio` ;
- ajout du nom communal canonique 2022 et de la version geographique ;
- diagnostics KRT regeneres depuis la selection canonique : H0A 14 pass / 12 caveat, H1 19 pass / 7 caveat ;
- trajectoires H0A/H1 et comparaison KRT-NLS regenerees ;
- dictionnaires public et technique reconstruits ;
- manifestes et chemins de livraison synchronises ;
- rapport professeur de huit pages regenere et verifie visuellement.

## Invariance scientifique

Aucune estimation H0A/H1 n'a ete recalculee. Les valeurs communales, agregats KRT, diagnostics canoniques et resultats NLS sont exactement identiques a la v1.0.1 apres tri par les cles.

## Replication NLS

- {int(nls_summary['n_election_scenario_pairs'])} couples reproduits en R et Python ;
- ecart maximal absolu {float(nls_summary['maximum_absolute_difference']):.7e} < 1e-6.

## Reserve

`ready=true` couvre uniquement `{scope.ready_scope}`. H2/H3 sont produits dans la v1.1 distincte. Les 22 RxC restent differes.
""",
    )


def _refresh_release_manifest(release_root: Path, scope: ReleaseScope, source_hashes: Mapping[str, str]) -> dict[str, Any]:
    result_dir = release_root / "01_resultats_python"
    outputs: dict[str, Any] = {}
    for filename in (
        "longitudinal_krt_commune.parquet",
        "longitudinal_krt_aggregate.parquet",
        "longitudinal_nls.parquet",
    ):
        path = result_dir / filename
        outputs[path.stem] = {
            "runtime_path": f"work/{release_root.name}/01_resultats_python/{filename}",
            "delivery_path": f"01_resultats_python/{filename}",
            "delivery_included": True,
            "external_required": False,
            "rows": int(pd.read_parquet(path).shape[0]),
            "sha256": file_sha256(path),
        }
    manifest = {
        "manifest_schema_version": "longitudinal_delivery_manifest_v1.0.2",
        "release_id": scope.release_id,
        "ready": True,
        "ready_scope": scope.ready_scope,
        "public_schema_version": scope.public_schema_version,
        "krt_scenarios": list(scope.krt_scenarios),
        "panel_size": scope.panel_size,
        "panel_sha256": scope.panel_sha256,
        "expected": {
            "elections": scope.expected_elections,
            "krt_pairs": scope.expected_krt_pairs,
            "krt_commune_rows": scope.expected_krt_commune_rows,
            "krt_aggregate_rows": scope.expected_krt_aggregate_rows,
            "nls_pairs": scope.expected_nls_pairs,
        },
        "outputs": outputs,
        "source_archives_immutable": dict(source_hashes),
        "full_reproduction_requires_parent_repository": True,
        "netcdf_included": False,
        "created_at_utc": _utc_now(),
    }
    _write_json(result_dir / "release_manifest.json", manifest)
    return manifest


def _relative_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module:
                result.add(node.module.split(".", 1)[0])
            else:
                result.update(alias.name for alias in node.names)
    return result


def _production_module_closure() -> set[str]:
    entrypoints = {
        "scoped_pipeline",
        "release_artifacts",
        "render_scoped_report_pdf",
        "scoped_finalizer",
        "run_r_nls_replication",
        "run_r_king_ei_replication",
    }
    queue = deque(entrypoints)
    selected = {"__init__"}
    source = ROOT / "code_longitudinal"
    while queue:
        module = queue.popleft()
        if module in selected:
            continue
        path = source / f"{module}.py"
        if not path.exists():
            raise FileNotFoundError(path)
        selected.add(module)
        for dependency in sorted(_relative_imports(path)):
            if (source / f"{dependency}.py").exists() and dependency not in selected:
                queue.append(dependency)
    prohibited = {
        "package_release_v101", "build_v101_report", "build_v101_syntheses",
        "run_priority_production", "run_priority_production_v2", "run_priority_production_v3",
    }
    if selected.intersection(prohibited):
        raise AssertionError(f"historical modules leaked into production bundle: {sorted(selected.intersection(prohibited))}")
    return selected


def _build_code_bundle(release_root: Path, config_path: Path) -> dict[str, Any]:
    bundle = release_root / "05_methodologie_et_code" / "current_v1.0.2"
    if bundle.exists():
        shutil.rmtree(bundle)
    modules = _production_module_closure()
    for module in sorted(modules):
        _copy(ROOT / "code_longitudinal" / f"{module}.py", bundle / "code_longitudinal" / f"{module}.py")
    _copy(config_path, bundle / "config" / "release_v1.0.2.json")
    _copy(ROOT / "config" / "releases" / "v1.1.json", bundle / "config" / "release_v1.1.json")
    _copy(ROOT / "config" / "run_settings.json", bundle / "config" / "run_settings.json")
    for name in (
        "test_release_scope.py", "test_diagnostics_v2.py", "test_identification_v2.py",
        "test_nls.py", "test_partitions.py", "test_postprocess_aggregates_v2.py",
        "test_panel_2000_integrity_audit.py", "test_longitudinal_v1.py",
    ):
        _copy(ROOT / "tests" / name, bundle / "tests" / name)
    _copy(ROOT / "tests" / "conftest.py", bundle / "tests" / "conftest.py")
    for name in ("run_king_ei_replication.R", "run_nls_replication.R"):
        _copy(ROOT / "r_replication" / name, bundle / "r_replication" / name)
    _copy(ROOT / "requirements-production-v101.txt", bundle / "requirements-production-v1.0.2.txt")
    _copy(ROOT / "requirements-dev.txt", bundle / "requirements-dev.txt")
    _copy(ROOT / "R_REQUIREMENTS.md", bundle / "R_REQUIREMENTS.md")
    _write_text(
        bundle / "START_HERE.md",
        """# Bundle minimal de production v1.0.2/v1.1

Ce bundle contient uniquement la chaine necessaire a l'audit, la consolidation, la migration v1.0.2, le rapport, le packaging et la production KRT H2/H3 configuree.

Exemples:

```powershell
python -m code_longitudinal.scoped_pipeline krt --release-config config/release_v1.1.json --scenario-id H2 --election-id leg_1962_r1
python -m code_longitudinal.scoped_pipeline finalize --release-config config/release_v1.1.json --canonical-selection canonical_run_selection.csv
```

La reproduction complete exige le depot parent, les archives brutes et les matrices preparees. Les NetCDF ne sont pas livres.
""",
    )
    inventory = []
    for module in sorted(modules):
        path = ROOT / "code_longitudinal" / f"{module}.py"
        inventory.append(
            {
                "module": module,
                "lines": len(path.read_text(encoding="utf-8").splitlines()),
                "bundle_path": f"code_longitudinal/{module}.py",
                "sha256": file_sha256(path),
            }
        )
    pd.DataFrame(inventory).to_csv(bundle / "CODE_INVENTORY.csv", index=False, encoding="utf-8-sig")
    return {"module_count": len(modules), "bundle_path": bundle.relative_to(release_root).as_posix()}


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {_sanitize_string(str(key)): _sanitize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if not isinstance(value, str):
        return value
    return _sanitize_string(value)


def _sanitize_string(value: str) -> str:
    normalized = value.replace(str(ROOT), ".").replace(ROOT.as_posix(), ".")
    candidate = Path(normalized)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            return f"external_required/{candidate.name}"
    return normalized.replace("\\", "/")


def _copy_run_diagnostics(run_id: str, destination: Path, *, kind: str) -> None:
    source = RUNS_DIR / run_id
    files = (
        ("model_diagnostics.csv", "manifest.json", "mcmc_diagnostics_v2.json", "identification_diagnostics.json", "aggregate_comparison_v2.csv", "mcmc_variable_metrics_v2.csv", "mcmc_block_metrics_v2.csv")
        if kind == "krt"
        else ("model_diagnostics.csv", "manifest.json", "nls_start_diagnostics.csv", "nls_coefficients.csv")
    )
    target = destination / "06_diagnostics_runs" / kind / run_id
    for filename in files:
        path = source / filename
        if not path.exists():
            continue
        if filename == "manifest.json":
            manifest = _sanitize_value(json.loads(path.read_text(encoding="utf-8")))
            manifest["runtime_path"] = f"outputs/runs/{run_id}"
            manifest["delivery_path"] = f"06_diagnostics_runs/{kind}/{run_id}"
            manifest["delivery_included"] = True
            manifest["external_required"] = True
            _write_json(target / filename, manifest)
        else:
            _copy(path, target / filename)


def _copy_professor_files(release_root: Path, staging: Path) -> None:
    mapping = {
        "RAPPORT_TECHNIQUE_v1.0.2.pdf": "RAPPORT_TECHNIQUE_v1.0.2.pdf",
        "README_PROFESSEUR.md": "README_PROFESSEUR.md",
        "CHANGELOG_v1.0.2.md": "CHANGELOG_v1.0.2.md",
        "VALIDATION_v1.0.2.md": "VALIDATION_v1.0.2.md",
        "DEPENDENCIES_AND_REPRODUCTION.md": "DEPENDENCIES_AND_REPRODUCTION.md",
        "05_methodologie_et_code/release_config_v1.0.2.json": "release_config_v1.0.2.json",
        "01_resultats_python/longitudinal_krt_commune.parquet": "01_resultats_python/longitudinal_krt_commune.parquet",
        "01_resultats_python/longitudinal_krt_aggregate.parquet": "01_resultats_python/longitudinal_krt_aggregate.parquet",
        "01_resultats_python/longitudinal_nls.parquet": "01_resultats_python/longitudinal_nls.parquet",
        "01_resultats_python/release_manifest.json": "01_resultats_python/release_manifest.json",
        "02_syntheses/canonical_run_selection.csv": "02_syntheses/canonical_run_selection.csv",
        "02_syntheses/diagnostics_krt_resume.csv": "02_syntheses/diagnostics_krt_resume.csv",
        "02_syntheses/diagnostics_krt_par_election.csv": "02_syntheses/diagnostics_krt_par_election.csv",
        "02_syntheses/etat_modeles_par_election.csv": "02_syntheses/etat_modeles_par_election.csv",
        "02_syntheses/trajectoires_krt.csv": "02_syntheses/trajectoires_krt.csv",
        "02_syntheses/krt_nls_comparison_h0a_h1.csv": "02_syntheses/krt_nls_comparison_h0a_h1.csv",
        "02_syntheses/nls_python_r_replication_summary.csv": "02_syntheses/nls_python_r_replication_summary.csv",
        "02_syntheses/h1_panel_sensitivity.csv": "02_syntheses/h1_panel_sensitivity.csv",
        "02_syntheses/targeted_mcmc_reruns.csv": "02_syntheses/targeted_mcmc_reruns.csv",
        "02_syntheses/definitions_hypotheses.csv": "02_syntheses/definitions_hypotheses.csv",
        "03_panel_et_audit/panel_primaire_2000.csv": "03_panel_et_audit/panel_primaire_2000.csv",
        "03_panel_et_audit/DATA_DICTIONARY.csv": "03_panel_et_audit/DATA_DICTIONARY.csv",
        "03_panel_et_audit/SCHEMA_MIGRATION_v1.0.1_to_v1.0.2.csv": "03_panel_et_audit/SCHEMA_MIGRATION_v1.0.1_to_v1.0.2.csv",
        "03_panel_et_audit/HARMONISATION_POLITIQUE.csv": "03_panel_et_audit/HARMONISATION_POLITIQUE.csv",
        "03_panel_et_audit/COVARIATE_PROVENANCE.csv": "03_panel_et_audit/COVARIATE_PROVENANCE.csv",
        "03_panel_et_audit/coverage_by_election_department.csv": "03_panel_et_audit/coverage_by_election_department.csv",
        "03_panel_et_audit/panel_exact_validation.json": "03_panel_et_audit/panel_exact_validation.json",
        "03_panel_et_audit/foreign_share_source_validation.csv": "03_panel_et_audit/foreign_share_source_validation.csv",
        "03_panel_et_audit/NUMERICAL_INVARIANCE_v1.0.1_to_v1.0.2.json": "03_panel_et_audit/NUMERICAL_INVARIANCE_v1.0.1_to_v1.0.2.json",
        "04_figures_essentielles/h0a_contrast.png": "04_figures_essentielles/h0a_contrast.png",
        "04_figures_essentielles/h1_contrast.png": "04_figures_essentielles/h1_contrast.png",
        "04_figures_essentielles/krt_nls_comparison.png": "04_figures_essentielles/krt_nls_comparison.png",
        "04_figures_essentielles/h1_panel_sensitivity.png": "04_figures_essentielles/h1_panel_sensitivity.png",
        "04_figures_essentielles/raw_scatter_2022_bounds_and_target_share.png": "04_figures_essentielles/raw_scatter_2022_bounds_and_target_share.png",
    }
    for source, destination in mapping.items():
        _copy(release_root / source, staging / destination)


def _delivery_manifest(staging: Path, scope: ReleaseScope, archive_role: str) -> dict[str, Any]:
    files = []
    for path in sorted(staging.rglob("*")):
        if path.is_file() and path.name != "DELIVERY_MANIFEST.json":
            files.append(
                {
                    "delivery_path": path.relative_to(staging).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "sha256": file_sha256(path),
                }
            )
    manifest = {
        "release_id": scope.release_id,
        "archive_role": archive_role,
        "ready": True,
        "ready_scope": scope.ready_scope,
        "delivery_root": ".",
        "contains_netcdf": False,
        "files": files,
    }
    _write_json(staging / "DELIVERY_MANIFEST.json", manifest)
    return manifest


def _scan_delivery(staging: Path) -> dict[str, Any]:
    netcdf = [path.relative_to(staging).as_posix() for path in staging.rglob("*.nc")]
    absolute_hits: list[str] = []
    stale_hits: list[str] = []
    for path in staging.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if ABSOLUTE_WINDOWS_PATH.search(text):
            absolute_hits.append(path.relative_to(staging).as_posix())
        stale_tokens = ("release" + "_01", "02_comparaison_python_r_" + "king/")
        if any(token in text for token in stale_tokens):
            stale_hits.append(path.relative_to(staging).as_posix())
    result = {
        "contains_netcdf": bool(netcdf),
        "netcdf_paths": netcdf,
        "absolute_path_files": absolute_hits,
        "stale_reference_files": stale_hits,
        "status": "pass" if not netcdf and not absolute_hits and not stale_hits else "fail",
    }
    if result["status"] != "pass":
        raise AssertionError(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _zip_verify(staging: Path, zip_path: Path) -> dict[str, Any]:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = zip_path.with_suffix(".zip.tmp")
    if temporary.exists():
        temporary.unlink()
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(staging).as_posix())
    temporary.replace(zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise AssertionError(f"ZIP CRC failure: {bad}")
        verification_name = f"zip_reextract_{zip_path.stem}"
        extracted = ROOT / "work" / verification_name
        _safe_clean_staging(extracted, verification_name)
        archive.extractall(extracted)
        manifest = json.loads((extracted / "DELIVERY_MANIFEST.json").read_text(encoding="utf-8"))
        for item in manifest["files"]:
            path = extracted / item["delivery_path"]
            if not path.exists() or file_sha256(path) != item["sha256"]:
                raise AssertionError(f"delivery hash mismatch after extraction: {item['delivery_path']}")
        _scan_delivery(extracted)
    digest = file_sha256(zip_path)
    _write_text(zip_path.with_suffix(zip_path.suffix + ".sha256"), f"{digest}  {zip_path.name}\n")
    return {"path": str(zip_path), "sha256": digest, "size_bytes": zip_path.stat().st_size}


def package_v102(release_root: Path, config_path: Path) -> dict[str, Any]:
    scope = load_release_scope(config_path)
    source_hashes_before = _verify_immutable_sources()
    _write_release_documents(release_root, scope)
    _copy(config_path, release_root / "05_methodologie_et_code" / "release_config_v1.0.2.json")
    code_bundle = _build_code_bundle(release_root, config_path)
    release_manifest = _refresh_release_manifest(release_root, scope, source_hashes_before)
    _write_text(
        release_root / "VALIDATION_v1.0.2.md",
        f"""# Validation v1.0.2

- ready: true
- ready_scope: {scope.ready_scope}
- panel: {scope.panel_size} communes, hash conforme
- KRT: {scope.expected_krt_pairs} couples, {scope.expected_krt_commune_rows} lignes communales, {scope.expected_krt_aggregate_rows} agregats
- NLS: {scope.expected_nls_pairs} couples publics
- invariance scientifique v1.0.1 vers v1.0.2: pass
- diagnostics canoniques: H0A 14 pass / 12 caveat; H1 19 pass / 7 caveat
- NetCDF livres: non
- reproduction complete: depot parent requis
""",
    )

    professor = ROOT / "work" / "package_staging_v102_professeur"
    technical = ROOT / "work" / "package_staging_v102_technique"
    _safe_clean_staging(professor, "package_staging_v102_professeur")
    _safe_clean_staging(technical, "package_staging_v102_technique")
    _copy_professor_files(release_root, professor)
    _copy_professor_files(release_root, technical)
    _copy(release_root / "03_panel_et_audit" / "DATA_DICTIONARY_TECHNICAL.csv", technical / "03_panel_et_audit" / "DATA_DICTIONARY_TECHNICAL.csv")
    _copy(release_root / "03_panel_et_audit" / "rxc_ineligible_audit.csv", technical / "03_panel_et_audit" / "rxc_ineligible_audit.csv")
    _copy(release_root / "03_panel_et_audit" / "department54_pre1988_rows.csv", technical / "03_panel_et_audit" / "department54_pre1988_rows.csv")
    for path in (release_root / "02_comparaison_python_r").glob("*"):
        if path.is_file() and path.suffix.lower() != ".nc":
            _copy(path, technical / "02_comparaison_python_r" / path.name)
    shutil.copytree(
        release_root / "05_methodologie_et_code" / "current_v1.0.2",
        technical / "05_methodologie_et_code" / "current_v1.0.2",
    )

    selection = pd.read_csv(release_root / "02_syntheses" / "canonical_run_selection.csv", dtype="string")
    for run_id in selection["run_id"].astype(str):
        _copy_run_diagnostics(run_id, technical, kind="krt")
    panel_id = str(pd.read_parquet(release_root / "01_resultats_python" / "longitudinal_nls.parquet")["panel_id"].iloc[0])
    for _, manifest in _selected_nls_runs(panel_id):
        _copy_run_diagnostics(str(manifest["run_id"]), technical, kind="nls")

    professor_manifest = _delivery_manifest(professor, scope, "professeur_light")
    technical_manifest = _delivery_manifest(technical, scope, "technical_complete")
    professor_scan = _scan_delivery(professor)
    technical_scan = _scan_delivery(technical)

    deliverables = ROOT / "deliverables"
    professor_zip = deliverables / "longitudinal_2000_v1.0.2_H0A_H1_validated_professeur.zip"
    technical_zip = deliverables / "longitudinal_2000_v1.0.2_H0A_H1_validated_technique.zip"
    zipped_professor = _zip_verify(professor, professor_zip)
    zipped_technical = _zip_verify(technical, technical_zip)
    source_hashes_after = _verify_immutable_sources()
    if source_hashes_before != source_hashes_after:
        raise AssertionError("an immutable source archive changed during packaging")

    validated = ROOT / "work" / "longitudinal_2000_v1.0.2_H0A_H1_validated"
    _safe_clean_staging(validated, "longitudinal_2000_v1.0.2_H0A_H1_validated")
    shutil.copytree(technical, validated, dirs_exist_ok=True)
    result = {
        "release_id": scope.release_id,
        "ready": True,
        "ready_scope": scope.ready_scope,
        "release_manifest": release_manifest,
        "code_bundle": code_bundle,
        "professor": {"manifest_files": len(professor_manifest["files"]), "scan": professor_scan, "zip": zipped_professor},
        "technical": {"manifest_files": len(technical_manifest["files"]), "scan": technical_scan, "zip": zipped_technical},
        "validated_root": str(validated),
        "immutable_source_hashes": source_hashes_after,
    }
    _write_json(deliverables / "longitudinal_2000_v1.0.2_H0A_H1_PACKAGE_VALIDATION.json", result)
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Build and verify v1.0.2 professor and technical archives.")
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(package_v102(args.release_root, args.config), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
