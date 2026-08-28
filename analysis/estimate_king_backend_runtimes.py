from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr


ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "outputs" / "runs"
PANEL_SHA = "bde70c71660fce29610d7931461d8db6181dba874514a1866b63cf16a81cec4a"
OUTPUT_STEM = ROOT / "analysis" / "king_backend_runtime_estimates_20260827"

EXPECTED_RUNS = {
    "H0A": 26,
    "H0B": 26,
    "H0C": 26,
    "H1": 26,
    "H2": 26,
    "H3": 26,
    "H4": 26,
    "H5": 26,
    "H6": 16,
    "H7": 16,
}

# These two pairs have identical model-ready input hashes, seeds, panel,
# model specification, and 1,000/1,000 x 4 settings under both backends.
STRICT_MATCHED_PAIRS = {
    "H2": {
        "numpyro": "20260822T190602Z__200f797a08d2",
        "pymc": "20260825T033641Z__37795b17add3",
    },
    "H3": {
        "numpyro": "20260822T195314Z__361b3b2c9fb0",
        "pymc": "20260825T101843Z__d3030b2cdc30",
    },
}


def read_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def trace_timing(trace_path: Path) -> dict[str, float | None]:
    if not trace_path.exists():
        return {"posterior_perf_s": None, "posterior_cpu_s": None, "n_steps_sum": None}
    with xr.open_dataset(trace_path, group="sample_stats", engine="netcdf4") as dataset:
        return {
            "posterior_perf_s": (
                float(dataset["perf_counter_diff"].sum().load())
                if "perf_counter_diff" in dataset
                else None
            ),
            "posterior_cpu_s": (
                float(dataset["process_time_diff"].sum().load())
                if "process_time_diff" in dataset
                else None
            ),
            "n_steps_sum": (
                float(dataset["n_steps"].sum().load()) if "n_steps" in dataset else None
            ),
        }


def collect_standard_runs() -> pd.DataFrame:
    rows: list[dict] = []
    for manifest_path in sorted(RUNS_DIR.glob("*/manifest.json")):
        try:
            manifest = read_manifest(manifest_path)
        except (OSError, json.JSONDecodeError):
            continue
        parameters = manifest.get("parameters", {})
        if manifest.get("status") != "success":
            continue
        if parameters.get("model_key") != "krt_beta_binomial":
            continue
        if parameters.get("sample_size") != 2000:
            continue
        if parameters.get("draws") != 1000 or parameters.get("tune") != 1000:
            continue
        if parameters.get("chains") != 4:
            continue
        panel_sha = parameters.get("panel_sha256") or manifest.get("panel_sha256")
        if panel_sha != PANEL_SHA:
            continue
        backend = parameters.get("sampler_backend") or "numpyro"
        row = {
            "run_id": manifest["run_id"],
            "election_id": parameters.get("election_id"),
            "scenario_id": parameters.get("scenario_id"),
            "backend": backend,
            "raw_elapsed_s": float(manifest["elapsed_seconds"]),
            "draws": parameters.get("draws"),
            "tune": parameters.get("tune"),
            "chains": parameters.get("chains"),
            "cores": parameters.get("cores"),
            "random_seed": parameters.get("random_seed"),
            "input_sha256": next(iter(manifest.get("input_sha256", {}).values()), None),
            "mcmc_status": (manifest.get("canonical_mcmc_diagnostic") or {}).get("mcmc_status"),
            "max_rhat": (manifest.get("canonical_mcmc_diagnostic") or {}).get("max_rhat"),
            "min_ess_bulk": (manifest.get("canonical_mcmc_diagnostic") or {}).get("min_ess_bulk"),
            "min_ess_tail": (manifest.get("canonical_mcmc_diagnostic") or {}).get("min_ess_tail"),
            "divergences": (manifest.get("canonical_mcmc_diagnostic") or {}).get("divergences"),
            "min_bfmi": (manifest.get("canonical_mcmc_diagnostic") or {}).get("min_bfmi"),
            "max_treedepth_hits": (manifest.get("canonical_mcmc_diagnostic") or {}).get(
                "max_treedepth_hits"
            ),
            "finished_at_utc": manifest.get("finished_at_utc"),
        }
        row.update(trace_timing(manifest_path.parent / "trace.nc"))
        rows.append(row)
    frame = pd.DataFrame(rows)
    frame = frame.sort_values(["scenario_id", "election_id", "backend", "finished_at_utc"])
    # The current production set has one standard run per scenario/election/backend.
    # Keep the latest only if a duplicate ever appears.
    frame = frame.drop_duplicates(
        ["scenario_id", "election_id", "backend"], keep="last"
    ).reset_index(drop=True)
    return frame


def apply_active_time_correction(frame: pd.DataFrame) -> tuple[pd.DataFrame, float, float]:
    result = frame.copy()
    result["raw_over_posterior"] = np.where(
        result["backend"].eq("pymc") & result["posterior_perf_s"].notna(),
        result["raw_elapsed_s"] / result["posterior_perf_s"],
        np.nan,
    )
    clean = result.loc[
        result["backend"].eq("pymc")
        & result["raw_over_posterior"].between(1.0, 3.0, inclusive="both"),
        "raw_over_posterior",
    ]
    clean_ratio = float(clean.median())
    result["runtime_active_s"] = result["raw_elapsed_s"]
    pymc_contaminated = result["backend"].eq("pymc") & result["raw_over_posterior"].gt(3.0)
    result.loc[pymc_contaminated, "runtime_active_s"] = (
        result.loc[pymc_contaminated, "posterior_perf_s"] * clean_ratio
    )

    # NumPyro traces do not save perf_counter_diff. Use the invariant graph work
    # proxy (posterior NUTS steps) to detect only extreme wall-time inflation.
    # The five-times-median threshold is intentionally conservative.
    result["numpyro_seconds_per_step"] = np.where(
        result["backend"].eq("numpyro") & result["n_steps_sum"].gt(0),
        result["raw_elapsed_s"] / result["n_steps_sum"],
        np.nan,
    )
    numpyro_reference = result[
        result["backend"].eq("numpyro") & result["scenario_id"].isin(["H0A", "H1"])
    ]["numpyro_seconds_per_step"].dropna()
    numpyro_step_median = float(numpyro_reference.median())
    numpyro_contaminated = (
        result["backend"].eq("numpyro")
        & result["numpyro_seconds_per_step"].gt(5.0 * numpyro_step_median)
    )
    result.loc[numpyro_contaminated, "runtime_active_s"] = (
        result.loc[numpyro_contaminated, "n_steps_sum"] * numpyro_step_median
    )
    result["timing_status"] = np.select(
        [
            numpyro_contaminated,
            result["backend"].eq("numpyro"),
            pymc_contaminated,
            result["backend"].eq("pymc"),
        ],
        [
            "numpyro_step_corrected",
            "numpyro_observed_clean",
            "pymc_sleep_corrected",
            "pymc_observed_clean",
        ],
        default="unknown",
    )
    return result, clean_ratio, numpyro_step_median


def geometric_mean(values: pd.Series) -> float:
    positive = values[values > 0].astype(float)
    return float(np.exp(np.log(positive).mean()))


def election_baseline(
    frame: pd.DataFrame, backend: str, scenarios: list[str]
) -> pd.Series:
    subset = frame[
        frame["backend"].eq(backend) & frame["scenario_id"].isin(scenarios)
    ]
    return subset.groupby("election_id")["runtime_active_s"].apply(geometric_mean)


def project_from_anchors(
    frame: pd.DataFrame,
    *,
    scenario: str,
    backend: str,
    expected_elections: list[str],
    baseline: pd.Series,
) -> dict:
    direct = frame[
        frame["scenario_id"].eq(scenario) & frame["backend"].eq(backend)
    ].copy()
    direct = direct[direct["election_id"].isin(expected_elections)]
    expected_set = set(expected_elections)
    observed_set = set(direct["election_id"])
    if observed_set == expected_set:
        total = float(direct["runtime_active_s"].sum())
        return {
            "hours": total / 3600,
            "low_hours": total / 3600,
            "high_hours": total / 3600,
            "direct_runs": len(direct),
            "method": "observed_complete",
            "anchor_factor": 1.0,
        }
    if direct.empty:
        return {
            "hours": np.nan,
            "low_hours": np.nan,
            "high_hours": np.nan,
            "direct_runs": 0,
            "method": "no_direct_anchor",
            "anchor_factor": np.nan,
        }
    direct["baseline_s"] = direct["election_id"].map(baseline)
    direct = direct[direct["baseline_s"].notna()]
    direct["factor"] = direct["runtime_active_s"] / direct["baseline_s"]
    factor = float(direct["factor"].median())
    if len(direct) == 1:
        low_factor, high_factor = factor / 2.0, factor * 2.0
    else:
        low_factor = float(direct["factor"].min())
        high_factor = float(direct["factor"].max())
    missing = sorted(expected_set - set(direct["election_id"]))
    missing_baseline = baseline.reindex(missing).dropna()
    observed_total = float(direct["runtime_active_s"].sum())
    total = observed_total + float((missing_baseline * factor).sum())
    low_total = observed_total + float((missing_baseline * low_factor).sum())
    high_total = observed_total + float((missing_baseline * high_factor).sum())
    return {
        "hours": total / 3600,
        "low_hours": min(low_total, high_total) / 3600,
        "high_hours": max(low_total, high_total) / 3600,
        "direct_runs": len(direct),
        "method": "election_adjusted_projection",
        "anchor_factor": factor,
    }


def strict_backend_multiplier(frame: pd.DataFrame) -> tuple[float, float, float, list[dict]]:
    ratios: list[float] = []
    evidence: list[dict] = []
    indexed = frame.set_index("run_id")
    for scenario, run_ids in STRICT_MATCHED_PAIRS.items():
        numpyro = indexed.loc[run_ids["numpyro"]]
        pymc = indexed.loc[run_ids["pymc"]]
        if numpyro["input_sha256"] != pymc["input_sha256"]:
            raise AssertionError(f"Strict pair input mismatch for {scenario}")
        if numpyro["random_seed"] != pymc["random_seed"]:
            raise AssertionError(f"Strict pair seed mismatch for {scenario}")
        ratio = float(pymc["runtime_active_s"] / numpyro["runtime_active_s"])
        ratios.append(ratio)
        evidence.append(
            {
                "scenario_id": scenario,
                "numpyro_run_id": run_ids["numpyro"],
                "pymc_run_id": run_ids["pymc"],
                "numpyro_minutes": float(numpyro["runtime_active_s"] / 60),
                "pymc_active_minutes": float(pymc["runtime_active_s"] / 60),
                "pymc_over_numpyro": ratio,
            }
        )
    central = float(math.exp(np.mean(np.log(ratios))))
    # The strict evidence has only two pairs. Widen beyond their observed range
    # to avoid presenting a fragile two-point calibration as precise.
    low = min(2.5, min(ratios))
    high = max(3.5, max(ratios))
    return central, low, high, evidence


def convert_estimate(
    source: dict, *, target_backend: str, multiplier: float, multiplier_low: float, multiplier_high: float
) -> dict:
    if target_backend == "pymc":
        hours = source["hours"] * multiplier
        low = source["low_hours"] * multiplier_low
        high = source["high_hours"] * multiplier_high
    else:
        hours = source["hours"] / multiplier
        low = source["low_hours"] / multiplier_high
        high = source["high_hours"] / multiplier_low
    return {
        "hours": hours,
        "low_hours": min(low, high),
        "high_hours": max(low, high),
        "direct_runs": 0,
        "method": "converted_from_other_backend",
        "anchor_factor": multiplier,
    }


def build_estimates(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    numpyro_baseline = election_baseline(frame, "numpyro", ["H0A", "H1"])
    pymc_baseline = election_baseline(frame, "pymc", ["H0B", "H0C"])
    all_26 = sorted(set(numpyro_baseline.index) & set(pymc_baseline.index))
    eligible_16 = sorted(
        set(
            frame.loc[
                frame["scenario_id"].eq("H6") & frame["backend"].eq("pymc"),
                "election_id",
            ]
        )
    )
    expected_by_scenario = {
        scenario: (eligible_16 if count == 16 else all_26)
        for scenario, count in EXPECTED_RUNS.items()
    }

    multiplier, multiplier_low, multiplier_high, matched_evidence = strict_backend_multiplier(frame)
    estimates: dict[tuple[str, str], dict] = {}
    for scenario in EXPECTED_RUNS:
        estimates[(scenario, "numpyro")] = project_from_anchors(
            frame,
            scenario=scenario,
            backend="numpyro",
            expected_elections=expected_by_scenario[scenario],
            baseline=numpyro_baseline,
        )
        estimates[(scenario, "pymc")] = project_from_anchors(
            frame,
            scenario=scenario,
            backend="pymc",
            expected_elections=expected_by_scenario[scenario],
            baseline=pymc_baseline,
        )

    for scenario in EXPECTED_RUNS:
        np_est = estimates[(scenario, "numpyro")]
        pm_est = estimates[(scenario, "pymc")]
        if math.isnan(np_est["hours"]) and not math.isnan(pm_est["hours"]):
            estimates[(scenario, "numpyro")] = convert_estimate(
                pm_est,
                target_backend="numpyro",
                multiplier=multiplier,
                multiplier_low=multiplier_low,
                multiplier_high=multiplier_high,
            )
        if math.isnan(pm_est["hours"]) and not math.isnan(np_est["hours"]):
            estimates[(scenario, "pymc")] = convert_estimate(
                np_est,
                target_backend="pymc",
                multiplier=multiplier,
                multiplier_low=multiplier_low,
                multiplier_high=multiplier_high,
            )

    rows: list[dict] = []
    for scenario, expected in EXPECTED_RUNS.items():
        for backend in ("numpyro", "pymc"):
            estimate = estimates[(scenario, backend)]
            rows.append(
                {
                    "scenario_id": scenario,
                    "backend": backend,
                    "expected_runs": expected,
                    "estimated_hours": estimate["hours"],
                    "low_hours": estimate["low_hours"],
                    "high_hours": estimate["high_hours"],
                    "direct_standard_runs": estimate["direct_runs"],
                    "method": estimate["method"],
                    "anchor_factor": estimate["anchor_factor"],
                }
            )
    result = pd.DataFrame(rows)
    metadata = {
        "as_of": "2026-08-27",
        "standard_fit": {
            "panel_size": 2000,
            "draws": 1000,
            "tune": 1000,
            "chains": 4,
            "strengthened_reruns_included": False,
        },
        "expected_runs": EXPECTED_RUNS,
        "pymc_active_time_clean_ratio": float(
            frame.loc[
                frame["backend"].eq("pymc") & frame["raw_over_posterior"].le(3.0),
                "raw_over_posterior",
            ].median()
        ),
        "pymc_sleep_corrected_runs": int(frame["timing_status"].eq("pymc_sleep_corrected").sum()),
        "numpyro_step_corrected_runs": int(
            frame["timing_status"].eq("numpyro_step_corrected").sum()
        ),
        "strict_pymc_over_numpyro_multiplier": multiplier,
        "strict_multiplier_low": multiplier_low,
        "strict_multiplier_high": multiplier_high,
        "strict_matched_evidence": matched_evidence,
        "method_notes": [
            "Complete scenario/backend cells are sums of observed standard production runs.",
            "Partial cells keep observed anchors and predict missing elections from a same-backend election baseline.",
            "Missing backends are converted with the geometric mean of two strict H2/H3 matched pairs.",
            "Ranges for anchor projections use the minimum and maximum observed anchor factors; one-anchor projections use factor/2 to factor*2.",
            "Ranges for backend conversion include a widened 2.5x to 3.5x PyMC/NumPyro multiplier.",
        ],
    }
    return result, metadata


def paired_diagnostics(frame: pd.DataFrame) -> pd.DataFrame:
    indexed = frame.set_index("run_id")
    rows: list[dict] = []
    for scenario, run_ids in STRICT_MATCHED_PAIRS.items():
        for backend, run_id in run_ids.items():
            row = indexed.loc[run_id]
            rows.append(
                {
                    "scenario_id": scenario,
                    "backend": backend,
                    "run_id": run_id,
                    "mcmc_status": row["mcmc_status"],
                    "max_rhat": row["max_rhat"],
                    "min_ess_bulk": row["min_ess_bulk"],
                    "min_ess_tail": row["min_ess_tail"],
                    "divergences": row["divergences"],
                    "min_bfmi": row["min_bfmi"],
                    "max_treedepth_hits": row["max_treedepth_hits"],
                    "active_minutes": row["runtime_active_s"] / 60,
                    "input_sha256": row["input_sha256"],
                    "random_seed": row["random_seed"],
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    frame = collect_standard_runs()
    frame, clean_ratio, numpyro_step_median = apply_active_time_correction(frame)
    estimates, metadata = build_estimates(frame)
    diagnostics = paired_diagnostics(frame)

    inputs_path = Path(f"{OUTPUT_STEM}_inputs.csv")
    estimates_path = Path(f"{OUTPUT_STEM}.csv")
    diagnostics_path = Path(f"{OUTPUT_STEM}_paired_diagnostics.csv")
    metadata_path = Path(f"{OUTPUT_STEM}.json")
    frame.to_csv(inputs_path, index=False)
    estimates.to_csv(estimates_path, index=False)
    diagnostics.to_csv(diagnostics_path, index=False)
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"standard runs: {len(frame)}")
    print(f"PyMC clean full/posterior ratio: {clean_ratio:.3f}")
    print(f"sleep-corrected PyMC runs: {metadata['pymc_sleep_corrected_runs']}")
    print(f"NumPyro clean seconds/posterior-step: {numpyro_step_median:.8f}")
    print(f"step-corrected NumPyro runs: {metadata['numpyro_step_corrected_runs']}")
    print(
        "strict PyMC/NumPyro multiplier: "
        f"{metadata['strict_pymc_over_numpyro_multiplier']:.3f} "
        f"[{metadata['strict_multiplier_low']:.2f}, {metadata['strict_multiplier_high']:.2f}]"
    )
    print("\nRuntime estimates (hours):")
    print(
        estimates.pivot(index="scenario_id", columns="backend", values="estimated_hours")
        .reindex(EXPECTED_RUNS)
        .round(2)
        .to_string()
    )
    print("\nPaired diagnostics:")
    print(diagnostics.round(3).to_string(index=False))
    print(f"\nWrote {estimates_path}")
    print(f"Wrote {inputs_path}")
    print(f"Wrote {diagnostics_path}")
    print(f"Wrote {metadata_path}")


if __name__ == "__main__":
    main()
