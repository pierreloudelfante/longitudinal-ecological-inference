from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .build_panel import load_settings
from .nls import NLSData, aggregate_probabilities, fit_nls, probabilities, sandwich_standard_errors, unpack_params
from .output_schema import EXCLUSION_COLUMNS, LONGITUDINAL_COLUMNS, NLS_COEFFICIENT_COLUMNS
from .paths import CONFIG_DIR, ROOT
from .prepare_inputs import model_ready_path, n_columns, prepare_model_ready, x_columns, y_columns
from .run_registry import begin_run, finish_run
from .spec_registry import HARMONIZATION_VERSION, SPEC_VERSION, ElectionSpec, ScenarioSpec
from .utils import file_sha256, portable_path


def _diagnostic_status(success: bool, rank: int, n_parameters: int, condition: float) -> str:
    if not success or not np.isfinite(condition) or condition > 1e12:
        return "fail"
    if rank < n_parameters or condition > 1e8:
        return "warning"
    return "pass"


def run_nls(
    election: ElectionSpec,
    scenario: ScenarioSpec,
    *,
    sample_size: int = 3000,
    covariate_name: str | None = None,
    force: bool = False,
    panel_path: Path | None = None,
    settings_path: Path | None = None,
) -> dict[str, object]:
    if scenario.model_family == "2x2":
        model_key = "rosen_nls_covariate" if covariate_name else "rosen_nls_2x2_unadjusted"
    else:
        model_key = "rosen_nls"
    settings_path = settings_path or CONFIG_DIR / "run_settings.json"
    settings = load_settings(settings_path)
    frame, prep_exclusions, prep_manifest = prepare_model_ready(
        election,
        scenario,
        sample_size=sample_size,
        panel_path=panel_path,
        settings_path=settings_path,
    )
    sample_id = str(frame["sample_id"].iloc[0])
    panel_id = str(frame["panel_id"].iloc[0]) if "panel_id" in frame else sample_id
    input_path = model_ready_path(election, scenario, sample_id, sample_size=sample_size)
    parameters = {
        "election_id": election.election_id,
        "scenario_id": scenario.scenario_id,
        "model_key": model_key,
        "sample_size": sample_size,
        "covariate_name": covariate_name or "",
        "nls": settings["nls"],
        "panel_id": panel_id,
        "spec_version": SPEC_VERSION,
        "harmonization_version": HARMONIZATION_VERSION,
    }
    if panel_path is not None:
        parameters["panel_path"] = portable_path(panel_path, root=ROOT)
        parameters["panel_sha256"] = file_sha256(panel_path)
    stage = "nls-longitudinal" if panel_id.startswith(SPEC_VERSION) else "rxc-nls"
    handle = begin_run(stage=stage, parameters=parameters, input_paths=[input_path, settings_path], force=force)
    if handle is None:
        return {"status": "skipped_existing_success", **parameters}
    started = time.perf_counter()
    try:
        dropped_covariate = pd.DataFrame()
        z_mean = np.array([], dtype=float)
        z_scale = np.array([], dtype=float)
        if covariate_name:
            if covariate_name not in frame:
                raise ValueError(f"missing covariate {covariate_name}")
            raw = pd.to_numeric(frame[covariate_name], errors="coerce")
            dropped_covariate = frame.loc[raw.isna(), ["unit_id", "sample_rank"]].copy()
            fit_frame = frame.loc[raw.notna()].copy()
            z_raw = pd.to_numeric(fit_frame[covariate_name], errors="raise").to_numpy()[:, None]
            z_mean = z_raw.mean(axis=0)
            z_scale = z_raw.std(axis=0, ddof=0)
            z_scale = np.where(z_scale > 0, z_scale, 1.0)
            z = (z_raw - z_mean) / z_scale
        else:
            fit_frame = frame.copy()
            z = np.empty((len(fit_frame), 0), dtype=float)
        x = fit_frame.loc[:, list(x_columns(scenario))].to_numpy(dtype=float)
        n = fit_frame["N_g"].to_numpy(dtype=float)
        y = fit_frame.loc[:, list(y_columns(scenario))].to_numpy(dtype=float)
        t = y / n[:, None]
        data = NLSData(x=x, t=t, n=n, z=z)
        nls_settings = settings["nls"]
        best, starts = fit_nls(
            data,
            n_starts=int(nls_settings["n_starts"]),
            start_scale=float(nls_settings["start_scale"]),
            n_start_strata=int(nls_settings["n_start_strata"]),
            max_nfev=int(nls_settings["max_nfev"]),
            tolerance=float(nls_settings["tolerance"]),
            random_seed=int(nls_settings["random_seed"]),
        )
        pi, fitted = probabilities(best.x, x, z, t.shape[1])
        aggregates = aggregate_probabilities(x, n, pi)
        standard_errors, sandwich = sandwich_standard_errors(best.x, data)
        elapsed = time.perf_counter() - started
        condition = float(sandwich["bread_condition"])
        rank = int(sandwich["bread_rank"])
        diagnostic_status = _diagnostic_status(bool(best.success), rank, int(best.x.size), condition)

        estimate_rows: list[dict[str, object]] = []
        for r, group in enumerate(scenario.social_groups):
            for c, vote in enumerate(scenario.vote_categories):
                estimate_rows.append(
                    {
                        "run_id": handle.run_id,
                        "run_key": handle.run_key,
                        "sample_id": sample_id,
                        "election_id": election.election_id,
                        "election_type": election.election_type,
                        "year": election.year,
                        "round": election.round,
                        "scenario_id": scenario.scenario_id,
                        "model_key": model_key,
                        "model_family": scenario.model_family,
                        "with_covariate": bool(covariate_name),
                        "covariate_name": covariate_name or "",
                        "social_group": group,
                        "vote_category": vote,
                        "estimate": float(aggregates[r, c]),
                        "lower": np.nan,
                        "upper": np.nan,
                        "n_communes_requested": sample_size,
                        "n_communes_used": len(fit_frame),
                        "N_total": int(n.sum()),
                        "elapsed_seconds": elapsed,
                        "fit_status": "success" if best.success else "warning",
                        "diagnostic_status": diagnostic_status,
                        "random_seed": int(nls_settings["random_seed"]),
                    }
                )
        estimates = pd.DataFrame(estimate_rows, columns=LONGITUDINAL_COLUMNS)

        terms = ("alpha", covariate_name) if covariate_name else ("alpha",)
        coef = unpack_params(best.x, x.shape[1], t.shape[1], len(terms))
        coef_se = unpack_params(standard_errors, x.shape[1], t.shape[1], len(terms))
        coefficient_rows: list[dict[str, object]] = []
        for r, group in enumerate(scenario.social_groups):
            for c, vote in enumerate(scenario.vote_categories[:-1]):
                for p, term in enumerate(terms):
                    coefficient_rows.append(
                        {
                            "run_id": handle.run_id,
                            "run_key": handle.run_key,
                            "sample_id": sample_id,
                            "election_id": election.election_id,
                            "scenario_id": scenario.scenario_id,
                            "model_key": model_key,
                            "covariate_name": covariate_name or "",
                            "social_group": group,
                            "vote_category": vote,
                            "reference_vote_category": scenario.vote_categories[-1],
                            "term": term,
                            "estimate": float(coef[r, c, p]),
                            "std_error": float(coef_se[r, c, p]),
                        }
                    )
        coefficients = pd.DataFrame(coefficient_rows, columns=NLS_COEFFICIENT_COLUMNS)
        start_diagnostics = pd.DataFrame(starts)
        start_diagnostics.insert(0, "run_id", handle.run_id)
        start_diagnostics.insert(1, "run_key", handle.run_key)
        start_diagnostics.insert(2, "election_id", election.election_id)
        start_diagnostics.insert(3, "scenario_id", scenario.scenario_id)
        start_diagnostics.insert(4, "covariate_name", covariate_name or "")
        diagnostics = pd.DataFrame(
            [
                {
                    "run_id": handle.run_id,
                    "run_key": handle.run_key,
                    "sample_id": sample_id,
                    "election_id": election.election_id,
                    "scenario_id": scenario.scenario_id,
                    "model_key": model_key,
                    "n_communes_requested": sample_size,
                    "n_communes_used": len(fit_frame),
                    "elapsed_seconds": elapsed,
                    "objective_sse_unweighted": float(np.sum((t[:, :-1] - fitted[:, :-1]) ** 2)),
                    "optimizer_success": bool(best.success),
                    "optimizer_status": int(best.status),
                    "optimizer_message": str(best.message),
                    "nfev": int(best.nfev),
                    "optimality": float(best.optimality),
                    "n_parameters": int(best.x.size),
                    "n_starts": len(starts),
                    "n_successful_starts": int(sum(bool(row["success"]) for row in starts)),
                    "covariate_mean": float(z_mean[0]) if z_mean.size else np.nan,
                    "covariate_scale": float(z_scale[0]) if z_scale.size else np.nan,
                    "fit_status": "success" if best.success else "warning",
                    "diagnostic_status": diagnostic_status,
                    **sandwich,
                }
            ]
        )
        estimates.to_csv(handle.run_dir / "longitudinal_estimates.csv", index=False, encoding="utf-8-sig")
        coefficients.to_csv(handle.run_dir / "nls_coefficients.csv", index=False, encoding="utf-8-sig")
        start_diagnostics.to_csv(handle.run_dir / "nls_start_diagnostics.csv", index=False, encoding="utf-8-sig")
        diagnostics.to_csv(handle.run_dir / "model_diagnostics.csv", index=False, encoding="utf-8-sig")
        prepared_exclusions = prep_exclusions.rename(columns={"exclusion_reason": "reason"}).copy()
        if not prepared_exclusions.empty:
            prepared_exclusions["stage"] = "prepare_inputs"
        if not dropped_covariate.empty:
            dropped_covariate["reason"] = f"missing_covariate:{covariate_name}"
            dropped_covariate["stage"] = "covariate_filter"
        exclusions = pd.concat([prepared_exclusions, dropped_covariate], ignore_index=True, sort=False)
        if not exclusions.empty:
            exclusions["run_id"] = handle.run_id
            exclusions["run_key"] = handle.run_key
            exclusions["sample_id"] = sample_id
            exclusions["election_id"] = election.election_id
            exclusions["scenario_id"] = scenario.scenario_id
            exclusions["model_key"] = model_key
            exclusions.reindex(columns=EXCLUSION_COLUMNS).to_csv(
                handle.run_dir / "excluded_units.csv", index=False, encoding="utf-8-sig"
            )
        metadata = {
            "election_id": election.election_id,
            "scenario_id": scenario.scenario_id,
            "model_key": model_key,
            "sample_id": sample_id,
            "panel_id": panel_id,
            "panel_sha256": parameters.get("panel_sha256", ""),
            "spec_version": SPEC_VERSION,
            "harmonization_version": HARMONIZATION_VERSION,
            "n_communes_requested": sample_size,
            "n_communes_used": len(fit_frame),
            "diagnostic_status": diagnostic_status,
            "elapsed_seconds": elapsed,
            "preparation_manifest": prep_manifest,
            "nls_estimand": (
                "intercept-only group-conditional probabilities fitted by unweighted nonlinear least squares "
                "to commune ecological margins, then aggregated with group-specific population counts"
                if scenario.model_family == "2x2" and not covariate_name
                else "group-conditional probabilities from the configured Rosen NLS specification"
            ),
        }
        finish_run(handle, status="success", metadata=metadata)
        return {"status": "success", "run_id": handle.run_id, **metadata}
    except Exception as exc:
        finish_run(
            handle,
            status="failed",
            metadata={
                "election_id": election.election_id,
                "scenario_id": scenario.scenario_id,
                "model_key": model_key,
                "sample_id": sample_id,
                "n_communes_requested": sample_size,
                "n_communes_used": 0,
                "diagnostic_status": "fail",
            },
            error=str(exc),
        )
        raise
