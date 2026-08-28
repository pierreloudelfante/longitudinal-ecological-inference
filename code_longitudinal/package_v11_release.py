from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .delivery_utils import (
    copy_file as _copy,
    copy_run_diagnostics as _copy_run_diagnostics,
    delivery_manifest as _delivery_manifest,
    safe_clean_staging as _safe_clean_staging,
    write_json as _write_json,
    write_text as _write_text,
    zip_verify,
)
from .paths import ROOT, RUNS_DIR
from .release_scope import ReleaseScope, load_release_scope
from .scoped_finalizer import _selected_nls_runs
from .utils import file_sha256


IMMUTABLE_SOURCES = {
    "longitudinal_2000_v1_H0A_H1_complet_20260816.zip": "ed80a7dfb14653ec0be943c811317c6786651fa8d97e12870f366dde1df74446",
    "longitudinal_2000_v1.0.2_H0A_H1_validated_professeur.zip": "ccd4ad0ed7c75e3dece34f7ebe1c1a3afa1e6772e65e85a6fd46e2b50ff917f8",
    "longitudinal_2000_v1.0.2_H0A_H1_validated_technique.zip": "db7bc3a04049f56b80dc40bc563044cbdc9ba4aa67b194b038b2e4c00e29bc97",
}
TEXT_SUFFIXES = {".txt", ".md", ".json", ".csv", ".py", ".r", ".toml", ".yaml", ".yml", ".html"}
ABSOLUTE_WINDOWS_PATH = re.compile(r"(?i)(?:^|[\s\"'])[A-Z]:[\\/]")
SOURCE_V102_CONFIG = ROOT / "config" / "releases" / "v1.0.2.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _verify_immutable_sources() -> dict[str, str]:
    observed: dict[str, str] = {}
    for filename, expected in IMMUTABLE_SOURCES.items():
        path = ROOT / "deliverables" / filename
        digest = file_sha256(path)
        if digest != expected:
            raise AssertionError(f"immutable source hash changed: {filename}")
        observed[filename] = digest
    return observed


def _write_release_documents(release_root: Path, scope: ReleaseScope) -> None:
    source_scope = load_release_scope(SOURCE_V102_CONFIG)
    extension_scenarios = tuple(
        scenario for scenario in scope.krt_scenarios if scenario not in source_scope.krt_scenarios
    )
    selection = pd.read_csv(release_root / "02_syntheses" / "canonical_run_selection.csv", dtype="string")
    diagnostics = pd.read_csv(release_root / "02_syntheses" / "diagnostics_krt_par_election.csv")
    h23 = selection.loc[selection["scenario_id"].isin(extension_scenarios)].copy()
    h23_pairs = scope.expected_elections * len(extension_scenarios)
    inherited_pairs = scope.expected_krt_pairs - h23_pairs
    pilot_pairs = min(6, h23_pairs)
    post_pilot_pairs = h23_pairs - pilot_pairs
    reruns = h23.loc[h23["replaces_run_id"].fillna("").ne("")].copy()
    status_counts = (
        diagnostics.groupby(["scenario_id", "mcmc_status"])
        .size()
        .rename("n")
        .reset_index()
    )
    status_lines = []
    for scenario_id in scope.krt_scenarios:
        part = status_counts.loc[status_counts["scenario_id"].eq(scenario_id)].set_index("mcmc_status")["n"]
        status_lines.append(
            f"- {scenario_id}: {int(part.get('pass', 0))} pass, {int(part.get('caveat', 0))} caveat, {int(part.get('fail', 0))} fail"
        )
    rerun_lines = [
        f"- {row.election_id} x {row.scenario_id}: {row.replaces_run_id} -> {row.run_id}"
        for row in reruns.itertuples(index=False)
    ] or ["- aucune relance renforcee selectionnee comme canonique"]
    _write_text(
        release_root / "README_PROFESSEUR.md",
        f"""# {scope.release_id}

Cette release couvre `{scope.ready_scope}` sur le meme panel fixe de {scope.panel_size} communes et {scope.expected_elections} scrutins.

Commencer par `RAPPORT_TECHNIQUE_v1.1.html` ou sa version PDF. Les trois tables publiques se trouvent dans `01_resultats_python/`.

H2 estime `P(gauche | ouvriers)` face aux non-ouvriers; H3 estime `P(gauche | employes)` face aux non-employes. Les complements sont differents: H2/H3 ne forment ni une decomposition formelle de H1 ni un posterior joint ouvriers-employes.

`ready=true` signifie uniquement que le perimetre `{scope.ready_scope}` est valide. Il ne signifie pas que toutes les hypotheses du projet sont achevees.
""",
    )
    _write_text(
        release_root / "DEPENDENCIES_AND_REPRODUCTION.md",
        f"""# Dependances et reproduction

La lecture des Parquet publics requiert un lecteur Parquet, par exemple pandas et pyarrow.

La reproduction complete exige le depot parent, les archives brutes documentees, Python 3.12 et les versions listees dans le bundle technique. Les archives brutes et les matrices `model_ready` ne sont pas incluses.

La regeneration du rapport HTML autonome depuis `report_artifact.json` exige le constructeur portable Data Analytics documente dans `report_delivery_receipt.json`. Le HTML et le PDF deja livres restent lisibles sans ce constructeur externe.

Les KRT utilisent PyEI/PyMC avec le backend NUTS `{scope.mcmc.sampler_backend}`, quatre chaines, 1 000 iterations de chauffe, 1 000 tirages, `target_accept=0.99`, `max_treedepth=14` et `king_lambda=0.5`. Les graines de run sont derivees de facon stable par SHA-256. Choix du backend : {scope.mcmc.sampler_backend_reason}

Les relances preenregistrees utilisent 2 000 iterations de chauffe et 2 000 tirages avec la base de graine 20260817. Les NetCDF ne sont livres dans aucune archive.

La replication NLS R/Python conserve exactement {scope.expected_nls_pairs} couples publics; les {h23_pairs} NLS H2/H3 existaient deja et n'ont pas ete recalcules.
""",
    )
    _write_text(
        release_root / "CHANGELOG_v1.1.md",
        f"""# Changelog v1.1

## Extension scientifique

- ajout des {h23_pairs} KRT H2/H3 sur le panel fixe de {scope.panel_size} communes ;
- conservation exacte des {inherited_pairs} KRT H0A/H1 de la v1.0.2 ;
- consolidation de {scope.expected_krt_pairs} couples KRT, {scope.expected_krt_commune_rows} lignes communales et {scope.expected_krt_aggregate_rows} agregats ;
- conservation de {scope.expected_nls_pairs} couples NLS publics ;
- graines distinctes et deterministes par `scenario_id x election_id` ;
- selection du backend `{scope.mcmc.sampler_backend}` apres benchmark diagnostique du graphe King exact a 2 000 communes ;
- conservation de la tentative PyMC interrompue comme preuve diagnostique uniquement, jamais comme run canonique ;
- porte pilote appliquee avant les {post_pilot_pairs} runs restants ;
- relance unique 2 000/2 000 uniquement pour les caveats severes ou fails MCMC ;
- diagnostics MCMC, identification ecologique et stabilite des estimations conserves separement ;
- trajectoires legislatives et presidentielles separees ;
- comparaison H2/H3 limitee aux deux beta1 descriptifs, sans difference posterieure jointe.

## Diagnostics canoniques

{chr(10).join(status_lines)}

## Relances renforcees devenues canoniques

{chr(10).join(rerun_lines)}

## Invariance

Les valeurs H0A/H1 de la v1.1 sont exactement identiques a celles de la v1.0.2 apres tri par les cles. Les trois Parquet publics utilisent toujours le schema `{scope.public_schema_version}`.

## Reserves

- H2 et H3 ont des complements differents et ne decomposent pas formellement H1 ;
- les trajectoires sont descriptives, sans modele temporel hierarchique ;
- la reproduction complete necessite le depot parent ;
- les RxC et les hypotheses suivantes restent hors du perimetre valide.
""",
    )
    validation = json.loads((release_root / "VALIDATION_v1.1.json").read_text(encoding="utf-8"))
    _write_text(
        release_root / "VALIDATION_v1.1.md",
        f"""# Validation v1.1

- ready: {str(validation['ready']).lower()}
- ready_scope: {scope.ready_scope}
- panel: {scope.panel_size} communes, hash `{scope.panel_sha256}`
- KRT: {validation['actual']['krt_pairs']} couples, {validation['actual']['commune_rows']} lignes communales, {validation['actual']['aggregate_rows']} agregats
- NLS: {validation['actual']['nls_pairs']} couples publics
- H0A/H1 identiques a la v1.0.2: pass
- huit champs d'incertitude communale complets: pass
- runs KRT fail inclus: 0
- NetCDF livres: non
- reproduction complete: depot parent requis
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
    reports = {}
    for filename in ("RAPPORT_TECHNIQUE_v1.1.html", "RAPPORT_TECHNIQUE_v1.1.pdf"):
        path = release_root / filename
        reports[path.stem] = {
            "runtime_path": f"work/{release_root.name}/{filename}",
            "delivery_path": filename,
            "delivery_included": True,
            "external_required": False,
            "sha256": file_sha256(path),
        }
    manifest = {
        "manifest_schema_version": "longitudinal_delivery_manifest_v1.1",
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
        "reports": reports,
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
        "v11_pipeline",
        "h23_supervisor",
        "benchmark_krt_backend_2000",
        "audit_v11_candidate",
        "materialize_v11_release",
        "build_v11_report_artifact",
        "deliver_v11_report_html",
        "render_v11_report_pdf",
        "package_v11_release",
        "scoped_finalizer",
        "run_r_nls_replication",
        "run_r_king_ei_replication",
    }
    source = ROOT / "code_longitudinal"
    queue = deque(entrypoints)
    selected = {"__init__"}
    while queue:
        module = queue.popleft()
        if module in selected:
            continue
        path = source / f"{module}.py"
        if not path.is_file():
            raise FileNotFoundError(path)
        selected.add(module)
        for dependency in sorted(_relative_imports(path)):
            if (source / f"{dependency}.py").is_file() and dependency not in selected:
                queue.append(dependency)
    prohibited = {
        "package_release_v101", "build_v101_report", "build_v101_syntheses",
        "run_priority_production", "run_priority_production_v2", "run_priority_production_v3",
        "finalize_priority_results", "finalize_priority_results_v2", "finalize_priority_results_v3",
    }
    leaked = selected.intersection(prohibited)
    if leaked:
        raise AssertionError(f"historical modules leaked into v1.1 bundle: {sorted(leaked)}")
    return selected


def _build_code_bundle(release_root: Path, config_path: Path) -> dict[str, Any]:
    bundle = release_root / "05_methodologie_et_code" / "current_v1.1"
    if bundle.exists():
        shutil.rmtree(bundle)
    modules = _production_module_closure()
    for module in sorted(modules):
        _copy(ROOT / "code_longitudinal" / f"{module}.py", bundle / "code_longitudinal" / f"{module}.py")
    _copy(config_path, bundle / "config" / "release_v1.1.json")
    _copy(ROOT / "config" / "run_settings.json", bundle / "config" / "run_settings.json")
    for name in (
        "conftest.py", "test_release_scope.py", "test_h23_pilot_gate.py",
        "test_diagnostics_v2.py", "test_identification_v2.py", "test_nls.py",
        "test_partitions.py", "test_postprocess_aggregates_v2.py",
        "test_panel_2000_integrity_audit.py", "test_longitudinal_v1.py",
    ):
        _copy(ROOT / "tests" / name, bundle / "tests" / name)
    for name in ("run_king_ei_replication.R", "run_nls_replication.R"):
        _copy(ROOT / "r_replication" / name, bundle / "r_replication" / name)
    _copy(ROOT / "requirements-production-v101.txt", bundle / "requirements-production-v1.1.txt")
    _copy(ROOT / "requirements-dev.txt", bundle / "requirements-dev.txt")
    _copy(ROOT / "R_REQUIREMENTS.md", bundle / "R_REQUIREMENTS.md")
    _write_text(
        bundle / "START_HERE.md",
        """# Bundle minimal de production v1.1

Le bundle couvre l'audit du panel, l'orchestration KRT H2/H3, la porte pilote, les relances preenregistrees, la selection canonique, la consolidation, les syntheses, le rapport HTML et le packaging.

```powershell
python -m code_longitudinal.h23_supervisor --release-config config/release_v1.1.json
python -m code_longitudinal.scoped_pipeline finalize --release-config config/release_v1.1.json --canonical-selection canonical_run_selection.csv
python -m code_longitudinal.deliver_v11_report_html --release-root <candidate> --config config/release_v1.1.json --plugin-root <data-analytics-plugin>
python -m code_longitudinal.render_v11_report_pdf --release-root <candidate> --chrome <chrome.exe>
```

La reproduction complete exige le depot parent, les archives brutes et les matrices preparees. Les NetCDF ne sont pas livres.
""",
    )
    inventory = []
    for module in sorted(modules):
        path = ROOT / "code_longitudinal" / f"{module}.py"
        inventory.append({
            "module": module,
            "lines": len(path.read_text(encoding="utf-8").splitlines()),
            "bundle_path": f"code_longitudinal/{module}.py",
            "sha256": file_sha256(path),
        })
    pd.DataFrame(inventory).to_csv(bundle / "CODE_INVENTORY.csv", index=False, encoding="utf-8-sig")
    return {"module_count": len(modules), "bundle_path": bundle.relative_to(release_root).as_posix()}


def _copy_professor_files(release_root: Path, staging: Path) -> None:
    exact = (
        "RAPPORT_TECHNIQUE_v1.1.html",
        "RAPPORT_TECHNIQUE_v1.1.pdf",
        "README_PROFESSEUR.md",
        "CHANGELOG_v1.1.md",
        "VALIDATION_v1.1.md",
        "VALIDATION_v1.1.json",
        "DEPENDENCIES_AND_REPRODUCTION.md",
        "FINAL_COMPLETION_AUDIT_v1.1.json",
        "01_resultats_python/longitudinal_krt_commune.parquet",
        "01_resultats_python/longitudinal_krt_aggregate.parquet",
        "01_resultats_python/longitudinal_nls.parquet",
        "01_resultats_python/release_manifest.json",
        "02_syntheses/canonical_run_selection.csv",
        "02_syntheses/diagnostics_krt_resume.csv",
        "02_syntheses/diagnostics_krt_par_election.csv",
        "02_syntheses/etat_modeles_par_election.csv",
        "02_syntheses/trajectoires_krt.csv",
        "02_syntheses/krt_nls_comparison_h0a_h1_h2_h3.csv",
        "02_syntheses/nls_python_r_replication_summary.csv",
        "02_syntheses/h1_panel_sensitivity.csv",
        "02_syntheses/targeted_mcmc_reruns.csv",
        "02_syntheses/definitions_hypotheses.csv",
        "03_panel_et_audit/panel_primaire_2000.csv",
        "03_panel_et_audit/DATA_DICTIONARY.csv",
        "03_panel_et_audit/HARMONISATION_POLITIQUE.csv",
        "03_panel_et_audit/COVARIATE_PROVENANCE.csv",
        "03_panel_et_audit/coverage_by_election_department.csv",
        "03_panel_et_audit/panel_exact_validation.json",
        "03_panel_et_audit/foreign_share_source_validation.csv",
        "03_panel_et_audit/NUMERICAL_INVARIANCE_v1.0.2_to_v1.1.json",
        "05_methodologie_et_code/release_config_v1.1.json",
    )
    for relative in exact:
        _copy(release_root / relative, staging / relative)
    for path in (release_root / "04_figures_essentielles").glob("*"):
        if path.is_file():
            _copy(path, staging / "04_figures_essentielles" / path.name)


def _scan_delivery_v11(staging: Path) -> dict[str, Any]:
    netcdf = [path.relative_to(staging).as_posix() for path in staging.rglob("*.nc")]
    absolute_hits: list[str] = []
    stale_hits: list[str] = []
    for path in staging.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if ABSOLUTE_WINDOWS_PATH.search(text):
            absolute_hits.append(path.relative_to(staging).as_posix())
        forbidden = ("02_comparaison_python_r_king/", "release_01")
        if any(token in text for token in forbidden):
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


def package_v11(release_root: Path, config_path: Path) -> dict[str, Any]:
    scope = load_release_scope(config_path)
    validation = json.loads((release_root / "VALIDATION_v1.1.json").read_text(encoding="utf-8"))
    if not validation.get("ready") or validation.get("ready_scope") != scope.ready_scope:
        raise AssertionError("v1.1 candidate is not validated for its configured scope")
    completion_audit = json.loads((release_root / "FINAL_COMPLETION_AUDIT_v1.1.json").read_text(encoding="utf-8"))
    if not completion_audit.get("ready") or completion_audit.get("ready_scope") != scope.ready_scope:
        raise AssertionError("v1.1 candidate completion audit is not ready")
    for report in ("RAPPORT_TECHNIQUE_v1.1.html", "RAPPORT_TECHNIQUE_v1.1.pdf"):
        if not (release_root / report).is_file():
            raise FileNotFoundError(release_root / report)
    sources_before = _verify_immutable_sources()
    _write_release_documents(release_root, scope)
    code_bundle = _build_code_bundle(release_root, config_path)
    release_manifest = _refresh_release_manifest(release_root, scope, sources_before)

    professor = ROOT / "work" / "package_staging_v11_professeur"
    technical = ROOT / "work" / "package_staging_v11_technique"
    _safe_clean_staging(professor, professor.name)
    _safe_clean_staging(technical, technical.name)
    _copy_professor_files(release_root, professor)
    _copy_professor_files(release_root, technical)
    for relative in (
        "03_panel_et_audit/DATA_DICTIONARY_TECHNICAL.csv",
        "03_panel_et_audit/rxc_ineligible_audit.csv",
        "03_panel_et_audit/department54_pre1988_rows.csv",
        "03_panel_et_audit/longitudinal_audit.parquet",
        "05_methodologie_et_code/report_artifact.json",
        "05_methodologie_et_code/report_delivery_receipt.json",
        "05_methodologie_et_code/REPORT_PDF_GENERATION.json",
        "05_methodologie_et_code/REPORT_PDF_QA.json",
        "05_methodologie_et_code/backend_benchmark_2000.json",
        "05_methodologie_et_code/REPORT_SOURCE_NOTES.md",
        "05_methodologie_et_code/AUDIT_NOTEBOOK_v1.1.ipynb",
        "MATERIALIZATION_v1.1.json",
    ):
        _copy(release_root / relative, technical / relative)
    for path in (release_root / "02_comparaison_python_r").glob("*"):
        if path.is_file() and path.suffix.lower() != ".nc":
            _copy(path, technical / "02_comparaison_python_r" / path.name)
    shutil.copytree(
        release_root / "05_methodologie_et_code" / "current_v1.1",
        technical / "05_methodologie_et_code" / "current_v1.1",
    )
    supervisor = release_root / "06_diagnostics_runs" / "h23_supervisor"
    if supervisor.is_dir():
        shutil.copytree(supervisor, technical / "06_diagnostics_runs" / "h23_supervisor", dirs_exist_ok=True)

    selection = pd.read_csv(release_root / "02_syntheses" / "canonical_run_selection.csv", dtype="string")
    if len(selection) != scope.expected_krt_pairs:
        raise AssertionError("canonical selection does not match configured KRT pair count")
    for run_id in selection["run_id"].astype(str):
        _copy_run_diagnostics(run_id, technical, kind="krt")
    panel_id = str(pd.read_parquet(release_root / "01_resultats_python" / "longitudinal_nls.parquet")["panel_id"].iloc[0])
    for _, manifest in _selected_nls_runs(panel_id):
        _copy_run_diagnostics(str(manifest["run_id"]), technical, kind="nls")

    professor_manifest = _delivery_manifest(professor, scope, "professeur_light")
    technical_manifest = _delivery_manifest(technical, scope, "technical_complete")
    professor_scan = _scan_delivery_v11(professor)
    technical_scan = _scan_delivery_v11(technical)

    deliverables = ROOT / "deliverables"
    professor_zip = deliverables / "longitudinal_2000_v1.1_H0A_H1_H2_H3_validated_professeur.zip"
    technical_zip = deliverables / "longitudinal_2000_v1.1_H0A_H1_H2_H3_validated_technique.zip"
    zipped_professor = zip_verify(professor, professor_zip, scan=_scan_delivery_v11)
    zipped_technical = zip_verify(technical, technical_zip, scan=_scan_delivery_v11)
    sources_after = _verify_immutable_sources()
    if sources_before != sources_after:
        raise AssertionError("an immutable source archive changed during v1.1 packaging")

    validated = ROOT / "work" / "longitudinal_2000_v1.1_H0A_H1_H2_H3_validated"
    _safe_clean_staging(validated, validated.name)
    shutil.copytree(technical, validated, dirs_exist_ok=True)
    result = {
        "release_id": scope.release_id,
        "ready": True,
        "ready_scope": scope.ready_scope,
        "release_manifest": release_manifest,
        "code_bundle": code_bundle,
        "professor": {"manifest_files": len(professor_manifest["files"]), "scan": professor_scan, "zip": zipped_professor},
        "technical": {"manifest_files": len(technical_manifest["files"]), "scan": technical_scan, "zip": zipped_technical},
        "validated_root": validated.relative_to(ROOT).as_posix(),
        "immutable_source_hashes": sources_after,
        "created_at_utc": _utc_now(),
    }
    _write_json(deliverables / "longitudinal_2000_v1.1_H0A_H1_H2_H3_PACKAGE_VALIDATION.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and verify v1.1 professor and technical archives.")
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(package_v11(args.release_root, args.config), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
