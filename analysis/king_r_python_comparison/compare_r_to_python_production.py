from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RESULT_DIR = HERE / "results"
R_DIR = RESULT_DIR / "r_ei"
PRODUCTION_DIR = ROOT / "outputs" / "v2" / "priority_3000_final"


def interval_overlap(lower_a: float, upper_a: float, lower_b: float, upper_b: float) -> tuple[float, float]:
    overlap = max(0.0, min(upper_a, upper_b) - max(lower_a, lower_b))
    union = max(upper_a, upper_b) - min(lower_a, lower_b)
    smaller = min(upper_a - lower_a, upper_b - lower_b)
    return (
        overlap / union if union > 0 else float("nan"),
        overlap / smaller if smaller > 0 else float("nan"),
    )


def main() -> None:
    python = pd.read_csv(PRODUCTION_DIR / "aggregate_drawwise_corrected_3000_v1.csv")
    python_diag = pd.read_csv(PRODUCTION_DIR / "canonical_mcmc_diagnostics_3000_v1.csv")
    release = json.loads((PRODUCTION_DIR / "release_manifest_3000_v1.json").read_text(encoding="utf-8"))
    r_est = pd.read_csv(R_DIR / "r_aggregate_estimates.csv")
    r_diag = pd.read_csv(R_DIR / "r_diagnostics.csv")
    r_runtime = pd.read_csv(R_DIR / "r_runtime_manifest.csv")
    r_inputs = pd.read_csv(RESULT_DIR / "input_audit.csv")

    python = python.rename(
        columns={
            "beta_parameter": "estimand",
            "mean": "estimate_python",
            "q025": "lower_python",
            "q50": "median_python",
            "q975": "upper_python",
            "n_posterior_draws": "n_simulations_python",
        }
    )
    r_beta = r_est.loc[r_est["estimand"].isin(["b_1", "b_2"])].rename(
        columns={
            "estimate": "estimate_r",
            "lower": "lower_r",
            "median": "median_r",
            "upper": "upper_r",
            "n_simulations": "n_simulations_r",
            "effective_n": "effective_n_r",
        }
    )
    keys = ["election_id", "year", "scenario_id", "estimand"]
    comparison = python.merge(
        r_beta[
            keys
            + [
                "estimate_r",
                "lower_r",
                "median_r",
                "upper_r",
                "n_simulations_r",
                "effective_n_r",
            ]
        ],
        on=keys,
        validate="one_to_one",
    )
    comparison["difference_r_minus_python"] = comparison["estimate_r"] - comparison["estimate_python"]
    comparison["absolute_difference_pp"] = comparison["difference_r_minus_python"].abs() * 100
    overlaps = comparison.apply(
        lambda row: interval_overlap(row.lower_python, row.upper_python, row.lower_r, row.upper_r), axis=1
    )
    comparison[["interval_overlap_union", "interval_overlap_smaller"]] = pd.DataFrame(
        overlaps.tolist(), index=comparison.index
    )
    comparison["group_label"] = comparison["estimand"].map(
        {"b_1": "ouvriers + employés", "b_2": "autres CSP"}
    )
    comparison["hypothesis_label"] = comparison["scenario_id"].map(
        {"H0A": "abstention", "H1": "vote de gauche"}
    )
    comparison["fit_group_label"] = comparison.apply(
        lambda row: f"{row.scenario_id} {int(row.year)} — {row.group_label}", axis=1
    )
    comparison["python_panel"] = "panel_3000_common_1962_1986_2022_v2"
    comparison["r_panel"] = "panel_3000_seed_20260802"
    comparison["exact_same_model"] = False
    comparison["exact_same_panel"] = False
    comparison = comparison.sort_values(["scenario_id", "year", "estimand"])
    comparison.to_csv(RESULT_DIR / "production_python_vs_r_estimates.csv", index=False, encoding="utf-8-sig")

    chart_python = comparison[
        ["election_id", "year", "scenario_id", "estimand", "group_label", "fit_group_label"]
    ].copy()
    chart_python["engine"] = "Python KRT"
    chart_python["estimate_pct"] = comparison["estimate_python"] * 100
    chart_python["lower_pct"] = comparison["lower_python"] * 100
    chart_python["upper_pct"] = comparison["upper_python"] * 100
    chart_python["n_units"] = 3000
    chart_r = comparison[
        ["election_id", "year", "scenario_id", "estimand", "group_label", "fit_group_label"]
    ].copy()
    chart_r["engine"] = "R ei"
    chart_r["estimate_pct"] = comparison["estimate_r"] * 100
    chart_r["lower_pct"] = comparison["lower_r"] * 100
    chart_r["upper_pct"] = comparison["upper_r"] * 100
    chart_r["n_units"] = comparison["effective_n_r"]
    chart = pd.concat([chart_python, chart_r], ignore_index=True)
    chart.to_csv(RESULT_DIR / "production_python_vs_r_chart.csv", index=False, encoding="utf-8-sig")

    contrast_r = r_est.loc[r_est["estimand"].eq("b_1_minus_b_2")].copy()
    contrast_python = comparison.pivot_table(
        index=["election_id", "year", "scenario_id"], columns="estimand", values="estimate_python"
    ).reset_index()
    contrast_python["contrast_python"] = contrast_python["b_1"] - contrast_python["b_2"]
    contrasts = contrast_python.merge(
        contrast_r[["election_id", "year", "scenario_id", "estimate", "lower", "upper"]].rename(
            columns={"estimate": "contrast_r", "lower": "lower_r", "upper": "upper_r"}
        ),
        on=["election_id", "year", "scenario_id"],
        validate="one_to_one",
    )
    contrasts["difference_r_minus_python_pp"] = (contrasts["contrast_r"] - contrasts["contrast_python"]) * 100
    contrasts["same_direction"] = (contrasts["contrast_r"] * contrasts["contrast_python"]) > 0
    contrasts.to_csv(RESULT_DIR / "production_python_vs_r_contrasts.csv", index=False, encoding="utf-8-sig")

    run_times: dict[str, float] = {}
    for run_id in release["run_ids"]:
        manifest = json.loads((ROOT / "outputs" / "runs" / run_id / "manifest.json").read_text(encoding="utf-8"))
        run_times[run_id] = float(manifest["elapsed_seconds"])

    diag = python_diag[
        [
            "run_id",
            "election_id",
            "year",
            "scenario_id",
            "mcmc_status",
            "mcmc_assessment_label",
            "beta_diagnostic_status",
            "non_beta_parameter_status",
            "saved_chains",
            "saved_draws_per_chain",
            "max_rhat",
            "min_ess_bulk",
            "min_ess_tail",
            "divergences",
            "min_bfmi",
        ]
    ].copy()
    diag["python_elapsed_seconds"] = diag["run_id"].map(run_times)
    diag = diag.merge(
        r_diag[
            [
                "election_id",
                "year",
                "scenario_id",
                "diagnostic_status",
                "importance_simulations",
                "unique_parameter_simulations",
                "importance_sampling_batches",
                "hessian_positive_definite",
                "hessian_condition_number",
                "finite_draw_fraction",
                "beta_bound_violations",
                "max_accounting_reconstruction_error",
                "warning_count",
                "elapsed_seconds",
            ]
        ].rename(
            columns={
                "diagnostic_status": "r_diagnostic_status",
                "elapsed_seconds": "r_elapsed_seconds",
            }
        ),
        on=["election_id", "year", "scenario_id"],
        validate="one_to_one",
    )
    diag["comparison_key"] = diag["election_id"] + "__" + diag["scenario_id"]
    diag = diag.merge(
        r_inputs[["comparison_key", "effective_rows", "excluded_during_preparation", "excluded_degenerate_rows"]],
        on="comparison_key",
        validate="one_to_one",
    )
    diag["python_n_units"] = 3000
    diag["exact_same_input"] = False
    diag.to_csv(RESULT_DIR / "production_python_vs_r_diagnostics.csv", index=False, encoding="utf-8-sig")

    absolute = comparison["absolute_difference_pp"]
    max_row = comparison.loc[absolute.idxmax()]
    highlights = {
        "comparison_scope": "Python KRT beta-binomial production versus R ei truncated-normal exploratory fits",
        "n_fits": 6,
        "n_group_estimates": 12,
        "exact_same_model": False,
        "exact_same_panel": False,
        "median_absolute_difference_pp": float(absolute.median()),
        "mean_absolute_difference_pp": float(absolute.mean()),
        "max_absolute_difference_pp": float(absolute.max()),
        "max_difference_fit_group": str(max_row["fit_group_label"]),
        "n_estimates_within_1pp": int(absolute.le(1).sum()),
        "mean_interval_overlap_smaller": float(comparison["interval_overlap_smaller"].mean()),
        "all_contrast_directions_agree": bool(contrasts["same_direction"].all()),
        "python_total_seconds": float(diag["python_elapsed_seconds"].sum()),
        "r_total_seconds": float(r_runtime["elapsed_seconds"].sum()),
        "python_to_r_elapsed_ratio": float(diag["python_elapsed_seconds"].sum() / r_runtime["elapsed_seconds"].sum()),
        "required_interpretation": (
            "The comparison is descriptive, not a controlled cross-language replication: model likelihood/prior, "
            "posterior engine, panel membership, and effective sample differ."
        ),
    }
    (RESULT_DIR / "production_python_vs_r_highlights.json").write_text(
        json.dumps(highlights, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(highlights, indent=2, ensure_ascii=False))
    print("\nEstimates")
    print(
        comparison[
            [
                "fit_group_label",
                "estimate_python",
                "estimate_r",
                "difference_r_minus_python",
                "absolute_difference_pp",
                "interval_overlap_smaller",
            ]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
