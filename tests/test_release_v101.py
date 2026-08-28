from __future__ import annotations

import json

import pandas as pd
import pytest

from code_longitudinal.finalize_longitudinal import KRT_COMMUNE_COLUMNS
from code_longitudinal.paths import CONFIG_DIR, ROOT
from code_longitudinal.package_release_v101 import WINDOWS_ABSOLUTE_PATH_RE, _sanitize_manifest_value
from code_longitudinal.prepare_inputs import _validate_electoral_denominators
from code_longitudinal.spec_registry import ELECTION_BY_ID, SCENARIO_BY_ID, planned_run_rows
from code_longitudinal.utils import package_versions


def test_release_configuration_uses_unambiguous_seed_and_size_fields() -> None:
    settings = json.loads((CONFIG_DIR / "run_settings.json").read_text(encoding="utf-8"))
    panel = settings["panel"]
    assert panel["panel_seed"] == 20260803
    assert panel["primary_panel_size"] == 2000
    assert panel["master_panel_size"] == 3000
    assert "size" not in panel
    assert "pilot_size" not in panel
    assert "initial_seed" not in panel
    assert settings["nls"]["random_seed"] == 20260802
    assert settings["mcmc"]["original_seed"] == 20260802
    assert settings["mcmc"]["rerun_seed"] == 20260817


def test_registry_keeps_292_pairs_and_admits_nls_for_2x2() -> None:
    rows = pd.DataFrame(planned_run_rows())
    assert len(rows[["election_id", "scenario_id"]].drop_duplicates()) == 292
    for scenario in SCENARIO_BY_ID.values():
        if scenario.model_family == "2x2":
            assert "rosen_nls_2x2_unadjusted" in scenario.models


def test_transversal_order_override_is_diagnostic_only_and_never_allows_negative_counts() -> None:
    election = ELECTION_BY_ID["leg_1962_r1"]
    order_violation = pd.DataFrame(
        [{"unit_id": "59473", "inscrits": 178, "votants": 149, "exprimes": 150}]
    )
    with pytest.raises(ValueError):
        _validate_electoral_denominators(order_violation, election, 0.01)
    audit = _validate_electoral_denominators(
        order_violation,
        election,
        0.01,
        diagnostic_only_allow_order_violations=True,
    )
    assert audit["order_violation_count"] == 1
    assert audit["diagnostic_only_override_applied"] is True

    negative = pd.DataFrame(
        [{"unit_id": "00001", "inscrits": 178, "votants": 149, "exprimes": -1}]
    )
    with pytest.raises(ValueError):
        _validate_electoral_denominators(
            negative,
            election,
            0.01,
            diagnostic_only_allow_order_violations=True,
        )


def test_public_commune_schema_carries_provenance_and_eight_uncertainty_fields() -> None:
    expected = {
        "vbbm_reference_year", "vbbm_status", "vbbm_source_column",
        "revenue_reference_year", "revenue_status", "revenue_source_column",
        "capital_reference_year", "capital_status", "capital_source_column",
        "foreign_share", "foreign_share_reference_year", "foreign_share_status", "foreign_share_source_column",
        "b1_sd", "b1_q025", "b1_q50", "b1_q975",
        "b2_sd", "b2_q025", "b2_q50", "b2_q975",
    }
    assert expected.issubset(KRT_COMMUNE_COLUMNS)
    assert "immigrant_share" not in KRT_COMMUNE_COLUMNS


def test_delivery_manifest_sanitizer_removes_windows_absolute_paths() -> None:
    payload = {
        str(ROOT / "outputs" / "x.parquet"): "hash",
        "command": f"'{ROOT / 'script.py'}' run",
        "external": r"D:\private\raw.zip",
    }
    sanitized = _sanitize_manifest_value(payload)
    rendered = json.dumps(sanitized)
    assert "C:\\\\" not in rendered
    assert "D:\\\\" not in rendered
    assert "outputs/x.parquet" in rendered
    assert "external_absolute_path_redacted" in rendered


def test_windows_absolute_path_scan_does_not_flag_https_urls() -> None:
    assert WINDOWS_ABSOLUTE_PATH_RE.search(r"C:\\Users\\example\\data.csv")
    assert not WINDOWS_ABSOLUTE_PATH_RE.search("https://www.example.org/source")


def test_package_versions_records_the_python_runtime() -> None:
    version = package_versions(["python"])["python"]
    assert version != "not-installed"
    assert version.count(".") >= 1
