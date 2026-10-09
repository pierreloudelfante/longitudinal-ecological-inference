"""Regression guards: the former independent mini pipeline must not return."""
from __future__ import annotations

import ast
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from reproducibility import replication_complete as production
from reproducibility.replication_scope import ENVIRONMENT_KEY, get_scope
from reproducibility.result_scope import project_result_contract

ROOT = Path(__file__).resolve().parents[2]


def test_launcher_has_one_driver_for_both_scopes():
    source = (ROOT / "REPRODUIRE_TOUT.ps1").read_text(encoding="utf-8-sig")
    assert "mini_replay_2022" not in source
    assert '$replicationScope = if ($ControleCourt -or $Controle2022)' in source
    assert '@("-m", "reproducibility.replication_complete", $action, "--scope", $replicationScope' in source


def test_legacy_module_contains_no_independent_workers_or_certifier():
    path = ROOT / "reproducibility/mini_replay_2022.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert [node.name for node in tree.body if isinstance(node, ast.FunctionDef)] == ["main"]
    assert "production_main()" in path.read_text(encoding="utf-8")


def test_legacy_command_delegates_to_the_shared_driver(monkeypatch):
    from reproducibility import mini_replay_2022
    monkeypatch.setattr("sys.argv", ["legacy", "plan", "--profile", "court2022"])
    monkeypatch.setenv(ENVIRONMENT_KEY, "full")
    with patch.object(production, "main") as main:
        mini_replay_2022.main()
        main.assert_called_once_with()
        assert get_scope().name == "court"


def test_court_has_same_stages_and_frozen_sampling_settings(monkeypatch):
    monkeypatch.setenv(ENVIRONMENT_KEY, "court")
    short = production.contract_plan()
    monkeypatch.setenv(ENVIRONMENT_KEY, "full")
    full = production.contract_plan()
    assert short["stages"] == full["stages"] == list(production.STAGES)
    assert len(short["stages"]) == 17
    assert (short["raw_archives"], short["krt_pairs"], short["nls_delivered_pairs"],
            short["nls_covariates"], short["density_images"]) == (31, 13, 19, 52, 26)
    contract = json.loads((production.CONTRACT / "krt_replay_240.json").read_text())["entries"]
    def branches(rows):
        return {(r["arguments"]["sampler_backend"], r["arguments"]["krt_parameterization_version"],
                 r["arguments"]["draws"], r["arguments"]["tune"]) for r in rows}
    selected = [row for row in contract if production.pair_key(row) in get_scope("court").pairs]
    assert branches(selected) == branches(contract)
    assert {row["scenario_id"] for row in selected} == set(production.SCENARIOS)


def test_scoped_and_full_inventory_have_same_table_schemas():
    full = json.loads((production.CONTRACT / "expected_results_610.json").read_text())
    short = project_result_contract(full, get_scope("court"))
    assert len(full["files"]) == 610
    assert len(short["files"]) == 138
    schemas = lambda c: {r["path"]: r["parquet"]["columns"] for r in c["files"] if "parquet" in r}
    assert schemas(short) == schemas(full)
    assert len(schemas(short)) == 8
    assert all(any(r["path"].startswith(prefix) for r in short["files"])
               for prefix in ("01_RAPPORT/", "03_FIGURES/", "04_PANEL_ET_HARMONISATION/", "05_DIAGNOSTICS/"))


def test_professor_guide_keeps_complete_final_output_contract():
    guide = (ROOT / "COMMENCER_ICI.md").read_text(encoding="utf-8-sig")
    contract = json.loads((production.CONTRACT / "expected_results_610.json").read_text())
    assert "deliverables/longitudinal_2000_results_recalcules.zip" in guide
    assert "deliverables/longitudinal_2000_results_recalcules.certification.json" in guide
    for entry in contract["files"]:
        if "parquet" in entry:
            assert entry["path"] in guide
    assert "mini_replay_2022" not in guide


def test_scope_cannot_silently_change_pair_values_or_accept_unknown_mode():
    with pytest.raises(ValueError, match="Unknown replication scope"):
        get_scope("unknown")
    scope = get_scope("court")
    assert scope.pairs <= get_scope("full").pairs
    assert scope.base_nls_pairs.isdisjoint(scope.extension_nls_pairs)
    assert scope.nls_pairs == scope.base_nls_pairs | scope.extension_nls_pairs
