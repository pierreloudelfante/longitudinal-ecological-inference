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
from .release_scope import load_release_scope
from .utils import file_sha256, portable_path, write_json


CONFIG = ROOT / "config" / "releases" / "v1.5_retained6.json"
SOURCE_V102 = ROOT / "work" / "longitudinal_2000_v1.0.2_H0A_H1_validated"
CANDIDATE = ROOT / "work" / "longitudinal_2000_v1.5_H0A_H1_H0B_H0C_H2_H3_candidate"
R_DIR = OUTPUT_DIR / "longitudinal_2000_v1" / "r_replication"


def _copy(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _safe_reset_candidate(candidate: Path) -> None:
    expected = CANDIDATE.resolve()
    resolved = candidate.resolve()
    if resolved != expected or resolved.parent != (ROOT / "work").resolve():
        raise ValueError(f"refusing to replace unexpected candidate: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True)


def _copy_static_audit(candidate: Path) -> None:
    source = SOURCE_V102 / "03_panel_et_audit"
    for name in (
        "coverage_by_election_department.csv",
        "DATA_DICTIONARY.csv",
        "DATA_DICTIONARY_TECHNICAL.csv",
        "COVARIATE_PROVENANCE.csv",
        "HARMONISATION_POLITIQUE.csv",
        "panel_exact_validation.json",
        "panel_primaire_2000.csv",
        "department54_pre1988_rows.csv",
        "foreign_share_source_validation.csv",
        "rxc_ineligible_audit.csv",
        "SCHEMA_MIGRATION_v1.0.1_to_v1.0.2.csv",
    ):
        _copy(source / name, candidate / "03_panel_et_audit" / name)
    for name in ("h1_panel_sensitivity.csv", "targeted_mcmc_reruns.csv"):
        _copy(SOURCE_V102 / "02_syntheses" / name, candidate / "02_syntheses" / name)
    for name in ("h1_panel_sensitivity.png", "raw_scatter_2022_bounds_and_target_share.png"):
        _copy(
            SOURCE_V102 / "04_figures_essentielles" / name,
            candidate / "04_figures_essentielles" / name,
        )


def _build_model_ready_index(candidate: Path, scenarios: tuple[str, ...], panel_id: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for scenario_id in scenarios:
        pattern = f"*__{scenario_id}__{panel_id}__n2000.parquet"
        paths = sorted((OUTPUT_DIR / "model_ready").glob(pattern))
        if len(paths) != 26:
            raise AssertionError(f"expected 26 model-ready inputs for {scenario_id}; found {len(paths)}")
        for path in paths:
            election_id = path.name.split("__", maxsplit=1)[0]
            frame = pd.read_parquet(path, columns=["unit_id", "panel_id", "election_id", "scenario_id"])
            checks = {
                "rows_2000": len(frame) == 2000,
                "unit_id_unique": not frame["unit_id"].astype("string").duplicated().any(),
                "panel_id_exact": frame["panel_id"].astype(str).eq(panel_id).all(),
                "election_id_exact": frame["election_id"].astype(str).eq(election_id).all(),
                "scenario_id_exact": frame["scenario_id"].astype(str).eq(scenario_id).all(),
            }
            if not all(checks.values()):
                raise AssertionError(f"invalid model-ready input {path.name}: {checks}")
            rows.append(
                {
                    "election_id": election_id,
                    "scenario_id": scenario_id,
                    "panel_id": panel_id,
                    "rows": len(frame),
                    "runtime_path": portable_path(path, root=ROOT),
                    "technical_delivery_path": f"01_entrees/model_ready/{path.name}",
                    "professor_delivery_included": False,
                    "technical_delivery_included": True,
                    "sha256": file_sha256(path),
                }
            )
    index = pd.DataFrame(rows).sort_values(["scenario_id", "election_id"])
    destination = candidate / "01_entrees" / "MODEL_READY_INDEX.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    index.to_csv(destination, index=False, encoding="utf-8-sig")
    return index


def _copy_r_results(candidate: Path) -> dict[str, int]:
    r_outputs = {
        "longitudinal_king_ei_r_commune_retained6.parquet": "03_resultats_r_eipack",
        "longitudinal_king_ei_r_aggregate_retained6.parquet": "03_resultats_r_eipack",
        "king_ei_retained6_run_audit.csv": "03_resultats_r_eipack",
        "king_ei_retained6_consolidation_manifest.json": "03_resultats_r_eipack",
        "king_python_r_retained6_aggregate_comparison.parquet": "04_comparaison_python_r",
        "king_python_r_retained6_commune_summary.parquet": "04_comparaison_python_r",
        "king_python_r_retained6_python_selection.csv": "04_comparaison_python_r",
        "king_python_r_retained6_comparison_manifest.json": "04_comparaison_python_r",
    }
    counts: dict[str, int] = {}
    for name, folder in r_outputs.items():
        source = R_DIR / name
        _copy(source, candidate / folder / name)
        if source.suffix == ".parquet":
            counts[name] = len(pd.read_parquet(source))
        elif source.suffix == ".csv":
            counts[name] = len(pd.read_csv(source))
    return counts


def _validate(candidate: Path, scope: Any, runtime_manifest: dict[str, Any]) -> dict[str, Any]:
    commune = pd.read_parquet(candidate / "01_resultats_python" / "longitudinal_krt_commune.parquet")
    aggregate = pd.read_parquet(candidate / "01_resultats_python" / "longitudinal_krt_aggregate.parquet")
    nls = pd.read_parquet(candidate / "01_resultats_python" / "longitudinal_nls.parquet")
    r_commune = pd.read_parquet(candidate / "03_resultats_r_eipack" / "longitudinal_king_ei_r_commune_retained6.parquet")
    r_aggregate = pd.read_parquet(candidate / "03_resultats_r_eipack" / "longitudinal_king_ei_r_aggregate_retained6.parquet")
    uncertainty = [
        "b1_sd", "b1_q025", "b1_q50", "b1_q975",
        "b2_sd", "b2_q025", "b2_q50", "b2_q975",
    ]
    structural_checks = {
        "python_krt_pairs_156": aggregate[["election_id", "scenario_id"]].drop_duplicates().shape[0] == scope.expected_krt_pairs,
        "python_commune_rows_312000": len(commune) == scope.expected_krt_commune_rows,
        "python_aggregate_rows_468": len(aggregate) == scope.expected_krt_aggregate_rows,
        "nls_pairs_156": nls[["election_id", "scenario_id"]].drop_duplicates().shape[0] == scope.expected_nls_pairs,
        "r_pairs_156": r_aggregate[["election_id", "scenario_id"]].drop_duplicates().shape[0] == scope.expected_krt_pairs,
        "r_commune_rows_312000": len(r_commune) == scope.expected_krt_commune_rows,
        "r_aggregate_rows_468": len(r_aggregate) == scope.expected_krt_aggregate_rows,
        "python_commune_key_unique": not commune[["election_id", "scenario_id", "unit_id"]].duplicated().any(),
        "r_commune_key_unique": not r_commune[["election_id", "scenario_id", "unit_id"]].duplicated().any(),
        "python_uncertainty_complete": commune[uncertainty].notna().all().all(),
        "r_uncertainty_complete": r_commune[uncertainty].notna().all().all(),
        "scenario_scope_exact": set(aggregate["scenario_id"].astype(str)) == set(scope.krt_scenarios),
    }
    if not all(structural_checks.values()):
        raise RuntimeError(f"retained release structural validation failed: {structural_checks}")
    diagnostic_counts = aggregate[["election_id", "scenario_id", "mcmc_status"]].drop_duplicates()[
        "mcmc_status"
    ].value_counts().to_dict()
    result = {
        "schema_version": "retained6_release_validation_v1",
        "release_id": scope.release_id,
        "structural_ready": True,
        "scientific_ready": bool(runtime_manifest.get("ready", False)),
        "release_status": runtime_manifest.get("release_status"),
        "ready_scope": scope.ready_scope,
        "structural_checks": {key: bool(value) for key, value in structural_checks.items()},
        "mcmc_status_counts": {str(key): int(value) for key, value in diagnostic_counts.items()},
        "warning": (
            "A structurally complete candidate is not a validated scientific release when canonical MCMC fails remain."
        ),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json(candidate / "VALIDATION_RETAINED6.json", result)
    return result


def materialize(*, release_config: Path, candidate: Path = CANDIDATE) -> dict[str, Any]:
    scope = load_release_scope(release_config)
    runtime_dir = OUTPUT_DIR / scope.spec_version / "final" / scope.release_id
    manifest_path = runtime_dir / "release_manifest.json"
    runtime_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selection_path = (
        OUTPUT_DIR / scope.spec_version / "production" / scope.release_id / "canonical_run_selection.csv"
    )
    if not selection_path.is_file():
        raise FileNotFoundError(selection_path)

    _safe_reset_candidate(candidate)
    _copy_static_audit(candidate)
    for name in (
        "longitudinal_krt_commune.parquet",
        "longitudinal_krt_aggregate.parquet",
        "longitudinal_nls.parquet",
        "release_manifest.json",
    ):
        _copy(runtime_dir / name, candidate / "01_resultats_python" / name)
    _copy(runtime_dir / "longitudinal_audit.parquet", candidate / "03_panel_et_audit" / "longitudinal_audit.parquet")
    _copy(selection_path, candidate / "02_syntheses" / "canonical_run_selection.csv")
    _copy(release_config, candidate / "05_methodologie_et_code" / "release_config_retained6.json")
    _copy(ROOT / "SCOPE_DECISION_20260826.md", candidate / "05_methodologie_et_code" / "SCOPE_DECISION_20260826.md")

    panel_manifest = json.loads((ROOT / "panel" / "longitudinal_2000_v1_manifest.json").read_text(encoding="utf-8"))
    model_ready_index = _build_model_ready_index(candidate, scope.krt_scenarios, str(panel_manifest["panel_id"]))
    r_counts = _copy_r_results(candidate)

    diagnostics, diagnostic_summary = build_canonical_diagnostics(candidate, scope)
    trajectory = build_trajectory_table(candidate, scope)
    trajectory_figures = plot_contrast_trajectories(candidate, scope, trajectory)
    target_figure = plot_h2_h3_target_probabilities(candidate, scope, trajectory)
    diagnostic_figure = plot_diagnostic_status(candidate, scope, diagnostics)
    comparison = build_krt_nls_comparison(candidate, scope)
    model_status = build_model_status(candidate, scope, diagnostics)
    definitions = build_hypothesis_definitions(candidate, scope)
    chart_map = write_chart_map(candidate, scope)
    public_dictionary, technical_dictionary = build_dictionaries(candidate)
    validation = _validate(candidate, scope, runtime_manifest)

    result = {
        "schema_version": "retained6_materialization_v1",
        "release_id": scope.release_id,
        "candidate_runtime_path": portable_path(candidate, root=ROOT),
        "structural_ready": validation["structural_ready"],
        "scientific_ready": validation["scientific_ready"],
        "scenarios": list(scope.krt_scenarios),
        "model_ready_inputs": len(model_ready_index),
        "r_output_rows": r_counts,
        "diagnostic_rows": len(diagnostics),
        "diagnostic_summary_rows": len(diagnostic_summary),
        "trajectory_rows": len(trajectory),
        "trajectory_figures": len(trajectory_figures),
        "h2_h3_target_figure": None if target_figure is None else target_figure.name,
        "diagnostic_figure": diagnostic_figure.name,
        "krt_nls_rows": len(comparison),
        "model_status_rows": len(model_status),
        "definition_rows": len(definitions),
        "chart_map_rows": len(chart_map),
        "public_dictionary_rows": len(public_dictionary),
        "technical_dictionary_rows": len(technical_dictionary),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json(candidate / "MATERIALIZATION_RETAINED6.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize the six-scenario Python/R candidate.")
    parser.add_argument("--release-config", type=Path, default=CONFIG)
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    args = parser.parse_args()
    print(json.dumps(materialize(release_config=args.release_config, candidate=args.candidate), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
