from __future__ import annotations

from typing import Any

import numpy as np


def tomography_bounds(group_fraction: Any, vote_fraction: Any) -> dict[str, np.ndarray]:
    x = np.asarray(group_fraction, dtype=float)
    y = np.asarray(vote_fraction, dtype=float)
    if x.shape != y.shape or x.ndim != 1:
        raise ValueError("group_fraction and vote_fraction must be one-dimensional with the same shape")
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("fractions must be finite")
    if np.any((x < 0) | (x > 1) | (y < 0) | (y > 1)):
        raise ValueError("fractions must lie in [0, 1]")

    b1_lower = np.zeros_like(x)
    b1_upper = np.ones_like(x)
    has_group1 = x > 0
    b1_lower[has_group1] = np.maximum(0.0, (y[has_group1] - 1.0 + x[has_group1]) / x[has_group1])
    b1_upper[has_group1] = np.minimum(1.0, y[has_group1] / x[has_group1])

    b2_lower = np.zeros_like(x)
    b2_upper = np.ones_like(x)
    has_group2 = x < 1
    b2_lower[has_group2] = np.maximum(0.0, (y[has_group2] - x[has_group2]) / (1.0 - x[has_group2]))
    b2_upper[has_group2] = np.minimum(1.0, y[has_group2] / (1.0 - x[has_group2]))
    return {
        "b1_lower": b1_lower,
        "b1_upper": b1_upper,
        "b2_lower": b2_lower,
        "b2_upper": b2_upper,
        "b1_width": np.clip(b1_upper - b1_lower, 0.0, 1.0),
        "b2_width": np.clip(b2_upper - b2_lower, 0.0, 1.0),
    }


def assess_identification(group_fraction: Any, vote_fraction: Any) -> dict[str, object]:
    x = np.asarray(group_fraction, dtype=float)
    bounds = tomography_bounds(x, vote_fraction)
    max_width = np.maximum(bounds["b1_width"], bounds["b2_width"])
    design = np.column_stack([x, 1.0 - x])
    singular = np.linalg.svd(design, compute_uv=False)
    rank = int(np.linalg.matrix_rank(design))
    condition = float(np.linalg.cond(design)) if rank == 2 else float("inf")
    metrics = {
        "n_communes": int(len(x)),
        "group_fraction_min": float(x.min()),
        "group_fraction_max": float(x.max()),
        "group_fraction_sd": float(x.std(ddof=1)) if len(x) > 1 else 0.0,
        "design_rank": rank,
        "design_condition": condition,
        "design_singular_values": singular.tolist(),
        "median_b1_bound_width": float(np.median(bounds["b1_width"])),
        "median_b2_bound_width": float(np.median(bounds["b2_width"])),
        "median_max_bound_width": float(np.median(max_width)),
        "p90_max_bound_width": float(np.quantile(max_width, 0.90)),
        "share_max_bound_width_gt_0_8": float(np.mean(max_width > 0.8)),
        "share_boundary_group_fraction": float(np.mean((x == 0) | (x == 1))),
    }
    reasons: list[str] = []
    if rank < 2 or metrics["group_fraction_sd"] < 0.02:
        status = "fail"
        if rank < 2:
            reasons.append("rank_deficient_ecological_design")
        if metrics["group_fraction_sd"] < 0.02:
            reasons.append("insufficient_group_fraction_variation")
    elif metrics["median_max_bound_width"] > 0.50 or metrics["p90_max_bound_width"] > 0.90:
        status = "caveat"
        reasons.append(
            "tomography_bounds_nearly_uninformative"
            if metrics["p90_max_bound_width"] > 0.98
            else "wide_tomography_bounds"
        )
    else:
        status = "pass"
    return {
        "identification_schema_version": "ecological_identification_v2.0",
        "identification_status": status,
        "identification_reasons": reasons,
        **metrics,
        "interpretation": (
            "Quantifies ecological tomography width and design variation; it does not prove individual-level identification."
        ),
    }


__all__ = ["assess_identification", "tomography_bounds"]
