"""Historical export fidelity; these tests never rerun statistical estimators."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from code_longitudinal.build_professor_release_assets import (
    _contrast_three_methods_from_frames, election_family, enrich_commune_metadata,
    r_aggregate_election_family,
)


def test_native_r_contrast_is_not_dropped_or_double_counted():
    common = {"election_id": "pre_2022_r1", "year": 2022, "round": 1, "scenario_id": "H0A"}
    krt = pd.DataFrame([{**common, "model_key": "krt_beta_binomial", "estimand": "b_1_minus_b_2",
                         "mean": .11, "q025": .09, "q975": .13, "mcmc_status": "caveat"}])
    r = pd.DataFrame([{**common, "model_key": "king_ei_1997_r", "estimand": "contrast_aggregate",
                       "mean": .12, "q025": .08, "q975": .16}])
    nls = pd.DataFrame([{**common, "estimand_type": "group_contrast", "estimate": .10,
                         "diagnostic_status": "pass"}])
    result = _contrast_three_methods_from_frames(krt, r, nls)
    assert len(result) == 3
    actual_r = result.loc[result.model_key.eq("king_ei_1997_r")].iloc[0]
    assert (actual_r.estimate, actual_r.q025, actual_r.q975) == (.12, .08, .16)
    assert actual_r.estimand == "b_1_minus_b_2"
    assert actual_r.diagnostic_status == "native_ei_importance_resampling"
    normalized_r = r.assign(estimand="b_1_minus_b_2")
    with pytest.raises(AssertionError, match="duplicate"):
        _contrast_three_methods_from_frames(krt, pd.concat([r, normalized_r]), nls)


def test_r_aggregate_preserves_french_label_without_changing_contrast_labels():
    elections = pd.Series(["leg_2022_r1", "pre_2022_r1"])
    assert list(r_aggregate_election_family(elections)) == ["legislative", "presidentielle"]
    assert list(election_family(elections)) == ["legislative", "presidential"]


def _metadata_row(election, scenario, unit="01001"):
    return {
        "panel_id": "panel", "election_id": election, "scenario_id": scenario, "unit_id": unit,
        "vbbm": .1, "vbbm_reference_year": 2022., "vbbm_status": "known", "vbbm_source_column": "vbbm2022",
        "revenue_ratio": .2, "revenue_reference_year": 2022., "revenue_status": "known", "revenue_source_column": "rev2022",
        "capital_ratio": .3, "capital_reference_year": 2022., "capital_status": "known", "capital_source_column": "cap2022",
        "foreign_share": .04, "foreign_share_reference_year": 2022., "foreign_share_status": "known", "foreign_share_source_column": "nat2022",
        "commune_name_canonical": "A", "geography_version": "v1", "commune_name_reference_year": 2022,
        "b1_mean": .123456789, "b2_mean": .23456789, "N_g": 300,
    }


def test_metadata_availability_follows_historical_preparation_not_reference_values():
    frame = pd.DataFrame([
        _metadata_row("pre_2022_r1", "H0A"),
        _metadata_row("pre_2022_r1", "H1"),
        _metadata_row("pre_2022_r1", "H0B"),
        _metadata_row("leg_2002_r1", "H0A"),  # Contract-selected targeted rerun.
    ])
    projected, audit = enrich_commune_metadata(frame)
    late = audit["columns_absent_in_initial_schema"]
    assert len(late) == 13
    assert projected.loc[[0, 1], late].isna().all().all()
    pd.testing.assert_frame_equal(projected.loc[[2, 3], late], frame.loc[[2, 3], late])
    unchanged = ["vbbm", "revenue_ratio", "capital_ratio", "b1_mean", "b2_mean", "N_g"]
    pd.testing.assert_frame_equal(projected[unchanged], frame[unchanged])
    pd.testing.assert_frame_equal(frame, pd.DataFrame([
        _metadata_row("pre_2022_r1", "H0A"), _metadata_row("pre_2022_r1", "H1"),
        _metadata_row("pre_2022_r1", "H0B"), _metadata_row("leg_2002_r1", "H0A"),
    ]))
    assert audit["rows_filled"] == 0 and audit["rows_with_initial_schema"] == 2
    assert len(audit["initial_schema_pairs"]) == 46


def test_genuinely_missing_extension_metadata_stays_null_not_unknown():
    row = _metadata_row("pre_2022_r1", "H0B")
    for column in ("capital_ratio", "capital_reference_year", "capital_status", "capital_source_column"):
        row[column] = np.nan
    frame = pd.DataFrame([row])
    result, _ = enrich_commune_metadata(frame)
    assert result.loc[0, ["capital_ratio", "capital_reference_year", "capital_status", "capital_source_column"]].isna().all()


def test_uncontracted_canonical_metadata_schema_fails_closed():
    with pytest.raises(AssertionError, match="unknown canonical metadata schema"):
        enrich_commune_metadata(pd.DataFrame([_metadata_row("pre_2099_r1", "H0A")]))
