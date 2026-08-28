from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .paths import ROOT, RUNS_DIR
from .release_scope import ReleaseScope, krt_parameterization_matches, load_release_scope
from .utils import file_sha256, write_json


ABSOLUTE_WINDOWS_PATH = re.compile(r"(?i)(?:^|[\s\"'])[A-Z]:[\\/]")
UNCERTAINTY_COLUMNS = (
    "b1_sd", "b1_q025", "b1_q50", "b1_q975",
    "b2_sd", "b2_q025", "b2_q50", "b2_q975",
)
SOURCE_V102_CONFIG = ROOT / "config" / "releases" / "v1.0.2.json"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _h23_manifest_checks(selection: pd.DataFrame, scope: ReleaseScope) -> dict[str, bool]:
    source_scope = load_release_scope(SOURCE_V102_CONFIG)
    extension_scenarios = tuple(
        scenario for scenario in scope.krt_scenarios if scenario not in source_scope.krt_scenarios
    )
    h23 = selection.loc[selection["scenario_id"].astype(str).isin(extension_scenarios)]
    manifests: list[dict[str, Any]] = []
    for run_id in h23["run_id"].astype(str):
        path = RUNS_DIR / run_id / "manifest.json"
        if not path.is_file():
            return {"h23_manifests_present": False}
        manifests.append(_read_json(path))
    parameters = [manifest.get("parameters", {}) for manifest in manifests]
    seeds = [int(value.get("random_seed", -1)) for value in parameters]
    return {
        "h23_manifests_present": True,
        "h23_manifests_success": all(manifest.get("status") == "success" for manifest in manifests),
        "h23_backend_exact": all(value.get("sampler_backend") == scope.mcmc.sampler_backend for value in parameters),
        "h23_panel_hash_exact": all(value.get("panel_sha256") == scope.panel_sha256 for value in parameters),
        "h23_contract_exact": all(
            int(value.get("sample_size", -1)) == scope.panel_size
            and int(value.get("chains", -1)) == scope.mcmc.chains
            and float(value.get("target_accept", -1)) == scope.mcmc.target_accept
            and int(value.get("max_treedepth", -1)) == scope.mcmc.max_treedepth
            and float(value.get("king_lambda", -1)) == scope.krt_model.king_lambda
            and krt_parameterization_matches(value, scope)
            and (int(value.get("tune", -1)), int(value.get("draws", -1)))
            in {(scope.mcmc.warmup, scope.mcmc.draws), (2000, 2000)}
            for value in parameters
        ),
        "h23_seeds_positive_unique": len(seeds) == len(set(seeds)) and all(seed > 0 for seed in seeds),
    }


def audit_candidate(candidate: Path, config_path: Path) -> dict[str, Any]:
    candidate = candidate.resolve()
    scope = load_release_scope(config_path)
    source_scope = load_release_scope(SOURCE_V102_CONFIG)
    extension_scenarios = tuple(
        scenario for scenario in scope.krt_scenarios if scenario not in source_scope.krt_scenarios
    )
    results = candidate / "01_resultats_python"
    syntheses = candidate / "02_syntheses"
    audit = candidate / "03_panel_et_audit"
    methodology = candidate / "05_methodologie_et_code"
    commune = pd.read_parquet(results / "longitudinal_krt_commune.parquet")
    aggregate = pd.read_parquet(results / "longitudinal_krt_aggregate.parquet")
    nls = pd.read_parquet(results / "longitudinal_nls.parquet")
    selection = pd.read_csv(syntheses / "canonical_run_selection.csv", dtype="string")
    diagnostics = pd.read_csv(syntheses / "diagnostics_krt_par_election.csv")
    comparison = pd.read_csv(syntheses / "krt_nls_comparison_h0a_h1_h2_h3.csv")
    validation = _read_json(candidate / "VALIDATION_v1.1.json")
    invariance = _read_json(audit / "NUMERICAL_INVARIANCE_v1.0.2_to_v1.1.json")
    benchmark = _read_json(methodology / "backend_benchmark_2000.json")
    html_receipt = _read_json(methodology / "report_delivery_receipt.json")
    pdf_generation = _read_json(methodology / "REPORT_PDF_GENERATION.json")
    pdf_qa = _read_json(methodology / "REPORT_PDF_QA.json")
    notebook = json.loads((methodology / "AUDIT_NOTEBOOK_v1.1.ipynb").read_text(encoding="utf-8"))
    code_cells = [cell for cell in notebook.get("cells", []) if cell.get("cell_type") == "code"]
    h23_pairs = scope.expected_elections * len(extension_scenarios)
    checks: dict[str, bool] = {
        "ready_scope_exact": validation.get("ready") is True and validation.get("ready_scope") == scope.ready_scope,
        "scenario_scope_exact": set(aggregate["scenario_id"].astype(str)) == set(scope.krt_scenarios),
        "elections_exact": aggregate["election_id"].astype(str).nunique() == scope.expected_elections,
        "krt_pairs_exact": len(aggregate[["election_id", "scenario_id"]].drop_duplicates()) == scope.expected_krt_pairs,
        "commune_rows_exact": len(commune) == scope.expected_krt_commune_rows,
        "aggregate_rows_exact": len(aggregate) == scope.expected_krt_aggregate_rows,
        "nls_pairs_exact": len(nls[["election_id", "scenario_id"]].drop_duplicates()) == scope.expected_nls_pairs,
        "nls_h23_pairs_preserved": len(
            nls.loc[nls["scenario_id"].astype(str).isin(extension_scenarios), ["election_id", "scenario_id"]].drop_duplicates()
        ) == h23_pairs,
        "commune_keys_unique": not commune[["election_id", "scenario_id", "unit_id"]].duplicated().any(),
        "aggregate_keys_unique": not aggregate[["election_id", "scenario_id", "estimand"]].duplicated().any(),
        "same_2000_units_every_run": commune["unit_id"].astype(str).nunique() == scope.panel_size
        and commune.groupby("unit_id", observed=True).size().eq(scope.expected_krt_pairs).all(),
        "uncertainty_complete": commune[list(UNCERTAINTY_COLUMNS)].notna().all().all(),
        "probability_summaries_in_bounds": commune[
            ["b1_mean", "b1_q025", "b1_q50", "b1_q975", "b2_mean", "b2_q025", "b2_q50", "b2_q975"]
        ].apply(lambda series: series.between(0, 1).all()).all(),
        "aggregate_estimands_exact": aggregate.groupby(["election_id", "scenario_id"], observed=True)["estimand"]
        .apply(lambda values: set(values.astype(str)) == {"b_1", "b_2", "b_1_minus_b_2"})
        .all(),
        "selection_exact_unique": len(selection) == scope.expected_krt_pairs
        and not selection[["election_id", "scenario_id"]].duplicated().any(),
        "selection_all_canonical": selection["run_role"].astype(str).eq("canonical").all(),
        "diagnostics_exact": len(diagnostics) == scope.expected_krt_pairs
        and diagnostics["mcmc_status"].astype(str).isin(["pass", "caveat"]).all(),
        "diagnostic_dimensions_separate": {"mcmc_status", "identification_status"}.issubset(diagnostics.columns),
        "comparison_exact": len(comparison) == scope.expected_krt_pairs,
        "h0a_h1_exact_invariance": invariance.get("exact") is True,
        "backend_benchmark_matches_config": benchmark.get("status") == "pass"
        and benchmark.get("recommended_backend") == scope.mcmc.sampler_backend,
        "html_delivery_validated": html_receipt.get("status") in {"pass", "pass_with_structural_qa"}
        and html_receipt.get("builder", {}).get("validation") == "passed"
        and html_receipt.get("builder", {}).get("package") == "passed",
        "pdf_generated_from_current_html": pdf_generation.get("status") == "generated_pending_visual_qa"
        and pdf_generation.get("source_html_sha256") == file_sha256(candidate / "RAPPORT_TECHNIQUE_v1.1.html")
        and pdf_generation.get("output_pdf_sha256") == file_sha256(candidate / "RAPPORT_TECHNIQUE_v1.1.pdf"),
        "pdf_visual_qa_pass": pdf_qa.get("status") == "pass"
        and pdf_qa.get("pages_rendered") == pdf_qa.get("page_count")
        and pdf_qa.get("selectable_text") is True
        and pdf_qa.get("app_controls_absent") is True
        and pdf_qa.get("internal_runtime_labels_absent") is True,
        "audit_notebook_executed": bool(code_cells)
        and all(isinstance(cell.get("execution_count"), int) for cell in code_cells),
        "essential_figures_present": all(
            (candidate / "04_figures_essentielles" / name).is_file()
            for name in (
                "h2_h3_target_probabilities_descriptive.png",
                "mcmc_status_by_scenario.png",
                "krt_nls_comparison.png",
            )
        ),
        "netcdf_absent": not any(candidate.rglob("*.nc")),
    }
    checks.update(_h23_manifest_checks(selection, scope))
    absolute_path_files: list[str] = []
    for path in candidate.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".txt", ".md", ".json", ".csv", ".py", ".r", ".html"}:
            continue
        if ABSOLUTE_WINDOWS_PATH.search(path.read_text(encoding="utf-8", errors="replace")):
            absolute_path_files.append(path.relative_to(candidate).as_posix())
    checks["absolute_local_paths_absent"] = not absolute_path_files
    result = {
        "audit_schema_version": "v1",
        "release_id": scope.release_id,
        "ready": all(checks.values()),
        "ready_scope": scope.ready_scope,
        "checks": checks,
        "failed_checks": [name for name, value in checks.items() if not value],
        "absolute_path_files": absolute_path_files,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json(candidate / "FINAL_COMPLETION_AUDIT_v1.1.json", result)
    if not result["ready"]:
        raise RuntimeError("v1.1 candidate completion audit failed: " + ", ".join(result["failed_checks"]))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Requirement-level completion audit for the v1.1 candidate.")
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit_candidate(args.candidate, args.config), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
