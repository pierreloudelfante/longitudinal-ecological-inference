from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from code_longitudinal.build_longitudinal_panel import _draw_balanced_panel
from code_longitudinal.data_io import (
    _canonicalize_near_integer_counts,
    department_from_unit_id,
    normalize_department,
)
from code_longitudinal.finalize_longitudinal import KRT_COMMUNE_COLUMNS, _build_krt_commune
from code_longitudinal.spec_registry import ELECTIONS, SCENARIOS, scenario_is_allowed


def _universe(size: int = 3600) -> pd.DataFrame:
    index = np.arange(size)
    return pd.DataFrame(
        {
            "unit_id": pd.Series(index).astype(str).str.zfill(5),
            "department": "01",
            "region13": np.where(index % 2, "region_a", "region_b"),
            "commune_name": "commune",
            "geography_source": "source_reference",
            "inscrits": 100 + index,
            "vbbm": 1 + index % 4,
            "log1p_inscrits": np.log1p(100 + index),
            "share_ouvr": 0.1 + (index % 10) / 100,
            "share_empl": 0.2 + (index % 8) / 100,
            "share_cadr": 0.15 + (index % 6) / 100,
            "share_agri_indp": 0.25 + (index % 4) / 100,
        }
    )


def test_registry_contains_26_elections_and_292_allowed_pairs() -> None:
    pairs = sum(scenario_is_allowed(scenario, election) for election in ELECTIONS for scenario in SCENARIOS)

    assert len(ELECTIONS) == 26
    assert pairs == 292


def test_near_integer_electoral_totals_are_canonicalized() -> None:
    frame = pd.DataFrame(
        {
            "inscrits": [156.0],
            "votants": [106.0],
            "exprimes": [106.0000038146973],
        }
    )

    result = _canonicalize_near_integer_counts(frame)

    assert result.loc[0, "exprimes"] == 106.0
    assert result.loc[0, "exprimes"] <= result.loc[0, "votants"] <= result.loc[0, "inscrits"]


def test_department_normalization_covers_corsica_overseas_and_historical_padding() -> None:
    assert normalize_department(2) == "02"
    assert normalize_department("2A") == "2A"
    assert normalize_department(971) == "971"
    assert department_from_unit_id("2B123") == "2B"
    assert department_from_unit_id("97123") == "971"


def test_longitudinal_draw_is_reproducible_and_primary_is_nested() -> None:
    universe = _universe()
    first, _, attempts, _ = _draw_balanced_panel(
        universe,
        universe,
        master_size=3000,
        primary_size=2000,
        initial_seed=20260802,
        max_attempts=3,
        max_smd=1.0,
        max_category_gap=1.0,
    )
    second, _, _, _ = _draw_balanced_panel(
        universe,
        universe,
        master_size=3000,
        primary_size=2000,
        initial_seed=20260802,
        max_attempts=3,
        max_smd=1.0,
        max_category_gap=1.0,
    )

    assert first is not None and second is not None
    assert first["unit_id"].tolist() == second["unit_id"].tolist()
    assert first.head(2000)["master_draw_order"].tolist() == list(range(1, 2001))
    assert bool(attempts.iloc[0]["accepted"])


def test_commune_finalizer_preserves_all_eight_uncertainty_fields() -> None:
    tmp_path = Path(__file__).parent / "runtime_longitudinal_v1"
    tmp_path.mkdir(parents=True, exist_ok=True)
    run_dir = tmp_path / "run"
    run_dir.mkdir(exist_ok=True)
    prepared = pd.DataFrame(
        {
            "unit_id": ["01001", "01002"],
            "N_g": [100, 120],
            "vbbm": [1, 2],
            "revenue": [0.9, 1.1],
            "capital": [0.8, 1.2],
            "immigrant_share": [0.1, 0.2],
            "region13": ["84_auvergne_rhone_alpes"] * 2,
        }
    )
    prepared_path = tmp_path / "prepared.parquet"
    prepared.to_parquet(prepared_path, index=False)
    latent = pd.DataFrame(
        {
            "run_id": ["run-1"] * 2,
            "run_key": ["key"] * 2,
            "sample_id": ["panel"] * 2,
            "election_id": ["leg_1962_r1"] * 2,
            "scenario_id": ["H0A"] * 2,
            "model_key": ["krt_beta_binomial"] * 2,
            "unit_id": ["01001", "01002"],
            "sample_rank": [1, 2],
            "b1_weight": [40, 50],
            "b2_weight": [60, 70],
            "b1_mean": [0.2, 0.3],
            "b1_sd": [0.01, 0.02],
            "b1_q025": [0.18, 0.26],
            "b1_q50": [0.2, 0.3],
            "b1_q975": [0.22, 0.34],
            "b2_mean": [0.4, 0.5],
            "b2_sd": [0.02, 0.03],
            "b2_q025": [0.36, 0.44],
            "b2_q50": [0.4, 0.5],
            "b2_q975": [0.44, 0.56],
        }
    )
    latent.to_parquet(run_dir / "commune_latent_summaries.parquet", index=False)
    manifest = {
        "run_id": "run-1",
        "status": "success",
        "election_id": "leg_1962_r1",
        "scenario_id": "H0A",
        "model_key": "krt_beta_binomial",
        "panel_id": "panel",
        "diagnostic_status": "pass",
        "preparation_manifest": {"output": str(prepared_path)},
        "identification_diagnostic": {"identification_status": "caveat"},
        "parameters": {"panel_id": "panel"},
    }
    panel = pd.DataFrame({"unit_id": ["01001", "01002"], "department": ["01", "01"]})

    result = _build_krt_commune([(run_dir, manifest)], panel)

    uncertainty = [
        "b1_sd",
        "b1_q025",
        "b1_q50",
        "b1_q975",
        "b2_sd",
        "b2_q025",
        "b2_q50",
        "b2_q975",
    ]
    assert list(result.columns) == KRT_COMMUNE_COLUMNS
    assert result[uncertainty].notna().all().all()
    assert result["identification_status"].eq("caveat").all()
