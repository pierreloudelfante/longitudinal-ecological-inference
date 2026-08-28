from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .build_longitudinal_panel import PANEL_PATH, load_longitudinal_panel_manifest
from .consolidation_core import (
    build_krt_aggregate,
    build_krt_commune,
    build_nls,
    build_unified_audit,
)
from .paths import OUTPUT_DIR, ROOT, RUNS_DIR, ensure_runtime_dirs
from .release_artifacts import validate_selection
from .release_scope import ReleaseScope, load_release_scope
from .utils import file_sha256, write_json


def _load_manifest(run_id: str) -> tuple[Path, dict[str, Any]]:
    run_dir = RUNS_DIR / run_id
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "success":
        raise AssertionError(f"selected run is not successful: {run_id}")
    return run_dir, manifest


def _selected_krt_runs(selection_path: Path, scope: ReleaseScope) -> list[tuple[Path, dict[str, Any]]]:
    selection = validate_selection(pd.read_csv(selection_path, dtype="string"), scope)
    runs: list[tuple[Path, dict[str, Any]]] = []
    for row in selection.itertuples(index=False):
        run_dir, manifest = _load_manifest(str(row.run_id))
        parameters = manifest.get("parameters", {})
        if parameters.get("election_id") != row.election_id or parameters.get("scenario_id") != row.scenario_id:
            raise AssertionError(f"canonical selection metadata mismatch: {row.run_id}")
        if str(parameters.get("model_key", manifest.get("model_key", ""))) != "krt_beta_binomial":
            raise AssertionError(f"canonical KRT selection references another model: {row.run_id}")
        runs.append((run_dir, manifest))
    return runs


def _selected_nls_runs(
    panel_id: str,
    scenarios: tuple[str, ...],
) -> list[tuple[Path, dict[str, Any]]]:
    selected: dict[tuple[str, str], tuple[str, Path, dict[str, Any]]] = {}
    for manifest_path in RUNS_DIR.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("status") != "success":
            continue
        parameters = manifest.get("parameters", {})
        if not isinstance(parameters, dict):
            continue
        model_key = str(parameters.get("model_key", manifest.get("model_key", "")))
        if not model_key.startswith("rosen_nls"):
            continue
        if str(parameters.get("scenario_id", "")) not in scenarios:
            continue
        recorded_panel = str(manifest.get("panel_id", parameters.get("panel_id", manifest.get("sample_id", ""))))
        if recorded_panel != panel_id:
            continue
        run_dir = manifest_path.parent
        if not (run_dir / "longitudinal_estimates.csv").exists():
            continue
        key = (str(parameters.get("election_id")), str(parameters.get("scenario_id")))
        finished = str(manifest.get("finished_at_utc", ""))
        current = selected.get(key)
        if current is None or finished > current[0]:
            selected[key] = (finished, run_dir, manifest)
    return [(value[1], value[2]) for value in sorted(selected.values(), key=lambda value: value[1].name)]


def _apply_public_schema(
    commune: pd.DataFrame,
    aggregate: pd.DataFrame,
    nls: pd.DataFrame,
    panel: pd.DataFrame,
    scope: ReleaseScope,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    commune = commune.rename(columns={"revenue": "revenue_ratio", "capital": "capital_ratio"})
    panel_names = panel[["unit_id", "commune_name", "harmonization_version"]].rename(
        columns={"commune_name": "commune_name_canonical", "harmonization_version": "geography_version"}
    )
    commune["unit_id"] = commune["unit_id"].astype("string")
    panel_names["unit_id"] = panel_names["unit_id"].astype("string")
    commune = commune.merge(panel_names, on="unit_id", how="left", validate="many_to_one")
    if commune[["commune_name_canonical", "geography_version"]].isna().any().any():
        raise AssertionError("canonical geography join is incomplete")
    commune["commune_name_reference_year"] = 2022
    commune["public_schema_version"] = scope.public_schema_version
    aggregate["public_schema_version"] = scope.public_schema_version
    nls["public_schema_version"] = scope.public_schema_version
    return commune, aggregate, nls


def _validate_scoped_outputs(
    *,
    commune: pd.DataFrame,
    aggregate: pd.DataFrame,
    nls: pd.DataFrame,
    scope: ReleaseScope,
) -> dict[str, Any]:
    krt_pairs = aggregate[["election_id", "scenario_id"]].drop_duplicates()
    nls_pairs = nls[["election_id", "scenario_id"]].drop_duplicates()
    uncertainty = [
        "b1_sd", "b1_q025", "b1_q50", "b1_q975",
        "b2_sd", "b2_q025", "b2_q50", "b2_q975",
    ]
    checks = {
        "krt_pairs": len(krt_pairs) == scope.expected_krt_pairs,
        "commune_rows": len(commune) == scope.expected_krt_commune_rows,
        "aggregate_rows": len(aggregate) == scope.expected_krt_aggregate_rows,
        "nls_pairs": len(nls_pairs) == scope.expected_nls_pairs,
        "commune_keys_unique": not commune[["election_id", "scenario_id", "unit_id"]].duplicated().any(),
        "aggregate_keys_unique": not aggregate[["election_id", "scenario_id", "estimand"]].duplicated().any(),
        "uncertainty_complete": commune[uncertainty].notna().all().all(),
        "mcmc_accepted": aggregate["mcmc_status"].isin(["pass", "caveat"]).all(),
        "probabilities_in_range": commune[["b1_mean", "b2_mean"]].ge(0).all().all() and commune[["b1_mean", "b2_mean"]].le(1).all().all(),
        "contrasts_in_range": aggregate.loc[aggregate["estimand"].eq("b_1_minus_b_2"), "mean"].between(-1, 1).all(),
    }
    return {
        "ready": bool(all(checks.values())),
        "ready_scope": scope.ready_scope,
        "checks": {name: bool(value) for name, value in checks.items()},
        "actual": {
            "krt_pairs": int(len(krt_pairs)),
            "commune_rows": int(len(commune)),
            "aggregate_rows": int(len(aggregate)),
            "nls_pairs": int(len(nls_pairs)),
        },
        "expected": {
            "krt_pairs": scope.expected_krt_pairs,
            "commune_rows": scope.expected_krt_commune_rows,
            "aggregate_rows": scope.expected_krt_aggregate_rows,
            "nls_pairs": scope.expected_nls_pairs,
        },
    }


def finalize_scoped_release(
    *,
    release_config_path: Path,
    canonical_selection_path: Path,
    allow_diagnostic_failures: bool = False,
) -> dict[str, Any]:
    ensure_runtime_dirs()
    scope = load_release_scope(release_config_path)
    panel_manifest = load_longitudinal_panel_manifest()
    if str(panel_manifest.get("panel_sha256", "")) != scope.panel_sha256:
        raise AssertionError("panel hash differs from release configuration")
    panel = pd.read_parquet(PANEL_PATH)
    if "included_primary_2000" in panel.columns:
        panel = panel.loc[panel["included_primary_2000"].astype(bool)].copy()
    panel["unit_id"] = panel["unit_id"].astype("string")
    if len(panel) != scope.panel_size:
        raise AssertionError("panel row count differs from release configuration")
    panel_id = str(panel_manifest["panel_id"])
    krt_runs = _selected_krt_runs(canonical_selection_path, scope)
    nls_runs = _selected_nls_runs(panel_id, scope.krt_scenarios)
    commune = build_krt_commune(krt_runs, panel)
    aggregate = build_krt_aggregate(krt_runs)
    nls = build_nls(nls_runs)
    audit = build_unified_audit(panel_id, panel, krt_runs + nls_runs)
    commune, aggregate, nls = _apply_public_schema(commune, aggregate, nls, panel, scope)
    validation = _validate_scoped_outputs(commune=commune, aggregate=aggregate, nls=nls, scope=scope)

    final_dir = OUTPUT_DIR / scope.spec_version / "final" / scope.release_id
    final_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "longitudinal_krt_commune": (final_dir / "longitudinal_krt_commune.parquet", commune),
        "longitudinal_krt_aggregate": (final_dir / "longitudinal_krt_aggregate.parquet", aggregate),
        "longitudinal_nls": (final_dir / "longitudinal_nls.parquet", nls),
        "longitudinal_audit": (final_dir / "longitudinal_audit.parquet", audit),
    }
    for path, frame in outputs.values():
        frame.to_parquet(path, index=False)
    manifest = {
        "manifest_schema_version": "longitudinal_scoped_release_manifest_v1",
        "release_id": scope.release_id,
        "ready": validation["ready"],
        "release_status": "validated" if validation["ready"] else "candidate_with_documented_diagnostics",
        "diagnostic_failures_allowed_for_candidate": bool(allow_diagnostic_failures),
        "ready_scope": scope.ready_scope,
        "public_schema_version": scope.public_schema_version,
        "spec_version": scope.spec_version,
        "panel_sha256": scope.panel_sha256,
        "canonical_selection_runtime_path": (
            canonical_selection_path.resolve().relative_to(ROOT).as_posix()
            if canonical_selection_path.resolve().is_relative_to(ROOT)
            else "external"
        ),
        "canonical_selection_delivery_path": "02_syntheses/canonical_run_selection.csv",
        "validation": validation,
        "outputs": {
            name: {
                "runtime_path": path.relative_to(ROOT).as_posix(),
                "delivery_path": f"01_resultats_python/{path.name}",
                "delivery_included": True,
                "external_required": False,
                "rows": int(len(frame)),
                "sha256": file_sha256(path),
            }
            for name, (path, frame) in outputs.items()
        },
        "selected_krt_run_ids": [manifest["run_id"] for _, manifest in krt_runs],
        "selected_nls_run_ids": [manifest["run_id"] for _, manifest in nls_runs],
        "netcdf_included_in_release": False,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json(final_dir / "release_manifest.json", manifest)
    if not validation["ready"] and not allow_diagnostic_failures:
        raise RuntimeError("scoped finalization failed validation; inspect release_manifest.json")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Finalize a release from configuration and explicit canonical runs.")
    parser.add_argument("--release-config", type=Path, required=True)
    parser.add_argument("--canonical-selection", type=Path, required=True)
    parser.add_argument(
        "--allow-diagnostic-failures",
        action="store_true",
        help="Materialize an explicitly non-ready candidate when completed fits retain MCMC fails.",
    )
    args = parser.parse_args()
    result = finalize_scoped_release(
        release_config_path=args.release_config,
        canonical_selection_path=args.canonical_selection,
        allow_diagnostic_failures=args.allow_diagnostic_failures,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
