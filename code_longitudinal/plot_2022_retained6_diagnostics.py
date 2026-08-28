from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .paths import OUTPUT_DIR, ROOT
from .release_scope import load_release_scope


CANDIDATE = ROOT / "work" / "longitudinal_2000_v1.5_H0A_H1_H0B_H0C_H2_H3_candidate"
CONFIG = ROOT / "config" / "releases" / "v1.5_retained6.json"
ELECTION_ID = "leg_2022_r1"


def _bounds(x: np.ndarray, t: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    b1_lower = np.zeros_like(x)
    b1_upper = np.ones_like(x)
    b2_lower = np.zeros_like(x)
    b2_upper = np.ones_like(x)
    mask1 = x > 0
    mask2 = x < 1
    b1_lower[mask1] = np.maximum(0.0, (t[mask1] - (1.0 - x[mask1])) / x[mask1])
    b1_upper[mask1] = np.minimum(1.0, t[mask1] / x[mask1])
    b2_lower[mask2] = np.maximum(0.0, (t[mask2] - x[mask2]) / (1.0 - x[mask2]))
    b2_upper[mask2] = np.minimum(1.0, t[mask2] / (1.0 - x[mask2]))
    return b1_lower, b1_upper, b2_lower, b2_upper


def plot(candidate: Path = CANDIDATE, config: Path = CONFIG) -> dict[str, object]:
    scope = load_release_scope(config)
    commune = pd.read_parquet(candidate / "01_resultats_python" / "longitudinal_krt_commune.parquet")
    output = candidate / "04_figures_essentielles"
    output.mkdir(parents=True, exist_ok=True)
    generated: list[str] = []
    summary_rows: list[dict[str, object]] = []
    for scenario_id in scope.krt_scenarios:
        matches = sorted((OUTPUT_DIR / "model_ready").glob(f"{ELECTION_ID}__{scenario_id}__*__n2000.parquet"))
        if len(matches) != 1:
            raise AssertionError(f"expected one 2022 model-ready input for {scenario_id}; found {len(matches)}")
        source = pd.read_parquet(matches[0])
        x_columns = [column for column in source.columns if column.startswith("X__")]
        y_columns = [column for column in source.columns if column.startswith("Y__")]
        if len(x_columns) != 2 or len(y_columns) != 2:
            raise AssertionError(f"{scenario_id} is not a 2x2 input")
        x = source[x_columns[0]].to_numpy(dtype=float)
        t = source[y_columns[0]].to_numpy(dtype=float) / source["N_g"].to_numpy(dtype=float)
        b1l, b1u, b2l, b2u = _bounds(x, t)
        width = np.maximum(b1u - b1l, b2u - b2l)
        estimates = commune.loc[
            commune["election_id"].eq(ELECTION_ID)
            & commune["scenario_id"].eq(scenario_id),
            ["unit_id", "b1_mean", "b2_mean"],
        ].copy()
        joined = source[["unit_id"]].copy()
        joined["target_share"] = x
        joined["max_bound_width"] = width
        joined["unit_id"] = joined["unit_id"].astype("string")
        estimates["unit_id"] = estimates["unit_id"].astype("string")
        joined = joined.merge(estimates, on="unit_id", how="left", validate="one_to_one")
        if joined[["b1_mean", "b2_mean"]].isna().any().any() or len(joined) != 2000:
            raise AssertionError(f"incomplete 2022 KRT join for {scenario_id}")

        fig, axes = plt.subplots(1, 2, figsize=(12.8, 5.2), sharex=True, sharey=True, constrained_layout=True)
        for axis, color_column, label, cmap in (
            (axes[0], "max_bound_width", "Largeur maximale des bornes", "viridis"),
            (axes[1], "target_share", "Part du groupe cible", "plasma"),
        ):
            points = axis.scatter(
                joined["b1_mean"],
                joined["b2_mean"],
                c=joined[color_column],
                cmap=cmap,
                s=10,
                alpha=0.72,
                linewidths=0,
            )
            axis.plot([0, 1], [0, 1], color="#555555", linestyle="--", linewidth=0.7)
            axis.set_xlim(0, 1)
            axis.set_ylim(0, 1)
            axis.set_xlabel("β1 communal moyen")
            axis.set_title(label)
            fig.colorbar(points, ax=axis, shrink=0.82)
        axes[0].set_ylabel("β2 communal moyen")
        fig.suptitle(f"{scenario_id} - législatives 2022 - nuage brut des 2 000 communes")
        path = output / f"raw_scatter_2022_{scenario_id.lower()}_bounds_target_share.png"
        fig.savefig(path, dpi=220, bbox_inches="tight")
        plt.close(fig)
        generated.append(path.name)
        summary_rows.append(
            {
                "election_id": ELECTION_ID,
                "scenario_id": scenario_id,
                "n_communes": len(joined),
                "median_max_bound_width": float(np.median(width)),
                "p90_max_bound_width": float(np.quantile(width, 0.9)),
                "mean_target_share": float(np.mean(x)),
                "figure": path.name,
            }
        )
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(output / "raw_scatter_2022_retained6_summary.csv", index=False, encoding="utf-8-sig")
    manifest = {
        "status": "complete",
        "election_id": ELECTION_ID,
        "scenarios": list(scope.krt_scenarios),
        "figures": generated,
        "summary_rows": len(summary),
    }
    (output / "raw_scatter_2022_retained6_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    print(json.dumps(plot(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
