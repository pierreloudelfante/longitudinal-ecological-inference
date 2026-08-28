from __future__ import annotations

import ctypes
import json
import os
import time
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .build_panel import load_settings
from .diagnostics_v2 import audit_trace, summary_row
from .identification_v2 import assess_identification
from .output_schema import DIAGNOSTIC_COLUMNS, EXCLUSION_COLUMNS, LATENT_COLUMNS, LONGITUDINAL_COLUMNS, RESOURCE_GATE_COLUMNS
from .paths import CONFIG_DIR, OUTPUT_DIR, ROOT, RUNS_DIR, ensure_runtime_dirs
from .prepare_inputs import model_ready_path, n_columns, prepare_model_ready, x_columns, y_columns
from .postprocess_aggregates_v2 import aggregate_krt_draws_v2, summarize_krt_aggregates_v2
from .run_registry import begin_run, finish_run
from .spec_registry import HARMONIZATION_VERSION, SPEC_VERSION, ElectionSpec, ScenarioSpec
from .utils import file_sha256, portable_path, write_json


PY_EI_MODEL = {"king_truncated_normal": "truncated_normal", "krt_beta_binomial": "king99"}


def stable_vote_fractions(counts: np.ndarray, totals: np.ndarray) -> np.ndarray:
    """Fractions whose PyEI ``fraction * total`` round trip truncates exactly.

    PyEI reconstructs integer Binomial observations from a floating fraction.
    Ordinary division can land one ULP below the original integer. Moving only
    interior fractions one representable value upward prevents a one-vote loss
    while leaving the statistical value unchanged at machine precision.
    """

    count_values = np.asarray(counts, dtype=np.int64)
    total_values = np.asarray(totals, dtype=np.int64)
    if count_values.shape != total_values.shape:
        raise ValueError("counts and totals must have the same shape")
    if np.any(total_values <= 0) or np.any(count_values < 0) or np.any(count_values > total_values):
        raise ValueError("counts must satisfy 0 <= counts <= totals with positive totals")
    fractions = count_values.astype(float) / total_values.astype(float)
    interior = (count_values > 0) & (count_values < total_values)
    fractions[interior] = np.nextafter(fractions[interior], np.inf)
    reconstructed = np.floor(fractions * total_values).astype(np.int64)
    if not np.array_equal(reconstructed, count_values):
        raise AssertionError("stable vote-fraction round trip failed")
    return fractions


def filter_truncated_normal_rows(
    df: pd.DataFrame,
    scenario: ScenarioSpec,
    *,
    tolerance: float = 1e-9,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    x = df[x_columns(scenario)[0]].astype(float)
    y = df[y_columns(scenario)[0]].astype(float) / df["N_g"].astype(float)
    valid = x.gt(tolerance) & x.lt(1 - tolerance) & y.gt(tolerance) & y.lt(1 - tolerance)
    interior = valid.copy()
    if valid.any():
        xv = x.loc[valid].to_numpy()
        yv = y.loc[valid].to_numpy()
        b1_lower = np.maximum(0.0, (yv - 1.0 + xv) / xv)
        b1_upper = np.minimum(1.0, yv / xv)
        b2_lower = np.maximum(0.0, (yv - xv) / (1.0 - xv))
        b2_upper = np.minimum(1.0, yv / (1.0 - xv))
        width = np.maximum(b1_upper - b1_lower, b2_upper - b2_lower)
        interior.loc[valid] = width > tolerance
    excluded = df.loc[~interior, ["unit_id", "sample_rank"]].copy()
    excluded["reason"] = "degenerate_tomography_row_for_truncated_normal"
    return df.loc[interior].copy(), excluded


def _flatten_dataset(dataset: Any) -> np.ndarray:
    if dataset is None:
        return np.array([], dtype=float)
    arrays = [np.asarray(dataset[name].values, dtype=float).ravel() for name in dataset.data_vars]
    return np.concatenate(arrays) if arrays else np.array([], dtype=float)


def sampler_diagnostics(trace: Any) -> dict[str, object]:
    result: dict[str, object] = {
        "mcmc_divergences": np.nan,
        "mcmc_divergence_fraction": np.nan,
        "mcmc_max_rhat": np.nan,
        "mcmc_min_ess_bulk": np.nan,
        "mcmc_min_ess_tail": np.nan,
        "mcmc_chains_saved": np.nan,
        "mcmc_draws_saved": np.nan,
        "mcmc_diagnostic_error": "",
    }
    if trace is None or not hasattr(trace, "posterior"):
        return result
    try:
        import arviz as az

        posterior = trace.posterior
        chains = int(posterior.sizes.get("chain", 0))
        draws = int(posterior.sizes.get("draw", 0))
        result["mcmc_chains_saved"] = chains
        result["mcmc_draws_saved"] = draws
        stats = getattr(trace, "sample_stats", None)
        if stats is not None and "diverging" in stats:
            divergences = int(np.asarray(stats["diverging"].values).sum())
            result["mcmc_divergences"] = divergences
            result["mcmc_divergence_fraction"] = divergences / max(chains * draws, 1)
        variables = [name for name in ("b_1", "b_2") if name in posterior.data_vars]
        if not variables:
            variables = list(posterior.data_vars)
        if chains >= 2 and variables:
            values = _flatten_dataset(az.rhat(trace, var_names=variables))
            finite = values[np.isfinite(values)]
            result["mcmc_max_rhat"] = float(finite.max()) if finite.size else np.nan
        if variables:
            bulk = _flatten_dataset(az.ess(trace, var_names=variables, method="bulk"))
            tail = _flatten_dataset(az.ess(trace, var_names=variables, method="tail"))
            bulk = bulk[np.isfinite(bulk)]
            tail = tail[np.isfinite(tail)]
            result["mcmc_min_ess_bulk"] = float(bulk.min()) if bulk.size else np.nan
            result["mcmc_min_ess_tail"] = float(tail.min()) if tail.size else np.nan
    except Exception as exc:
        result["mcmc_diagnostic_error"] = str(exc)
    return result


def diagnostic_status(diagnostics: dict[str, object], settings: dict[str, object]) -> str:
    def finite(name: str) -> float | None:
        value = diagnostics.get(name)
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if np.isfinite(number) else None

    divergence_fraction = finite("mcmc_divergence_fraction")
    rhat = finite("mcmc_max_rhat")
    ess_bulk = finite("mcmc_min_ess_bulk")
    ess_tail = finite("mcmc_min_ess_tail")
    saved_chains = finite("mcmc_chains_saved")
    ess = min(value for value in (ess_bulk, ess_tail) if value is not None) if any(value is not None for value in (ess_bulk, ess_tail)) else None
    if (
        (divergence_fraction is not None and divergence_fraction > float(settings["fail_divergence_fraction"]))
        or (rhat is not None and rhat > float(settings["fail_rhat"]))
        or (ess is not None and ess < float(settings["fail_ess"]))
    ):
        return "fail"
    if (
        (divergence_fraction is not None and divergence_fraction > 0)
        or (rhat is not None and rhat > float(settings["warning_rhat"]))
        or (ess is not None and ess < float(settings["warning_ess"]))
        or saved_chains is None
        or saved_chains < 2
    ):
        return "warning"
    return "pass"


def extract_latent_summaries(
    trace: Any,
    fit_frame: pd.DataFrame,
    scenario: ScenarioSpec,
    *,
    run_id: str,
    run_key: str,
    model_key: str,
) -> pd.DataFrame:
    posterior = trace.posterior
    samples: dict[str, np.ndarray] = {}
    for name in ("b_1", "b_2"):
        if name not in posterior:
            raise ValueError(f"posterior variable {name} is missing")
        samples[name] = posterior[name].stack(all_draws=["chain", "draw"]).values.T
        if samples[name].shape[1] != len(fit_frame):
            raise ValueError(f"{name} has {samples[name].shape[1]} precincts, expected {len(fit_frame)}")
    rows = pd.DataFrame(
        {
            "run_id": run_id,
            "run_key": run_key,
            "sample_id": fit_frame["sample_id"].astype(str).to_numpy(),
            "election_id": fit_frame["election_id"].astype(str).to_numpy(),
            "scenario_id": fit_frame["scenario_id"].astype(str).to_numpy(),
            "model_key": model_key,
            "unit_id": fit_frame["unit_id"].astype(str).to_numpy(),
            "sample_rank": fit_frame["sample_rank"].astype(int).to_numpy(),
            "b1_weight": fit_frame[n_columns(scenario)[0]].astype(float).to_numpy(),
            "b2_weight": fit_frame[n_columns(scenario)[1]].astype(float).to_numpy(),
        }
    )
    for name, prefix in (("b_1", "b1"), ("b_2", "b2")):
        values = samples[name]
        rows[f"{prefix}_mean"] = values.mean(axis=0)
        rows[f"{prefix}_sd"] = values.std(axis=0, ddof=1)
        rows[f"{prefix}_q025"] = np.quantile(values, 0.025, axis=0)
        rows[f"{prefix}_q50"] = np.quantile(values, 0.50, axis=0)
        rows[f"{prefix}_q975"] = np.quantile(values, 0.975, axis=0)
    return rows.loc[:, LATENT_COLUMNS]


def _rss_mb() -> float:
    try:
        import psutil

        return float(psutil.Process().memory_info().rss / (1024**2))
    except ImportError:
        pass
    if os.name == "nt":
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        )
        if ok:
            return float(counters.WorkingSetSize / (1024**2))
    return float("nan")


def _peak_rss_mb() -> float:
    if os.name == "nt":
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        )
        if ok:
            return float(counters.PeakWorkingSetSize / (1024**2))
    return _rss_mb()


def _available_memory_mb() -> float:
    try:
        import psutil

        return float(psutil.virtual_memory().available / (1024**2))
    except ImportError:
        pass
    if os.name == "nt":
        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return float(status.ullAvailPhys / (1024**2))
    return float("nan")


def _preflight_ladder_gate(
    election: ElectionSpec,
    scenario: ScenarioSpec,
    model_key: str,
    *,
    sample_size: int,
    draws: int,
    tune: int,
    chains: int,
    cores: int,
    settings: dict[str, object],
) -> dict[str, object]:
    ladder = [int(value) for value in settings["mcmc"]["ladder"]]
    if sample_size not in ladder:
        raise ValueError(f"sample_size must be one of the configured ladder rungs: {ladder}")
    position = ladder.index(sample_size)
    if position == 0:
        return {"allowed": True, "reason": "initial_ladder_rung", "current_n": None, "next_n": sample_size}
    prior_n = ladder[position - 1]
    candidates: list[dict[str, object]] = []
    for path in RUNS_DIR.glob("*/manifest.json"):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        parameters = manifest.get("parameters", {})
        if not isinstance(parameters, dict):
            continue
        if (
            manifest.get("status") == "success"
            and parameters.get("election_id") == election.election_id
            and parameters.get("scenario_id") == scenario.scenario_id
            and parameters.get("model_key") == model_key
            and int(parameters.get("sample_size", -1)) == prior_n
        ):
            candidates.append(manifest)
    if not candidates:
        raise RuntimeError(
            f"ladder gate blocked: no successful {prior_n}-commune run for "
            f"{election.election_id}/{scenario.scenario_id}/{model_key}"
        )
    previous = max(candidates, key=lambda item: str(item.get("finished_at_utc", "")))
    previous_parameters = previous["parameters"]
    previous_work = max(
        (int(previous_parameters.get("draws", 1)) + int(previous_parameters.get("tune", 0)))
        * int(previous_parameters.get("chains", 1)),
        1,
    )
    requested_work = max((draws + tune) * chains, 1)
    workload_scale = requested_work / previous_work
    elapsed = float(previous.get("elapsed_seconds", np.nan)) * workload_scale
    peak_memory = float(previous.get("peak_memory_mb", np.nan))
    memory_method = "previous_run_process_peak"
    if not np.isfinite(peak_memory):
        # Old pilot manifests predate native peak-memory collection. A 1 GiB
        # floor is deliberately conservative for the first comparable rung.
        measured_peak = _peak_rss_mb()
        peak_memory = max(measured_peak, 1024.0) if np.isfinite(measured_peak) else 1024.0
        memory_method = "conservative_1gb_floor_for_legacy_run"
    # Sequential chains do not multiply peak resident memory. Scale by the
    # number of chains that can actually run concurrently, not by the total
    # chain count requested for the fit.
    previous_chains = max(int(previous_parameters.get("chains", 1)), 1)
    previous_cores = max(int(previous_parameters.get("cores", 1)), 1)
    previous_concurrency = min(previous_chains, previous_cores)
    requested_concurrency = min(max(chains, 1), max(cores, 1))
    peak_memory *= max(requested_concurrency / previous_concurrency, 1.0)
    gate = next_ladder_gate(
        prior_n,
        elapsed,
        settings,
        peak_memory_mb=peak_memory,
        available_memory_mb=_available_memory_mb(),
    )
    # The PyMC process has a large fixed import/compilation footprint. Scaling
    # the *entire* RSS linearly from n=25 therefore grossly overstates the next
    # rung. When comparable fits already exist, use their observed upper
    # envelope at the requested (or a larger) n, plus a 10% safety margin.
    # This is still checked against the configured 80% share of currently
    # available physical memory; it is an empirical estimate, not a bypass.
    empirical_peaks: list[float] = []
    comparable_peaks: list[float] = []
    for path in RUNS_DIR.glob("*/manifest.json"):
        try:
            comparable = json.loads(path.read_text(encoding="utf-8"))
            comparable_parameters = comparable.get("parameters", {})
            comparable_peak = float(comparable.get("peak_memory_mb", np.nan))
            if (
                comparable.get("status") == "success"
                and isinstance(comparable_parameters, dict)
                and comparable_parameters.get("model_key") == model_key
                and int(comparable_parameters.get("sample_size", -1)) >= sample_size
                and int(comparable_parameters.get("chains", -1)) == chains
                and np.isfinite(comparable_peak)
                and comparable_peak > 0
            ):
                comparable_chains = max(int(comparable_parameters.get("chains", 1)), 1)
                comparable_cores = max(int(comparable_parameters.get("cores", 1)), 1)
                comparable_concurrency = min(comparable_chains, comparable_cores)
                comparable_peaks.append(
                    comparable_peak * max(requested_concurrency / comparable_concurrency, 1.0)
                )
            if (
                comparable.get("status") == "success"
                and isinstance(comparable_parameters, dict)
                and comparable_parameters.get("model_key") == model_key
                and int(comparable_parameters.get("sample_size", -1)) >= sample_size
                and int(comparable_parameters.get("draws", -1)) == draws
                and int(comparable_parameters.get("tune", -1)) == tune
                and int(comparable_parameters.get("chains", -1)) == chains
                and np.isfinite(comparable_peak)
                and comparable_peak > 0
            ):
                empirical_peaks.append(comparable_peak)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
    if empirical_peaks or comparable_peaks:
        empirical_prediction = max(empirical_peaks or comparable_peaks) * 1.10
        memory_limit = float(gate["memory_limit_mb"])
        allowed_memory = bool(
            np.isfinite(empirical_prediction)
            and np.isfinite(memory_limit)
            and empirical_prediction <= memory_limit
        )
        gate["predicted_peak_memory_mb"] = empirical_prediction
        gate["allowed_memory"] = allowed_memory
        gate["allowed"] = bool(gate["allowed_time"] and allowed_memory)
        gate["memory_estimate_method"] = (
            "empirical_same_workload_upper_envelope_plus_10pct"
            if empirical_peaks
            else "empirical_same_model_concurrency_scaled_upper_envelope_plus_10pct"
        )
        if not gate["allowed_time"]:
            gate["reason"] = "predicted_time_exceeds_budget"
        elif not allowed_memory:
            gate["reason"] = "predicted_memory_exceeds_budget"
        else:
            gate["reason"] = "within_time_and_memory_budget"
    else:
        gate["memory_estimate_method"] = memory_method
    row = {
        "run_id": "",
        "run_key": "",
        "election_id": election.election_id,
        "scenario_id": scenario.scenario_id,
        "model_key": model_key,
        "current_n": prior_n,
        "elapsed_seconds": elapsed,
        **gate,
    }
    preflight_path = OUTPUT_DIR / "resource_ladder_preflight.csv"
    previous_rows = pd.read_csv(preflight_path) if preflight_path.exists() and preflight_path.stat().st_size else pd.DataFrame()
    key_columns = ["election_id", "scenario_id", "model_key", "current_n", "next_n"]
    combined = pd.concat([previous_rows, pd.DataFrame([row])], ignore_index=True, sort=False)
    combined = combined.drop_duplicates(key_columns, keep="last")
    combined.to_csv(preflight_path, index=False, encoding="utf-8-sig")
    if not gate["allowed"]:
        raise RuntimeError(
            f"ladder gate blocked {election.election_id}/{scenario.scenario_id}/{model_key} "
            f"at n={sample_size}: {gate['reason']}"
        )
    return row


def run_2x2(
    election: ElectionSpec,
    scenario: ScenarioSpec,
    model_key: str,
    *,
    sample_size: int,
    draws: int,
    tune: int,
    chains: int,
    cores: int = 1,
    target_accept: float = 0.99,
    max_treedepth: int = 10,
    sampler_backend: str = "numpyro",
    king_lambda: float | None = None,
    krt_parameterization_version: str = "",
    random_seed: int = 20260802,
    force: bool = False,
    progressbar: bool = False,
    panel_path: Path | None = None,
    skip_preflight: bool = False,
    preflight_override_reason: str = "",
    settings_path: Path | None = None,
    diagnostic_only_allow_transversal_order_violations: bool = False,
    run_metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    ensure_runtime_dirs()
    if scenario.model_family != "2x2" or model_key not in PY_EI_MODEL:
        raise ValueError("invalid 2x2 scenario/model")
    if sampler_backend not in {"numpyro", "pymc"}:
        raise ValueError(f"unsupported sampler backend: {sampler_backend}")
    settings_path = settings_path or CONFIG_DIR / "run_settings.json"
    settings = load_settings(settings_path)
    effective_king_lambda = (
        float(king_lambda)
        if king_lambda is not None
        else float(settings["mcmc"]["king_lambda"])
    )
    if model_key == "krt_beta_binomial" and (
        not np.isfinite(effective_king_lambda) or effective_king_lambda <= 0
    ):
        raise ValueError("king_lambda must be finite and positive")
    effective_parameterization_version = (
        krt_parameterization_version.strip()
        or "legacy_unversioned_pyei_king99"
    )
    if skip_preflight:
        if not preflight_override_reason.strip():
            raise ValueError("skip_preflight requires a non-empty preflight_override_reason")
    else:
        _preflight_ladder_gate(
            election,
            scenario,
            model_key,
            sample_size=sample_size,
            draws=draws,
            tune=tune,
            chains=chains,
            cores=cores,
            settings=settings,
        )
    frame, prep_exclusions, prep_manifest = prepare_model_ready(
        election,
        scenario,
        sample_size=sample_size,
        panel_path=panel_path,
        settings_path=settings_path,
        diagnostic_only_allow_transversal_order_violations=diagnostic_only_allow_transversal_order_violations,
    )
    sample_id = str(frame["sample_id"].iloc[0])
    panel_id = str(frame["panel_id"].iloc[0]) if "panel_id" in frame else sample_id
    input_path = model_ready_path(election, scenario, sample_id, sample_size=sample_size)
    parameters = {
        "election_id": election.election_id,
        "scenario_id": scenario.scenario_id,
        "model_key": model_key,
        "sample_size": sample_size,
        "draws": draws,
        "tune": tune,
        "chains": chains,
        "cores": cores,
        "target_accept": target_accept,
        "max_treedepth": max_treedepth,
        "sampler_backend": sampler_backend,
        "random_seed": random_seed,
        "panel_id": panel_id,
        "spec_version": SPEC_VERSION,
        "harmonization_version": HARMONIZATION_VERSION,
        "king_lambda": effective_king_lambda if model_key == "krt_beta_binomial" else None,
        "king_lambda_source": (
            "release_scope" if king_lambda is not None else "run_settings_legacy_fallback"
        ) if model_key == "krt_beta_binomial" else None,
        "krt_parameterization_version": (
            effective_parameterization_version if model_key == "krt_beta_binomial" else None
        ),
        "diagnostic_only_allow_transversal_order_violations": bool(
            diagnostic_only_allow_transversal_order_violations
        ),
    }
    if panel_path is not None:
        parameters["panel_path"] = portable_path(panel_path, root=ROOT)
        parameters["panel_sha256"] = file_sha256(panel_path)
    if skip_preflight:
        parameters["preflight_override_reason"] = preflight_override_reason.strip()
    if run_metadata:
        protected = sorted(set(parameters).intersection(run_metadata))
        if protected:
            raise ValueError(f"run_metadata cannot override core parameters: {protected}")
        parameters.update({str(key): value for key, value in run_metadata.items()})
    handle = begin_run(stage="2x2", parameters=parameters, input_paths=[input_path, settings_path], force=force)
    if handle is None:
        return {"status": "skipped_existing_success", **parameters}
    started = time.perf_counter()
    memory_before = _rss_mb()
    try:
        fit_frame = frame.copy()
        model_exclusions = pd.DataFrame()
        if model_key == "king_truncated_normal":
            fit_frame, model_exclusions = filter_truncated_normal_rows(fit_frame, scenario)
        if fit_frame.empty:
            raise ValueError("no rows left after model-specific filtering")
        from pyei.two_by_two import TwoByTwoEI

        x = fit_frame[x_columns(scenario)[0]].astype(float).to_numpy()
        n = fit_frame["N_g"].astype(int).to_numpy()
        y_counts = fit_frame[y_columns(scenario)[0]].astype(int).to_numpy()
        y = (
            stable_vote_fractions(y_counts, n)
            if model_key == "krt_beta_binomial"
            else y_counts.astype(float) / n.astype(float)
        )
        identification = assess_identification(x, y)
        write_json(handle.run_dir / "identification_diagnostics.json", identification)
        pd.DataFrame([{key: value for key, value in identification.items() if key != "design_singular_values"}]).to_csv(
            handle.run_dir / "identification_diagnostics.csv", index=False, encoding="utf-8-sig"
        )
        kwargs = {"lmbda": effective_king_lambda} if model_key == "krt_beta_binomial" else {}
        model = TwoByTwoEI(PY_EI_MODEL[model_key], **kwargs)
        sampler_options = {
            "nuts": {
                "max_tree_depth" if sampler_backend == "numpyro" else "max_treedepth": max_treedepth
            }
        }
        fit_kwargs = {
            "demographic_group_name": list(scenario.social_groups)[0],
            "candidate_name": scenario.vote_categories[0],
            "precinct_names": fit_frame["unit_id"].astype(str).tolist(),
            "target_accept": target_accept,
            "tune": tune,
            "draws": draws,
            "chains": chains,
            "cores": cores,
            "random_seed": random_seed,
            "progressbar": progressbar,
            **sampler_options,
        }
        if model_key == "krt_beta_binomial" and sampler_backend == "pymc":
            # PyEI hard-codes NumPyro for King99. Replace only the sampler
            # dispatcher while PyEI builds and post-processes the same model.
            import pyei.two_by_two as two_by_two_module

            original_sample = two_by_two_module.pm.sample

            def sample_with_pymc(*args: object, **sample_kwargs: object) -> object:
                if sample_kwargs.get("nuts_sampler") == "numpyro":
                    sample_kwargs["nuts_sampler"] = "pymc"
                return original_sample(*args, **sample_kwargs)

            two_by_two_module.pm.sample = sample_with_pymc
            try:
                model.fit(x, y, n, **fit_kwargs)
            finally:
                two_by_two_module.pm.sample = original_sample
        else:
            model.fit(x, y, n, **fit_kwargs)
        elapsed = time.perf_counter() - started
        memory_after = _rss_mb()
        peak_memory = _peak_rss_mb()
        if not np.isfinite(peak_memory):
            peak_memory = max(value for value in (memory_before, memory_after) if np.isfinite(value)) if any(
                np.isfinite(value) for value in (memory_before, memory_after)
            ) else np.nan
        trace = model.sim_trace
        trace.to_netcdf(handle.run_dir / "trace.nc")
        latent = extract_latent_summaries(
            trace, fit_frame, scenario, run_id=handle.run_id, run_key=handle.run_key, model_key=model_key
        )
        latent.to_parquet(handle.run_dir / "commune_latent_summaries.parquet", index=False)
        latent.to_csv(handle.run_dir / "commune_latent_summaries.csv", index=False, encoding="utf-8-sig")

        aggregate_draws = aggregate_krt_draws_v2(
            trace,
            fit_frame[n_columns(scenario)[0]].astype(float).to_numpy(),
            fit_frame[n_columns(scenario)[1]].astype(float).to_numpy(),
            total_weights=fit_frame["N_g"].astype(float).to_numpy(),
            include_contrast=True,
        )
        aggregate_summary = summarize_krt_aggregates_v2(aggregate_draws)
        aggregate_summary.insert(0, "run_id", handle.run_id)
        aggregate_summary.insert(1, "election_id", election.election_id)
        aggregate_summary.insert(2, "scenario_id", scenario.scenario_id)
        aggregate_summary.insert(3, "model_key", model_key)
        aggregate_summary.to_csv(
            handle.run_dir / "aggregate_comparison_v2.csv", index=False, encoding="utf-8-sig"
        )
        corrected = aggregate_summary.loc[
            aggregate_summary["aggregation_method"].eq("group_specific_population_v2")
        ].set_index("beta_parameter")
        means = np.array(
            [corrected.loc["b_1", "mean"], corrected.loc["b_2", "mean"]], dtype=float
        )
        intervals = np.array(
            [
                [corrected.loc["b_1", "q025"], corrected.loc["b_1", "q975"]],
                [corrected.loc["b_2", "q025"], corrected.loc["b_2", "q975"]],
            ],
            dtype=float,
        )
        estimate_rows: list[dict[str, object]] = []
        canonical_audit = audit_trace(
            trace,
            fit_status="success",
            identification_status=str(identification["identification_status"]),
            expected_chains=chains,
            expected_draws_per_chain=draws,
            max_treedepth=max_treedepth,
        )
        diag_status = str(canonical_audit["mcmc_status"])
        write_json(handle.run_dir / "mcmc_diagnostics_v2.json", canonical_audit)
        pd.DataFrame(canonical_audit["variable_metrics"]).to_csv(
            handle.run_dir / "mcmc_variable_metrics_v2.csv", index=False, encoding="utf-8-sig"
        )
        pd.DataFrame(canonical_audit["block_metrics"]).to_csv(
            handle.run_dir / "mcmc_block_metrics_v2.csv", index=False, encoding="utf-8-sig"
        )
        diagnostics = {
            "mcmc_divergences": canonical_audit["divergences"],
            "mcmc_divergence_fraction": canonical_audit["divergence_fraction"],
            "mcmc_max_rhat": canonical_audit["max_rhat"],
            "mcmc_min_ess_bulk": canonical_audit["min_ess_bulk"],
            "mcmc_min_ess_tail": canonical_audit["min_ess_tail"],
            "mcmc_chains_saved": canonical_audit["saved_chains"],
            "mcmc_draws_saved": canonical_audit["saved_draws_per_chain"],
            "mcmc_diagnostic_error": "",
        }
        gate = next_ladder_gate(
            sample_size,
            elapsed,
            settings,
            peak_memory_mb=peak_memory,
            available_memory_mb=_available_memory_mb(),
        )
        gate["memory_estimate_method"] = "observed_process_peak"
        gate_row = {
            "run_id": handle.run_id,
            "run_key": handle.run_key,
            "election_id": election.election_id,
            "scenario_id": scenario.scenario_id,
            "model_key": model_key,
            "current_n": sample_size,
            "elapsed_seconds": elapsed,
            **gate,
        }
        pd.DataFrame([gate_row]).reindex(columns=RESOURCE_GATE_COLUMNS).to_csv(
            handle.run_dir / "resource_ladder_gate.csv", index=False, encoding="utf-8-sig"
        )
        write_json(handle.run_dir / "resource_ladder_gate.json", gate_row)
        for group_index, group in enumerate(scenario.social_groups):
            target_estimate = float(means[group_index])
            lower, upper = map(float, intervals[group_index])
            for vote, estimate, lo, hi in (
                (scenario.vote_categories[0], target_estimate, lower, upper),
                (scenario.vote_categories[1], 1 - target_estimate, 1 - upper, 1 - lower),
            ):
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
                        "model_family": "2x2",
                        "with_covariate": False,
                        "covariate_name": "",
                        "social_group": group,
                        "vote_category": vote,
                        "estimate": estimate,
                        "lower": lo,
                        "upper": hi,
                        "n_communes_requested": sample_size,
                        "n_communes_used": len(fit_frame),
                        "N_total": int(n.sum()),
                        "elapsed_seconds": elapsed,
                        "fit_status": "success",
                        "diagnostic_status": diag_status,
                        "random_seed": random_seed,
                    }
                )
        estimates = pd.DataFrame(estimate_rows, columns=LONGITUDINAL_COLUMNS)
        estimates.to_csv(handle.run_dir / "longitudinal_estimates.csv", index=False, encoding="utf-8-sig")
        diagnostic_row = {
            "run_id": handle.run_id,
            "run_key": handle.run_key,
            "sample_id": sample_id,
            "panel_id": panel_id,
            "election_id": election.election_id,
            "scenario_id": scenario.scenario_id,
            "model_key": model_key,
            "draws": draws,
            "tune": tune,
            "chains": chains,
            "target_accept": target_accept,
            "n_communes_requested": sample_size,
            "n_communes_used": len(fit_frame),
            "dropped_degenerate_rows": len(model_exclusions),
            "elapsed_seconds": elapsed,
            "peak_memory_mb": peak_memory,
            "fit_status": "success",
            "diagnostic_status": diag_status,
            "error": "",
            **diagnostics,
        }
        pd.DataFrame([diagnostic_row]).reindex(columns=DIAGNOSTIC_COLUMNS).to_csv(
            handle.run_dir / "model_diagnostics.csv", index=False, encoding="utf-8-sig"
        )
        exclusions = pd.concat(
            [
                prep_exclusions.rename(columns={"exclusion_reason": "reason"}),
                model_exclusions,
            ],
            ignore_index=True,
        )
        if not exclusions.empty:
            exclusions["run_id"] = handle.run_id
            exclusions["run_key"] = handle.run_key
            exclusions["sample_id"] = sample_id
            exclusions["election_id"] = election.election_id
            exclusions["scenario_id"] = scenario.scenario_id
            exclusions["model_key"] = model_key
            exclusions["stage"] = np.where(
                exclusions["reason"].eq("degenerate_tomography_row_for_truncated_normal"), "model_filter", "prepare_inputs"
            )
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
            "diagnostic_status": diag_status,
            "elapsed_seconds": elapsed,
            "peak_memory_mb": peak_memory,
            "next_ladder_gate": gate,
            "preparation_manifest": prep_manifest,
            "identification_diagnostic": identification,
            "aggregate_estimand": {
                "version": "2",
                "group_1": "sum_i(N1_i*b1_i)/sum_i(N1_i)",
                "group_2": "sum_i(N2_i*b2_i)/sum_i(N2_i)",
                "audit_comparison": "aggregate_comparison_v2.csv",
            },
            "observed_count_roundtrip": (
                "interior vote fractions moved upward by one ULP and verified by floor(fraction*N)==Y"
                if model_key == "krt_beta_binomial"
                else "not_applicable_to_truncated_normal"
            ),
            "canonical_mcmc_diagnostic": summary_row(canonical_audit),
            "preflight_overridden": skip_preflight,
            "preflight_override_reason": preflight_override_reason.strip() if skip_preflight else "",
        }
        if run_metadata:
            metadata["run_metadata"] = {str(key): value for key, value in run_metadata.items()}
        finish_run(handle, status="success", metadata=metadata)
        return {"status": "success", "run_id": handle.run_id, **metadata}
    except Exception as exc:
        elapsed = time.perf_counter() - started
        pd.DataFrame(
            [
                {
                    "run_id": handle.run_id,
                    "run_key": handle.run_key,
                    "sample_id": sample_id,
                    "election_id": election.election_id,
                    "scenario_id": scenario.scenario_id,
                    "model_key": model_key,
                    "draws": draws,
                    "tune": tune,
                    "chains": chains,
                    "target_accept": target_accept,
                    "n_communes_requested": sample_size,
                    "n_communes_used": 0,
                    "elapsed_seconds": elapsed,
                    "fit_status": "failed",
                    "diagnostic_status": "fail",
                    "error": str(exc),
                }
            ]
        ).reindex(columns=DIAGNOSTIC_COLUMNS).to_csv(handle.run_dir / "model_diagnostics.csv", index=False, encoding="utf-8-sig")
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
                "elapsed_seconds": elapsed,
            },
            error=str(exc),
        )
        raise


def next_ladder_gate(
    current_n: int,
    elapsed_seconds: float,
    settings: dict[str, object],
    *,
    peak_memory_mb: float | None = None,
    available_memory_mb: float | None = None,
) -> dict[str, object]:
    ladder = [int(value) for value in settings["mcmc"]["ladder"]]
    next_values = [value for value in ladder if value > current_n]
    if not next_values:
        return {
            "next_n": None,
            "predicted_seconds": np.nan,
            "observed_peak_memory_mb": peak_memory_mb,
            "memory_estimate_method": "observed_process_peak",
            "predicted_peak_memory_mb": np.nan,
            "available_memory_mb": available_memory_mb,
            "memory_limit_mb": np.nan,
            "allowed_time": False,
            "allowed_memory": False,
            "allowed": False,
            "reason": "ladder_complete",
        }
    next_n = next_values[0]
    predicted_seconds = elapsed_seconds * next_n / current_n
    observed_peak = float(peak_memory_mb) if peak_memory_mb is not None else _peak_rss_mb()
    available = float(available_memory_mb) if available_memory_mb is not None else _available_memory_mb()
    predicted_peak = observed_peak * next_n / current_n if np.isfinite(observed_peak) else np.nan
    memory_limit = available * float(settings["mcmc"]["max_memory_fraction"]) if np.isfinite(available) else np.nan
    allowed_time = predicted_seconds <= float(settings["mcmc"]["max_estimated_hours_per_fit"]) * 3600
    allowed_memory = bool(np.isfinite(predicted_peak) and np.isfinite(memory_limit) and predicted_peak <= memory_limit)
    allowed = bool(allowed_time and allowed_memory)
    if not allowed_time:
        reason = "predicted_time_exceeds_budget"
    elif not np.isfinite(predicted_peak) or not np.isfinite(memory_limit):
        reason = "memory_estimate_unavailable"
    elif not allowed_memory:
        reason = "predicted_memory_exceeds_budget"
    else:
        reason = "within_time_and_memory_budget"
    return {
        "next_n": next_n,
        "predicted_seconds": predicted_seconds,
        "observed_peak_memory_mb": observed_peak,
        "memory_estimate_method": "observed_process_peak",
        "predicted_peak_memory_mb": predicted_peak,
        "available_memory_mb": available,
        "memory_limit_mb": memory_limit,
        "allowed_time": bool(allowed_time),
        "allowed_memory": allowed_memory,
        "allowed": allowed,
        "reason": reason,
    }
