from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from code_longitudinal import run_fast_nls_covariate_specs as cov


def _frame_digest(frame: pd.DataFrame) -> str:
    hashed = pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes()
    attrs = json.dumps(frame.attrs, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(hashed + attrs).hexdigest()


def _input(path: Path, offset: float) -> None:
    x1 = np.array([0.2, 0.4, 0.6, 0.8])
    y1 = np.array([0.3, 0.45, 0.55, 0.7])
    pd.DataFrame({
        "unit_id": ["u1", "u2", "u3", "u4"],
        "N_g": [100, 100, 100, 100],
        "X__g1": x1, "X__g2": 1.0 - x1,
        "Y__v1": 100.0 * y1, "Y__v2": 100.0 * (1.0 - y1),
        "vbbm": [1, 2, 3, 4],
        "revenue": [10 + offset, 20 + offset, 30 + offset, 40 + offset],
        "capital": [5 + offset, 9 + offset, 15 + offset, 25 + offset],
        "foreign_share": [0.05 + offset / 100, 0.10, 0.15, 0.20],
    }).to_csv(path, index=False)


def test_election_filtered_lookup_and_fit_inputs_equal_full_scope(tmp_path, monkeypatch):
    target_a = tmp_path / "target-a.csv"
    target_b = tmp_path / "target-b.csv"
    other = tmp_path / "other.csv"
    _input(target_a, 0.0)
    _input(target_b, 1.0)
    _input(other, 50.0)
    target_rows = [
        {"election_id": "pre_2017_r1", "scenario_id": "H0A",
         "input_csv": str(target_a), "source_manifest": "m/a.json"},
        {"election_id": "pre_2017_r1", "scenario_id": "H1",
         "input_csv": str(target_b), "source_manifest": "m/b.json"},
    ]
    full_scope = [*target_rows, {
        "election_id": "pre_2022_r1", "scenario_id": "H0A",
        "input_csv": str(other), "source_manifest": "m/c.json",
    }]
    full_lookup = cov.build_covariate_lookup(full_scope)["pre_2017_r1"]
    filtered_lookup = cov.build_covariate_lookup(target_rows)["pre_2017_r1"]
    pd.testing.assert_frame_equal(full_lookup, filtered_lookup)
    assert full_lookup.attrs == filtered_lookup.attrs
    assert _frame_digest(full_lookup) == _frame_digest(filtered_lookup)

    captures = []

    def fake_fit(data, **kwargs):
        captures.append({
            "x": data.x.copy(), "t": data.t.copy(), "n": data.n.copy(), "z": data.z.copy(),
            **kwargs,
        })
        best = SimpleNamespace(
            x=np.zeros(4), success=True, cost=0.0, jac=np.eye(4), status=1,
            nfev=1, message="fixture",
        )
        starts = [{"success": True, "max_abs_prediction_difference_from_best": 0.0}]
        return best, starts

    monkeypatch.setattr(cov, "fit_nls", fake_fit)
    monkeypatch.setattr(
        cov, "probabilities",
        lambda parameters, x, z, categories: (
            np.full((len(x), 2, 2), 0.5), np.full((len(x), 2), 0.5),
        ),
    )
    for lookup in (full_lookup, filtered_lookup):
        cov.fit_pair_spec(
            target_rows[0], "demographic_foreign_share", lookup,
            n_starts=4, max_nfev=1200,
        )

    assert len(captures) == 2
    for name in ("x", "t", "n", "z"):
        np.testing.assert_array_equal(captures[0][name], captures[1][name])
    expected_seed = cov.stable_seed("pre_2017_r1", "H0A", "demographic_foreign_share")
    assert captures[0]["random_seed"] == captures[1]["random_seed"] == expected_seed
    for name, expected in {
        "n_starts": 4, "start_scale": 0.35, "n_start_strata": 5,
        "max_nfev": 1200, "tolerance": 1e-8,
    }.items():
        assert captures[0][name] == captures[1][name] == expected
