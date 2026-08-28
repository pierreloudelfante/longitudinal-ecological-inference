from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .beta_outputs import build_beta_density_data, build_commune_beta_estimates
from .build_figure_catalog import build_figure_catalog
from .build_illustrated_report import build_illustrated_report
from .build_professor_global_recap import build_professor_global_recap
from .extract_latent_densities import build_density_data, plot_density_figures
from .output_schema import (
    DIAGNOSTIC_COLUMNS,
    EXCLUSION_COLUMNS,
    LATENT_COLUMNS,
    LONGITUDINAL_COLUMNS,
    NLS_COEFFICIENT_COLUMNS,
    RESOURCE_GATE_COLUMNS,
    empty_frame,
)
from .paths import OUTPUT_DIR, RUNS_DIR, ensure_runtime_dirs
from .plot_longitudinal import plot_longitudinal
from .plot_election_2022 import plot_election_2022
from .pilot_outputs import build_pilot_audit_tables
from .run_registry import read_registry, selected_successful_run_dirs
from .spec_registry import planned_run_rows


def _collect(filename: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for run_dir in selected_successful_run_dirs():
        path = run_dir / filename
        if not path.exists():
            continue
        try:
            frame = pd.read_csv(path, low_memory=False)
        except pd.errors.EmptyDataError:
            continue
        if not frame.empty:
            frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _write_table(name: str, frame: pd.DataFrame, *, parquet: bool = False) -> None:
    frame.to_csv(OUTPUT_DIR / f"{name}.csv", index=False, encoding="utf-8-sig")
    if parquet:
        frame.to_parquet(OUTPUT_DIR / f"{name}.parquet", index=False)


def _collect_exclusions() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for run_dir in selected_successful_run_dirs():
        path = run_dir / "excluded_units.csv"
        if not path.exists():
            continue
        try:
            frame = pd.read_csv(path, dtype={"unit_id": "string"}, low_memory=False)
        except pd.errors.EmptyDataError:
            continue
        if "exclusion_reason" in frame and "reason" not in frame:
            frame = frame.rename(columns={"exclusion_reason": "reason"})
        manifest_path = path.parent / "manifest.json"
        manifest: dict[str, object] = {}
        if manifest_path.exists():
            import json

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        parameters = manifest.get("parameters", {}) if isinstance(manifest.get("parameters", {}), dict) else {}
        defaults = {
            "run_id": manifest.get("run_id", path.parent.name),
            "run_key": manifest.get("run_key", ""),
            "sample_id": manifest.get("sample_id", ""),
            "election_id": manifest.get("election_id", parameters.get("election_id", "")),
            "scenario_id": manifest.get("scenario_id", parameters.get("scenario_id", "")),
            "model_key": manifest.get("model_key", parameters.get("model_key", "")),
        }
        for column, value in defaults.items():
            if column not in frame:
                frame[column] = value
            else:
                frame[column] = frame[column].fillna(value).replace("", value)
        if "stage" not in frame:
            reasons = frame.get("reason", pd.Series("", index=frame.index)).astype(str)
            frame["stage"] = np.where(reasons.str.startswith("missing_covariate:"), "covariate_filter", "model_filter")
        frames.append(frame.reindex(columns=EXCLUSION_COLUMNS))
    return pd.concat(frames, ignore_index=True) if frames else empty_frame(EXCLUSION_COLUMNS)


def _planned_registry() -> pd.DataFrame:
    executed = read_registry()
    if not executed.empty:
        executed.to_csv(OUTPUT_DIR / "run_registry_executed.csv", index=False, encoding="utf-8-sig")
    planned = pd.DataFrame(planned_run_rows())
    if not executed.empty:
        executed_keys = set(zip(executed["election_id"], executed["scenario_id"], executed["model_key"]))
        planned = planned.loc[
            ~planned.apply(lambda row: (row["election_id"], row["scenario_id"], row["model_key"]) in executed_keys, axis=1)
        ]
    combined = pd.concat([executed, planned], ignore_index=True, sort=False)
    combined.to_csv(OUTPUT_DIR / "run_registry.csv", index=False, encoding="utf-8-sig")
    # Compatibility alias retained for callers of the first implementation.
    combined.to_csv(OUTPUT_DIR / "run_registry_all.csv", index=False, encoding="utf-8-sig")
    return combined


def consolidate_outputs() -> dict[str, int]:
    ensure_runtime_dirs()
    estimates = _collect("longitudinal_estimates.csv")
    if estimates.empty:
        estimates = empty_frame(LONGITUDINAL_COLUMNS)
    else:
        estimates = estimates.reindex(columns=LONGITUDINAL_COLUMNS).sort_values(
            ["election_type", "year", "scenario_id", "model_key", "social_group", "vote_category"]
        )
    _write_table("longitudinal_estimates", estimates, parquet=True)

    diagnostics = _collect("model_diagnostics.csv")
    if diagnostics.empty:
        diagnostics = empty_frame(DIAGNOSTIC_COLUMNS)
    _write_table("model_diagnostics", diagnostics)

    latent_frames = [
        pd.read_parquet(run_dir / "commune_latent_summaries.parquet")
        for run_dir in selected_successful_run_dirs()
        if (run_dir / "commune_latent_summaries.parquet").exists()
    ]
    latent = pd.concat(latent_frames, ignore_index=True) if latent_frames else empty_frame(LATENT_COLUMNS)
    _write_table("commune_latent_summaries", latent.reindex(columns=LATENT_COLUMNS), parquet=True)
    beta_estimates, beta_trace_index = build_commune_beta_estimates(latent.reindex(columns=LATENT_COLUMNS))

    coefficients = _collect("nls_coefficients.csv")
    if coefficients.empty:
        coefficients = empty_frame(NLS_COEFFICIENT_COLUMNS)
    _write_table("nls_coefficients", coefficients.reindex(columns=NLS_COEFFICIENT_COLUMNS))
    _write_table("nls_start_diagnostics", _collect("nls_start_diagnostics.csv"))
    _write_table("excluded_units", _collect_exclusions())
    gates = _collect("resource_ladder_gate.csv")
    _write_table("resource_ladder_gates", gates.reindex(columns=RESOURCE_GATE_COLUMNS) if not gates.empty else empty_frame(RESOURCE_GATE_COLUMNS))
    _write_table("rxc_runtime_benchmark", _collect("rxc_runtime_benchmark.csv"))
    pilot_audit = build_pilot_audit_tables()
    _planned_registry()
    marginal, joint = build_density_data(latent)
    beta_density = build_beta_density_data(marginal)
    plot_density_figures(marginal, joint)
    illustrated_report = build_illustrated_report()
    professor_recap = build_professor_global_recap()
    plot_longitudinal(estimates)
    election_2022 = plot_election_2022(estimates)
    figure_catalog = build_figure_catalog()
    return {
        "longitudinal_estimates": len(estimates),
        "model_diagnostics": len(diagnostics),
        "commune_latent_summaries": len(latent),
        "commune_beta_estimates": len(beta_estimates),
        "beta_trace_index": len(beta_trace_index),
        "beta_density_data": len(beta_density),
        "nls_coefficients": len(coefficients),
        "density_marginal_data": len(marginal),
        "density_joint_data": len(joint),
        **{f"illustrated_report_{key}": value for key, value in illustrated_report.items()},
        **{f"professor_recap_{key}": value for key, value in professor_recap.items()},
        **pilot_audit,
        **{f"election_2022_{key}": value for key, value in election_2022.items()},
        **{f"figure_catalog_{key}": value for key, value in figure_catalog.items()},
    }
