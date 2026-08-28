from __future__ import annotations

import argparse
import ast
import csv
import json
import shutil
import tempfile
import zipfile
from collections import deque
from pathlib import Path
from typing import Any, Iterable

from .paths import ROOT
from .utils import file_sha256, write_json


BUNDLE_NAME = "longitudinal_2000_v1.0.1_H0A_H1_code_production"
DEFAULT_OUTPUT = ROOT / "work" / BUNDLE_NAME
DEFAULT_ZIP = ROOT / "deliverables" / f"{BUNDLE_NAME}.zip"

PRODUCTION_ENTRYPOINTS = (
    "release_v1_0_1_audit",
    "run_h1_panel_sensitivity_v101",
    "run_targeted_mcmc_v101",
    "build_v101_syntheses",
    "build_v101_report",
    "render_v101_report_pdf",
    "package_release_v101",
)
REPLICATION_ENTRYPOINTS = (
    "run_r_king_ei_replication",
    "run_r_nls_replication",
)
EXPECTED_MODULES = {
    "__init__",
    "audit_longitudinal",
    "balance_checks",
    "build_longitudinal_panel",
    "build_panel",
    "build_v101_report",
    "build_v101_syntheses",
    "consolidation_core",
    "data_io",
    "diagnostics_v2",
    "finalize_longitudinal",
    "identification_v2",
    "nls",
    "output_schema",
    "package_release_v101",
    "paths",
    "postprocess_aggregates_v2",
    "prepare_inputs",
    "release_artifacts",
    "release_scope",
    "release_v1_0_1_audit",
    "render_v101_report_pdf",
    "run_2x2_batch",
    "run_h1_panel_sensitivity_v101",
    "run_r_king_ei_replication",
    "run_r_nls_replication",
    "run_registry",
    "run_targeted_mcmc_v101",
    "scoped_finalizer",
    "spec_registry",
    "utils",
}
PRODUCTION_TESTS = (
    "test_diagnostics_v2.py",
    "test_identification_v2.py",
    "test_longitudinal_v1.py",
    "test_nls.py",
    "test_partitions.py",
    "test_postprocess_aggregates_v2.py",
    "test_release_v101.py",
    "test_rscript_discovery.py",
)
R_SCRIPTS = (
    "run_king_ei_replication.R",
    "run_nls_replication.R",
)


def _relative_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    dependencies: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level != 1:
            continue
        if node.module:
            dependencies.add(node.module.split(".", 1)[0])
        else:
            for alias in node.names:
                candidate = ROOT / "code_longitudinal" / f"{alias.name}.py"
                if candidate.exists():
                    dependencies.add(alias.name)
    return dependencies


def production_dependency_closure() -> set[str]:
    source = ROOT / "code_longitudinal"
    queue = deque((*PRODUCTION_ENTRYPOINTS, *REPLICATION_ENTRYPOINTS))
    selected = {"__init__"}
    while queue:
        module = queue.popleft()
        if module in selected:
            continue
        path = source / f"{module}.py"
        if not path.exists():
            raise FileNotFoundError(f"missing production dependency: {path}")
        selected.add(module)
        queue.extend(sorted(_relative_imports(path) - selected))
    if selected != EXPECTED_MODULES:
        missing = sorted(EXPECTED_MODULES - selected)
        unexpected = sorted(selected - EXPECTED_MODULES)
        raise AssertionError(
            f"production dependency closure changed; missing={missing}, unexpected={unexpected}"
        )
    return selected


def _safe_replace_directory(path: Path) -> None:
    work_root = (ROOT / "work").resolve()
    resolved = path.resolve()
    if resolved.parent != work_root or resolved.name != BUNDLE_NAME:
        raise ValueError(f"refusing to replace unexpected bundle path: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True)


def _copy_file(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _module_role(module: str) -> str:
    if module in PRODUCTION_ENTRYPOINTS:
        return "production_entrypoint"
    if module in REPLICATION_ENTRYPOINTS:
        return "replication_entrypoint"
    if module == "__init__":
        return "package"
    return "production_dependency"


def _write_code_inventory(bundle: Path, modules: set[str]) -> None:
    rows = []
    for module in sorted(modules):
        path = ROOT / "code_longitudinal" / f"{module}.py"
        dependencies = sorted(_relative_imports(path) & modules)
        rows.append(
            {
                "module": module,
                "role": _module_role(module),
                "lines": len(path.read_text(encoding="utf-8").splitlines()),
                "direct_internal_dependencies": ";".join(dependencies),
                "bundle_path": f"code_longitudinal/{module}.py",
                "sha256": file_sha256(path),
            }
        )
    _write_csv(
        bundle / "CODE_INVENTORY.csv",
        rows,
        [
            "module",
            "role",
            "lines",
            "direct_internal_dependencies",
            "bundle_path",
            "sha256",
        ],
    )


def _production_steps() -> list[dict[str, Any]]:
    return [
        {"order": 1, "stage": "audit", "expensive": False, "command": "python -m code_longitudinal.release_v1_0_1_audit", "main_outputs": "03_panel_et_audit; canonical_run_selection.csv"},
        {"order": 2, "stage": "h1_sensitivity_prepare", "expensive": False, "command": "python -m code_longitudinal.run_h1_panel_sensitivity_v101 prepare", "main_outputs": "runtime panels; NLS diagnostics; input hashes"},
        {"order": 3, "stage": "h1_sensitivity_krt", "expensive": True, "command": "python -m code_longitudinal.run_h1_panel_sensitivity_v101 run-krt", "main_outputs": "six auxiliary KRT runs"},
        {"order": 4, "stage": "h1_sensitivity_finalize", "expensive": False, "command": "python -m code_longitudinal.run_h1_panel_sensitivity_v101 finalize", "main_outputs": "h1_panel_sensitivity.csv; figure"},
        {"order": 5, "stage": "targeted_mcmc", "expensive": True, "command": "python -m code_longitudinal.run_targeted_mcmc_v101 run", "main_outputs": "six long robustness runs"},
        {"order": 6, "stage": "targeted_finalize", "expensive": False, "command": "python -m code_longitudinal.run_targeted_mcmc_v101 finalize", "main_outputs": "targeted_mcmc_reruns.csv; canonical selection"},
        {"order": 7, "stage": "syntheses", "expensive": False, "command": "python -m code_longitudinal.build_v101_syntheses all", "main_outputs": "three Parquet; comparisons; figures"},
        {"order": 8, "stage": "sync_delivery", "expensive": False, "command": "python -m code_longitudinal.package_release_v101 clean", "main_outputs": "sanitized manifests and current code"},
        {"order": 9, "stage": "report", "expensive": False, "command": "python -m code_longitudinal.build_v101_report --ready", "main_outputs": "HTML; changelog; reproduction notice"},
        {"order": 10, "stage": "pdf", "expensive": False, "command": "python -m code_longitudinal.render_v101_report_pdf --payload work/longitudinal_2000_v1.0.1_H0A_H1_candidate/05_methodologie_et_code/report_payload_v1.0.1.json --release-root work/longitudinal_2000_v1.0.1_H0A_H1_candidate --output work/longitudinal_2000_v1.0.1_H0A_H1_candidate/RAPPORT_TECHNIQUE_v1.0.1.pdf", "main_outputs": "RAPPORT_TECHNIQUE_v1.0.1.pdf"},
        {"order": 11, "stage": "validate", "expensive": False, "command": "python -m code_longitudinal.package_release_v101 validate", "main_outputs": "validation report; ready scope"},
        {"order": 12, "stage": "package", "expensive": False, "command": "python -m code_longitudinal.package_release_v101 package", "main_outputs": "professor and technical ZIPs"},
        {"order": 13, "stage": "r_nls_replication", "expensive": False, "command": "python -m code_longitudinal.run_r_nls_replication", "main_outputs": "R/Python NLS comparison"},
        {"order": 14, "stage": "r_king_replication", "expensive": True, "command": "python -m code_longitudinal.run_r_king_ei_replication", "main_outputs": "R/Python King comparison"},
    ]


def _write_documentation(bundle: Path, modules: set[str]) -> None:
    _write_csv(
        bundle / "PRODUCTION_STEPS.csv",
        _production_steps(),
        ["order", "stage", "expensive", "command", "main_outputs"],
    )
    lines = sum(
        len((ROOT / "code_longitudinal" / f"{module}.py").read_text(encoding="utf-8").splitlines())
        for module in modules
    )
    start = f"""# Code de production — longitudinal 2000 v1.0.1 H0A/H1

Ce paquet contient uniquement le code nécessaire aux sorties importantes de la release : audit, sensibilité H1, relances KRT ciblées, consolidation des trois Parquet, figures, rapport, packaging et réplications R/Python.

## Périmètre

- {len(PRODUCTION_ENTRYPOINTS)} points d'entrée de production Python ;
- {len(REPLICATION_ENTRYPOINTS)} points d'entrée de réplication R/Python ;
- {len(modules)} modules Python au total, dépendances comprises ({lines} lignes) ;
- {len(PRODUCTION_TESTS)} fichiers de tests ciblés ;
- aucun script V2/V3 de livraison historique, aucun cache, aucun résultat et aucune trace MCMC.

`CODE_INVENTORY.csv` décrit chaque module et ses dépendances. `PRODUCTION_STEPS.csv` donne l'ordre des commandes et signale les étapes coûteuses.

## Installation

Python 3.12 est requis.

```powershell
python -m pip install -r requirements-production-v101.txt
python -m pip install -r requirements-dev.txt
```

Pour utiliser ce paquet depuis un autre emplacement, pointer explicitement vers le dépôt de calcul :

```powershell
$env:LONGITUDINAL_PROJECT_ROOT = "C:\\chemin\\vers\\longitudinal_2022"
```

Pour R, mettre `Rscript` dans `PATH` ou définir `LONGITUDINAL_RSCRIPT`.
Les paquets et versions de référence sont listés dans `R_REQUIREMENTS.md`.

## Exécution

Commencer par les étapes non coûteuses de `PRODUCTION_STEPS.csv`. Les commandes marquées `expensive=true` relancent des KRT seulement si aucun succès compatible n'est déjà enregistré.

## Limite volontaire

Le paquet ne contient ni les archives brutes, ni les matrices `model_ready`, ni les traces NetCDF. La reproduction numérique complète nécessite le dépôt parent et les sources documentées dans la release validée. Le paquet est autonome pour auditer le code et exécuter les tests unitaires ciblés.
"""
    (bundle / "START_HERE.md").write_text(start, encoding="utf-8")
    test_readme = """# Tests ciblés du code de production

Cette sélection teste les partitions, le NLS, les diagnostics MCMC, l'identification écologique, les agrégats, le schéma v1.0.1, les chemins de livraison et la détection de Rscript.

```powershell
python -m pytest -q -p no:cacheprovider tests
```

Les tests ne relancent aucune estimation MCMC de production.
"""
    (bundle / "tests" / "README.md").write_text(test_readme, encoding="utf-8")


def _validate_bundle(bundle: Path, modules: set[str]) -> dict[str, Any]:
    bundled_modules = {
        path.stem for path in (bundle / "code_longitudinal").glob("*.py")
    }
    unresolved: dict[str, list[str]] = {}
    for module in sorted(modules):
        path = bundle / "code_longitudinal" / f"{module}.py"
        missing = sorted(_relative_imports(path) - modules)
        if missing:
            unresolved[module] = missing
    checks = {
        "exact_production_module_set": bundled_modules == modules == EXPECTED_MODULES,
        "all_relative_imports_resolved": not unresolved,
        "exact_targeted_test_set": {
            path.name for path in (bundle / "tests").glob("test_*.py")
        } == set(PRODUCTION_TESTS),
        "r_replication_scripts_present": all(
            (bundle / "r_replication" / name).is_file() for name in R_SCRIPTS
        ),
        "configuration_present": (bundle / "config" / "run_settings.json").is_file(),
        "requirements_present": all(
            (bundle / name).is_file()
            for name in ("requirements-production-v101.txt", "requirements-dev.txt", "R_REQUIREMENTS.md")
        ),
        "no_python_cache": not any(bundle.rglob("__pycache__")) and not any(bundle.rglob("*.pyc")),
        "start_here_present": (bundle / "START_HERE.md").is_file(),
        "code_inventory_present": (bundle / "CODE_INVENTORY.csv").is_file(),
        "production_steps_present": (bundle / "PRODUCTION_STEPS.csv").is_file(),
    }
    report = {
        "bundle_name": BUNDLE_NAME,
        "checks": checks,
        "all_pass": all(checks.values()),
        "module_count": len(modules),
        "test_file_count": len(PRODUCTION_TESTS),
        "unresolved_imports": unresolved,
    }
    write_json(bundle / "BUNDLE_VALIDATION.json", report)
    if not report["all_pass"]:
        raise AssertionError(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _write_manifest(bundle: Path) -> dict[str, Any]:
    files = []
    for path in sorted(bundle.rglob("*")):
        if path.is_file() and path.name != "BUNDLE_MANIFEST.json":
            files.append(
                {
                    "path": path.relative_to(bundle).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": file_sha256(path),
                }
            )
    manifest = {
        "bundle_name": BUNDLE_NAME,
        "scope": "code_required_for_v1.0.1_H0A_H1_core_outputs_and_R_replications",
        "parent_repository_required_for_full_reproduction": True,
        "files": files,
    }
    write_json(bundle / "BUNDLE_MANIFEST.json", manifest)
    return manifest


def _zip_and_verify(bundle: Path, zip_path: Path) -> dict[str, Any]:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = zip_path.with_suffix(".zip.tmp")
    if temporary.exists():
        temporary.unlink()
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(bundle).as_posix())
    temporary.replace(zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        if archive.testzip() is not None:
            raise AssertionError("ZIP CRC validation failed")
        with tempfile.TemporaryDirectory(prefix="verify_code_v101_") as temp:
            extracted = Path(temp)
            archive.extractall(extracted)
            manifest = json.loads((extracted / "BUNDLE_MANIFEST.json").read_text(encoding="utf-8"))
            for item in manifest["files"]:
                if file_sha256(extracted / item["path"]) != item["sha256"]:
                    raise AssertionError(f"ZIP manifest hash mismatch: {item['path']}")
    digest = file_sha256(zip_path)
    zip_path.with_suffix(zip_path.suffix + ".sha256").write_text(
        f"{digest}  {zip_path.name}\n", encoding="ascii"
    )
    with zipfile.ZipFile(zip_path) as archive:
        file_count = len(archive.namelist())
    return {"path": str(zip_path), "sha256": digest, "files": file_count}


def build_bundle(output: Path = DEFAULT_OUTPUT, zip_path: Path = DEFAULT_ZIP) -> dict[str, Any]:
    modules = production_dependency_closure()
    _safe_replace_directory(output)
    for module in sorted(modules):
        _copy_file(
            ROOT / "code_longitudinal" / f"{module}.py",
            output / "code_longitudinal" / f"{module}.py",
        )
    for path in (ROOT / "config").glob("*"):
        if path.is_file():
            _copy_file(path, output / "config" / path.name)
    _copy_file(ROOT / "tests" / "conftest.py", output / "tests" / "conftest.py")
    for name in PRODUCTION_TESTS:
        _copy_file(ROOT / "tests" / name, output / "tests" / name)
    for name in R_SCRIPTS:
        _copy_file(ROOT / "r_replication" / name, output / "r_replication" / name)
    for name in ("requirements-production-v101.txt", "requirements-dev.txt", "R_REQUIREMENTS.md"):
        _copy_file(ROOT / name, output / name)
    _write_code_inventory(output, modules)
    _write_documentation(output, modules)
    validation = _validate_bundle(output, modules)
    manifest = _write_manifest(output)
    zipped = _zip_and_verify(output, zip_path)
    return {
        "bundle": str(output),
        "module_count": len(modules),
        "manifest_file_count": len(manifest["files"]),
        "validation": validation,
        "zip": zipped,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the minimal v1.0.1 production-code bundle.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--zip", dest="zip_path", type=Path, default=DEFAULT_ZIP)
    args = parser.parse_args()
    print(json.dumps(build_bundle(args.output, args.zip_path), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
