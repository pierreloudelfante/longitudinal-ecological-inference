from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .compare_python_r_ei_all_2x2 import AGGREGATE_COMPARISON_PATH, RETAINED_SCENARIOS
from .spec_registry import ELECTION_BY_ID


def _decorate_elections(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["year"] = result["election_id"].map(
        {key: value.year for key, value in ELECTION_BY_ID.items()}
    )
    result["election_type"] = result["election_id"].map(
        {key: value.election_type for key, value in ELECTION_BY_ID.items()}
    )
    if result[["year", "election_type"]].isna().any().any():
        raise AssertionError("unknown election metadata in Python/R comparison")
    return result


def plot(output_dir: Path) -> dict[str, object]:
    frame = _decorate_elections(pd.read_parquet(AGGREGATE_COMPARISON_PATH))
    expected_pairs = 26 * len(RETAINED_SCENARIOS)
    if frame[["election_id", "scenario_id"]].drop_duplicates().shape[0] != expected_pairs:
        raise AssertionError("Python/R comparison is incomplete for the retained scope")
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    colors = {"python": "#2f6b9a", "r": "#d0823b"}
    labels = {"legislative": "Législatives", "presidential": "Présidentielles"}

    contrast = frame.loc[frame["estimand"].eq("b_1_minus_b_2")].copy()
    for scenario_id in RETAINED_SCENARIOS:
        part = contrast.loc[contrast["scenario_id"].eq(scenario_id)]
        fig, axes = plt.subplots(1, 2, figsize=(13, 4.8), sharey=True, constrained_layout=True)
        for axis, election_type in zip(axes, ("legislative", "presidential")):
            sub = part.loc[part["election_type"].eq(election_type)].sort_values("year")
            x = sub["year"].to_numpy(dtype=int)
            py = sub["mean_python_krt"].to_numpy(dtype=float)
            rr = sub["mean_r_ei"].to_numpy(dtype=float)
            axis.errorbar(
                x - 0.18,
                py,
                yerr=np.vstack(
                    [
                        py - sub["q025_python_krt"].to_numpy(dtype=float),
                        sub["q975_python_krt"].to_numpy(dtype=float) - py,
                    ]
                ),
                fmt="o",
                color=colors["python"],
                capsize=2,
                label="Python KRT beta-binomial",
            )
            axis.errorbar(
                x + 0.18,
                rr,
                yerr=np.vstack(
                    [
                        rr - sub["q025_r_ei"].to_numpy(dtype=float),
                        sub["q975_r_ei"].to_numpy(dtype=float) - rr,
                    ]
                ),
                fmt="s",
                markerfacecolor="white",
                color=colors["r"],
                capsize=2,
                label="R ei / eiPack",
            )
            axis.axhline(0, color="#666666", linestyle="--", linewidth=0.8)
            axis.set_title(labels[election_type])
            axis.set_xticks(x)
            axis.tick_params(axis="x", rotation=55)
            axis.grid(axis="y", color="#e5e7eb", linewidth=0.6)
        axes[0].set_ylabel("Contraste agrégé β1 − β2")
        axes[0].legend(frameon=False, fontsize=8)
        fig.suptitle(
            f"{scenario_id} — comparaison descriptive Python/R\n"
            "Modèles King non identiques : robustesse, pas réplication bit-à-bit"
        )
        path = output_dir / f"python_r_contrast_{scenario_id.lower()}.png"
        fig.savefig(path, dpi=220, bbox_inches="tight")
        plt.close(fig)
        generated.append(path)

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8), constrained_layout=True)
    estimands = ("b_1", "b_2", "b_1_minus_b_2")
    for axis, estimand in zip(axes, estimands):
        part = frame.loc[frame["estimand"].eq(estimand)]
        for scenario_id in RETAINED_SCENARIOS:
            sub = part.loc[part["scenario_id"].eq(scenario_id)]
            axis.scatter(
                sub["mean_python_krt"],
                sub["mean_r_ei"],
                s=18,
                alpha=0.72,
                label=scenario_id,
            )
        lower = min(float(part["mean_python_krt"].min()), float(part["mean_r_ei"].min()))
        upper = max(float(part["mean_python_krt"].max()), float(part["mean_r_ei"].max()))
        axis.plot([lower, upper], [lower, upper], color="#555555", linestyle="--", linewidth=0.9)
        axis.set_title(estimand)
        axis.set_xlabel("Python KRT")
        axis.set_ylabel("R ei / eiPack")
        axis.grid(color="#eeeeee", linewidth=0.5)
    axes[-1].legend(frameon=False, fontsize=8, ncol=2)
    fig.suptitle("Estimations agrégées Python et R — périmètre retenu")
    scatter_path = output_dir / "python_r_aggregate_scatter.png"
    fig.savefig(scatter_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    generated.append(scatter_path)

    summary = {
        "status": "complete",
        "scenarios": list(RETAINED_SCENARIOS),
        "pairs": expected_pairs,
        "figures": [path.name for path in generated],
        "interpretation": "robustness_between_nonidentical_King_models_not_bitwise_replication",
    }
    (output_dir / "python_r_figures_manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    output = Path("work/longitudinal_2000_v1.5_H0A_H1_H0B_H0C_H2_H3_candidate/04_figures_essentielles")
    print(json.dumps(plot(output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
