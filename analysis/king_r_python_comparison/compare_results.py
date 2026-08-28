from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = ROOT / "outputs" / "runs"
HERE = Path(__file__).resolve().parent
RESULT_DIR = HERE / "results"
R_DIR = RESULT_DIR / "r_ei"


def python_rows(manifest: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    estimates: list[pd.DataFrame] = []
    diagnostics: list[pd.DataFrame] = []
    for row in manifest.itertuples(index=False):
        run_dir = RUNS_DIR / row.python_run_id
        estimate = pd.read_csv(run_dir / "longitudinal_estimates.csv")
        diag = pd.read_csv(run_dir / "model_diagnostics.csv")
        event = row.event
        estimate = estimate.loc[estimate["vote_category"].eq(event)].copy()
        estimate["comparison_key"] = row.comparison_key
        estimate["estimand"] = estimate["social_group"].map(
            {row.group_1: "b_1", row.group_2: "b_2"}
        )
        estimate["engine"] = "Python PyEI 1.1.4"
        estimate["model"] = "king_truncated_normal"
        estimate["median"] = np.nan
        estimate["n_simulations"] = estimate["draws"] * estimate["chains"] if "draws" in estimate else 20
        estimate["effective_n"] = estimate["n_communes_used"]
        estimate["weight_total"] = np.nan
        estimates.append(
            estimate[
                [
                    "comparison_key",
                    "election_id",
                    "year",
                    "scenario_id",
                    "engine",
                    "model",
                    "estimand",
                    "social_group",
                    "estimate",
                    "lower",
                    "median",
                    "upper",
                    "n_simulations",
                    "effective_n",
                    "weight_total",
                ]
            ]
        )
        diag = diag.copy()
        diag["comparison_key"] = row.comparison_key
        diag["engine"] = "Python PyEI 1.1.4"
        diag["diagnostic_reason"] = (
            "Pinned exploratory run: one chain and 20 retained draws; R-hat unavailable and ESS/divergence diagnostics fail."
        )
        diag["effective_n"] = diag["n_communes_used"]
        diagnostics.append(diag)
    return pd.concat(estimates, ignore_index=True), pd.concat(diagnostics, ignore_index=True)


def interval_overlap(lower_a: float, upper_a: float, lower_b: float, upper_b: float) -> float:
    overlap = max(0.0, min(upper_a, upper_b) - max(lower_a, lower_b))
    union = max(upper_a, upper_b) - min(lower_a, lower_b)
    return overlap / union if union > 0 else float("nan")


def main() -> None:
    manifest = pd.read_csv(RESULT_DIR / "comparison_manifest.csv")
    r_estimates = pd.read_csv(R_DIR / "r_aggregate_estimates.csv")
    r_diagnostics = pd.read_csv(R_DIR / "r_diagnostics.csv")
    python_estimates, python_diagnostics = python_rows(manifest)
    python_estimates.to_csv(RESULT_DIR / "python_aggregate_estimates.csv", index=False, encoding="utf-8-sig")

    comparable_r = r_estimates.loc[r_estimates["estimand"].isin(["b_1", "b_2"])].copy()
    keys = ["comparison_key", "election_id", "year", "scenario_id", "estimand", "social_group"]
    comparison = python_estimates.merge(
        comparable_r,
        on=keys,
        suffixes=("_python", "_r"),
        validate="one_to_one",
    )
    comparison["difference_r_minus_python"] = comparison["estimate_r"] - comparison["estimate_python"]
    comparison["absolute_difference_pp"] = comparison["difference_r_minus_python"].abs() * 100
    comparison["python_interval_width_pp"] = (comparison["upper_python"] - comparison["lower_python"]) * 100
    comparison["r_interval_width_pp"] = (comparison["upper_r"] - comparison["lower_r"]) * 100
    comparison["interval_overlap_ratio"] = comparison.apply(
        lambda row: interval_overlap(row.lower_python, row.upper_python, row.lower_r, row.upper_r), axis=1
    )
    comparison["same_effective_n"] = comparison["effective_n_python"].eq(comparison["effective_n_r"])
    comparison["fit_group_label"] = comparison.apply(
        lambda row: f"{row.scenario_id} {int(row.year)} - {'beta1 cible' if row.estimand == 'b_1' else 'beta2 autres'}",
        axis=1,
    )
    comparison = comparison.sort_values(["scenario_id", "year", "estimand"])
    comparison.to_csv(RESULT_DIR / "comparison_summary.csv", index=False, encoding="utf-8-sig")

    chart_python = comparison[
        ["comparison_key", "year", "scenario_id", "estimand", "social_group", "fit_group_label"]
    ].copy()
    chart_python["engine"] = "Python PyEI"
    chart_python["estimate"] = comparison["estimate_python"]
    chart_python["lower"] = comparison["lower_python"]
    chart_python["upper"] = comparison["upper_python"]
    chart_python["effective_n"] = comparison["effective_n_python"]
    chart_r = comparison[
        ["comparison_key", "year", "scenario_id", "estimand", "social_group", "fit_group_label"]
    ].copy()
    chart_r["engine"] = "R ei"
    chart_r["estimate"] = comparison["estimate_r"]
    chart_r["lower"] = comparison["lower_r"]
    chart_r["upper"] = comparison["upper_r"]
    chart_r["effective_n"] = comparison["effective_n_r"]
    chart_data = pd.concat([chart_python, chart_r], ignore_index=True)
    chart_data.to_csv(RESULT_DIR / "comparison_chart_data.csv", index=False, encoding="utf-8-sig")

    py_diag_cols = [
        "comparison_key",
        "engine",
        "fit_status",
        "diagnostic_status",
        "diagnostic_reason",
        "effective_n",
        "elapsed_seconds",
        "draws",
        "tune",
        "chains",
        "mcmc_divergences",
        "mcmc_divergence_fraction",
        "mcmc_max_rhat",
        "mcmc_min_ess_bulk",
        "mcmc_min_ess_tail",
    ]
    py_diag = python_diagnostics.reindex(columns=py_diag_cols)
    r_diag = r_diagnostics.copy()
    diagnostic_comparison = pd.concat([py_diag, r_diag], ignore_index=True, sort=False)
    diagnostic_comparison = diagnostic_comparison.sort_values(["comparison_key", "engine"])
    diagnostic_comparison.to_csv(RESULT_DIR / "diagnostic_comparison.csv", index=False, encoding="utf-8-sig")

    max_row = comparison.loc[comparison["absolute_difference_pp"].idxmax()]
    summary = {
        "n_fits": int(manifest.shape[0]),
        "n_group_estimates": int(comparison.shape[0]),
        "all_inputs_same_effective_n": bool(comparison["same_effective_n"].all()),
        "max_absolute_difference_pp": float(comparison["absolute_difference_pp"].max()),
        "max_difference_fit_group": str(max_row["fit_group_label"]),
        "median_absolute_difference_pp": float(comparison["absolute_difference_pp"].median()),
        "mean_interval_overlap_ratio": float(comparison["interval_overlap_ratio"].mean()),
        "python_diagnostics": "fail for all six pinned exploratory fits (1 chain, 20 draws)",
        "r_diagnostics": "caveat when numerical checks pass because R ei exposes 99 importance simulations, not multi-chain MCMC",
        "interpretation": (
            "Differences combine implementation, prior, and posterior-simulation choices. Matching inputs isolates composition "
            "but does not make the two posterior engines mathematically identical."
        ),
    }
    (RESULT_DIR / "comparison_highlights.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("\nComparison")
    print(
        comparison[
            [
                "fit_group_label",
                "estimate_python",
                "estimate_r",
                "difference_r_minus_python",
                "absolute_difference_pp",
                "interval_overlap_ratio",
            ]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
