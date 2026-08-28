from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

from .build_panel import load_settings
from .output_schema import LONGITUDINAL_COLUMNS
from .paths import CONFIG_DIR, ensure_runtime_dirs
from .prepare_inputs import model_ready_path, prepare_model_ready, x_columns, y_columns
from .run_2x2_batch import _rss_mb, diagnostic_status, sampler_diagnostics
from .run_registry import begin_run, finish_run
from .spec_registry import ElectionSpec, ScenarioSpec


def run_rosen_benchmark(
    election: ElectionSpec,
    scenario: ScenarioSpec,
    *,
    sample_size: int,
    draws: int,
    tune: int,
    chains: int,
    cores: int = 1,
    target_accept: float = 0.99,
    random_seed: int = 20260802,
    force: bool = False,
    progressbar: bool = False,
    settings_path: Path | None = None,
) -> dict[str, object]:
    ensure_runtime_dirs()
    if scenario.scenario_id != "RXC1":
        raise ValueError("Rosen benchmark is gated to RXC1 until RXC1 succeeds")
    settings_path = settings_path or CONFIG_DIR / "run_settings.json"
    settings = load_settings(settings_path)
    frame, _, prep_manifest = prepare_model_ready(election, scenario, sample_size=sample_size, settings_path=settings_path)
    sample_id = str(frame["sample_id"].iloc[0])
    input_path = model_ready_path(election, scenario, sample_id, sample_size=sample_size)
    parameters = {
        "election_id": election.election_id,
        "scenario_id": scenario.scenario_id,
        "model_key": "rosen_multinomial_dirichlet",
        "sample_size": sample_size,
        "draws": draws,
        "tune": tune,
        "chains": chains,
        "cores": cores,
        "target_accept": target_accept,
        "random_seed": random_seed,
    }
    handle = begin_run(stage="rxc-rosen-benchmark", parameters=parameters, input_paths=[input_path, settings_path], force=force)
    if handle is None:
        return {"status": "skipped_existing_success", **parameters}
    started = time.perf_counter()
    try:
        from pyei import RowByColumnEI

        group_fractions = frame.loc[:, list(x_columns(scenario))].to_numpy(dtype=float).T
        vote_counts = frame.loc[:, list(y_columns(scenario))].to_numpy(dtype=float)
        populations = frame["N_g"].to_numpy(dtype=int)
        vote_fractions = (vote_counts / populations[:, None]).T
        model = RowByColumnEI("multinomial-dirichlet")
        model.fit(
            group_fractions,
            vote_fractions,
            populations,
            demographic_group_names=list(scenario.social_groups),
            candidate_names=list(scenario.vote_categories),
            precinct_names=frame["unit_id"].astype(str).tolist(),
            target_accept=target_accept,
            tune=tune,
            draws=draws,
            chains=chains,
            cores=cores,
            random_seed=random_seed,
            progressbar=progressbar,
        )
        elapsed = time.perf_counter() - started
        trace = model.sim_trace
        trace.to_netcdf(handle.run_dir / "trace.nc")
        diagnostics = sampler_diagnostics(trace)
        diag_status = diagnostic_status(diagnostics, settings["mcmc"])
        means = np.asarray(model.posterior_mean_voting_prefs, dtype=float)
        intervals = np.asarray(model.credible_interval_95_mean_voting_prefs, dtype=float)
        rows: list[dict[str, object]] = []
        for r, group in enumerate(scenario.social_groups):
            for c, vote in enumerate(scenario.vote_categories):
                rows.append(
                    {
                        "run_id": handle.run_id,
                        "run_key": handle.run_key,
                        "sample_id": sample_id,
                        "election_id": election.election_id,
                        "election_type": election.election_type,
                        "year": election.year,
                        "round": election.round,
                        "scenario_id": scenario.scenario_id,
                        "model_key": "rosen_multinomial_dirichlet",
                        "model_family": "rxc",
                        "with_covariate": False,
                        "covariate_name": "",
                        "social_group": group,
                        "vote_category": vote,
                        "estimate": float(means[r, c]),
                        "lower": float(intervals[r, c, 0]),
                        "upper": float(intervals[r, c, 1]),
                        "n_communes_requested": sample_size,
                        "n_communes_used": len(frame),
                        "N_total": int(populations.sum()),
                        "elapsed_seconds": elapsed,
                        "fit_status": "success",
                        "diagnostic_status": diag_status,
                        "random_seed": random_seed,
                    }
                )
        pd.DataFrame(rows, columns=LONGITUDINAL_COLUMNS).to_csv(
            handle.run_dir / "longitudinal_estimates.csv", index=False, encoding="utf-8-sig"
        )
        benchmark = {
            "run_id": handle.run_id,
            "scenario": scenario.scenario_id,
            "year": election.year,
            "election_id": election.election_id,
            "model": "rosen_multinomial_dirichlet",
            "number_groups": len(scenario.social_groups),
            "number_votes": len(scenario.vote_categories),
            "number_communes": len(frame),
            "draws": draws,
            "tune": tune,
            "chains": chains,
            "elapsed_seconds": elapsed,
            "peak_memory_mb": _rss_mb(),
            "diagnostic_status": diag_status,
            **diagnostics,
        }
        pd.DataFrame([benchmark]).to_csv(handle.run_dir / "rxc_runtime_benchmark.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame([benchmark]).to_csv(handle.run_dir / "model_diagnostics.csv", index=False, encoding="utf-8-sig")
        metadata = {
            "election_id": election.election_id,
            "scenario_id": scenario.scenario_id,
            "model_key": "rosen_multinomial_dirichlet",
            "sample_id": sample_id,
            "n_communes_requested": sample_size,
            "n_communes_used": len(frame),
            "diagnostic_status": diag_status,
            "elapsed_seconds": elapsed,
            "preparation_manifest": prep_manifest,
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
                "model_key": "rosen_multinomial_dirichlet",
                "sample_id": sample_id,
                "n_communes_requested": sample_size,
                "n_communes_used": 0,
                "diagnostic_status": "fail",
            },
            error=str(exc),
        )
        raise
