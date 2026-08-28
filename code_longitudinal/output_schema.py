from __future__ import annotations

from pathlib import Path

import pandas as pd

from .paths import OUTPUT_DIR, ensure_runtime_dirs


LONGITUDINAL_COLUMNS = [
    "run_id",
    "run_key",
    "sample_id",
    "election_id",
    "election_type",
    "year",
    "round",
    "scenario_id",
    "model_key",
    "model_family",
    "with_covariate",
    "covariate_name",
    "social_group",
    "vote_category",
    "estimate",
    "lower",
    "upper",
    "n_communes_requested",
    "n_communes_used",
    "N_total",
    "elapsed_seconds",
    "fit_status",
    "diagnostic_status",
    "random_seed",
]

DIAGNOSTIC_COLUMNS = [
    "run_id",
    "run_key",
    "sample_id",
    "election_id",
    "scenario_id",
    "model_key",
    "draws",
    "tune",
    "chains",
    "target_accept",
    "n_communes_requested",
    "n_communes_used",
    "dropped_degenerate_rows",
    "mcmc_divergences",
    "mcmc_divergence_fraction",
    "mcmc_max_rhat",
    "mcmc_min_ess_bulk",
    "mcmc_min_ess_tail",
    "elapsed_seconds",
    "peak_memory_mb",
    "fit_status",
    "diagnostic_status",
    "error",
]

LATENT_COLUMNS = [
    "run_id",
    "run_key",
    "sample_id",
    "election_id",
    "scenario_id",
    "model_key",
    "unit_id",
    "sample_rank",
    "b1_weight",
    "b2_weight",
    "b1_mean",
    "b1_sd",
    "b1_q025",
    "b1_q50",
    "b1_q975",
    "b2_mean",
    "b2_sd",
    "b2_q025",
    "b2_q50",
    "b2_q975",
]

NLS_COEFFICIENT_COLUMNS = [
    "run_id",
    "run_key",
    "sample_id",
    "election_id",
    "scenario_id",
    "model_key",
    "covariate_name",
    "social_group",
    "vote_category",
    "reference_vote_category",
    "term",
    "estimate",
    "posterior_sd",
]

EXCLUSION_COLUMNS = [
    "run_id",
    "run_key",
    "sample_id",
    "election_id",
    "scenario_id",
    "model_key",
    "unit_id",
    "sample_rank",
    "stage",
    "reason",
]

RESOURCE_GATE_COLUMNS = [
    "run_id",
    "run_key",
    "election_id",
    "scenario_id",
    "model_key",
    "current_n",
    "next_n",
    "elapsed_seconds",
    "predicted_seconds",
    "observed_peak_memory_mb",
    "memory_estimate_method",
    "predicted_peak_memory_mb",
    "available_memory_mb",
    "memory_limit_mb",
    "allowed_time",
    "allowed_memory",
    "allowed",
    "reason",
]

BETA_ESTIMATE_COLUMNS = [
    "run_id",
    "run_key",
    "sample_id",
    "election_id",
    "scenario_id",
    "model_key",
    "comparison_key",
    "n_communes_requested",
    "n_communes_used",
    "draws",
    "tune",
    "chains",
    "diagnostic_status",
    "unit_id",
    "sample_rank",
    "beta_parameter",
    "social_group",
    "estimate_basis",
    "weight",
    "estimate",
    "std_error",
    "q025",
    "q50",
    "q975",
]

BETA_TRACE_INDEX_COLUMNS = [
    "run_id",
    "run_key",
    "sample_id",
    "election_id",
    "scenario_id",
    "model_key",
    "n_communes_requested",
    "n_communes_used",
    "draws",
    "tune",
    "chains",
    "variables",
    "trace_path",
    "trace_size_bytes",
    "trace_sha256",
]


def empty_frame(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame({column: pd.Series(dtype="object") for column in columns})


def initialize_output_schema() -> dict[str, Path]:
    ensure_runtime_dirs()
    tables = {
        "longitudinal_estimates": empty_frame(LONGITUDINAL_COLUMNS),
        "model_diagnostics": empty_frame(DIAGNOSTIC_COLUMNS),
        "commune_latent_summaries": empty_frame(LATENT_COLUMNS),
        "nls_coefficients": empty_frame(NLS_COEFFICIENT_COLUMNS),
        "nls_start_diagnostics": pd.DataFrame(),
        "density_marginal_data": pd.DataFrame(),
        "density_joint_data": pd.DataFrame(),
        "excluded_units": empty_frame(EXCLUSION_COLUMNS),
        "resource_ladder_gates": empty_frame(RESOURCE_GATE_COLUMNS),
        "commune_beta_estimates": empty_frame(BETA_ESTIMATE_COLUMNS),
        "beta_trace_index": empty_frame(BETA_TRACE_INDEX_COLUMNS),
        "beta_density_data": pd.DataFrame(),
        "rxc_runtime_benchmark": pd.DataFrame(),
    }
    paths: dict[str, Path] = {}
    for name, frame in tables.items():
        csv_path = OUTPUT_DIR / f"{name}.csv"
        frame.to_csv(csv_path, index=False, encoding="utf-8-sig")
        paths[name] = csv_path
        if name in {
            "longitudinal_estimates",
            "commune_latent_summaries",
            "commune_beta_estimates",
            "beta_density_data",
            "density_marginal_data",
            "density_joint_data",
        }:
            parquet_path = OUTPUT_DIR / f"{name}.parquet"
            frame.to_parquet(parquet_path, index=False)
    return paths
