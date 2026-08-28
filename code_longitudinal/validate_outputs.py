from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .output_schema import (
    BETA_ESTIMATE_COLUMNS,
    BETA_TRACE_INDEX_COLUMNS,
    DIAGNOSTIC_COLUMNS,
    EXCLUSION_COLUMNS,
    LATENT_COLUMNS,
    LONGITUDINAL_COLUMNS,
    NLS_COEFFICIENT_COLUMNS,
    RESOURCE_GATE_COLUMNS,
)
from .paths import DOCS_DIR, FIGURE_DIR, OUTPUT_DIR, PANEL_DIR, REVIEW_DIR, ROOT, RUNS_DIR, ensure_runtime_dirs
from .prepare_inputs import validate_model_ready
from .run_pilot_ladder import MODELS as PILOT_MODELS, PILOT_SCENARIOS
from .spec_registry import ELECTIONS, SCENARIOS, SCENARIO_BY_ID, scenario_is_allowed
from .utils import write_json


class ValidationLog:
    def __init__(self) -> None:
        self.rows: list[dict[str, str]] = []

    def add(self, check: str, status: str, observed: Any, criterion: str, detail: str = "") -> None:
        self.rows.append(
            {
                "check": check,
                "status": status,
                "observed": str(observed),
                "criterion": criterion,
                "detail": detail,
            }
        )

    def require(self, check: str, condition: bool, observed: Any, criterion: str, detail: str = "") -> None:
        self.add(check, "pass" if condition else "fail", observed, criterion, detail)

    def warn(self, check: str, condition: bool, observed: Any, criterion: str, detail: str = "") -> None:
        self.add(check, "pass" if condition else "warning", observed, criterion, detail)

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows, columns=["check", "status", "observed", "criterion", "detail"])


def _read_csv(path: Path, **kwargs: Any) -> pd.DataFrame:
    if not path.exists() or not path.stat().st_size:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False, **kwargs)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _columns(log: ValidationLog, name: str, frame: pd.DataFrame, expected: list[str]) -> None:
    missing = [column for column in expected if column not in frame.columns]
    log.require(f"schema::{name}", not missing, missing or "none", "no required column missing")


def _finite_between(frame: pd.DataFrame, columns: list[str], lower: float, upper: float) -> bool:
    if frame.empty:
        return True
    values = frame.loc[:, [column for column in columns if column in frame]].apply(pd.to_numeric, errors="coerce")
    return bool(np.isfinite(values.to_numpy()).all() and values.ge(lower).all().all() and values.le(upper).all().all())


def _validate_panels(log: ValidationLog) -> None:
    main = _read_csv(PANEL_DIR / "panel_3000.csv", dtype={"unit_id": "string"})
    pilot = _read_csv(PANEL_DIR / "panel_2000.csv", dtype={"unit_id": "string"})
    log.require("panel::main_size", len(main) == 3000, len(main), "exactly 3000 rows")
    log.require("panel::pilot_size", len(pilot) == 2000, len(pilot), "exactly 2000 rows")
    log.require("panel::main_unique_ids", not main.get("unit_id", pd.Series(dtype=str)).duplicated().any(), len(main), "unit_id unique")
    log.require("panel::pilot_unique_ids", not pilot.get("unit_id", pd.Series(dtype=str)).duplicated().any(), len(pilot), "unit_id unique")
    if not main.empty and not pilot.empty and {"unit_id", "sample_rank"}.issubset(main) and {"unit_id", "sample_rank"}.issubset(pilot):
        expected = main.sort_values("sample_rank").head(2000)["unit_id"].astype(str).tolist()
        observed = pilot.sort_values("sample_rank")["unit_id"].astype(str).tolist()
        log.require("panel::nested", observed == expected, sum(a == b for a, b in zip(observed, expected)), "pilot equals first 2000 main-panel ranks")

    balance = _read_csv(PANEL_DIR / "panel_balance_checks.csv")
    continuous = balance.loc[balance.get("variable_type", pd.Series(dtype=str)).eq("continuous")]
    categorical = balance.loc[balance.get("variable_type", pd.Series(dtype=str)).eq("categorical")]
    max_smd = pd.to_numeric(continuous.get("standardized_mean_difference"), errors="coerce").abs().max()
    max_gap = pd.to_numeric(categorical.get("proportion_difference"), errors="coerce").abs().max()
    log.require("panel::balance_smd", bool(pd.notna(max_smd) and max_smd <= 0.10), max_smd, "max |SMD| <= 0.10")
    log.require("panel::balance_categories", bool(pd.notna(max_gap) and max_gap <= 0.02), max_gap, "max categorical gap <= 0.02")

    presence = _read_csv(PANEL_DIR / "panel_election_presence.csv", dtype={"unit_id": "string"})
    key = ["sample_id", "election_id", "unit_id"]
    log.require("presence::rows", len(presence) == 3000 * len(ELECTIONS), len(presence), f"3000 x {len(ELECTIONS)} rows")
    log.require("presence::unique_key", bool(set(key).issubset(presence) and not presence.duplicated(key).any()), int(presence.duplicated(key).sum()) if set(key).issubset(presence) else "missing columns", "unique sample/election/unit key")
    per_unit = presence.groupby("unit_id")["election_id"].nunique() if set(["unit_id", "election_id"]).issubset(presence) else pd.Series(dtype=int)
    log.require("presence::all_elections", bool(not per_unit.empty and per_unit.eq(len(ELECTIONS)).all()), int(per_unit.min()) if not per_unit.empty else 0, f"every panel unit has {len(ELECTIONS)} presence records")


def _validate_model_ready_tables(log: ValidationLog) -> None:
    paths = sorted((OUTPUT_DIR / "model_ready").glob("*.parquet"))
    failures: list[str] = []
    for path in paths:
        try:
            frame = pd.read_parquet(path)
            scenario_ids = frame["scenario_id"].dropna().astype(str).unique().tolist()
            if len(scenario_ids) != 1:
                raise AssertionError(f"scenario ids={scenario_ids}")
            validate_model_ready(frame, SCENARIO_BY_ID[scenario_ids[0]])
        except Exception as exc:  # every bad table must be reported, not stop the audit
            failures.append(f"{path.name}: {exc}")
    log.require("model_ready::partitions", bool(paths) and not failures, f"{len(paths)} tables; {len(failures)} invalid", "all cached model-ready tables close exactly", " | ".join(failures[:5]))


def _validate_consolidated(log: ValidationLog) -> None:
    estimates = _read_csv(OUTPUT_DIR / "longitudinal_estimates.csv")
    diagnostics = _read_csv(OUTPUT_DIR / "model_diagnostics.csv")
    latent = pd.read_parquet(OUTPUT_DIR / "commune_latent_summaries.parquet") if (OUTPUT_DIR / "commune_latent_summaries.parquet").exists() else pd.DataFrame()
    coefficients = _read_csv(OUTPUT_DIR / "nls_coefficients.csv")
    starts = _read_csv(OUTPUT_DIR / "nls_start_diagnostics.csv")
    marginal = _read_csv(OUTPUT_DIR / "density_marginal_data.csv")
    joint = _read_csv(OUTPUT_DIR / "density_joint_data.csv", dtype={"unit_id": "string"})
    exclusions = _read_csv(OUTPUT_DIR / "excluded_units.csv", dtype={"unit_id": "string"})
    gates = _read_csv(OUTPUT_DIR / "resource_ladder_gates.csv")
    beta = pd.read_parquet(OUTPUT_DIR / "commune_beta_estimates.parquet") if (OUTPUT_DIR / "commune_beta_estimates.parquet").exists() else pd.DataFrame()
    beta_traces = _read_csv(OUTPUT_DIR / "beta_trace_index.csv")
    beta_density = _read_csv(OUTPUT_DIR / "beta_density_data.csv")

    _columns(log, "longitudinal_estimates", estimates, LONGITUDINAL_COLUMNS)
    _columns(log, "model_diagnostics", diagnostics, DIAGNOSTIC_COLUMNS)
    _columns(log, "commune_latent_summaries", latent, LATENT_COLUMNS)
    _columns(log, "nls_coefficients", coefficients, NLS_COEFFICIENT_COLUMNS)
    _columns(log, "excluded_units", exclusions, EXCLUSION_COLUMNS)
    _columns(log, "resource_ladder_gates", gates, RESOURCE_GATE_COLUMNS)
    _columns(log, "commune_beta_estimates", beta, BETA_ESTIMATE_COLUMNS)
    _columns(log, "beta_trace_index", beta_traces, BETA_TRACE_INDEX_COLUMNS)

    estimate_key = ["run_id", "social_group", "vote_category", "covariate_name"]
    duplicate_estimates = int(estimates.duplicated(estimate_key).sum()) if set(estimate_key).issubset(estimates) else -1
    log.require("estimates::unique_key", duplicate_estimates == 0, duplicate_estimates, "unique run/social-group/vote-category/covariate key")
    log.require("estimates::bounded", _finite_between(estimates, ["estimate"], 0, 1), len(estimates), "finite estimates in [0,1]")
    interval_rows = estimates.loc[estimates.get("lower", pd.Series(dtype=float)).notna() | estimates.get("upper", pd.Series(dtype=float)).notna()].copy()
    if interval_rows.empty:
        intervals_valid = True
    else:
        lo = pd.to_numeric(interval_rows["lower"], errors="coerce")
        mid = pd.to_numeric(interval_rows["estimate"], errors="coerce")
        hi = pd.to_numeric(interval_rows["upper"], errors="coerce")
        intervals_valid = bool(np.isfinite(np.column_stack([lo, mid, hi])).all() and ((0 <= lo) & (lo <= mid) & (mid <= hi) & (hi <= 1)).all())
    log.require("estimates::interval_order", intervals_valid, len(interval_rows), "0 <= lower <= estimate <= upper <= 1 when intervals exist")

    latent_key = ["run_id", "unit_id"]
    duplicate_latent = int(latent.duplicated(latent_key).sum()) if set(latent_key).issubset(latent) else -1
    log.require("latent::unique_key", duplicate_latent == 0, duplicate_latent, "unique run/unit key")
    probability_columns = ["b1_mean", "b1_q025", "b1_q50", "b1_q975", "b2_mean", "b2_q025", "b2_q50", "b2_q975"]
    log.require("latent::bounded", _finite_between(latent, probability_columns, 0, 1), len(latent), "finite posterior summaries in [0,1]")
    if latent.empty:
        quantile_order = True
    else:
        b1 = latent[["b1_q025", "b1_q50", "b1_q975"]].apply(pd.to_numeric, errors="coerce")
        b2 = latent[["b2_q025", "b2_q50", "b2_q975"]].apply(pd.to_numeric, errors="coerce")
        quantile_order = bool((b1.iloc[:, 0] <= b1.iloc[:, 1]).all() and (b1.iloc[:, 1] <= b1.iloc[:, 2]).all() and (b2.iloc[:, 0] <= b2.iloc[:, 1]).all() and (b2.iloc[:, 1] <= b2.iloc[:, 2]).all())
    log.require("latent::quantile_order", quantile_order, len(latent), "q025 <= q50 <= q975")

    beta_key = ["run_id", "unit_id", "beta_parameter"]
    beta_duplicates = int(beta.duplicated(beta_key).sum()) if set(beta_key).issubset(beta) else -1
    log.require("beta::unique_commune_parameter", beta_duplicates == 0, beta_duplicates, "unique run/unit/beta key")
    log.require(
        "beta::bounded_estimates",
        _finite_between(beta, ["estimate", "q025", "q50", "q975"], 0, 1),
        len(beta),
        "commune beta estimates and quantiles in [0,1]",
    )
    beta_basis = set(beta.get("estimate_basis", pd.Series(dtype=str)).dropna().astype(str))
    log.require("beta::one_commune_one_observation", beta_basis == {"commune_posterior_mean"}, sorted(beta_basis), "density grain is the commune posterior mean")
    missing_trace_files = [
        str(path)
        for path in beta_traces.get("trace_path", pd.Series(dtype=str))
        if not (ROOT / str(path)).exists()
    ]
    log.require("beta::posterior_traces_retained", bool(not beta_traces.empty and not missing_trace_files), len(missing_trace_files), "every indexed b_1/b_2 NetCDF trace exists")

    if marginal.empty:
        density_valid = True
    else:
        grid = pd.to_numeric(marginal["grid_value"], errors="coerce")
        density = pd.to_numeric(marginal["density"], errors="coerce")
        density_valid = bool(np.isfinite(grid).all() and np.isfinite(density).all() and grid.between(0, 1).all() and density.ge(0).all())
    log.require("density::domain", density_valid, len(marginal), "finite grid in [0,1] and nonnegative density")
    beta_density_basis = set(beta_density.get("estimate_basis", pd.Series(dtype=str)).dropna().astype(str))
    log.require(
        "beta::density_export",
        bool(not beta_density.empty and beta_density_basis == {"density_of_commune_posterior_means"}),
        len(beta_density),
        "explicit beta density data exported from commune posterior means",
    )

    common = joint.loc[joint.get("comparison_scope", pd.Series(dtype=str)).eq("common_intersection")]
    intersection_failures: list[str] = []
    comparison_groups = ["sample_id", "election_id", "scenario_id"]
    if "comparison_key" in common:
        comparison_groups.append("comparison_key")
    for key, group in common.groupby(comparison_groups, dropna=False):
        sets = {model: set(part["unit_id"].astype(str)) for model, part in group.groupby("model_key")}
        if {"king_truncated_normal", "krt_beta_binomial"}.issubset(sets) and sets["king_truncated_normal"] != sets["krt_beta_binomial"]:
            intersection_failures.append(str(key))
    log.require("density::exact_common_intersection", not intersection_failures, len(intersection_failures), "King and KRT common views contain identical unit sets", ", ".join(intersection_failures[:5]))

    nls_counts = starts.groupby("run_id").size() if not starts.empty and "run_id" in starts else pd.Series(dtype=int)
    log.require("nls::twenty_starts", bool(not nls_counts.empty and nls_counts.eq(20).all()), sorted(nls_counts.unique().tolist()), "exactly 20 starts per NLS run")
    coefficient_values = pd.to_numeric(coefficients.get("estimate"), errors="coerce")
    log.require("nls::finite_coefficients", bool(coefficients.empty or np.isfinite(coefficient_values).all()), len(coefficients), "all fitted coefficients finite")

    required_exclusion_values = [
        "run_id",
        "run_key",
        "sample_id",
        "election_id",
        "scenario_id",
        "model_key",
        "unit_id",
        "stage",
        "reason",
    ]
    exclusion_complete = bool(
        exclusions.empty
        or exclusions.loc[:, required_exclusion_values].notna().all().all()
        and exclusions.loc[:, required_exclusion_values].astype(str).ne("").all().all()
    )
    log.require("exclusions::complete_keys", exclusion_complete, len(exclusions), "all exclusion keys, stage and reason populated")
    if gates.empty:
        gate_valid = True
    else:
        numeric = gates[
            [
                "current_n",
                "observed_peak_memory_mb",
                "available_memory_mb",
                "predicted_seconds",
                "predicted_peak_memory_mb",
                "memory_limit_mb",
            ]
        ].apply(pd.to_numeric, errors="coerce")
        terminal = gates.get("reason", pd.Series("", index=gates.index)).eq(
            "ladder_complete"
        )
        observed_valid = np.isfinite(
            numeric[["current_n", "observed_peak_memory_mb", "available_memory_mb"]]
        ).all(axis=1)
        prediction_valid = np.isfinite(
            numeric[["predicted_seconds", "predicted_peak_memory_mb", "memory_limit_mb"]]
        ).all(axis=1)
        gate_valid = bool((observed_valid & (terminal | prediction_valid)).all())
    log.require("ladder::time_and_memory_estimates", gate_valid, len(gates), "every recorded next-rung gate has finite time and memory estimates")

    failed_diagnostics = int(diagnostics.get("diagnostic_status", pd.Series(dtype=str)).eq("fail").sum())
    log.warn(
        "mcmc::substantive_diagnostics",
        failed_diagnostics == 0,
        failed_diagnostics,
        "no diagnostic failure for substantive interpretation",
        "Expected for calibration smoke tests (20 draws, one chain); these runs remain explicitly non-substantive.",
    )

    _validate_2022_snapshot(log, estimates, diagnostics)
    _validate_longitudinal_partitions_and_pilot(log)


def _validate_longitudinal_partitions_and_pilot(log: ValidationLog) -> None:
    integrity = _read_csv(OUTPUT_DIR / "all_elections_partition_integrity.csv")
    expected = sum(
        scenario_is_allowed(scenario, election)
        for election in ELECTIONS
        for scenario in SCENARIOS
    )
    unique = bool(
        {"election_id", "scenario_id"}.issubset(integrity)
        and not integrity.duplicated(["election_id", "scenario_id"]).any()
    )
    log.require(
        "partitions_1962_2022::complete_registry",
        len(integrity) == expected and unique,
        f"{len(integrity)}/{expected}",
        "one unique audit row for every admissible election/scenario partition",
    )

    valid_mask = integrity.get("valid", pd.Series(dtype=str)).astype(str).str.lower().eq("true")
    valid = integrity.loc[valid_mask].copy()
    gaps = valid.reindex(
        columns=[
            "maximum_social_share_gap",
            "maximum_social_count_gap",
            "maximum_vote_count_gap",
        ]
    ).apply(pd.to_numeric, errors="coerce")
    closures_valid = bool(
        not valid.empty
        and np.isfinite(gaps.to_numpy()).all()
        and gaps["maximum_social_share_gap"].le(1e-10).all()
        and gaps["maximum_social_count_gap"].eq(0).all()
        and gaps["maximum_vote_count_gap"].eq(0).all()
        and valid.get("no_duplicate_units", pd.Series(dtype=str)).astype(str).str.lower().eq("true").all()
        and valid.get("no_negative_values", pd.Series(dtype=str)).astype(str).str.lower().eq("true").all()
    )
    log.require(
        "partitions_1962_2022::materialized_closures",
        closures_valid,
        f"{len(valid)} valid materialized partitions",
        "all materialized tables have unique units, nonnegative values, shares summing to one and exact count closures",
    )

    failed = integrity.loc[~valid_mask]
    failed_pairs = failed[["election_id", "scenario_id"]].astype(str).agg("/".join, axis=1).tolist() if not failed.empty else []
    only_rxc = bool(
        failed.empty or failed["scenario_id"].isin(["RXC1", "RXC2"]).all()
    )
    log.require(
        "partitions_1962_2022::failure_traceability",
        bool(only_rxc and (failed.empty or failed["validation_error"].astype(str).ne("").all())),
        f"{len(failed)} rejected source partitions",
        "every non-materialized partition is an explicit RXC raw-margin failure with a recorded reason",
        ", ".join(failed_pairs[:8]),
    )
    log.warn(
        "partitions_1962_2022::full_rxc_source_coverage",
        failed.empty,
        f"{len(failed)} RXC partitions rejected",
        "all five-block source margins satisfy the absolute 0.01-vote tolerance",
        "No closure was forced for the rejected sources; see all_elections_partition_integrity.csv.",
    )

    pilot_elections = {"leg_1962_r1", "leg_1986_r1", "leg_2022_r1"}
    pilot = integrity.loc[integrity["election_id"].isin(pilot_elections)]
    log.require(
        "pilot_partitions::all_34_valid",
        len(pilot) == 34 and pilot.get("valid", pd.Series(dtype=str)).astype(str).str.lower().eq("true").all(),
        f"{int(pilot.get('valid', pd.Series(dtype=str)).astype(str).str.lower().eq('true').sum())}/34",
        "all admissible 1962/1986/2022 pilot partitions validate at requested n=3000",
    )

    coverage = _read_csv(OUTPUT_DIR / "pilot_model_coverage.csv")
    status_counts = coverage.get("coverage_status", pd.Series(dtype=str)).value_counts().to_dict()
    expected_pairs = sum(len(values) for values in PILOT_SCENARIOS.values()) * len(PILOT_MODELS)
    allowed_coverage_statuses = {
        "reached_n3000",
        "partial_resource_block",
        "structurally_inapplicable",
        "partial",
        "not_run",
    }
    coverage_valid = bool(
        len(coverage) == expected_pairs
        and set(status_counts).issubset(allowed_coverage_statuses)
        and pd.to_numeric(coverage.loc[coverage["coverage_status"].eq("reached_n3000"), "largest_successful_n_requested"], errors="coerce").eq(3000).all()
    )
    log.require(
        "pilot_mcmc::coverage_accounted",
        coverage_valid,
        status_counts,
        f"all {expected_pairs} extended-pilot model pairs explicitly accounted for, including incomplete and not-run pairs",
    )
    terminal_statuses = {
        "reached_n3000",
        "partial_resource_block",
        "structurally_inapplicable",
    }
    incomplete = coverage.loc[~coverage["coverage_status"].isin(terminal_statuses)]
    log.warn(
        "pilot_mcmc::extended_coverage_complete",
        incomplete.empty,
        f"{len(incomplete)}/{expected_pairs} incomplete or not run",
        "every extended-pilot model pair reaches n=3000 or a documented resource/structural terminal state",
        "The illustrated core pilot remains available; incomplete extension pairs are not presented as finished.",
    )

    selection = _read_csv(OUTPUT_DIR / "pilot_density_selection.csv")
    selected_scenarios = selection[["election_id", "scenario_id"]].drop_duplicates() if not selection.empty else pd.DataFrame()
    figures = list((FIGURE_DIR / "densities" / "curated").glob("*.svg"))
    expected_figure_names = {
        f"density_overlay__{election_id}__{scenario_id}__n{int(pd.to_numeric(group['n_communes_requested'], errors='coerce').max())}.svg"
        for (election_id, scenario_id), group in selection.groupby(["election_id", "scenario_id"])
    }
    actual_figure_names = {path.name for path in figures}
    log.require(
        "pilot_density::curated_largest_views",
        bool(
            len(selected_scenarios) == len(expected_figure_names)
            and actual_figure_names == expected_figure_names
        ),
        f"{len(selected_scenarios)} selections; {len(figures)} SVG",
        "one curated largest-common (or explicitly native-only) density overlay per selected election/scenario",
    )


def _validate_illustrated_report(log: ValidationLog) -> None:
    data = _read_csv(OUTPUT_DIR / "illustrated_report_estimates.csv")
    selection = _read_csv(OUTPUT_DIR / "pilot_density_selection.csv")
    pilot_elections = {"leg_1962_r1", "leg_1986_r1", "leg_2022_r1"}
    pilot_scenarios = {"H0A", "H1", "H5", "H6", "H7"}
    expected_selection = selection.loc[
        selection.get("election_id", pd.Series(dtype=str)).isin(pilot_elections)
        & selection.get("scenario_id", pd.Series(dtype=str)).isin(pilot_scenarios)
    ]
    key_columns = ["election_id", "scenario_id", "model_key", "beta_parameter"]
    required_columns = {
        *key_columns,
        "year",
        "run_id",
        "n_communes_selected",
        "mean_equal_commune",
        "p25_between_communes",
        "median_between_communes",
        "p75_between_communes",
        "diagnostic_status",
    }
    expected_rows = 2 * len(expected_selection)
    schema_valid = bool(
        required_columns.issubset(data.columns)
        and len(data) == expected_rows
        and not data.duplicated(key_columns).any()
        and set(data.get("election_id", pd.Series(dtype=str))) == pilot_elections
        and set(data.get("scenario_id", pd.Series(dtype=str))) == pilot_scenarios
    )
    log.require(
        "illustrated_report::table_schema_and_keys",
        schema_valid,
        f"{len(data)}/{expected_rows} rows",
        "two unique beta summaries for every selected pilot run across the three elections",
    )

    numeric = data.reindex(
        columns=[
            "mean_equal_commune",
            "p25_between_communes",
            "median_between_communes",
            "p75_between_communes",
            "mean_social_weighted",
        ]
    ).apply(pd.to_numeric, errors="coerce")
    values_valid = bool(
        not numeric.empty
        and np.isfinite(numeric.to_numpy()).all()
        and numeric.ge(0).all().all()
        and numeric.le(1).all().all()
        and numeric["p25_between_communes"].le(numeric["median_between_communes"]).all()
        and numeric["median_between_communes"].le(numeric["p75_between_communes"]).all()
    )
    log.require(
        "illustrated_report::beta_domain",
        values_valid,
        len(data),
        "all illustrated beta summaries are finite in [0,1] and quartiles are ordered",
    )

    report_path = DOCS_DIR / "RESULTS_ILLUSTRATED_1962_1986_2022.md"
    report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    comparison_figures = [
        FIGURE_DIR / "illustrated_report" / f"comparison_interannuelle__{scenario_id}.svg"
        for scenario_id in ("H0A", "H1", "H5", "H6", "H7")
    ]
    expected_curated = []
    for (election_id, scenario_id), group in expected_selection.groupby(
        ["election_id", "scenario_id"]
    ):
        n_requested = int(pd.to_numeric(group["n_communes_requested"], errors="coerce").max())
        expected_curated.append(
            FIGURE_DIR
            / "densities"
            / "curated"
            / f"density_overlay__{election_id}__{scenario_id}__n{n_requested}.svg"
        )
    image_refs = report_text.count("![")
    artifact_valid = bool(
        report_path.exists()
        and all(path.exists() for path in comparison_figures)
        and len(expected_curated) == 13
        and all(path.exists() for path in expected_curated)
        and image_refs == 18
    )
    log.require(
        "illustrated_report::embedded_figures",
        artifact_valid,
        f"{image_refs} Markdown images; {len(comparison_figures)} comparisons; {len(expected_curated)} target densities",
        "one Markdown report embeds five interannual comparisons and thirteen curated density figures",
    )


def _validate_professor_global_recap(log: ValidationLog) -> None:
    data = _read_csv(OUTPUT_DIR / "professor_canonical_comparisons.csv")
    selection = _read_csv(OUTPUT_DIR / "pilot_density_selection.csv")
    elections = {"leg_1962_r1", "leg_1986_r1", "leg_2022_r1"}
    scenarios = {"H0A", "H0B", "H0C", "H1", "H2", "H3", "H4", "H5"}
    expected_selection = selection.loc[
        selection.get("election_id", pd.Series(dtype=str)).isin(elections)
        & selection.get("scenario_id", pd.Series(dtype=str)).isin(scenarios)
    ]
    key_columns = ["election_id", "scenario_id", "model_key", "beta_parameter"]
    required_columns = {
        *key_columns,
        "year",
        "run_id",
        "n_communes_selected",
        "mean_equal_commune",
        "p25_between_communes",
        "median_between_communes",
        "p75_between_communes",
        "diagnostic_status",
    }
    expected_rows = 2 * len(expected_selection)
    schema_valid = bool(
        required_columns.issubset(data.columns)
        and len(data) == expected_rows
        and not data.duplicated(key_columns).any()
        and set(data.get("election_id", pd.Series(dtype=str))) == elections
        and set(data.get("scenario_id", pd.Series(dtype=str))) == scenarios
    )
    log.require(
        "professor_recap::table_schema_and_keys",
        schema_valid,
        f"{len(data)}/{expected_rows} rows",
        "two unique beta summaries for every selected canonical run across the three elections",
    )

    numeric = data.reindex(
        columns=[
            "mean_equal_commune",
            "p25_between_communes",
            "median_between_communes",
            "p75_between_communes",
            "mean_social_weighted",
        ]
    ).apply(pd.to_numeric, errors="coerce")
    values_valid = bool(
        not numeric.empty
        and np.isfinite(numeric.to_numpy()).all()
        and numeric.ge(0).all().all()
        and numeric.le(1).all().all()
        and numeric["p25_between_communes"].le(numeric["median_between_communes"]).all()
        and numeric["median_between_communes"].le(numeric["p75_between_communes"]).all()
    )
    log.require(
        "professor_recap::beta_domain",
        values_valid,
        len(data),
        "all canonical beta summaries are finite in [0,1] and quartiles are ordered",
    )

    report_path = DOCS_DIR / "PROFESSOR_GLOBAL_RECAP_1962_1986_2022.md"
    report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    image_references = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", report_text)
    missing_references = [
        reference
        for reference in image_references
        if not (report_path.parent / reference).resolve().is_file()
    ]
    comparison_figures = [
        FIGURE_DIR / "professor_recap" / f"comparison_interannuelle__{scenario_id}.svg"
        for scenario_id in sorted(scenarios)
    ]
    figures_valid = bool(
        report_path.exists()
        and len(image_references) == 16
        and not missing_references
        and all(path.exists() and path.stat().st_size > 0 for path in comparison_figures)
    )
    log.require(
        "professor_recap::embedded_figures",
        figures_valid,
        f"{len(image_references)} Markdown images; {len(missing_references)} missing; {len(comparison_figures)} canonical SVG",
        "the global report embeds eight canonical comparisons and eight documented examples with no broken link",
        ", ".join(missing_references[:5]),
    )


def _validate_2022_snapshot(
    log: ValidationLog, estimates: pd.DataFrame, diagnostics: pd.DataFrame
) -> None:
    """Validate the full 3,000-commune preparation and available 2022 fits."""
    integrity = _read_csv(OUTPUT_DIR / "election_2022_input_integrity.csv")
    expected_2x2 = {"H0A", "H0B", "H0C", "H1", "H2", "H3", "H4", "H5", "H6", "H7"}
    present_2x2 = set(integrity.get("scenario_id", pd.Series(dtype=str)).astype(str))
    numerical = integrity.reindex(
        columns=[
            "n_rows",
            "n_unique_units",
            "n_duplicate_units",
            "maximum_social_count_gap",
            "maximum_vote_count_gap",
        ]
    ).apply(pd.to_numeric, errors="coerce")
    prepared_valid = bool(
        present_2x2 == expected_2x2
        and len(integrity) == len(expected_2x2)
        and np.isfinite(numerical.to_numpy()).all()
        and numerical["n_rows"].eq(3000).all()
        and numerical["n_unique_units"].eq(3000).all()
        and numerical["n_duplicate_units"].eq(0).all()
        and numerical["maximum_social_count_gap"].eq(0).all()
        and numerical["maximum_vote_count_gap"].eq(0).all()
    )
    log.require(
        "snapshot_2022::all_2x2_inputs_n3000",
        prepared_valid,
        f"{len(integrity)}/10 scenarios",
        "ten 2x2 scenarios, 3000 unique communes, exact social and political closures",
    )

    n_requested = pd.to_numeric(estimates.get("n_communes_requested"), errors="coerce")
    nls = estimates.loc[
        estimates.get("election_id", pd.Series(dtype=str)).eq("leg_2022_r1")
        & estimates.get("scenario_id", pd.Series(dtype=str)).isin(["RXC1", "RXC2"])
        & estimates.get("model_key", pd.Series(dtype=str)).eq("rosen_nls")
        & n_requested.eq(3000)
        & estimates.get("diagnostic_status", pd.Series(dtype=str)).eq("pass")
    ].copy()
    complete_nls: set[str] = set()
    for (scenario_id, run_id), part in nls.groupby(["scenario_id", "run_id"]):
        expected_rows = len(SCENARIO_BY_ID[str(scenario_id)].social_groups) * len(
            SCENARIO_BY_ID[str(scenario_id)].vote_categories
        )
        sums = part.groupby("social_group")["estimate"].sum()
        if len(part) == expected_rows and len(sums) == len(SCENARIO_BY_ID[str(scenario_id)].social_groups) and np.allclose(sums, 1, atol=1e-10):
            complete_nls.add(str(scenario_id))
    log.require(
        "snapshot_2022::rxc_nls_n3000",
        complete_nls == {"RXC1", "RXC2"},
        sorted(complete_nls),
        "RXC1 and RXC2 have complete diagnostic-pass probability matrices whose rows sum to one",
    )

    quality = _read_csv(OUTPUT_DIR / "election_2022_fit_quality.csv")
    metric_columns = ["rmse", "mae", "max_absolute_error", "observed_mean", "predicted_mean"]
    metric_values = quality.reindex(columns=metric_columns).apply(pd.to_numeric, errors="coerce")
    quality_valid = bool(
        len(quality) == 10
        and set(quality.get("scenario_id", pd.Series(dtype=str))) == {"RXC1", "RXC2"}
        and np.isfinite(metric_values.to_numpy()).all()
        and metric_values.ge(0).all().all()
        and metric_values.le(1).all().all()
    )
    log.require(
        "snapshot_2022::fit_quality",
        quality_valid,
        len(quality),
        "five finite [0,1] margin-fit metrics for each of RXC1 and RXC2",
    )

    required_figures = [
        FIGURE_DIR / "election_2022" / "input_margins__all_2x2_scenarios.svg",
        *[
            FIGURE_DIR / "election_2022" / f"{stem}__{scenario_id}.svg"
            for scenario_id in ("RXC1", "RXC2")
            for stem in ("nls_probability_matrix", "nls_composition", "nls_observed_vs_predicted")
        ],
    ]
    missing_figures = [path.name for path in required_figures if not path.exists() or path.stat().st_size == 0]
    log.require(
        "snapshot_2022::figures",
        not missing_figures,
        missing_figures or f"{len(required_figures)} SVG",
        "all required 2022 single-election figures exist and are non-empty",
    )

    diag_n = pd.to_numeric(diagnostics.get("n_communes_requested"), errors="coerce")
    draws = pd.to_numeric(diagnostics.get("draws"), errors="coerce")
    chains = pd.to_numeric(diagnostics.get("chains"), errors="coerce")
    production = diagnostics.loc[
        diagnostics.get("election_id", pd.Series(dtype=str)).eq("leg_2022_r1")
        & diagnostics.get("scenario_id", pd.Series(dtype=str)).isin(expected_2x2)
        & diag_n.eq(3000)
        & draws.ge(1000)
        & chains.eq(4)
        & diagnostics.get("diagnostic_status", pd.Series(dtype=str)).eq("pass")
    ]
    covered = production[["scenario_id", "model_key"]].drop_duplicates() if not production.empty else pd.DataFrame()
    log.warn(
        "snapshot_2022::pyei_production_coverage",
        len(covered) == 20,
        f"{len(covered)}/20 scenario-model pairs",
        "King and KRT production n=3000 pass for all ten 2x2 scenarios",
        "The resource ladder and the 12-hour/80%-memory guards remain binding; missing pairs are not silently replaced by smoke tests.",
    )


def _validate_registry_and_review(log: ValidationLog) -> None:
    executed = _read_csv(OUTPUT_DIR / "run_registry_executed.csv", dtype={"run_id": "string"})
    public = _read_csv(OUTPUT_DIR / "run_registry.csv", dtype={"run_id": "string"})
    log.require("registry::executed_unique_run_id", bool(not executed.empty and not executed["run_id"].duplicated().any()), int(executed.get("run_id", pd.Series(dtype=str)).duplicated().sum()), "execution run_id unique")
    missing_dirs = [run_id for run_id in executed.get("run_id", pd.Series(dtype=str)).dropna() if not (RUNS_DIR / str(run_id)).is_dir()]
    log.require("registry::run_directories", not missing_dirs, len(missing_dirs), "every executed run has an immutable directory", ", ".join(missing_dirs[:5]))
    statuses = set(public.get("status", pd.Series(dtype=str)).dropna().astype(str))
    log.require("registry::planned_and_executed", "planned" in statuses and bool(statuses & {"success", "failed"}), sorted(statuses), "public registry includes planned and executed states")

    required = [
        REVIEW_DIR / "panel" / "panel_3000.csv",
        REVIEW_DIR / "panel" / "panel_election_presence.csv",
        REVIEW_DIR / "table_extracts" / "longitudinal_estimates__first50.csv",
        REVIEW_DIR / "table_extracts" / "illustrated_report_estimates__first50.csv",
        REVIEW_DIR / "docs" / "RESULTS_ILLUSTRATED_1962_1986_2022.md",
        REVIEW_DIR / "docs" / "PROFESSOR_GLOBAL_RECAP_1962_1986_2022.md",
        REVIEW_DIR / "table_extracts" / "professor_canonical_comparisons__first50.csv",
        REVIEW_DIR / "figures" / "illustrated_report" / "comparison_interannuelle__H0A.svg",
        REVIEW_DIR / "figures" / "professor_recap" / "comparison_interannuelle__H0A.svg",
        REVIEW_DIR / "README.md",
    ]
    missing = [str(path.relative_to(REVIEW_DIR)) for path in required if not path.exists()]
    log.require("review_package::required_files", not missing, missing or "none", "core professor-review files present")


def _render_report(checks: pd.DataFrame, summary: dict[str, Any]) -> str:
    failed = checks.loc[checks["status"].eq("fail")]
    warned = checks.loc[checks["status"].eq("warning")]
    lines = [
        "# Rapport de validation longitudinale",
        "",
        f"Validation générée le `{summary['generated_at_utc']}`.",
        "",
        f"**Verdict : {summary['overall_status']}** — {summary['passed']} contrôles réussis, "
        f"{summary['warnings']} avertissement(s), {summary['failed']} échec(s).",
        "",
        "Les avertissements MCMC des calibrations 20/20/1 sont attendus, y compris lorsque le palier demandé atteint 3 000 : ils qualifient le pipeline et le coût du calcul, pas des résultats substantiels. Le NLS 2022 à 3 000 communes est validé séparément.",
        "",
        "## Contrôles non réussis",
        "",
    ]
    if failed.empty and warned.empty:
        lines.append("Aucun.")
    else:
        for row in pd.concat([failed, warned]).itertuples(index=False):
            lines.append(f"- `{row.status}` — **{row.check}** : observé `{row.observed}` ; attendu : {row.criterion}. {row.detail}".rstrip())
    lines.extend(
        [
            "",
            "## Portée",
            "",
            "Le contrôle couvre les tailles et l'emboîtement des panels, la balance, le registre de présence des 26 scrutins, la fermeture exacte des partitions préparées, les schémas consolidés, les clés uniques, les bornes et quantiles latents, les intersections King/KRT, les 20 départs NLS et la traçabilité des runs.",
            "",
            "Le détail machine-lisible se trouve dans `outputs/validation_checks.csv` et `outputs/validation_summary.json`.",
        ]
    )
    return "\n".join(lines) + "\n"


def validate_outputs() -> dict[str, Any]:
    ensure_runtime_dirs()
    log = ValidationLog()
    _validate_panels(log)
    _validate_model_ready_tables(log)
    _validate_consolidated(log)
    _validate_illustrated_report(log)
    _validate_professor_global_recap(log)
    _validate_registry_and_review(log)
    checks = log.frame()
    checks.to_csv(OUTPUT_DIR / "validation_checks.csv", index=False, encoding="utf-8-sig")
    counts = checks["status"].value_counts()
    failed = int(counts.get("fail", 0))
    warnings = int(counts.get("warning", 0))
    summary: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "overall_status": "fail" if failed else ("pass_with_warnings" if warnings else "pass"),
        "passed": int(counts.get("pass", 0)),
        "warnings": warnings,
        "failed": failed,
        "checks": int(len(checks)),
    }
    write_json(OUTPUT_DIR / "validation_summary.json", summary)
    (DOCS_DIR / "VALIDATION_REPORT.md").write_text(_render_report(checks, summary), encoding="utf-8")
    return summary
