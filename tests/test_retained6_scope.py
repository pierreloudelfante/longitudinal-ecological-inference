from __future__ import annotations

import os
from pathlib import Path

from code_longitudinal import run_r_ei_all_2x2
from code_longitudinal.consolidate_r_ei_all_2x2 import (
    ALL_2X2_OUTPUTS,
    ALL_SCENARIOS,
    RETAINED_SCENARIOS,
)
from code_longitudinal.package_retained6_release import _code_closure
from code_longitudinal.paths import ROOT
from code_longitudinal.release_scope import load_release_scope


def test_retained6_release_counts_derive_from_configuration() -> None:
    scope = load_release_scope(ROOT / "config" / "releases" / "v1.5_retained6.json")
    assert scope.krt_scenarios == RETAINED_SCENARIOS
    assert scope.expected_krt_pairs == 156
    assert scope.expected_krt_commune_rows == 312_000
    assert scope.expected_krt_aggregate_rows == 468
    assert scope.expected_nls_pairs == 156


def test_full240_r_consolidation_scope_is_explicit_and_separate() -> None:
    assert len(ALL_SCENARIOS) == 10
    assert set(ALL_SCENARIOS) == {"H0A", "H0B", "H0C", "H1", "H2", "H3", "H4", "H5", "H6", "H7"}
    assert ALL_2X2_OUTPUTS["aggregate"].name == "longitudinal_king_ei_r_aggregate_all_2x2.parquet"
    assert ALL_2X2_OUTPUTS["commune"].name == "longitudinal_king_ei_r_commune_all_2x2.parquet"


def test_r_library_search_path_keeps_project_library_first(monkeypatch, tmp_path: Path) -> None:
    local = tmp_path / "LocalAppData"
    (local / "R" / "win-library" / "4.6").mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    value = run_r_ei_all_2x2._r_library_search_path().split(os.pathsep)
    assert Path(value[0]).resolve() == run_r_ei_all_2x2.R_PROJECT_LIBRARY.resolve()
    assert (local / "R" / "win-library" / "4.6").resolve() in {
        Path(item).resolve() for item in value[1:]
    }


def test_r_ei_script_is_parsimonious_and_never_uses_nimble() -> None:
    source = (ROOT / "r_replication" / "run_king_ei_replication.R").read_text(encoding="utf-8")
    assert "library(ei)" in source
    assert "eiPack_version" in source
    assert "saveRDS" not in source
    assert "nimble" not in source.lower()


def test_minimal_code_closure_excludes_historical_and_nimble_entrypoints() -> None:
    closure = _code_closure()
    assert "run_r_ei_all_2x2" in closure
    assert "scoped_finalizer" in closure
    assert "materialize_v11_release" not in closure
    assert "package_v11_release" not in closure
    assert "run_r_krt_exact_all_2x2" not in closure
