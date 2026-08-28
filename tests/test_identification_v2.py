from __future__ import annotations

import numpy as np

from code_longitudinal.identification_v2 import assess_identification, tomography_bounds


def test_tomography_bounds_contain_generating_preferences() -> None:
    x = np.array([0.2, 0.5, 0.8])
    b1 = np.array([0.7, 0.6, 0.5])
    b2 = np.array([0.1, 0.2, 0.3])
    y = x * b1 + (1 - x) * b2

    bounds = tomography_bounds(x, y)

    assert np.all((b1 >= bounds["b1_lower"]) & (b1 <= bounds["b1_upper"]))
    assert np.all((b2 >= bounds["b2_lower"]) & (b2 <= bounds["b2_upper"]))


def test_rank_deficient_design_fails_identification() -> None:
    result = assess_identification(np.repeat(0.5, 20), np.linspace(0.2, 0.8, 20))

    assert result["identification_status"] == "fail"
    assert "rank_deficient_ecological_design" in result["identification_reasons"]


def test_identification_metrics_are_bounded() -> None:
    x = np.linspace(0.05, 0.95, 50)
    y = 0.2 + 0.5 * x

    result = assess_identification(x, y)

    assert result["identification_status"] in {"pass", "caveat", "fail"}
    assert 0 <= result["median_max_bound_width"] <= 1
    assert 0 <= result["p90_max_bound_width"] <= 1
