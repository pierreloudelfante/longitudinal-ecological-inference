"""Versioned density figures for the three priority longitudinal periods.

This module reads the already-versioned commune-level posterior means and
writes only below ``figures/v2/densities`` (plus optional V2 bandwidth
metadata).  Historical figures and the V1 finalizer are deliberately outside
its scope.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd

from .paths import FIGURE_DIR, OUTPUT_DIR


YEARS = (1962, 1986, 2022)
DEFAULT_SCENARIOS = ("H0A", "H1", "H2", "H4")
INPUT_PATH = OUTPUT_DIR / "priority_joint_beta_data.csv"
FIGURE_PATH = FIGURE_DIR / "v2" / "densities"
METADATA_PATH = OUTPUT_DIR / "v2" / "density_bandwidths.csv"

INK = "#20262E"
MUTED = "#59636E"
GRID = "#E2E6EA"
BLUE = "#315C8C"
GOLD = "#C6922B"
PINK = "#B45A78"
YEAR_COLORS = {1962: BLUE, 1986: GOLD, 2022: PINK}
YEAR_STYLES = {1962: "-", 1986: "--", 2022: ":"}
JOINT_CMAP = LinearSegmentedColormap.from_list(
    "joint_beta_v2",
    ["#F7F9FB", "#D7E2EE", "#7D9DBC", BLUE, "#173A5E"],
)

SCENARIO_LABELS = {
    "H0A": "Abstention — ouvriers et employés vs autres CSP",
    "H1": "Vote à gauche — ouvriers et employés vs autres CSP",
    "H2": "Vote à gauche — ouvriers vs autres CSP",
    "H4": "Vote à droite — agriculteurs et indépendants vs salariés",
}

BETA_AXIS_LABELS = {
    "H0A": ("β₁ — ouvriers + employés", "β₂ — autres CSP"),
    "H1": ("β₁ — ouvriers + employés", "β₂ — autres CSP"),
    "H2": ("β₁ — ouvriers", "β₂ — autres CSP"),
    "H4": ("β₁ — agriculteurs + indépendants", "β₂ — salariés"),
}


@dataclass(frozen=True)
class JointDensitySurfaces:
    axis: np.ndarray
    densities: dict[int, np.ndarray]
    bandwidth_matrix: np.ndarray
    reference_effective_n: float
    weight_basis: str


@dataclass(frozen=True)
class MarginalDensitySurfaces:
    axis: np.ndarray
    densities: dict[int, np.ndarray]
    bandwidth_sd: float
    reference_effective_n: float
    value_column: str
    weight_column: str


def validate_density_data(data: pd.DataFrame, scenarios: Sequence[str]) -> pd.DataFrame:
    """Validate and normalize the commune-level input used by every figure."""

    required = {
        "scenario_id",
        "year",
        "unit_id",
        "b1_mean",
        "b2_mean",
        "b1_weight",
        "b2_weight",
    }
    missing = sorted(required.difference(data.columns))
    if missing:
        raise ValueError(f"density input is missing columns: {', '.join(missing)}")
    frame = data.copy()
    for column in ("year", "b1_mean", "b2_mean", "b1_weight", "b2_weight"):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    frame["year"] = frame["year"].astype(int)
    frame["scenario_id"] = frame["scenario_id"].astype(str)
    frame["unit_id"] = frame["unit_id"].astype(str)
    frame = frame.loc[frame["scenario_id"].isin(scenarios)].copy()
    if frame.empty:
        raise ValueError("density input contains none of the requested scenarios")
    numeric = frame[["b1_mean", "b2_mean", "b1_weight", "b2_weight"]].to_numpy(float)
    if not np.isfinite(numeric).all():
        raise ValueError("density input contains non-finite beta values or weights")
    if np.any((frame[["b1_mean", "b2_mean"]].to_numpy(float) < 0) | (frame[["b1_mean", "b2_mean"]].to_numpy(float) > 1)):
        raise ValueError("posterior beta means must lie in [0, 1]")
    if np.any(frame[["b1_weight", "b2_weight"]].to_numpy(float) < 0):
        raise ValueError("population weights must be non-negative")
    if frame.duplicated(["scenario_id", "year", "unit_id"]).any():
        raise ValueError("density input contains duplicate scenario/year/unit rows")
    frame["N_total"] = frame["b1_weight"] + frame["b2_weight"]
    if np.any(frame["N_total"].to_numpy(float) <= 0):
        raise ValueError("every commune must have a strictly positive N_total")

    for scenario_id in scenarios:
        subset = frame.loc[frame["scenario_id"].eq(scenario_id)]
        observed_years = set(subset["year"].unique())
        if observed_years != set(YEARS):
            raise ValueError(
                f"{scenario_id} must contain exactly the periods {YEARS}; found {sorted(observed_years)}"
            )
        for year in YEARS:
            period = subset.loc[subset["year"].eq(year)]
            if len(period) < 3:
                raise ValueError(f"{scenario_id}/{year} has too few communes for a density estimate")
            for weight_column in ("b1_weight", "b2_weight", "N_total"):
                if float(period[weight_column].sum()) <= 0:
                    raise ValueError(f"{scenario_id}/{year} has zero total {weight_column}")
    return frame


def effective_sample_size(weights: np.ndarray) -> float:
    values = np.asarray(weights, dtype=float)
    total = float(values.sum())
    squared = float(values @ values)
    if total <= 0 or squared <= 0:
        raise ValueError("weights must have positive total and squared total")
    return total * total / squared


def _period_balanced_weights(data: pd.DataFrame, weight_column: str | None) -> np.ndarray:
    balanced = np.empty(len(data), dtype=float)
    for year in YEARS:
        mask = data["year"].eq(year).to_numpy()
        raw = (
            np.ones(int(mask.sum()), dtype=float)
            if weight_column is None
            else data.loc[mask, weight_column].to_numpy(dtype=float)
        )
        total = float(raw.sum())
        if total <= 0:
            raise ValueError(f"period {year} has a zero weight denominator")
        balanced[mask] = raw / total
    return balanced


def _regularized_covariance(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    total = float(weights.sum())
    mean = np.sum(values * weights[:, None], axis=0) / total
    centered = values - mean
    covariance = (centered * weights[:, None]).T @ centered / total
    covariance = (covariance + covariance.T) / 2
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    ceiling = max(float(eigenvalues.max()), 1e-8)
    eigenvalues = np.maximum(eigenvalues, max(ceiling * 1e-6, 1e-10))
    return (eigenvectors * eigenvalues) @ eigenvectors.T


def common_bandwidth_matrix(
    data: pd.DataFrame,
    *,
    weight_column: str | None,
) -> tuple[np.ndarray, float]:
    """Return one fixed 2D KDE bandwidth matrix shared by all periods.

    The pooled covariance gives each period equal total influence.  Within a
    period, observations are either equally weighted or weighted by the named
    population column.  Scott's factor uses the median period-level effective
    sample size rather than the pooled row count.
    """

    values = data[["b1_mean", "b2_mean"]].to_numpy(dtype=float)
    pooled_weights = _period_balanced_weights(data, weight_column)
    covariance = _regularized_covariance(values, pooled_weights)
    period_effective_n = []
    for year in YEARS:
        period = data.loc[data["year"].eq(year)]
        weights = (
            np.ones(len(period), dtype=float)
            if weight_column is None
            else period[weight_column].to_numpy(dtype=float)
        )
        period_effective_n.append(effective_sample_size(weights))
    reference_n = float(np.median(period_effective_n))
    scott_factor = reference_n ** (-1.0 / 6.0)
    return covariance * scott_factor**2, reference_n


def common_bandwidth_1d(
    data: pd.DataFrame,
    *,
    value_column: str,
    weight_column: str,
) -> tuple[float, float]:
    values = data[value_column].to_numpy(dtype=float)
    pooled_weights = _period_balanced_weights(data, weight_column)
    mean = float(np.sum(values * pooled_weights) / pooled_weights.sum())
    variance = float(np.sum(pooled_weights * (values - mean) ** 2) / pooled_weights.sum())
    variance = max(variance, 1e-10)
    period_effective_n = [
        effective_sample_size(data.loc[data["year"].eq(year), weight_column].to_numpy(dtype=float))
        for year in YEARS
    ]
    reference_n = float(np.median(period_effective_n))
    scott_factor = reference_n ** (-1.0 / 5.0)
    return float(np.sqrt(variance) * scott_factor), reference_n


def fixed_kde_2d(
    values: np.ndarray,
    axis: np.ndarray,
    bandwidth_matrix: np.ndarray,
    *,
    weights: np.ndarray | None = None,
    chunk_size: int = 1024,
) -> np.ndarray:
    """Evaluate a Gaussian KDE using an explicit, fixed 2D covariance."""

    samples = np.asarray(values, dtype=float)
    grid_axis = np.asarray(axis, dtype=float)
    bandwidth = np.asarray(bandwidth_matrix, dtype=float)
    if samples.ndim != 2 or samples.shape[1] != 2:
        raise ValueError("values must have shape (n_observations, 2)")
    if bandwidth.shape != (2, 2):
        raise ValueError("bandwidth_matrix must have shape (2, 2)")
    sample_weights = np.ones(len(samples), dtype=float) if weights is None else np.asarray(weights, dtype=float)
    if sample_weights.shape != (len(samples),) or np.any(sample_weights < 0) or not np.isfinite(sample_weights).all():
        raise ValueError("weights must be a finite, non-negative vector matching values")
    if float(sample_weights.sum()) <= 0:
        raise ValueError("weights must have a strictly positive sum")
    sign, log_determinant = np.linalg.slogdet(bandwidth)
    if sign <= 0:
        raise ValueError("bandwidth_matrix must be positive definite")
    inverse = np.linalg.inv(bandwidth)
    xx, yy = np.meshgrid(grid_axis, grid_axis)
    queries = np.column_stack([xx.ravel(), yy.ravel()])
    result = np.empty(len(queries), dtype=float)
    normalizer = 2.0 * np.pi * np.exp(0.5 * log_determinant) * float(sample_weights.sum())
    for start in range(0, len(queries), chunk_size):
        stop = min(start + chunk_size, len(queries))
        differences = queries[start:stop, None, :] - samples[None, :, :]
        mahalanobis = np.einsum(
            "qni,ij,qnj->qn", differences, inverse, differences, optimize=True
        )
        result[start:stop] = np.exp(-0.5 * mahalanobis) @ sample_weights / normalizer
    return result.reshape(xx.shape)


def fixed_kde_1d(
    values: np.ndarray,
    axis: np.ndarray,
    bandwidth_sd: float,
    *,
    weights: np.ndarray,
) -> np.ndarray:
    samples = np.asarray(values, dtype=float)
    grid_axis = np.asarray(axis, dtype=float)
    sample_weights = np.asarray(weights, dtype=float)
    if samples.ndim != 1 or sample_weights.shape != samples.shape:
        raise ValueError("values and weights must be matching one-dimensional vectors")
    if bandwidth_sd <= 0 or not np.isfinite(bandwidth_sd):
        raise ValueError("bandwidth_sd must be finite and strictly positive")
    if np.any(sample_weights < 0) or not np.isfinite(sample_weights).all() or float(sample_weights.sum()) <= 0:
        raise ValueError("weights must be finite, non-negative, and have positive total")
    standardized = (grid_axis[:, None] - samples[None, :]) / bandwidth_sd
    kernels = np.exp(-0.5 * standardized**2) / np.sqrt(2.0 * np.pi)
    return kernels @ sample_weights / (bandwidth_sd * float(sample_weights.sum()))


def joint_density_surfaces(
    data: pd.DataFrame,
    *,
    weight_column: str | None,
    grid_size: int = 121,
) -> JointDensitySurfaces:
    if grid_size < 21:
        raise ValueError("grid_size must be at least 21")
    bandwidth, reference_n = common_bandwidth_matrix(data, weight_column=weight_column)
    axis = np.linspace(0.0, 1.0, grid_size)
    densities: dict[int, np.ndarray] = {}
    for year in YEARS:
        period = data.loc[data["year"].eq(year)]
        weights = None if weight_column is None else period[weight_column].to_numpy(dtype=float)
        densities[year] = fixed_kde_2d(
            period[["b1_mean", "b2_mean"]].to_numpy(dtype=float),
            axis,
            bandwidth,
            weights=weights,
        )
    return JointDensitySurfaces(
        axis=axis,
        densities=densities,
        bandwidth_matrix=bandwidth,
        reference_effective_n=reference_n,
        weight_basis="equal_communes" if weight_column is None else weight_column,
    )


def marginal_density_surfaces(
    data: pd.DataFrame,
    *,
    value_column: str,
    weight_column: str,
    grid_size: int = 401,
) -> MarginalDensitySurfaces:
    bandwidth, reference_n = common_bandwidth_1d(
        data, value_column=value_column, weight_column=weight_column
    )
    axis = np.linspace(0.0, 1.0, grid_size)
    densities = {}
    for year in YEARS:
        period = data.loc[data["year"].eq(year)]
        densities[year] = fixed_kde_1d(
            period[value_column].to_numpy(dtype=float),
            axis,
            bandwidth,
            weights=period[weight_column].to_numpy(dtype=float),
        )
    return MarginalDensitySurfaces(
        axis=axis,
        densities=densities,
        bandwidth_sd=bandwidth,
        reference_effective_n=reference_n,
        value_column=value_column,
        weight_column=weight_column,
    )


def hdr_density_levels(density: np.ndarray, masses: Iterable[float] = (0.50, 0.80, 0.95)) -> dict[float, float]:
    """Return density thresholds whose upper level sets contain each mass."""

    surface = np.asarray(density, dtype=float)
    requested = tuple(float(mass) for mass in masses)
    if not requested or any(mass <= 0 or mass >= 1 for mass in requested):
        raise ValueError("HDR masses must lie strictly between 0 and 1")
    if surface.ndim != 2 or not np.isfinite(surface).all() or np.any(surface < 0):
        raise ValueError("density must be a finite, non-negative matrix")
    flat = surface.ravel()
    total = float(flat.sum())
    if total <= 0:
        raise ValueError("density must have positive total mass")
    ordered = np.sort(flat)[::-1]
    cumulative = np.cumsum(ordered) / total
    levels = {}
    for mass in requested:
        index = min(int(np.searchsorted(cumulative, mass, side="left")), len(ordered) - 1)
        levels[mass] = float(ordered[index])
    return levels


def _save_figure(fig: plt.Figure, output_dir: Path, stem: str) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = [output_dir / f"{stem}.png", output_dir / f"{stem}.svg"]
    fig.savefig(paths[0], dpi=200, bbox_inches="tight", facecolor="white")
    fig.savefig(paths[1], bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return paths


def _draw_hdr_contours(ax: plt.Axes, xx: np.ndarray, yy: np.ndarray, density: np.ndarray) -> None:
    thresholds = hdr_density_levels(density)
    style_by_mass = {0.50: "-", 0.80: "--", 0.95: ":"}
    ordered = sorted(thresholds.items(), key=lambda item: item[1])
    unique: list[tuple[float, float]] = []
    for mass, threshold in ordered:
        if not unique or threshold > unique[-1][1]:
            unique.append((mass, threshold))
    if not unique:
        return
    contour = ax.contour(
        xx,
        yy,
        density,
        levels=[threshold for _, threshold in unique],
        colors=INK,
        linewidths=0.9,
        linestyles=[style_by_mass[mass] for mass, _ in unique],
        alpha=0.9,
    )
    labels = {threshold: f"{int(mass * 100)} %" for mass, threshold in unique}
    ax.clabel(contour, contour.levels, inline=True, fmt=labels, fontsize=7.5)


def plot_joint_density_v2(
    data: pd.DataFrame,
    scenario_id: str,
    output_dir: Path,
    *,
    weight_column: str | None,
    grid_size: int,
) -> tuple[list[Path], dict[str, object]]:
    surfaces = joint_density_surfaces(data, weight_column=weight_column, grid_size=grid_size)
    axis = surfaces.axis
    xx, yy = np.meshgrid(axis, axis)
    maximum = max(float(density.max()) for density in surfaces.densities.values())
    norm = Normalize(vmin=0, vmax=maximum)
    x_label, y_label = BETA_AXIS_LABELS.get(scenario_id, ("β₁", "β₂"))
    weighted = weight_column is not None
    variant_label = (
        "KDE pondérée par N_total (population communale)"
        if weighted
        else "KDE à poids égal entre communes"
    )

    fig, axes = plt.subplots(1, 3, figsize=(14.2, 5.35), sharex=True, sharey=True, constrained_layout=True)
    mesh = None
    for ax, year in zip(axes, YEARS, strict=True):
        period = data.loc[data["year"].eq(year)]
        density = surfaces.densities[year]
        mesh = ax.pcolormesh(
            xx, yy, density, cmap=JOINT_CMAP, norm=norm, shading="auto", rasterized=True
        )
        _draw_hdr_contours(ax, xx, yy, density)
        if weighted:
            weights = period["N_total"].to_numpy(dtype=float)
            scale = np.quantile(weights, 0.99)
            sizes = 4.0 + 22.0 * np.sqrt(np.clip(weights / max(scale, 1.0), 0, 1))
        else:
            sizes = np.full(len(period), 7.0)
        ax.scatter(
            period["b1_mean"],
            period["b2_mean"],
            s=sizes,
            facecolors="white",
            edgecolors=INK,
            linewidths=0.20,
            alpha=0.32,
            rasterized=True,
        )
        ax.plot([0, 1], [0, 1], linestyle="--", color="#4F5964", linewidth=1.0)
        ax.set_title(f"{year}\nn={len(period)} communes", fontsize=10.5, color=INK)
        ax.set(xlim=(0, 1), ylim=(0, 1), xlabel=x_label)
        ax.set_xticks([0, 0.25, 0.50, 0.75, 1.0])
        ax.set_yticks([0, 0.25, 0.50, 0.75, 1.0])
        ax.set_aspect("equal", adjustable="box")
        ax.grid(False)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel(y_label)
    if mesh is not None:
        colorbar = fig.colorbar(mesh, ax=axes, fraction=0.028, pad=0.02)
        colorbar.set_label("Densité KDE — échelle commune")
    contour_legend = [
        Line2D([0], [0], color=INK, lw=0.9, ls=style, label=f"HDR {int(mass * 100)} %")
        for mass, style in ((0.50, "-"), (0.80, "--"), (0.95, ":"))
    ]
    axes[-1].legend(handles=contour_legend, loc="lower right", frameon=True, fontsize=8)
    title = SCENARIO_LABELS.get(scenario_id, scenario_id)
    fig.suptitle(f"{scenario_id} — densité jointe de β₁ et β₂\n{title}", fontsize=13.5, color=INK)
    point_note = "aire des points proportionnelle à N_total" if weighted else "points de taille constante"
    fig.supxlabel(
        f"{variant_label}; même matrice de lissage H pour 1962, 1986 et 2022; {point_note}.",
        fontsize=9,
        color=MUTED,
    )
    suffix = "N_total_weighted" if weighted else "equal_communes"
    paths = _save_figure(fig, output_dir, f"joint_beta_{scenario_id}_common_bandwidth_{suffix}")
    bandwidth = surfaces.bandwidth_matrix
    metadata = {
        "scenario_id": scenario_id,
        "figure_type": "joint_2d",
        "weight_basis": surfaces.weight_basis,
        "bandwidth_h11": float(bandwidth[0, 0]),
        "bandwidth_h12": float(bandwidth[0, 1]),
        "bandwidth_h22": float(bandwidth[1, 1]),
        "bandwidth_sd": np.nan,
        "reference_effective_n": surfaces.reference_effective_n,
        "bandwidth_scope": "single_period_balanced_matrix_shared_across_1962_1986_2022",
    }
    return paths, metadata


def plot_marginal_density_v2(
    data: pd.DataFrame,
    scenario_id: str,
    output_dir: Path,
    *,
    grid_size: int,
) -> tuple[list[Path], list[dict[str, object]]]:
    specifications = (
        ("b1_mean", "b1_weight", "β₁ pondérée par N1"),
        ("b2_mean", "b2_weight", "β₂ pondérée par N2"),
    )
    results = [
        marginal_density_surfaces(
            data,
            value_column=value_column,
            weight_column=weight_column,
            grid_size=max(grid_size * 3, 121),
        )
        for value_column, weight_column, _ in specifications
    ]
    fig, axes = plt.subplots(1, 2, figsize=(11.8, 4.65), sharex=True, constrained_layout=True)
    for ax, result, (_, _, panel_title) in zip(axes, results, specifications, strict=True):
        for year in YEARS:
            density = result.densities[year]
            ax.plot(
                result.axis,
                density,
                color=YEAR_COLORS[year],
                linestyle=YEAR_STYLES[year],
                linewidth=2.0,
                label=str(year),
            )
            ax.fill_between(result.axis, 0, density, color=YEAR_COLORS[year], alpha=0.055)
        ax.set_title(panel_title, fontsize=11, color=INK)
        ax.set_xlim(0, 1)
        ax.set_ylim(bottom=0)
        ax.set_xlabel("Moyenne postérieure communale")
        ax.set_ylabel("Densité pondérée")
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(frameon=False, title="Période")
    title = SCENARIO_LABELS.get(scenario_id, scenario_id)
    fig.suptitle(f"{scenario_id} — densités marginales sociales comparées\n{title}", fontsize=13.5, color=INK)
    fig.supxlabel(
        "Pondération par l’effectif du groupe; largeur de lissage fixe entre les trois périodes dans chaque panneau.",
        fontsize=9,
        color=MUTED,
    )
    paths = _save_figure(fig, output_dir, f"marginal_beta_{scenario_id}_group_population_weighted")
    metadata = []
    for result in results:
        metadata.append(
            {
                "scenario_id": scenario_id,
                "figure_type": f"marginal_1d_{result.value_column}",
                "weight_basis": result.weight_column,
                "bandwidth_h11": np.nan,
                "bandwidth_h12": np.nan,
                "bandwidth_h22": np.nan,
                "bandwidth_sd": result.bandwidth_sd,
                "reference_effective_n": result.reference_effective_n,
                "bandwidth_scope": "single_bandwidth_shared_across_1962_1986_2022",
            }
        )
    return paths, metadata


def generate_density_figures(
    input_path: Path | str = INPUT_PATH,
    output_dir: Path | str = FIGURE_PATH,
    *,
    metadata_path: Path | str | None = METADATA_PATH,
    scenarios: Sequence[str] = DEFAULT_SCENARIOS,
    grid_size: int = 121,
) -> tuple[list[Path], pd.DataFrame]:
    """Generate every V2 density figure without touching V1 artifacts."""

    input_path = Path(input_path)
    output_dir = Path(output_dir)
    data = validate_density_data(pd.read_csv(input_path), scenarios)
    output_paths: list[Path] = []
    metadata_rows: list[dict[str, object]] = []
    for scenario_id in scenarios:
        scenario_data = data.loc[data["scenario_id"].eq(scenario_id)].copy()
        for weight_column in (None, "N_total"):
            paths, metadata = plot_joint_density_v2(
                scenario_data,
                scenario_id,
                output_dir,
                weight_column=weight_column,
                grid_size=grid_size,
            )
            output_paths.extend(paths)
            metadata_rows.append(metadata)
        paths, metadata = plot_marginal_density_v2(
            scenario_data,
            scenario_id,
            output_dir,
            grid_size=grid_size,
        )
        output_paths.extend(paths)
        metadata_rows.extend(metadata)
    metadata_frame = pd.DataFrame(metadata_rows)
    if metadata_path is not None:
        metadata_output = Path(metadata_path)
        metadata_output.parent.mkdir(parents=True, exist_ok=True)
        metadata_frame.to_csv(metadata_output, index=False, encoding="utf-8-sig")
    return output_paths, metadata_frame


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT_PATH)
    parser.add_argument("--output-dir", type=Path, default=FIGURE_PATH)
    parser.add_argument("--metadata-path", type=Path, default=METADATA_PATH)
    parser.add_argument("--scenarios", nargs="+", default=list(DEFAULT_SCENARIOS))
    parser.add_argument("--grid-size", type=int, default=121)
    args = parser.parse_args()
    paths, metadata = generate_density_figures(
        args.input,
        args.output_dir,
        metadata_path=args.metadata_path,
        scenarios=tuple(args.scenarios),
        grid_size=args.grid_size,
    )
    print(f"Generated {len(paths)} figure files and {len(metadata)} bandwidth rows.")


if __name__ == "__main__":
    main()


__all__ = [
    "DEFAULT_SCENARIOS",
    "FIGURE_PATH",
    "METADATA_PATH",
    "YEARS",
    "common_bandwidth_1d",
    "common_bandwidth_matrix",
    "effective_sample_size",
    "fixed_kde_1d",
    "fixed_kde_2d",
    "generate_density_figures",
    "hdr_density_levels",
    "joint_density_surfaces",
    "marginal_density_surfaces",
    "validate_density_data",
]
