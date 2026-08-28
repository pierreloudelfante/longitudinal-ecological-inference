from __future__ import annotations

import json

import numpy as np
import pandas as pd

from code_longitudinal.balance_checks import balance_summary, compute_balance_checks
from code_longitudinal.paths import PANEL_DIR


def test_balance_checks_accept_identical_sample() -> None:
    frame = pd.DataFrame(
        {
            "log1p_inscrits": np.linspace(1, 5, 40),
            "share_ouvr": np.linspace(0.1, 0.4, 40),
            "share_empl": np.linspace(0.2, 0.3, 40),
            "share_cadr": np.linspace(0.05, 0.2, 40),
            "share_agri_indp": np.linspace(0.01, 0.15, 40),
            "region13": np.repeat(["a", "b"], 20),
            "vbbm": np.tile([1, 2, 3, 4], 10),
        }
    )
    checks = compute_balance_checks(frame, frame.copy())
    result = balance_summary(checks, max_smd=0.1, max_category_gap=0.02)
    assert result["accepted"]
    assert result["max_abs_smd"] == 0
    assert result["max_abs_category_gap"] == 0


def test_saved_panels_are_reproducible_and_nested() -> None:
    panel_3000 = pd.read_csv(PANEL_DIR / "panel_3000.csv", dtype={"unit_id": "string"})
    panel_2000 = pd.read_csv(PANEL_DIR / "panel_2000.csv", dtype={"unit_id": "string"})
    manifest = json.loads((PANEL_DIR / "panel_manifest.json").read_text(encoding="utf-8"))
    assert len(panel_3000) == 3000
    assert len(panel_2000) == 2000
    assert panel_3000["unit_id"].is_unique
    assert panel_2000["unit_id"].tolist() == panel_3000.sort_values("sample_rank").head(2000)["unit_id"].tolist()
    assert manifest["panel_3000"]["accepted"] is True
    assert manifest["panel_2000_nested"]["accepted"] is True


def test_saved_panel_identifiers_and_presence_ledger_are_stable() -> None:
    panel = pd.read_csv(PANEL_DIR / "panel_3000.csv", dtype={"unit_id": "string"})
    presence = pd.read_csv(PANEL_DIR / "panel_election_presence.csv", dtype={"unit_id": "string"}, low_memory=False)
    assert panel["unit_id"].str.fullmatch(r"[0-9A-Z]{5}").all()
    assert panel["inscrits"].gt(0).all()
    assert len(presence) == 3000 * 26
    assert not presence.duplicated(["sample_id", "election_id", "unit_id"]).any()
    assert presence.groupby("unit_id")["election_id"].nunique().eq(26).all()
