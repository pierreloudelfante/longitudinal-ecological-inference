from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd
from scipy.stats import ks_2samp


CONTINUOUS_BALANCE = ("log1p_inscrits", "share_ouvr", "share_empl", "share_cadr", "share_agri_indp")
CATEGORICAL_BALANCE = ("region13", "vbbm")
QUANTILES = (0.05, 0.25, 0.50, 0.75, 0.95)


def compute_balance_checks(
    universe: pd.DataFrame,
    sample: pd.DataFrame,
    *,
    continuous: Sequence[str] = CONTINUOUS_BALANCE,
    categorical: Sequence[str] = CATEGORICAL_BALANCE,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for column in continuous:
        u = pd.to_numeric(universe[column], errors="coerce").dropna()
        s = pd.to_numeric(sample[column], errors="coerce").dropna()
        universe_sd = float(u.std(ddof=0))
        smd = float((s.mean() - u.mean()) / universe_sd) if universe_sd > 0 else 0.0
        row: dict[str, object] = {
            "variable": column,
            "variable_type": "continuous",
            "level": "",
            "universe_n": int(len(u)),
            "sample_n": int(len(s)),
            "universe_mean": float(u.mean()),
            "sample_mean": float(s.mean()),
            "universe_sd": universe_sd,
            "standardized_mean_difference": smd,
            "universe_proportion": np.nan,
            "sample_proportion": np.nan,
            "proportion_difference": np.nan,
            "ks_distance": float(ks_2samp(u, s).statistic),
        }
        for q in QUANTILES:
            suffix = f"q{int(q * 100):02d}"
            row[f"universe_{suffix}"] = float(u.quantile(q))
            row[f"sample_{suffix}"] = float(s.quantile(q))
        rows.append(row)
    for column in categorical:
        levels = sorted(set(universe[column].dropna().astype(str)) | set(sample[column].dropna().astype(str)))
        for level in levels:
            up = float(universe[column].astype(str).eq(level).mean())
            sp = float(sample[column].astype(str).eq(level).mean())
            rows.append(
                {
                    "variable": column,
                    "variable_type": "categorical",
                    "level": level,
                    "universe_n": int(len(universe)),
                    "sample_n": int(len(sample)),
                    "universe_mean": np.nan,
                    "sample_mean": np.nan,
                    "universe_sd": np.nan,
                    "standardized_mean_difference": np.nan,
                    "universe_proportion": up,
                    "sample_proportion": sp,
                    "proportion_difference": sp - up,
                    "ks_distance": np.nan,
                }
            )
    return pd.DataFrame(rows)


def balance_summary(checks: pd.DataFrame, *, max_smd: float, max_category_gap: float) -> dict[str, object]:
    continuous = checks.loc[checks["variable_type"].eq("continuous"), "standardized_mean_difference"].abs()
    categorical = checks.loc[checks["variable_type"].eq("categorical"), "proportion_difference"].abs()
    categorical_rows = checks.loc[checks["variable_type"].eq("categorical")]
    large_categories = categorical_rows["universe_proportion"].ge(0.005)
    no_empty = bool((categorical_rows.loc[large_categories, "sample_proportion"] > 0).all())
    observed_smd = float(continuous.max()) if len(continuous) else 0.0
    observed_gap = float(categorical.max()) if len(categorical) else 0.0
    return {
        "accepted": bool(observed_smd <= max_smd and observed_gap <= max_category_gap and no_empty),
        "max_abs_smd": observed_smd,
        "max_abs_category_gap": observed_gap,
        "no_empty_category": no_empty,
    }
