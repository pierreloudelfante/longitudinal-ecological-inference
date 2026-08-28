from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "analysis" / "king_backend_runtime_estimates_20260827_inputs.csv"
OUTPUT = ROOT / "analysis" / "king_recent_active_runtime_estimates_20260827.csv"
EVIDENCE = ROOT / "analysis" / "king_recent_active_runtime_evidence_20260827.csv"
CUTOFF_RUN_ID = "20260822"


def geometric_mean(values: list[float]) -> float:
    clean = [float(v) for v in values if np.isfinite(v) and v > 0]
    if not clean:
        return float("nan")
    return math.exp(sum(math.log(v) for v in clean) / len(clean))


df = pd.read_csv(INPUT)
numeric = [
    "raw_elapsed_s",
    "posterior_perf_s",
    "posterior_cpu_s",
    "n_steps_sum",
]
for column in numeric:
    df[column] = pd.to_numeric(df[column], errors="coerce")

recent = df.loc[df["run_id"].astype(str).str[:8] >= CUTOFF_RUN_ID].copy()
recent["recent_source"] = True

# PyMC stores both perf-counter time and process CPU time for posterior draws.
# CPU time excludes machine sleep.  We estimate the non-sampling fit overhead
# (compile, initialization, summaries and writes) from recent traces whose wall,
# perf and CPU clocks agree closely enough to rule out an obvious sleep interval.
pymc_mask = recent["backend"].eq("pymc")
recent.loc[pymc_mask, "perf_over_cpu"] = (
    recent.loc[pymc_mask, "posterior_perf_s"]
    / recent.loc[pymc_mask, "posterior_cpu_s"]
)
recent.loc[pymc_mask, "raw_over_perf"] = (
    recent.loc[pymc_mask, "raw_elapsed_s"]
    / recent.loc[pymc_mask, "posterior_perf_s"]
)
recent.loc[pymc_mask, "overhead_observed_s"] = (
    recent.loc[pymc_mask, "raw_elapsed_s"]
    - recent.loc[pymc_mask, "posterior_perf_s"]
)
recent["pymc_clock_clean"] = False
recent.loc[
    pymc_mask
    & recent["posterior_cpu_s"].gt(0)
    & recent["posterior_perf_s"].gt(0)
    & recent["perf_over_cpu"].between(0.90, 1.35)
    & recent["raw_over_perf"].between(1.0, 3.0),
    "pymc_clock_clean",
] = True

clean_pymc = recent.loc[recent["pymc_clock_clean"]].copy()
global_overhead = float(clean_pymc["overhead_observed_s"].median())
scenario_overheads = clean_pymc.groupby("scenario_id")["overhead_observed_s"].median()
recent["overhead_reference_s"] = np.nan
for scenario, value in scenario_overheads.items():
    recent.loc[
        pymc_mask & recent["scenario_id"].eq(scenario),
        "overhead_reference_s",
    ] = float(value)
recent.loc[pymc_mask, "overhead_reference_s"] = recent.loc[
    pymc_mask, "overhead_reference_s"
].fillna(global_overhead)
recent.loc[pymc_mask, "active_fit_s"] = (
    recent.loc[pymc_mask, "posterior_cpu_s"]
    + recent.loc[pymc_mask, "overhead_reference_s"]
)
recent.loc[pymc_mask, "active_time_method"] = (
    "posterior CPU + median recent clean scenario overhead"
)

# NumPyro traces do not store a process-time clock.  The six recent pilots have
# mutually consistent seconds/NUTS-step rates, so their elapsed values are kept.
# This is explicitly weaker evidence than PyMC CPU time but no sleep outlier is
# detectable in this recent subset.
numpyro_mask = recent["backend"].eq("numpyro")
recent.loc[numpyro_mask, "seconds_per_step"] = (
    recent.loc[numpyro_mask, "raw_elapsed_s"]
    / recent.loc[numpyro_mask, "n_steps_sum"]
)
numpyro_step_median_initial = float(
    recent.loc[numpyro_mask, "seconds_per_step"].median()
)
numpyro_step_outlier = numpyro_mask & recent["seconds_per_step"].gt(
    2.0 * numpyro_step_median_initial
)
numpyro_clean_step_median = float(
    recent.loc[numpyro_mask & ~numpyro_step_outlier, "seconds_per_step"].median()
)
recent.loc[numpyro_mask, "active_fit_s"] = recent.loc[numpyro_mask, "raw_elapsed_s"]
recent.loc[numpyro_mask, "active_time_method"] = (
    "recent elapsed; NUTS step-rate consistent"
)
recent.loc[numpyro_step_outlier, "active_fit_s"] = (
    recent.loc[numpyro_step_outlier, "n_steps_sum"] * numpyro_clean_step_median
)
recent.loc[numpyro_step_outlier, "active_time_method"] = (
    "reconstructed from NUTS steps x median of 5 recent consistent runs"
)

# The 26-election baseline comes only from recent, complete H0B/H0C PyMC fits.
pymc = recent.loc[pymc_mask].copy()
numpyro = recent.loc[numpyro_mask].copy()
baseline_wide = (
    pymc.loc[pymc["scenario_id"].isin(["H0B", "H0C"])]
    .pivot(index="election_id", columns="scenario_id", values="active_fit_s")
    .dropna(subset=["H0B", "H0C"])
)
if len(baseline_wide) != 26:
    raise RuntimeError(f"Expected 26 recent H0B/H0C baselines, found {len(baseline_wide)}")
baseline_wide["baseline_pymc_s"] = np.sqrt(
    baseline_wide["H0B"] * baseline_wide["H0C"]
)

# Recent strictly paired, same-election H2/H3 fits determine the backend factor.
paired_ratios: list[float] = []
paired_rows: list[dict[str, object]] = []
for scenario in ["H2", "H3"]:
    left = numpyro.loc[numpyro["scenario_id"].eq(scenario)]
    right = pymc.loc[pymc["scenario_id"].eq(scenario)]
    paired = left.merge(right, on=["scenario_id", "election_id"], suffixes=("_numpyro", "_pymc"))
    for row in paired.itertuples(index=False):
        ratio = float(row.active_fit_s_pymc / row.active_fit_s_numpyro)
        paired_ratios.append(ratio)
        paired_rows.append(
            {
                "scenario_id": scenario,
                "election_id": row.election_id,
                "pymc_active_s": row.active_fit_s_pymc,
                "numpyro_active_s": row.active_fit_s_numpyro,
                "pymc_over_numpyro": ratio,
            }
        )
speed_central = geometric_mean(paired_ratios)
speed_low = min(paired_ratios)
speed_high = max(paired_ratios)
baseline_wide["baseline_numpyro_s"] = baseline_wide["baseline_pymc_s"] / speed_central


def project_from_anchors(scenario: str, backend: str) -> dict[str, float]:
    source = numpyro if backend == "numpyro" else pymc
    anchors = source.loc[source["scenario_id"].eq(scenario)].copy()
    baseline_column = f"baseline_{backend}_s"
    anchors = anchors.merge(
        baseline_wide[[baseline_column]], left_on="election_id", right_index=True
    )
    anchors["scenario_factor"] = anchors["active_fit_s"] / anchors[baseline_column]
    factors = anchors["scenario_factor"].tolist()
    central_factor = float(np.median(factors))
    return {
        "estimate_s": float(baseline_wide[baseline_column].sum() * central_factor),
        "low_s": float(baseline_wide[baseline_column].sum() * min(factors)),
        "high_s": float(baseline_wide[baseline_column].sum() * max(factors)),
        "factor": central_factor,
        "factor_low": min(factors),
        "factor_high": max(factors),
        "n_anchors": len(anchors),
    }


rows: list[dict[str, object]] = []


def add_result(
    scenario: str,
    expected: int,
    np_est: float,
    np_low: float,
    np_high: float,
    pm_est: float,
    pm_low: float,
    pm_high: float,
    primary_backend: str,
    method: str,
    confidence: str,
) -> None:
    rows.append(
        {
            "scenario_id": scenario,
            "expected_runs": expected,
            "recent_numpyro_runs": int(
                numpyro["scenario_id"].eq(scenario).sum()
            ),
            "recent_pymc_runs": int(pymc["scenario_id"].eq(scenario).sum()),
            "numpyro_hours": np_est / 3600,
            "numpyro_low_hours": np_low / 3600,
            "numpyro_high_hours": np_high / 3600,
            "pymc_hours": pm_est / 3600,
            "pymc_low_hours": pm_low / 3600,
            "pymc_high_hours": pm_high / 3600,
            "primary_backend": primary_backend,
            "method": method,
            "confidence": confidence,
        }
    )


# H0B/H0C/H6/H7 have complete recent PyMC coverage.  Their NumPyro columns are
# backend conversions, not direct observations.
for scenario, expected in [("H0B", 26), ("H0C", 26), ("H6", 16), ("H7", 16)]:
    total = float(pymc.loc[pymc["scenario_id"].eq(scenario), "active_fit_s"].sum())
    add_result(
        scenario,
        expected,
        total / speed_central,
        total / speed_high,
        total / speed_low,
        total,
        total,
        total,
        "pymc",
        "complete recent PyMC active total; NumPyro converted by recent paired factor",
        "high for PyMC; medium for NumPyro",
    )

# H2/H3 use their three recent NumPyro pilots (early/middle/late elections),
# then convert to PyMC.  This avoids extrapolating 26 elections from only the
# one or two unusually slow PyMC pilots.
projected: dict[str, dict[str, float]] = {}
for scenario in ["H2", "H3"]:
    result = project_from_anchors(scenario, "numpyro")
    projected[scenario] = result
    add_result(
        scenario,
        26,
        result["estimate_s"],
        result["low_s"],
        result["high_s"],
        result["estimate_s"] * speed_central,
        result["low_s"] * speed_low,
        result["high_s"] * speed_high,
        "numpyro",
        "3 recent NumPyro anchors, election-adjusted; PyMC converted from strict recent pairs",
        "medium-low",
    )

# H4/H5 have three recent PyMC pilots each.
for scenario in ["H4", "H5"]:
    result = project_from_anchors(scenario, "pymc")
    projected[scenario] = result
    add_result(
        scenario,
        26,
        result["estimate_s"] / speed_central,
        result["low_s"] / speed_high,
        result["high_s"] / speed_low,
        result["estimate_s"],
        result["low_s"],
        result["high_s"],
        "pymc",
        "3 recent PyMC anchors, election-adjusted; NumPyro converted from strict recent pairs",
        "medium-low",
    )

# No recent direct H0A/H1 fits exist.  H0A uses the recent null-model baseline.
h0a_pm = float(baseline_wide["baseline_pymc_s"].sum())
h0a_pm_low = float(min(baseline_wide["H0B"].sum(), baseline_wide["H0C"].sum()))
h0a_pm_high = float(max(baseline_wide["H0B"].sum(), baseline_wide["H0C"].sum()))
add_result(
    "H0A",
    26,
    h0a_pm / speed_central,
    h0a_pm_low / speed_high,
    h0a_pm_high / speed_low,
    h0a_pm,
    h0a_pm_low,
    h0a_pm_high,
    "proxy",
    "no recent direct fit; geometric H0B/H0C recent null-model proxy",
    "low",
)

# H1 uses the geometric middle of the two recent substantive hypotheses H2/H3.
# It is a transparent planning proxy, not a recovered or directly measured time.
h1_np = geometric_mean([projected["H2"]["estimate_s"], projected["H3"]["estimate_s"]])
h1_np_low = min(projected["H2"]["low_s"], projected["H3"]["low_s"])
h1_np_high = max(projected["H2"]["high_s"], projected["H3"]["high_s"])
add_result(
    "H1",
    26,
    h1_np,
    h1_np_low,
    h1_np_high,
    h1_np * speed_central,
    h1_np_low * speed_low,
    h1_np_high * speed_high,
    "proxy",
    "no recent direct fit; geometric H2/H3 recent substantive-model proxy",
    "low",
)

estimates = pd.DataFrame(rows)
order = ["H0A", "H0B", "H0C", "H1", "H2", "H3", "H4", "H5", "H6", "H7"]
estimates["_order"] = estimates["scenario_id"].map({v: i for i, v in enumerate(order)})
estimates = estimates.sort_values("_order").drop(columns="_order")
estimates.to_csv(OUTPUT, index=False)

evidence_columns = [
    "run_id",
    "election_id",
    "scenario_id",
    "backend",
    "raw_elapsed_s",
    "posterior_perf_s",
    "posterior_cpu_s",
    "n_steps_sum",
    "perf_over_cpu",
    "raw_over_perf",
    "pymc_clock_clean",
    "overhead_reference_s",
    "seconds_per_step",
    "active_fit_s",
    "active_time_method",
    "mcmc_status",
]
recent[evidence_columns].sort_values(["scenario_id", "backend", "election_id"]).to_csv(
    EVIDENCE, index=False
)

print(f"recent runs: {len(recent)}")
print(f"recent clean PyMC clocks: {int(recent['pymc_clock_clean'].sum())}/{int(pymc_mask.sum())}")
print(
    "recent NumPyro seconds/step range: "
    f"{recent.loc[numpyro_mask, 'seconds_per_step'].min():.8f} - "
    f"{recent.loc[numpyro_mask, 'seconds_per_step'].max():.8f}"
)
print(
    f"recent NumPyro step outliers reconstructed: {int(numpyro_step_outlier.sum())}; "
    f"clean median={numpyro_clean_step_median:.8f}s/step"
)
print(
    "recent strict PyMC/NumPyro pairs: "
    + ", ".join(f"{x:.3f}x" for x in paired_ratios)
)
print(f"central backend factor: {speed_central:.3f}x [{speed_low:.3f}, {speed_high:.3f}]")
print(estimates[["scenario_id", "expected_runs", "numpyro_hours", "pymc_hours", "confidence"]].to_string(index=False))
print(f"NumPyro total: {estimates['numpyro_hours'].sum():.2f}h")
print(f"PyMC total: {estimates['pymc_hours'].sum():.2f}h")
print(f"Wrote {OUTPUT}")
print(f"Wrote {EVIDENCE}")
