from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from code_longitudinal.prepare_inputs import (
    _validate_electoral_denominators,
    _validate_raw_political_partition,
    n_columns,
    validate_model_ready,
    x_columns,
    y_columns,
)
from code_longitudinal.spec_registry import ELECTION_BY_ID, SCENARIO_BY_ID
from code_longitudinal.utils import largest_remainder_round, normalize_unit_id


def test_largest_remainder_closes_exactly_and_is_deterministic() -> None:
    first = largest_remainder_round([1.2, 2.2, 3.6], 11)
    second = largest_remainder_round([1.2, 2.2, 3.6], 11)
    assert np.array_equal(first, second)
    assert first.sum() == 11
    assert (first >= 0).all()


def test_normalize_unit_id_preserves_corsica() -> None:
    assert normalize_unit_id("2a004") == "2A004"
    assert normalize_unit_id(1234) == "01234"


def test_model_ready_partition_validation() -> None:
    spec = SCENARIO_BY_ID["H0A"]
    frame = pd.DataFrame({"unit_id": ["01001", "01002"], "N_g": [10, 20]})
    frame[x_columns(spec)[0]] = [0.4, 0.6]
    frame[x_columns(spec)[1]] = [0.6, 0.4]
    frame[n_columns(spec)[0]] = [4, 12]
    frame[n_columns(spec)[1]] = [6, 8]
    frame[y_columns(spec)[0]] = [3, 5]
    frame[y_columns(spec)[1]] = [7, 15]
    result = validate_model_ready(frame, spec)
    assert result["rows"] == 2
    broken = frame.copy()
    broken.loc[0, y_columns(spec)[0]] += 1
    with pytest.raises(AssertionError, match="vote counts"):
        validate_model_ready(broken, spec)


def test_raw_validation_uses_the_scenario_partition() -> None:
    election = ELECTION_BY_ID["leg_2022_r1"]
    data = pd.DataFrame(
        {
            "unit_id": ["01001"],
            "inscrits": [100.0],
            "votants": [80.0],
            "exprimes": [70.0],
            "voteG": [10.004],
            "voteCG": [10.004],
            "voteC": [10.004],
            "voteCD": [20.004],
            "voteD": [20.004],
        }
    )
    # The unrelated five-block gap must not invalidate abstention/participation.
    result = _validate_raw_political_partition(
        data, election, SCENARIO_BY_ID["H0A"], 0.01
    )
    assert result["rule"] == "votants_inside_inscrits"

    # RXC consumes the five raw blocks and therefore rejects the 0.02-vote gap.
    with pytest.raises(ValueError, match="five-block partition"):
        _validate_raw_political_partition(
            data, election, SCENARIO_BY_ID["RXC1"], 0.01
        )


def test_transversal_denominator_validation_rejects_expressed_above_voters() -> None:
    frame = pd.DataFrame(
        {
            "unit_id": ["02643"],
            "inscrits": [383],
            "votants": [383],
            "exprimes": [392],
        }
    )
    with pytest.raises(ValueError, match="exprimes <= votants <= inscrits"):
        _validate_electoral_denominators(
            frame, ELECTION_BY_ID["leg_1986_r1"], 0.01
        )


def test_transversal_denominator_validation_accepts_float_tolerance() -> None:
    frame = pd.DataFrame(
        {
            "unit_id": ["28327"],
            "inscrits": [147.0],
            "votants": [71.0],
            "exprimes": [71.000002],
        }
    )
    result = _validate_electoral_denominators(
        frame, ELECTION_BY_ID["leg_2022_r1"], 0.01
    )
    assert result["rule"] == "zero_le_exprimes_le_votants_le_inscrits"
