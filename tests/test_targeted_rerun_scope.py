from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from code_longitudinal import targeted_rerun_scope as module


def _plan() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"election_id": "leg_1986_r1", "scenario_id": "H6", "year": 1986, "election_type": "leg", "preparation_status": "admissible"},
            {"election_id": "leg_1962_r1", "scenario_id": "H0B", "year": 1962, "election_type": "leg", "preparation_status": "admissible"},
            {"election_id": "leg_1986_r1", "scenario_id": "H7", "year": 1986, "election_type": "leg", "preparation_status": "rejected"},
        ]
    )


def test_eligible_pairs_follow_release_scope_and_admissibility(monkeypatch) -> None:
    monkeypatch.setattr(module, "load_release_scope", lambda _: SimpleNamespace(krt_scenarios=("H6", "H7")))
    monkeypatch.setattr(module.pd, "read_parquet", lambda _: _plan())
    _scope, selected = module._eligible_pairs(Path("scope.json"))
    assert selected[["election_id", "scenario_id"]].to_records(index=False).tolist() == [("leg_1986_r1", "H6")]


def test_duplicate_pair_is_rejected(monkeypatch) -> None:
    duplicate = pd.concat([_plan().iloc[[0]], _plan().iloc[[0]]], ignore_index=True)
    monkeypatch.setattr(module, "load_release_scope", lambda _: SimpleNamespace(krt_scenarios=("H6",)))
    monkeypatch.setattr(module.pd, "read_parquet", lambda _: duplicate)
    with pytest.raises(AssertionError, match="duplicate"):
        module._eligible_pairs(Path("scope.json"))
