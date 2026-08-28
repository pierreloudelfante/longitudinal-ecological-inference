from __future__ import annotations

from code_longitudinal.run_priority_production import (
    PRIORITY_ELECTIONS,
    PRIORITY_SCENARIOS,
    diagnostic_verdict,
)
from code_longitudinal.run_2x2_batch import stable_vote_fractions

import numpy as np


def test_priority_scope_is_four_hypotheses_for_three_periods() -> None:
    assert PRIORITY_ELECTIONS == ("leg_1962_r1", "leg_1986_r1", "leg_2022_r1")
    assert PRIORITY_SCENARIOS == ("H0A", "H1", "H2", "H4")
    assert len(PRIORITY_SCENARIOS) == 4


def test_diagnostic_verdict_requires_all_production_checks() -> None:
    diagnostics = {
        "saved_chains": 4,
        "saved_draws_per_chain": 1000,
        "divergences": 0,
        "max_rhat": 1.005,
        "min_ess_bulk": 650,
        "min_ess_tail": 520,
        "min_bfmi": 0.42,
        "max_tree_depth_hits": 0,
    }
    assert diagnostic_verdict(diagnostics, requested_draws=1000, requested_chains=4) == ("pass", "")

    diagnostics["divergences"] = 1
    verdict, reasons = diagnostic_verdict(diagnostics, requested_draws=1000, requested_chains=4)
    assert verdict == "fail"
    assert "divergences=1.0" in reasons


def test_stable_vote_fractions_preserve_exact_integer_counts() -> None:
    counts = np.array([0, 1, 17, 288, 1591, 1592], dtype=np.int64)
    totals = np.array([38, 38, 38, 1592, 1592, 1592], dtype=np.int64)

    fractions = stable_vote_fractions(counts, totals)

    assert np.array_equal(np.floor(fractions * totals).astype(np.int64), counts)
    assert np.all((fractions >= 0) & (fractions <= 1))
