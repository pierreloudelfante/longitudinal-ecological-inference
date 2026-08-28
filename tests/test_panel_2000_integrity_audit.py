from __future__ import annotations

import pandas as pd

from code_longitudinal.audit_longitudinal import PRESENCE_PATH
from code_longitudinal.audit_panel_2000_integrity import _model_ready_integrity
from code_longitudinal.build_longitudinal_panel import PANEL_PATH


def test_primary_panel_is_the_same_strict_2000_units_in_all_26_elections() -> None:
    panel = pd.read_parquet(PANEL_PATH)
    primary = panel.loc[panel["included_primary_2000"].astype(bool)].copy()
    presence = pd.read_parquet(
        PRESENCE_PATH,
        columns=["unit_id", "election_id", "panel_core_admissible"],
    )
    joined = primary[["unit_id"]].merge(presence, on="unit_id", how="left", validate="one_to_many")

    assert len(primary) == 2000
    assert primary["unit_id"].is_unique
    assert primary.sort_values("master_draw_order")["master_draw_order"].tolist() == list(range(1, 2001))
    assert joined["election_id"].nunique() == 26
    assert len(joined) == 52_000
    assert joined.groupby("election_id")["unit_id"].nunique().eq(2000).all()
    assert joined["panel_core_admissible"].astype(bool).all()


def test_model_ready_integrity_detects_wrong_denominator_and_closure() -> None:
    frame = pd.DataFrame(
        {
            "unit_id": ["01001", "01002"],
            "N_g": [100, 119],
            "X__target_group": [0.4, 0.5],
            "X__complement_group": [0.6, 0.4],
            "N__target_group": [40, 60],
            "N__complement_group": [60, 60],
            "Y__abstention": [20, 20],
            "Y__participation": [80, 98],
        }
    )
    expected = pd.Series([100, 120], index=["01001", "01002"])

    result = _model_ready_integrity(
        frame,
        expected_unit_ids={"01001", "01002"},
        expected_denominator=expected,
        scenario_id="H0A",
    )

    assert result["denominator_mismatch_rows"] == 1
    assert result["social_closure_anomaly_rows"] == 1
    assert result["vote_closure_anomaly_rows"] == 1
    assert result["social_fraction_anomaly_rows"] == 1
