from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

from code_longitudinal import density_figures_v2
from code_longitudinal.density_figures_v2 import (
    YEARS,
    fixed_kde_1d,
    generate_density_figures,
    hdr_density_levels,
    joint_density_surfaces,
    validate_density_data,
)


def _density_frame() -> pd.DataFrame:
    rng = np.random.default_rng(20260804)
    rows = []
    for year_index, year in enumerate(YEARS):
        center = np.array([0.25 + 0.08 * year_index, 0.60 - 0.06 * year_index])
        points = np.clip(rng.normal(center, [0.055, 0.07], size=(30, 2)), 0.01, 0.99)
        for unit_index, (b1, b2) in enumerate(points):
            rows.append(
                {
                    "scenario_id": "H0A",
                    "year": year,
                    "unit_id": f"{year}-{unit_index}",
                    "b1_mean": b1,
                    "b2_mean": b2,
                    "b1_weight": 10 + unit_index,
                    "b2_weight": 40 - unit_index,
                }
            )
    return pd.DataFrame(rows)


def test_joint_surfaces_use_one_positive_definite_bandwidth_for_all_periods() -> None:
    data = validate_density_data(_density_frame(), ["H0A"])

    result = joint_density_surfaces(data, weight_column=None, grid_size=41)

    assert set(result.densities) == set(YEARS)
    assert result.bandwidth_matrix.shape == (2, 2)
    assert np.all(np.linalg.eigvalsh(result.bandwidth_matrix) > 0)
    assert all(density.shape == (41, 41) for density in result.densities.values())
    assert all(np.isfinite(density).all() and (density >= 0).all() for density in result.densities.values())


def test_hdr_thresholds_enclose_requested_probability_mass() -> None:
    axis = np.linspace(-2, 2, 81)
    xx, yy = np.meshgrid(axis, axis)
    density = np.exp(-0.5 * (xx**2 + yy**2))

    levels = hdr_density_levels(density)

    assert levels[0.50] > levels[0.80] > levels[0.95]
    total = density.sum()
    for mass, threshold in levels.items():
        enclosed = density[density >= threshold].sum() / total
        assert enclosed >= mass
        assert enclosed - mass < 0.02


def test_population_weighting_moves_a_marginal_density_toward_the_heavy_point() -> None:
    axis = np.linspace(0, 1, 201)
    values = np.array([0.2, 0.8])

    left_heavy = fixed_kde_1d(values, axis, 0.05, weights=np.array([9.0, 1.0]))
    right_heavy = fixed_kde_1d(values, axis, 0.05, weights=np.array([1.0, 9.0]))

    assert axis[np.argmax(left_heavy)] < 0.3
    assert axis[np.argmax(right_heavy)] > 0.7


def test_validation_rejects_a_missing_period_and_duplicate_commune() -> None:
    data = _density_frame()
    with pytest.raises(ValueError, match="exactly the periods"):
        validate_density_data(data.loc[data["year"].ne(1986)], ["H0A"])

    duplicated = pd.concat([data, data.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate"):
        validate_density_data(duplicated, ["H0A"])


def test_end_to_end_generation_is_confined_to_the_requested_v2_paths(monkeypatch) -> None:
    figure_dir = Path("figures") / "v2" / "densities"
    monkeypatch.setattr(density_figures_v2.pd, "read_csv", lambda _: _density_frame())

    def record_save(fig, output_dir: Path, stem: str) -> list[Path]:
        plt.close(fig)
        return [output_dir / f"{stem}.png", output_dir / f"{stem}.svg"]

    monkeypatch.setattr(density_figures_v2, "_save_figure", record_save)

    paths, metadata = generate_density_figures(
        "priority_joint_beta_data.csv",
        figure_dir,
        metadata_path=None,
        scenarios=("H0A",),
        grid_size=31,
    )

    assert len(paths) == 6
    assert all(path.parent == figure_dir for path in paths)
    assert {path.suffix for path in paths} == {".png", ".svg"}
    assert len(metadata) == 4
    assert metadata.loc[metadata["figure_type"].eq("joint_2d"), "bandwidth_scope"].eq(
        "single_period_balanced_matrix_shared_across_1962_1986_2022"
    ).all()
