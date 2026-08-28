from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .paths import FIGURE_DIR, OUTPUT_DIR
from .spec_registry import SCENARIO_BY_ID


ELECTION_ID = "leg_2022_r1"
N_COMMUNES = 3000


def _save(fig: plt.Figure, path: Path, *, top: float = 1.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=(0, 0, 1, top))
    fig.savefig(path.with_suffix(".png"), dpi=180)
    fig.savefig(path.with_suffix(".svg"))
    plt.close(fig)


def _current_input(scenario_id: str) -> pd.DataFrame | None:
    matches = sorted(
        (OUTPUT_DIR / "model_ready").glob(
            f"{ELECTION_ID}__{scenario_id}__*__n{N_COMMUNES}.parquet"
        ),
        key=lambda path: path.stat().st_mtime_ns,
    )
    return pd.read_parquet(matches[-1]) if matches else None


def _nls_snapshot(estimates: pd.DataFrame, scenario_id: str) -> pd.DataFrame:
    if estimates.empty:
        return estimates.copy()
    requested = pd.to_numeric(estimates["n_communes_requested"], errors="coerce")
    mask = (
        estimates["election_id"].eq(ELECTION_ID)
        & estimates["scenario_id"].eq(scenario_id)
        & estimates["model_key"].eq("rosen_nls")
        & requested.eq(N_COMMUNES)
        & estimates["diagnostic_status"].eq("pass")
    )
    selected = estimates.loc[mask].copy()
    if selected.empty:
        return selected
    # A deterministic run registry may contain superseded successful runs. Keep
    # only the newest complete probability matrix for the election snapshot.
    run_id = sorted(selected["run_id"].astype(str).unique())[-1]
    return selected.loc[selected["run_id"].astype(str).eq(run_id)].copy()


def _probability_matrix(estimates: pd.DataFrame, scenario_id: str) -> pd.DataFrame:
    scenario = SCENARIO_BY_ID[scenario_id]
    matrix = estimates.pivot(
        index="social_group", columns="vote_category", values="estimate"
    )
    return matrix.reindex(
        index=list(scenario.social_groups), columns=list(scenario.vote_categories)
    ).astype(float)


def _plot_matrix(matrix: pd.DataFrame, scenario_id: str, output_root: Path) -> None:
    fig, ax = plt.subplots(figsize=(9.2, max(3.8, 0.62 * len(matrix) + 1.7)))
    image = ax.imshow(matrix.to_numpy(), vmin=0, vmax=1, cmap="Blues", aspect="auto")
    ax.set_xticks(range(len(matrix.columns)), matrix.columns, rotation=25, ha="right")
    ax.set_yticks(range(len(matrix.index)), matrix.index)
    for row in range(len(matrix.index)):
        for column in range(len(matrix.columns)):
            value = matrix.iat[row, column]
            ax.text(column, row, f"{value:.3f}", ha="center", va="center", color="white" if value > 0.52 else "black", fontsize=8)
    ax.set_title(f"{scenario_id} — probabilités NLS estimées, législatives 2022\n3 000 communes, diagnostic pass")
    ax.set_xlabel("Bloc politique")
    ax.set_ylabel("Groupe social")
    fig.colorbar(image, ax=ax, label="Probabilité estimée", shrink=0.84)
    _save(fig, output_root / f"nls_probability_matrix__{scenario_id}")


def _plot_composition(matrix: pd.DataFrame, scenario_id: str, output_root: Path) -> None:
    fig, ax = plt.subplots(figsize=(9.2, max(3.8, 0.58 * len(matrix) + 1.8)))
    left = np.zeros(len(matrix))
    colors = plt.get_cmap("RdYlBu_r")(np.linspace(0.08, 0.92, len(matrix.columns)))
    for color, vote in zip(colors, matrix.columns):
        values = matrix[vote].to_numpy()
        ax.barh(matrix.index, values, left=left, label=vote, color=color)
        left += values
    ax.set_xlim(0, 1)
    ax.set_xlabel("Répartition estimée du vote (somme = 1)")
    ax.set_ylabel("Groupe social")
    ax.set_title(f"{scenario_id} — composition politique estimée, législatives 2022")
    ax.legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.16), frameon=False)
    _save(fig, output_root / f"nls_composition__{scenario_id}")


def _fit_quality(data: pd.DataFrame, matrix: pd.DataFrame, scenario_id: str) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    groups = list(matrix.index)
    votes = list(matrix.columns)
    X = data[[f"X__{group}" for group in groups]].to_numpy(dtype=float)
    N = data["N_g"].to_numpy(dtype=float)
    observed = data[[f"Y__{vote}" for vote in votes]].to_numpy(dtype=float) / N[:, None]
    predicted = X @ matrix.to_numpy(dtype=float)
    rows: list[dict[str, object]] = []
    for column, vote in enumerate(votes):
        residual = predicted[:, column] - observed[:, column]
        rows.append(
            {
                "election_id": ELECTION_ID,
                "scenario_id": scenario_id,
                "model_key": "rosen_nls",
                "n_communes": len(data),
                "vote_category": vote,
                "rmse": float(np.sqrt(np.mean(np.square(residual)))),
                "mae": float(np.mean(np.abs(residual))),
                "max_absolute_error": float(np.max(np.abs(residual))),
                "observed_mean": float(np.mean(observed[:, column])),
                "predicted_mean": float(np.mean(predicted[:, column])),
            }
        )
    return pd.DataFrame(rows), observed, predicted


def _plot_fit_quality(observed: np.ndarray, predicted: np.ndarray, metrics: pd.DataFrame, scenario_id: str, output_root: Path) -> None:
    votes = metrics["vote_category"].tolist()
    fig, axes = plt.subplots(2, 3, figsize=(12.0, 7.5), sharex=True, sharey=True)
    for column, (ax, vote) in enumerate(zip(axes.flat, votes)):
        ax.hexbin(observed[:, column], predicted[:, column], gridsize=32, mincnt=1, cmap="viridis")
        ax.plot([0, 1], [0, 1], color="black", linewidth=0.8, linestyle="--")
        row = metrics.iloc[column]
        ax.set_title(f"{vote}\nRMSE={row['rmse']:.3f}; MAE={row['mae']:.3f}")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
    axes.flat[-1].axis("off")
    for ax in axes[:, 0]:
        ax.set_ylabel("Part prédite")
    for ax in axes[-1, :]:
        ax.set_xlabel("Part observée")
    fig.suptitle(f"{scenario_id} — ajustement des marges communales, législatives 2022\nChaque hexagone regroupe des communes; diagonale = prédiction parfaite", y=0.98)
    _save(fig, output_root / f"nls_observed_vs_predicted__{scenario_id}", top=0.88)


def _plot_input_margins(output_root: Path) -> pd.DataFrame:
    scenario_ids = [f"H{index}" for index in range(1, 8)]
    scenario_ids = ["H0A", "H0B", "H0C", *scenario_ids]
    fig, axes = plt.subplots(2, 5, figsize=(15.0, 6.5), sharex=True, sharey=True)
    integrity_rows: list[dict[str, object]] = []
    for ax, scenario_id in zip(axes.flat, scenario_ids):
        data = _current_input(scenario_id)
        scenario = SCENARIO_BY_ID[scenario_id]
        if data is None:
            ax.set_title(f"{scenario_id} — absent")
            ax.axis("off")
            continue
        social = next(iter(scenario.social_groups))
        vote = scenario.vote_categories[0]
        N = data["N_g"].to_numpy(dtype=float)
        x = data[f"N__{social}"].to_numpy(dtype=float) / N
        y = data[f"Y__{vote}"].to_numpy(dtype=float) / N
        ax.hexbin(x, y, gridsize=30, mincnt=1, cmap="magma")
        ax.set_title(f"{scenario_id}: {social} / {vote}")
        integrity_rows.append(
            {
                "election_id": ELECTION_ID,
                "scenario_id": scenario_id,
                "n_rows": len(data),
                "n_unique_units": data["unit_id"].astype(str).nunique(),
                "n_duplicate_units": int(data["unit_id"].astype(str).duplicated().sum()),
                "minimum_N_g": float(np.min(N)),
                "maximum_social_count_gap": float(
                    np.max(np.abs(data[[f"N__{key}" for key in scenario.social_groups]].sum(axis=1).to_numpy() - N))
                ),
                "maximum_vote_count_gap": float(
                    np.max(np.abs(data[[f"Y__{key}" for key in scenario.vote_categories]].sum(axis=1).to_numpy() - N))
                ),
            }
        )
    for ax in axes[:, 0]:
        ax.set_ylabel("Marge politique observée")
    for ax in axes[-1, :]:
        ax.set_xlabel("Marge sociale recalée")
    fig.suptitle("Législatives 2022 — marges d’entrée des scénarios 2×2\nDescriptif des données préparées; ce graphique n’est pas une estimation écologique", y=0.98)
    _save(fig, output_root / "input_margins__all_2x2_scenarios", top=0.88)
    return pd.DataFrame(integrity_rows)


def plot_election_2022(estimates: pd.DataFrame) -> dict[str, int]:
    """Build honest single-election figures and their machine-readable QA tables."""
    output_root = FIGURE_DIR / "election_2022"
    output_root.mkdir(parents=True, exist_ok=True)
    for pattern in ("*.png", "*.svg"):
        for path in output_root.glob(pattern):
            path.unlink()

    quality_frames: list[pd.DataFrame] = []
    for scenario_id in ("RXC1", "RXC2"):
        snapshot = _nls_snapshot(estimates, scenario_id)
        data = _current_input(scenario_id)
        if snapshot.empty or data is None:
            continue
        matrix = _probability_matrix(snapshot, scenario_id)
        if matrix.isna().any().any() or not np.isfinite(matrix.to_numpy()).all():
            continue
        _plot_matrix(matrix, scenario_id, output_root)
        _plot_composition(matrix, scenario_id, output_root)
        metrics, observed, predicted = _fit_quality(data, matrix, scenario_id)
        quality_frames.append(metrics)
        _plot_fit_quality(observed, predicted, metrics, scenario_id, output_root)

    quality = pd.concat(quality_frames, ignore_index=True) if quality_frames else pd.DataFrame()
    quality.to_csv(OUTPUT_DIR / "election_2022_fit_quality.csv", index=False, encoding="utf-8-sig")
    integrity = _plot_input_margins(output_root)
    integrity.to_csv(OUTPUT_DIR / "election_2022_input_integrity.csv", index=False, encoding="utf-8-sig")
    return {"fit_quality_rows": len(quality), "input_integrity_rows": len(integrity)}
