from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .paths import PANEL_DIR, ROOT, RUNS_DIR
from .utils import file_sha256


RELEASE_NAME = "longitudinal_2000_v1.0.1_H0A_H1"
CANDIDATE = ROOT / "work" / f"{RELEASE_NAME}_candidate"
VALIDATED = ROOT / "work" / f"{RELEASE_NAME}_validated"
ORIGINAL_ZIP = ROOT / "deliverables" / "longitudinal_2000_v1_H0A_H1_complet_20260816.zip"
ORIGINAL_SHA = "ed80a7dfb14653ec0be943c811317c6786651fa8d97e12870f366dde1df74446"
PANEL_SHA = "bde70c71660fce29610d7931461d8db6181dba874514a1866b63cf16a81cec4a"
DELIVERABLE_DIR = ROOT / "deliverables"
WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]")
SELF_REFERENTIAL_VALIDATION_OUTPUTS = {
    "validation_report_v1.0.1.json",
    "VALIDATION_v1.0.1.md",
}

HISTORICAL_TOP_LEVEL = (
    "artifact.json",
    "COMPARAISON_AVEC_RENDU_PRECEDENT.md",
    "MAIL_RECAPITULATIF_PROFESSEUR.md",
    "package_manifest.json",
    "RAPPORT_TECHNIQUE_LONGITUDINAL_2000_H0A_H1.html",
    "RAPPORT_VALIDATION.md",
    "README.md",
    "validation_report.json",
)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def clean_and_label_historical() -> None:
    historical = CANDIDATE / "05_methodologie_et_code" / "historical_only_v1.0"
    historical.mkdir(parents=True, exist_ok=True)
    for name in HISTORICAL_TOP_LEVEL:
        source = CANDIDATE / name
        if not source.exists():
            continue
        target = historical / name
        if target.exists():
            if source.is_file() and file_sha256(source) == file_sha256(target):
                source.unlink()
            elif source.is_file():
                shutil.move(str(source), str(historical / f"duplicate_{name}"))
            continue
        shutil.move(str(source), str(target))
    for name in ("code_longitudinal", "config", "docs"):
        source = CANDIDATE / "05_methodologie_et_code" / name
        target = historical / name
        if not source.exists():
            continue
        if target.exists():
            shutil.copytree(source, target, dirs_exist_ok=True)
            shutil.rmtree(source)
        else:
            shutil.move(str(source), str(target))
    warning = (
        "# Documents historiques v1.0 — ne pas utiliser comme documentation courante\n\n"
        "Ces fichiers sont conservés uniquement pour la traçabilité. Ils peuvent mentionner des chemins, "
        "statuts ou synthèses antérieurs. La documentation canonique est au niveau racine de la release v1.0.1.\n"
    )
    (historical / "HISTORICAL_ONLY.md").write_text(warning, encoding="utf-8")


def sync_current_code_and_configuration() -> None:
    destination = CANDIDATE / "05_methodologie_et_code" / "current_v1.0.1"
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "code_longitudinal", destination / "code_longitudinal", dirs_exist_ok=True)
    for stale_readme in (destination / "code_longitudinal" / "README.md", destination / "code_longitudinal" / "README.html"):
        if stale_readme.exists():
            stale_readme.unlink()
    shutil.copytree(ROOT / "config", destination / "config", dirs_exist_ok=True)
    tests = ROOT / "tests"
    if tests.exists():
        shutil.copytree(tests, destination / "tests", dirs_exist_ok=True)
    scope = """# Périmètre du code v1.0.1

La chaîne canonique de cette release repose sur les modules `release_v1_0_1_audit.py`,
`run_h1_panel_sensitivity_v101.py`, `run_targeted_mcmc_v101.py`,
`build_v101_syntheses.py`, `build_v101_report.py`, `render_v101_report_pdf.py` et
`package_release_v101.py`, ainsi que sur leurs dépendances d'import.

Les autres générateurs sont conservés pour compatibilité et traçabilité du dépôt parent ;
ils ne constituent pas la documentation exécutée de v1.0.1 et peuvent contenir des noms
historiques. La configuration canonique est `config/run_settings.json`.
"""
    (destination / "CURRENT_CODE_SCOPE.md").write_text(scope, encoding="utf-8")


def _sanitize_runtime_string(value: str) -> str:
    replacements = (
        (str(ROOT), "."),
        (ROOT.as_posix(), "."),
        (str(ROOT.parent), ".."),
        (ROOT.parent.as_posix(), ".."),
    )
    result = value
    for source, replacement in replacements:
        result = result.replace(source, replacement)
    if re.search(r"[A-Za-z]:[\\/]", result):
        return "[external_absolute_path_redacted; see external_required dependencies]"
    return result.replace("\\", "/") if "/" in result or "\\" in result else result


def _sanitize_manifest_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {_sanitize_runtime_string(str(key)): _sanitize_manifest_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_manifest_value(item) for item in value]
    if isinstance(value, str):
        return _sanitize_runtime_string(value)
    return value


def _copy_run_without_trace(run_id: str, category: str) -> None:
    source = RUNS_DIR / run_id
    if not source.exists():
        raise FileNotFoundError(source)
    target = CANDIDATE / "06_diagnostics_runs" / category / run_id
    target.mkdir(parents=True, exist_ok=True)
    for path in source.iterdir():
        if not path.is_file() or path.suffix.lower() in {".nc", ".rds"}:
            continue
        destination = target / path.name
        if path.name == "manifest.json":
            manifest = _sanitize_manifest_value(json.loads(path.read_text(encoding="utf-8")))
            panel_id = str(manifest.get("parameters", {}).get("panel_id", ""))
            if category == "krt":
                run_role = "canonical"
            elif "panel_sensitivity" in panel_id or "sensitivity" in panel_id:
                run_role = "panel_sensitivity"
            elif "targeted_rerun" in panel_id:
                run_role = "targeted_rerun"
            else:
                run_role = "diagnostic_only"
            manifest.update(
                {
                    "run_role": run_role,
                    "runtime_root": ".",
                    "runtime_path": f"outputs/runs/{run_id}",
                    "delivery_path": f"06_diagnostics_runs/{category}/{run_id}",
                    "delivery_included": True,
                    "external_required": True,
                    "external_requirement": "Parent repository and raw archives are required to reproduce this run; delivered files support audit only.",
                }
            )
            _write_json(destination, manifest)
        else:
            shutil.copy2(path, destination)


def sync_release_runs() -> None:
    selection = pd.read_csv(CANDIDATE / "02_syntheses" / "canonical_run_selection.csv", dtype="string")
    for run_id in selection["run_id"].dropna().unique():
        _copy_run_without_trace(str(run_id), "krt")
    for relative in (
        "07_auxiliary_runs/h1_panel_sensitivity/auxiliary_run_registry.csv",
        "07_auxiliary_runs/targeted_mcmc_reruns/auxiliary_run_registry.csv",
    ):
        path = CANDIDATE / relative
        if not path.exists():
            continue
        registry = pd.read_csv(path, dtype="string")
        for column in ("run_id", "new_run_id", "old_run_id"):
            if column in registry:
                for run_id in registry[column].dropna().unique():
                    _copy_run_without_trace(str(run_id), "auxiliary")
    sensitivity_path = CANDIDATE / "02_syntheses" / "h1_panel_sensitivity.csv"
    if sensitivity_path.exists():
        sensitivity = pd.read_csv(sensitivity_path, dtype="string")
        estimate_ids = sensitivity.loc[sensitivity["row_type"].eq("estimate"), "run_id"].dropna().unique()
        for run_id in estimate_ids:
            _copy_run_without_trace(str(run_id), "auxiliary")


def sanitize_all_delivery_run_manifests() -> None:
    canonical = pd.read_csv(CANDIDATE / "02_syntheses" / "canonical_run_selection.csv", dtype="string")
    canonical_ids = set(canonical["run_id"].dropna().astype(str))
    sensitivity_ids: set[str] = set()
    targeted_ids: set[str] = set()
    sensitivity_registry = CANDIDATE / "07_auxiliary_runs" / "h1_panel_sensitivity" / "auxiliary_run_registry.csv"
    targeted_registry = CANDIDATE / "07_auxiliary_runs" / "targeted_mcmc_reruns" / "auxiliary_run_registry.csv"
    if sensitivity_registry.exists():
        frame = pd.read_csv(sensitivity_registry, dtype="string")
        sensitivity_ids.update(frame.get("run_id", pd.Series(dtype="string")).dropna().astype(str))
    if targeted_registry.exists():
        frame = pd.read_csv(targeted_registry, dtype="string")
        targeted_ids.update(frame.get("new_run_id", pd.Series(dtype="string")).dropna().astype(str))
    diagnostics_root = CANDIDATE / "06_diagnostics_runs"
    for path in diagnostics_root.rglob("manifest.json"):
        run_id = path.parent.name
        category = path.relative_to(diagnostics_root).parts[0]
        manifest = _sanitize_manifest_value(json.loads(path.read_text(encoding="utf-8")))
        if run_id in canonical_ids or category == "nls":
            role = "canonical"
        elif run_id in sensitivity_ids:
            role = "panel_sensitivity"
        elif run_id in targeted_ids:
            role = "targeted_rerun"
        else:
            role = "diagnostic_only"
        diagnostic = manifest.get("canonical_mcmc_diagnostic")
        if isinstance(diagnostic, dict):
            # This legacy field encoded a stricter joint MCMC/identification
            # gate and is not the v1.0.1 canonical-selection decision.
            diagnostic.pop("selected_for_interpretation", None)
        manifest["canonical_selection"] = {
            "selected": run_id in canonical_ids,
            "selection_source": "02_syntheses/canonical_run_selection.csv",
            "run_role": role,
        }
        manifest.update(
            {
                "run_role": role,
                "runtime_root": ".",
                "runtime_path": f"outputs/runs/{run_id}",
                "delivery_path": path.parent.relative_to(CANDIDATE).as_posix(),
                "delivery_included": True,
                "external_required": True,
                "external_requirement": "Parent repository and raw archives are required to reproduce this run; delivered files support audit only.",
            }
        )
        _write_json(path, manifest)


def _check_counts() -> dict[str, Any]:
    result_dir = CANDIDATE / "01_resultats_python"
    audit_dir = CANDIDATE / "03_panel_et_audit"
    synthesis_dir = CANDIDATE / "02_syntheses"
    panel = pd.read_parquet(audit_dir / "longitudinal_2000_v1.parquet").sort_values("master_draw_order")
    primary = panel.head(2000)
    krt_commune = pd.read_parquet(result_dir / "longitudinal_krt_commune.parquet")
    krt_aggregate = pd.read_parquet(result_dir / "longitudinal_krt_aggregate.parquet")
    nls = pd.read_parquet(result_dir / "longitudinal_nls.parquet")
    political = pd.read_csv(audit_dir / "HARMONISATION_POLITIQUE.csv")
    canonical = pd.read_csv(synthesis_dir / "canonical_run_selection.csv")
    rxc = pd.read_csv(audit_dir / "rxc_ineligible_audit.csv")
    uncertainty = ["b1_sd", "b1_q025", "b1_q50", "b1_q975", "b2_sd", "b2_q025", "b2_q50", "b2_q975"]
    checks = {
        "panel_file_sha256": file_sha256(PANEL_DIR / "longitudinal_2000_v1.parquet") == PANEL_SHA,
        "candidate_panel_file_sha256": file_sha256(audit_dir / "longitudinal_2000_v1.parquet") == PANEL_SHA,
        "panel_master_rows": len(panel) == 3000,
        "panel_primary_rows": len(primary) == 2000,
        "panel_primary_unique_units": primary["unit_id"].astype("string").nunique() == 2000,
        "panel_election_keys": len(primary) * 26 == 52000,
        "political_pairs": len(political) == 292 and not political[["election_id", "scenario_id"]].duplicated().any(),
        "krt_pairs": krt_aggregate[["election_id", "scenario_id"]].drop_duplicates().shape[0] == 52,
        "krt_aggregate_rows": len(krt_aggregate) == 156,
        "krt_commune_rows": len(krt_commune) == 104000,
        "krt_commune_unique": not krt_commune[["election_id", "scenario_id", "unit_id"]].duplicated().any(),
        "krt_exact_2000_each": bool(krt_commune.groupby(["election_id", "scenario_id"])["unit_id"].nunique().eq(2000).all()),
        "uncertainty_fields_exact": all(column in krt_commune for column in uncertainty),
        "uncertainty_complete": bool(krt_commune[uncertainty].notna().all().all()),
        "foreign_share_unit": bool(krt_commune["foreign_share"].dropna().between(0, 1).all()),
        "no_invented_covariate_year": all(f"{variable}_reference_year" in krt_commune for variable in ("vbbm", "revenue", "capital", "foreign_share")),
        "nls_pairs": nls[["election_id", "scenario_id"]].drop_duplicates().shape[0] == 270,
        "canonical_pairs": len(canonical) == 52 and not canonical[["election_id", "scenario_id"]].duplicated().any(),
        "rxc_pairs": rxc[["election_id", "scenario_id"]].drop_duplicates().shape[0] == 22,
        "rxc_off_panel": int(rxc["in_panel_2000"].sum()) == 0,
        "rxc_panel_closure": bool(rxc["panel_model_ready_exact_closure"].all()),
    }
    return {"checks": checks, "all_pass": all(checks.values())}


def _check_sensitivity() -> dict[str, Any]:
    path = CANDIDATE / "02_syntheses" / "h1_panel_sensitivity.csv"
    if not path.exists():
        return {"checks": {"sensitivity_present": False}, "all_pass": False}
    frame = pd.read_csv(path)
    estimates = frame.loc[frame["row_type"].eq("estimate")]
    differences = frame.loc[frame["row_type"].eq("descriptive_difference")]
    pipeline = differences.loc[differences["comparison_label"].isin(["pipeline_only", "changement_preparation_pipeline"])]
    unexplained = pipeline.loc[~pipeline["intervals_overlap"].astype(bool)]
    checks = {
        "sensitivity_estimate_rows": len(estimates) == 36,
        "sensitivity_difference_rows": len(differences) == 27,
        "three_elections": estimates["election_id"].nunique() == 3,
        "four_cells": estimates["cell"].nunique() == 4,
        "pipeline_labels_present": len(pipeline) == 9,
        "no_unexplained_pipeline_interval_contradiction": unexplained.empty,
        "descriptive_scope_labeled": bool(
            differences["interpretation_scope"].eq("distribution_descriptive_difference_independent_fits_not_causal").all()
        ),
    }
    return {"checks": checks, "all_pass": all(checks.values()), "unexplained": unexplained.to_dict("records")}


def _check_targeted() -> dict[str, Any]:
    path = CANDIDATE / "02_syntheses" / "targeted_mcmc_reruns.csv"
    if not path.exists():
        return {"checks": {"targeted_present": False}, "all_pass": False}
    frame = pd.read_csv(path)
    checks = {
        "six_targeted_rows": len(frame) == 6,
        "three_status_dimensions": all(column in frame for column in ("mcmc_status", "identification_status", "estimate_stability_status")),
        "no_ready_blocker": not frame["ready_blocker"].astype(bool).any(),
        "no_unexplained_fail": not frame["mcmc_status"].eq("fail").any(),
    }
    return {"checks": checks, "all_pass": all(checks.values()), "blockers": frame.loc[frame["ready_blocker"].astype(bool)].to_dict("records")}


def _check_documents() -> dict[str, Any]:
    required = (
        "RAPPORT_TECHNIQUE_v1.0.1.html",
        "RAPPORT_TECHNIQUE_v1.0.1.pdf",
        "CHANGELOG_v1.0.1.md",
        "DEPENDENCIES_AND_REPRODUCTION.md",
        "README_PROFESSEUR.md",
    )
    text_paths = [
        CANDIDATE / name for name in required if name.endswith((".html", ".md"))
    ] + list((CANDIDATE / "03_panel_et_audit").glob("*.csv"))
    text_paths.extend(
        path
        for path in CANDIDATE.rglob("*")
        if path.is_file()
        and path.suffix.lower() in {".json", ".md", ".html", ".txt"}
        and "historical_only_v1.0" not in path.parts
        # These reports contain the check key ``release_01_absent`` itself.
        # Scanning them would make a successful validation fail on the next
        # invocation even though no current document mentions the old release.
        and path.name not in SELF_REFERENTIAL_VALIDATION_OUTPUTS
    )
    text_paths = list(dict.fromkeys(text_paths))
    wrong_path = []
    stale_release = []
    absolute_local_paths = []
    for path in text_paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        if "02_comparaison_python_r_king/" in text:
            wrong_path.append(str(path.relative_to(CANDIDATE)))
        if "release_01" in text.lower():
            stale_release.append(str(path.relative_to(CANDIDATE)))
        # A URI such as ``https://...`` contains the substring ``s:/`` but is
        # not a local Windows path.  Requiring the drive letter not to be
        # preceded by another letter preserves detection of ``C:\\...`` while
        # allowing documented web sources in provenance tables.
        if WINDOWS_ABSOLUTE_PATH_RE.search(text):
            absolute_local_paths.append(str(path.relative_to(CANDIDATE)))
    configuration_path = CANDIDATE / "05_methodologie_et_code" / "release_configuration_v1.0.1.json"
    configuration = json.loads(configuration_path.read_text(encoding="utf-8")) if configuration_path.exists() else {}
    checks = {
        "required_documents": all((CANDIDATE / name).exists() for name in required),
        "wrong_python_r_path_absent": not wrong_path,
        "release_01_absent": not stale_release,
        "absolute_local_paths_absent": not absolute_local_paths,
        "reproduction_warning_present": "dépôt parent" in (CANDIDATE / "DEPENDENCIES_AND_REPRODUCTION.md").read_text(encoding="utf-8") if (CANDIDATE / "DEPENDENCIES_AND_REPRODUCTION.md").exists() else False,
        "release_configuration_ready_scope": configuration.get("ready") is True and configuration.get("ready_scope") == "H0A-H1",
    }
    return {
        "checks": checks,
        "all_pass": all(checks.values()),
        "wrong_paths": wrong_path,
        "stale_release": stale_release,
        "absolute_local_paths": absolute_local_paths,
    }


def validate_candidate() -> dict[str, Any]:
    if file_sha256(ORIGINAL_ZIP) != ORIGINAL_SHA:
        raise AssertionError("original archive hash changed")
    sections = {
        "counts_and_schema": _check_counts(),
        "h1_sensitivity": _check_sensitivity(),
        "targeted_mcmc": _check_targeted(),
        "documentation": _check_documents(),
    }
    ready = all(section["all_pass"] for section in sections.values())
    report = {
        "release_id": RELEASE_NAME,
        "ready": ready,
        "ready_scope": "H0A-H1" if ready else "candidate_pending_or_failed_gates",
        "original_zip_sha256_before": file_sha256(ORIGINAL_ZIP),
        "sections": sections,
    }
    _write_json(CANDIDATE / "validation_report_v1.0.1.json", report)
    lines = [
        "# Validation v1.0.1",
        "",
        f"- `ready={str(ready).lower()}`",
        f"- `ready_scope={report['ready_scope']}`",
        f"- archive originale : `{report['original_zip_sha256_before']}`",
        "",
    ]
    for name, section in sections.items():
        lines.append(f"## {name}")
        lines.append("")
        for check, passed in section["checks"].items():
            lines.append(f"- {'PASS' if passed else 'FAIL'} — `{check}`")
        lines.append("")
    (CANDIDATE / "VALIDATION_v1.0.1.md").write_text("\n".join(lines), encoding="utf-8")
    return report


def _copy_relative(source_root: Path, destination_root: Path, relatives: Iterable[str]) -> None:
    for relative in relatives:
        source = source_root / relative
        if not source.exists():
            continue
        destination = destination_root / relative
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True, ignore=shutil.ignore_patterns("*.nc", "*.rds", "__pycache__", ".cache"))
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


def _manifest_for_staging(staging: Path, runtime_source: Path, archive_role: str) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for path in sorted(staging.rglob("*")):
        if not path.is_file() or path.name == "DELIVERY_MANIFEST.json":
            continue
        relative = path.relative_to(staging).as_posix()
        runtime = runtime_source / relative
        entries.append(
            {
                "runtime_root": str(runtime_source.relative_to(ROOT)).replace("\\", "/"),
                "runtime_path": str(runtime.relative_to(ROOT)).replace("\\", "/") if runtime.is_relative_to(ROOT) else "",
                "delivery_path": relative,
                "delivery_included": True,
                "external_required": False,
                "size_bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }
        )
    external = [
        {
            "runtime_root": "../pour_moi_avec_data/data/raw/archives",
            "runtime_path": "../pour_moi_avec_data/data/raw/archives/*.zip",
            "delivery_path": "",
            "delivery_included": False,
            "external_required": True,
            "purpose": "reproduction complète depuis les données brutes",
        },
        {
            "runtime_root": "repository_parent",
            "runtime_path": "repository_parent",
            "delivery_path": "",
            "delivery_included": False,
            "external_required": True,
            "purpose": "environnement et données préparées du dépôt parent",
        },
    ]
    manifest = {
        "release_id": f"{RELEASE_NAME}_validated",
        "archive_role": archive_role,
        "ready": True,
        "ready_scope": "H0A-H1",
        "entries": entries,
        "external_dependencies": external,
        "netcdf_included": False,
    }
    _write_json(staging / "DELIVERY_MANIFEST.json", manifest)
    return manifest


def _zip_and_verify(staging: Path, output: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(staging).as_posix())
    with zipfile.ZipFile(output) as archive:
        bad = archive.testzip()
        names = archive.namelist()
        if bad is not None:
            raise AssertionError(f"CRC failure in {output.name}: {bad}")
        if any(name.lower().endswith((".nc", ".rds")) for name in names):
            raise AssertionError(f"forbidden trace/object included in {output.name}")
        extraction = Path(tempfile.mkdtemp(prefix=f"verify_{output.stem}_", dir=str(ROOT / "work")))
        archive.extractall(extraction)
    manifest = json.loads((extraction / "DELIVERY_MANIFEST.json").read_text(encoding="utf-8"))
    for entry in manifest["entries"]:
        delivered = extraction / entry["delivery_path"]
        if not delivered.exists() or file_sha256(delivered) != entry["sha256"]:
            raise AssertionError(f"delivery hash mismatch: {entry['delivery_path']}")
        for key in ("runtime_root", "runtime_path", "delivery_path"):
            value = str(entry.get(key, ""))
            if Path(value).is_absolute() or (len(value) >= 2 and value[1] == ":"):
                raise AssertionError(f"absolute path in delivery manifest: {value}")
    sha = file_sha256(output)
    output.with_suffix(output.suffix + ".sha256").write_text(f"{sha}  {output.name}\n", encoding="utf-8")
    return {"path": str(output), "sha256": sha, "files": len(names), "crc": "pass", "manifest_hashes": "pass"}


def package_release() -> dict[str, Any]:
    validation = json.loads((CANDIDATE / "validation_report_v1.0.1.json").read_text(encoding="utf-8"))
    if not validation.get("ready"):
        raise RuntimeError("candidate is not ready; refusing validated promotion and packaging")
    if VALIDATED.exists():
        raise FileExistsError(f"validated destination already exists: {VALIDATED}")
    shutil.copytree(CANDIDATE, VALIDATED, ignore=shutil.ignore_patterns("*.nc", "*.rds", "__pycache__", ".cache"))

    staging_parent = ROOT / "work" / "release_staging_v1.0.1"
    staging_parent.mkdir(parents=True, exist_ok=True)
    professor = Path(tempfile.mkdtemp(prefix="professeur_", dir=str(staging_parent)))
    technical = Path(tempfile.mkdtemp(prefix="technique_", dir=str(staging_parent)))
    professor_items = (
        "RAPPORT_TECHNIQUE_v1.0.1.html", "RAPPORT_TECHNIQUE_v1.0.1.pdf", "README_PROFESSEUR.md",
        "CHANGELOG_v1.0.1.md", "DEPENDENCIES_AND_REPRODUCTION.md", "VALIDATION_v1.0.1.md",
        "validation_report_v1.0.1.json",
        "01_resultats_python/longitudinal_krt_commune.parquet",
        "01_resultats_python/longitudinal_krt_aggregate.parquet",
        "01_resultats_python/longitudinal_nls.parquet",
        "02_syntheses/canonical_run_selection.csv", "02_syntheses/h1_panel_sensitivity.csv",
        "02_syntheses/h1_panel_sensitivity_nls_diagnostics.csv",
        "02_syntheses/targeted_mcmc_reruns.csv", "02_syntheses/krt_nls_comparison_h0a_h1.csv",
        "02_syntheses/nls_python_r_replication_summary.csv", "02_syntheses/diagnostics_krt_resume.csv",
        "02_comparaison_python_r/nls_python_r_comparison.parquet",
        "02_comparaison_python_r/king_python_r_aggregate_comparison.parquet",
        "03_panel_et_audit/longitudinal_2000_v1.parquet", "03_panel_et_audit/panel_primaire_2000.csv",
        "03_panel_et_audit/coverage_by_election_department.csv", "03_panel_et_audit/department54_pre1988_rows.csv",
        "03_panel_et_audit/rxc_ineligible_audit.csv", "03_panel_et_audit/DATA_DICTIONARY.csv",
        "03_panel_et_audit/foreign_share_source_validation.csv",
        "03_panel_et_audit/COVARIATE_PROVENANCE.csv", "03_panel_et_audit/HARMONISATION_POLITIQUE.csv",
        "03_panel_et_audit/panel_exact_validation.json", "04_figures_essentielles",
    )
    _copy_relative(VALIDATED, professor, professor_items)
    for path in VALIDATED.iterdir():
        if path.name == "05_methodologie_et_code" and (path / "historical_only_v1.0").exists():
            destination = technical / path.name
            shutil.copytree(path, destination, dirs_exist_ok=True, ignore=shutil.ignore_patterns("historical_only_v1.0", "*.nc", "*.rds", "__pycache__", ".cache"))
        elif path.name != "05_methodologie_et_code":
            _copy_relative(VALIDATED, technical, [path.name])
    _manifest_for_staging(professor, VALIDATED, "professeur_legere")
    _manifest_for_staging(technical, VALIDATED, "technique_complete")
    professor_zip = DELIVERABLE_DIR / f"{RELEASE_NAME}_validated_professeur.zip"
    technical_zip = DELIVERABLE_DIR / f"{RELEASE_NAME}_validated_technique.zip"
    results = {
        "professeur": _zip_and_verify(professor, professor_zip),
        "technique": _zip_and_verify(technical, technical_zip),
    }
    after = file_sha256(ORIGINAL_ZIP)
    if after != ORIGINAL_SHA:
        raise AssertionError("original archive changed during packaging")
    results["original_zip_sha256_after"] = after
    _write_json(VALIDATED / "FINAL_PACKAGE_VALIDATION.json", results)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean, validate, promote and package v1.0.1.")
    parser.add_argument("stage", choices=("clean", "validate", "package", "all"))
    args = parser.parse_args()
    if args.stage in {"clean", "all"}:
        clean_and_label_historical()
        sync_current_code_and_configuration()
        sync_release_runs()
        sanitize_all_delivery_run_manifests()
        print(json.dumps({"clean": "complete"}))
    if args.stage in {"validate", "all"}:
        print(json.dumps(validate_candidate(), ensure_ascii=False))
    if args.stage in {"package", "all"}:
        print(json.dumps(package_release(), ensure_ascii=False))


if __name__ == "__main__":
    main()
