from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .paths import OUTPUT_DIR, ROOT
from .release_artifacts import (
    build_canonical_diagnostics,
    build_dictionaries,
    build_hypothesis_definitions,
    build_krt_nls_comparison,
    build_model_status,
    build_trajectory_table,
    plot_contrast_trajectories,
    plot_diagnostic_status,
    plot_h2_h3_target_probabilities,
    write_chart_map,
)
from .release_scope import ReleaseScope, load_release_scope
from .utils import file_sha256, write_json


SOURCE_V102 = ROOT / "work" / "longitudinal_2000_v1.0.2_H0A_H1_validated"
SOURCE_V102_CONFIG = ROOT / "config" / "releases" / "v1.0.2.json"
CANDIDATE_V11 = ROOT / "work" / "longitudinal_2000_v1.1_H0A_H1_H2_H3_candidate"


def _copy(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _safe_replace_candidate(path: Path) -> None:
    expected = CANDIDATE_V11.resolve()
    resolved = path.resolve()
    if resolved != expected or resolved.parent != (ROOT / "work").resolve():
        raise ValueError(f"refusing to replace unexpected candidate path: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True)


def _copy_preserved_v102_evidence(candidate: Path) -> None:
    for folder in ("02_comparaison_python_r", "03_panel_et_audit"):
        source_dir = SOURCE_V102 / folder
        for source in source_dir.glob("*"):
            if not source.is_file():
                continue
            if source.name == "NUMERICAL_INVARIANCE_v1.0.1_to_v1.0.2.json":
                continue
            _copy(source, candidate / folder / source.name)
    for name in (
        "h1_panel_sensitivity.csv",
        "targeted_mcmc_reruns.csv",
        "nls_python_r_replication_summary.csv",
    ):
        _copy(SOURCE_V102 / "02_syntheses" / name, candidate / "02_syntheses" / name)
    for name in (
        "h1_panel_sensitivity.png",
        "raw_scatter_2022_bounds_and_target_share.png",
    ):
        _copy(SOURCE_V102 / "04_figures_essentielles" / name, candidate / "04_figures_essentielles" / name)


def _validate_materialized_outputs(candidate: Path, scope: ReleaseScope) -> dict[str, Any]:
    commune = pd.read_parquet(candidate / "01_resultats_python" / "longitudinal_krt_commune.parquet")
    aggregate = pd.read_parquet(candidate / "01_resultats_python" / "longitudinal_krt_aggregate.parquet")
    nls = pd.read_parquet(candidate / "01_resultats_python" / "longitudinal_nls.parquet")
    uncertainty = [
        "b1_sd", "b1_q025", "b1_q50", "b1_q975",
        "b2_sd", "b2_q025", "b2_q50", "b2_q975",
    ]
    checks = {
        "krt_scenario_scope_exact": set(aggregate["scenario_id"].astype(str)) == set(scope.krt_scenarios),
        "krt_pairs_exact": len(aggregate[["election_id", "scenario_id"]].drop_duplicates()) == scope.expected_krt_pairs,
        "commune_rows_exact": len(commune) == scope.expected_krt_commune_rows,
        "aggregate_rows_exact": len(aggregate) == scope.expected_krt_aggregate_rows,
        "nls_pairs_exact": len(nls[["election_id", "scenario_id"]].drop_duplicates()) == scope.expected_nls_pairs,
        "commune_keys_unique": not commune[["election_id", "scenario_id", "unit_id"]].duplicated().any(),
        "aggregate_keys_unique": not aggregate[["election_id", "scenario_id", "estimand"]].duplicated().any(),
        "uncertainty_complete": commune[uncertainty].notna().all().all(),
        "mcmc_no_fail": aggregate["mcmc_status"].isin(["pass", "caveat"]).all(),
        "probabilities_in_bounds": commune[["b1_mean", "b2_mean"]].ge(0).all().all()
        and commune[["b1_mean", "b2_mean"]].le(1).all().all(),
        "contrast_in_bounds": aggregate.loc[
            aggregate["estimand"].eq("b_1_minus_b_2"), "mean"
        ].between(-1, 1).all(),
        "h0a_h1_invariance_present": (
            candidate / "03_panel_et_audit" / "NUMERICAL_INVARIANCE_v1.0.2_to_v1.1.json"
        ).is_file(),
    }
    result = {
        "release_id": scope.release_id,
        "ready": bool(all(checks.values())),
        "ready_scope": scope.ready_scope,
        "checks": {name: bool(value) for name, value in checks.items()},
        "actual": {
            "krt_pairs": int(len(aggregate[["election_id", "scenario_id"]].drop_duplicates())),
            "commune_rows": int(len(commune)),
            "aggregate_rows": int(len(aggregate)),
            "nls_pairs": int(len(nls[["election_id", "scenario_id"]].drop_duplicates())),
        },
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json(candidate / "VALIDATION_v1.1.json", result)
    if not result["ready"]:
        raise RuntimeError("materialized v1.1 candidate failed validation")
    return result


def materialize_v11(release_config_path: Path, candidate: Path = CANDIDATE_V11) -> dict[str, Any]:
    scope = load_release_scope(release_config_path)
    source_scope = load_release_scope(SOURCE_V102_CONFIG)
    inherited = tuple(scenario for scenario in scope.krt_scenarios if scenario in source_scope.krt_scenarios)
    extensions = tuple(scenario for scenario in scope.krt_scenarios if scenario not in source_scope.krt_scenarios)
    if inherited != source_scope.krt_scenarios or len(extensions) != 2:
        raise ValueError(
            "v1.1 materialization requires the complete configured v1.0.2 scope plus two extension scenarios"
        )
    final_dir = OUTPUT_DIR / scope.spec_version / "final" / scope.release_id
    final_manifest_path = final_dir / "release_manifest.json"
    if not final_manifest_path.is_file():
        raise FileNotFoundError(final_manifest_path)
    final_manifest = json.loads(final_manifest_path.read_text(encoding="utf-8"))
    if not final_manifest.get("ready") or final_manifest.get("ready_scope") != scope.ready_scope:
        raise AssertionError("runtime final release is not ready for materialization")

    production_dir = OUTPUT_DIR / scope.spec_version / "production" / scope.release_id
    selection_path = production_dir / "canonical_run_selection.csv"
    invariance_path = production_dir / "NUMERICAL_INVARIANCE_v1.0.2_to_v1.1.json"
    backend_benchmark_path = production_dir / "backend_benchmark_2000.json"
    if not selection_path.is_file() or not invariance_path.is_file() or not backend_benchmark_path.is_file():
        raise FileNotFoundError("canonical selection, H0A/H1 invariance, or backend benchmark evidence missing")

    _safe_replace_candidate(candidate)
    _copy_preserved_v102_evidence(candidate)
    result_dir = candidate / "01_resultats_python"
    for filename in (
        "longitudinal_krt_commune.parquet",
        "longitudinal_krt_aggregate.parquet",
        "longitudinal_nls.parquet",
        "release_manifest.json",
    ):
        _copy(final_dir / filename, result_dir / filename)
    _copy(final_dir / "longitudinal_audit.parquet", candidate / "03_panel_et_audit" / "longitudinal_audit.parquet")
    _copy(selection_path, candidate / "02_syntheses" / "canonical_run_selection.csv")
    _copy(invariance_path, candidate / "03_panel_et_audit" / invariance_path.name)
    _copy(
        backend_benchmark_path,
        candidate / "05_methodologie_et_code" / "backend_benchmark_2000.json",
    )
    for filename in (
        "h23_run_evaluations.csv",
        "h23_pilot_gate_supervised.csv",
        "h23_pilot_gate_supervised.json",
        "h23_pilot_input_audit.csv",
        "h23_pilot_input_audit.json",
        "h23_supervisor_status.json",
    ):
        source = production_dir / filename
        if source.is_file():
            _copy(source, candidate / "06_diagnostics_runs" / "h23_supervisor" / filename)
    _copy(release_config_path, candidate / "05_methodologie_et_code" / "release_config_v1.1.json")

    diagnostics, summary = build_canonical_diagnostics(candidate, scope)
    trajectory = build_trajectory_table(candidate, scope)
    trajectory_figures = plot_contrast_trajectories(candidate, scope, trajectory)
    target_figure = plot_h2_h3_target_probabilities(candidate, scope, trajectory)
    diagnostic_figure = plot_diagnostic_status(candidate, scope, diagnostics)
    comparison = build_krt_nls_comparison(candidate, scope)
    status = build_model_status(candidate, scope, diagnostics)
    definitions = build_hypothesis_definitions(candidate, scope)
    chart_map = write_chart_map(candidate, scope)
    public_dictionary, technical_dictionary = build_dictionaries(candidate)
    validation = _validate_materialized_outputs(candidate, scope)
    from .build_v11_audit_notebook import build_and_execute_notebook

    notebook = build_and_execute_notebook(
        candidate,
        release_config_path,
        candidate / "05_methodologie_et_code" / "AUDIT_NOTEBOOK_v1.1.ipynb",
    )

    manifest = {
        "release_id": scope.release_id,
        "ready": validation["ready"],
        "ready_scope": scope.ready_scope,
        "candidate_runtime_path": candidate.relative_to(ROOT).as_posix(),
        "public_schema_version": scope.public_schema_version,
        "panel_sha256": scope.panel_sha256,
        "canonical_selection_sha256": file_sha256(candidate / "02_syntheses" / "canonical_run_selection.csv"),
        "diagnostic_rows": len(diagnostics),
        "diagnostic_summary_rows": len(summary),
        "trajectory_rows": len(trajectory),
        "trajectory_figure_files": len(trajectory_figures),
        "h2_h3_target_figure": target_figure.relative_to(candidate).as_posix() if target_figure else None,
        "diagnostic_figure": diagnostic_figure.relative_to(candidate).as_posix(),
        "krt_nls_rows": len(comparison),
        "model_status_rows": len(status),
        "definition_rows": len(definitions),
        "chart_map_rows": len(chart_map),
        "public_dictionary_rows": len(public_dictionary),
        "technical_dictionary_rows": len(technical_dictionary),
        "audit_notebook": notebook,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json(candidate / "MATERIALIZATION_v1.1.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize the validated H0A/H1/H2/H3 v1.1 candidate.")
    parser.add_argument("--release-config", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, default=CANDIDATE_V11)
    args = parser.parse_args()
    print(json.dumps(materialize_v11(args.release_config, args.candidate), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
