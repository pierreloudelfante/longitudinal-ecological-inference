from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .paths import FIGURE_DIR


def _largest_comparable_rungs(estimates: pd.DataFrame) -> pd.DataFrame:
    """Use one rung per election: common King/KRT for 2x2, largest otherwise."""
    keep: list[pd.DataFrame] = []
    keys = ["election_id", "scenario_id"]
    for _, group in estimates.groupby(keys, sort=True):
        family = str(group["model_family"].iloc[0])
        sizes = pd.to_numeric(group["n_communes_requested"], errors="coerce")
        group = group.assign(_n_requested=sizes)
        if family == "2x2":
            counts = group.groupby("_n_requested")["model_key"].agg(lambda values: set(values.astype(str)))
            common_sizes = [
                int(size)
                for size, models in counts.items()
                if {"king_truncated_normal", "krt_beta_binomial"}.issubset(models)
            ]
            if common_sizes:
                keep.append(group.loc[group["_n_requested"].eq(max(common_sizes))])
                continue
        for _, model_group in group.groupby("model_key", sort=True):
            keep.append(model_group.loc[model_group["_n_requested"].eq(model_group["_n_requested"].max())])
    return pd.concat(keep, ignore_index=True).drop(columns="_n_requested") if keep else estimates.iloc[0:0].copy()


def plot_longitudinal(estimates: pd.DataFrame) -> None:
    if estimates.empty:
        return
    output_root = FIGURE_DIR / "longitudinal"
    output_root.mkdir(parents=True, exist_ok=True)
    for pattern in ("*.png", "*.svg"):
        for generated_figure in output_root.glob(pattern):
            generated_figure.unlink()
    main = estimates.loc[~estimates["with_covariate"].astype(str).str.lower().isin({"true", "1"})].copy()
    main = _largest_comparable_rungs(main)
    for key, group in main.groupby(["scenario_id", "model_key", "election_type"], sort=True):
        scenario_id, model_key, election_type = key
        target_vote = group["vote_category"].iloc[0]
        target = group.loc[group["vote_category"].eq(target_vote)].copy()
        if target.empty:
            continue
        fig, ax = plt.subplots(figsize=(8.2, 4.8))
        for social_group, part in target.groupby("social_group", sort=False):
            part = part.sort_values("year")
            lower = pd.to_numeric(part["lower"], errors="coerce")
            upper = pd.to_numeric(part["upper"], errors="coerce")
            estimate = pd.to_numeric(part["estimate"], errors="coerce")
            yerr = None
            if lower.notna().any() and upper.notna().any():
                yerr = np.vstack([estimate - lower, upper - estimate])
            line_style = "-" if part["year"].nunique() > 1 else "none"
            ax.errorbar(part["year"], estimate, yerr=yerr, marker="o", linestyle=line_style, capsize=3, label=social_group)
        years = sorted(pd.to_numeric(target["year"], errors="coerce").dropna().astype(int).unique().tolist())
        ax.set_xticks(years)
        ax.tick_params(axis="x", labelrotation=45 if len(years) > 4 else 0)
        ax.set(xlabel="Année", ylabel=f"P({target_vote})", ylim=(0, 1))
        rungs = sorted(pd.to_numeric(target["n_communes_requested"], errors="coerce").dropna().astype(int).unique())
        statuses = sorted(target["diagnostic_status"].dropna().astype(str).unique())
        ax.set_title(
            f"{scenario_id} — {model_key} — {election_type}\n"
            f"paliers={rungs}, diagnostics={statuses}"
        )
        ax.legend()
        out = FIGURE_DIR / "longitudinal" / f"probabilities__{scenario_id}__{model_key}__{election_type}"
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.tight_layout()
        fig.savefig(out.with_suffix(".png"), dpi=170)
        fig.savefig(out.with_suffix(".svg"))
        plt.close(fig)

        pivot = target.pivot_table(index=["year", "election_id"], columns="social_group", values="estimate", aggfunc="first")
        if pivot.shape[1] < 2:
            continue
        first, second = pivot.columns[:2]
        gap = pivot[first] - pivot[second]
        fig, ax = plt.subplots(figsize=(8.2, 4.4))
        ax.scatter(gap.index.get_level_values("year"), gap.values)
        ax.axhline(0, color="black", linewidth=0.8)
        ax.set_xticks(years)
        ax.tick_params(axis="x", labelrotation=45 if len(years) > 4 else 0)
        ax.set(xlabel="Année", ylabel=f"{first} − {second}")
        ax.set_title(
            f"Écart {scenario_id} — {model_key} — {election_type}\n"
            f"paliers={rungs}, diagnostics={statuses}"
        )
        out = FIGURE_DIR / "longitudinal" / f"gap__{scenario_id}__{model_key}__{election_type}"
        fig.tight_layout()
        fig.savefig(out.with_suffix(".png"), dpi=170)
        fig.savefig(out.with_suffix(".svg"))
        plt.close(fig)
