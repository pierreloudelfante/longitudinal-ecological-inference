"""Bounded tests of selection and coverage; no statistical estimation is run."""
from __future__ import annotations

import json
import ast
import hashlib
import inspect
from pathlib import Path
import subprocess
from types import ModuleType

import pandas as pd
import pytest

from reproducibility.replication_scope import get_scope
from reproducibility import replication_complete as production
from code_longitudinal import compare_python_r_ei_full_240 as comparison
from code_longitudinal import consolidate_rxc_panel_extension_v11 as rxc_consolidation
from code_longitudinal import run_r_ei_all_2x2 as r_runner
from code_longitudinal import run_rxc_panel_extension_v11 as rxc_runner
from code_longitudinal import run_fast_nls_covariate_specs as covariates
from code_longitudinal import run_longitudinal_production as nls_runner


@pytest.mark.parametrize("name,count", [("full", 240), ("court", 13)])
def test_r_inputs_select_exact_scoped_pairs(monkeypatch, tmp_path: Path, name: str, count: int):
    monkeypatch.setenv("LONGITUDINAL_REPLICATION_SCOPE", name)
    scope = get_scope()
    directory = tmp_path / "model_ready"
    directory.mkdir()
    # Make every full input available: the bounded dispatcher must still select
    # only its exact pair set, including asymmetric election/scenario coverage.
    for election, scenario in get_scope("full").pairs:
        (directory / f"{election}__{scenario}__fixture__n2000.csv").touch()
    monkeypatch.setattr(r_runner, "OUTPUT_DIR", tmp_path)
    selected = r_runner._model_ready_inputs("fixture", r_runner.DEFAULT_SCENARIOS)
    assert len(selected) == count
    assert {tuple(path.name.split("__")[:2]) for path in selected} == scope.pairs
    selected[0].unlink()
    with pytest.raises(AssertionError, match="model-ready CSV"):
        r_runner._model_ready_inputs("fixture", r_runner.DEFAULT_SCENARIOS)


@pytest.mark.parametrize("name", ["full", "court"])
def test_comparison_requires_pair_identity_not_just_count(monkeypatch, name: str):
    monkeypatch.setenv("LONGITUDINAL_REPLICATION_SCOPE", name)
    frame = pd.DataFrame(sorted(get_scope().pairs), columns=["election_id", "scenario_id"])
    comparison._assert_pair_coverage(frame, label="fixture")
    frame.loc[0, "election_id"] = "wrong_election_same_row_count"
    with pytest.raises(AssertionError, match="pair coverage differs"):
        comparison._assert_pair_coverage(frame, label="fixture")


@pytest.mark.parametrize("name,count", [("full", 22), ("court", 4)])
def test_rxc_scope_keeps_closure_validation(monkeypatch, name: str, count: int):
    monkeypatch.setenv("LONGITUDINAL_REPLICATION_SCOPE", name)
    audit = pd.read_csv(rxc_runner.ROOT / "reproducibility/reference/rxc_ineligible_audit.csv")
    selected = rxc_runner.eligible_deferred_pairs(audit)
    assert len(selected) == count
    assert frozenset(selected) == get_scope().extension_nls_pairs
    election, scenario = selected[0]
    mask = audit["election_id"].eq(election) & audit["scenario_id"].eq(scenario)
    audit.loc[mask, "panel_model_ready_exact_closure"] = False
    with pytest.raises(ValueError, match="unsafe or ambiguous"):
        rxc_runner.eligible_deferred_pairs(audit)


def test_rxc_missing_pair_cannot_be_replaced_by_duplicate(monkeypatch):
    monkeypatch.setenv("LONGITUDINAL_REPLICATION_SCOPE", "court")
    pairs = sorted(get_scope().extension_nls_pairs)
    frame = pd.DataFrame(pairs, columns=["election_id", "scenario_id"])
    frame["run_id"] = "unused"
    frame["execution_status"] = "success"
    frame.loc[1, ["election_id", "scenario_id"]] = frame.loc[0, ["election_id", "scenario_id"]].values
    with pytest.raises(ValueError, match="scoped unique pairs"):
        rxc_consolidation._selected_runs(frame)


@pytest.mark.parametrize("name,base_count,extension_count,total_rows", [
    ("full", 270, 22, 2370), ("court", 15, 4, 200),
])
def test_nls_row_contract_uses_original_model_dimensions(name, base_count, extension_count, total_rows):
    scope = get_scope(name)
    assert len(scope.base_nls_pairs) == base_count
    assert len(scope.extension_nls_pairs) == extension_count
    assert rxc_consolidation._expected_nls_rows(scope.nls_pairs) == total_rows
    assert scope.nls_rows() == total_rows


@pytest.mark.parametrize("name", ["full", "court"])
def test_nls_common_worker_dispatch_preserves_panel_and_eligibility(monkeypatch, tmp_path: Path, name):
    monkeypatch.setenv("LONGITUDINAL_REPLICATION_SCOPE", name)
    monkeypatch.setattr(nls_runner, "ROOT", tmp_path)
    monkeypatch.setattr(nls_runner, "OUTPUT_DIR", tmp_path / "outputs")
    monkeypatch.setattr(nls_runner, "RUNS_DIR", tmp_path / "outputs/runs")
    scope = get_scope()
    full = get_scope("full")
    plan = pd.DataFrame([
        {
            "election_id": election, "scenario_id": scenario,
            "year": nls_runner.ELECTION_BY_ID[election].year,
            "election_type": nls_runner.ELECTION_BY_ID[election].election_type,
            "preparation_status": "admissible" if (election, scenario) in full.base_nls_pairs else "deferred",
            "preparation_reason": "fixture deferred RxC closure audit",
        }
        for election, scenario in sorted(full.nls_pairs)
    ])
    monkeypatch.setattr(nls_runner, "_ensure_inputs", lambda: (plan, {"panel_id": "fixture"}))
    saved = []
    calls = []
    monkeypatch.setattr(nls_runner, "_save_progress", lambda path, rows: saved.append(list(rows)))

    def worker(election, scenario, **kwargs):
        calls.append((election.election_id, scenario.scenario_id, kwargs))
        run_id = f"fixture_{election.election_id}__{scenario.scenario_id}"
        run_dir = nls_runner.RUNS_DIR / run_id
        run_dir.mkdir(parents=True)
        for output_name in ("longitudinal_estimates.csv", "model_diagnostics.csv",
                            "nls_coefficients.csv", "nls_start_diagnostics.csv"):
            (run_dir / output_name).write_text("fixture_value\n1\n", encoding="utf-8")
        return {"status": "success", "run_id": run_id}

    monkeypatch.setattr(nls_runner, "run_nls", worker)
    result = nls_runner.run_nls_longitudinal(force=True)
    assert {(election, scenario) for election, scenario, _ in calls} == scope.base_nls_pairs
    assert all(kwargs == {"sample_size": 2000, "panel_path": nls_runner.PANEL_PATH, "force": True}
               for _, _, kwargs in calls)
    assert result["planned"] == len(scope.nls_pairs)
    assert result["success_or_resumed"] == len(scope.base_nls_pairs)
    assert result["skipped_ineligible"] == len(scope.extension_nls_pairs)
    assert result["failed"] == 0
    assert len(saved[-1]) == len(scope.nls_pairs)


@pytest.mark.parametrize("name,count", [("full", 240), ("court", 13)])
def test_covariates_use_scoped_r_inputs_and_reject_missing_pair(monkeypatch, tmp_path: Path, name, count):
    monkeypatch.setenv("LONGITUDINAL_REPLICATION_SCOPE", name)
    monkeypatch.setattr(covariates, "ROOT", tmp_path)
    monkeypatch.setattr(covariates, "R_RUNS", tmp_path)
    for election, scenario in get_scope("full").pairs:
        folder = tmp_path / f"{election}__{scenario}"
        folder.mkdir()
        (folder / "manifest_r.json").write_text(json.dumps({
            "status": "success", "election_id": election, "scenario_id": scenario,
            "input_csv": "fixture.csv",
        }), encoding="utf-8")
    selected = covariates.load_scope()
    assert len(selected) == count
    assert {(row["election_id"], row["scenario_id"]) for row in selected} == get_scope().pairs
    (tmp_path / selected[0]["source_manifest"]).unlink()
    with pytest.raises(AssertionError, match="unique 2x2 pairs"):
        covariates.load_scope()


@pytest.mark.parametrize("name", ["full", "court"])
def test_common_pipeline_order_resume_and_code_guard(monkeypatch, tmp_path: Path, name):
    """Dispatch-only unit test; every subprocess and scientific preflight is mocked."""
    monkeypatch.setenv("LONGITUDINAL_REPLICATION_SCOPE", name)
    (tmp_path / "reproducibility").mkdir()
    (tmp_path / "reproducibility/requirements-python312.lock.txt").write_text("fixture", encoding="utf-8")
    code_file = tmp_path / "reproducibility/fixture.py"
    code_file.write_text("# immutable dispatch fixture", encoding="utf-8")
    state_dir = tmp_path / ".runtime" / ("replication_v2" if name == "full" else "replication_court")
    monkeypatch.setattr(production, "ROOT", tmp_path)
    monkeypatch.setattr(production, "STATE_DIR", state_dir)
    monkeypatch.setattr(production, "preflight", lambda *args: {
        "raw": {"raw_dir": str(tmp_path), "fingerprint": "fixture"}})
    monkeypatch.setattr(production, "configure", lambda *args: None)
    calls = []

    class FakeProcess:
        pid = 723456
        returncode = 0
        def wait(self, timeout=None): return self.returncode
        def poll(self): return self.returncode
        def kill(self): self.returncode = -9

    def subprocess_fixture(command, **kwargs):
        assert kwargs["environment"]["LONGITUDINAL_REPLICATION_SCOPE"] == name
        calls.append(command[-1])
        return FakeProcess(), kwargs.get("job"), False

    monkeypatch.setattr(production, "start_owned_process_tree", subprocess_fixture)
    production.run_pipeline(tmp_path, "unused_R", "unused_browser")
    assert calls == list(production.STAGES)
    assert production.read_json(state_dir / "state.json")["scope"]["name"] == name
    calls.clear()
    production.run_pipeline(tmp_path, "unused_R", "unused_browser")
    assert calls == ["verify", "package"]
    calls.clear()
    code_file.write_text("# changed fixture", encoding="utf-8")
    with pytest.raises(production.ReplicationError, match="Sources/code/contrat modifies"):
        production.run_pipeline(tmp_path, "unused_R", "unused_browser")
    assert calls == []


def test_another_scope_cannot_reuse_existing_scientific_outputs(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("LONGITUDINAL_REPLICATION_SCOPE", "court")
    (tmp_path / "reproducibility").mkdir()
    (tmp_path / "reproducibility/requirements-python312.lock.txt").write_text("fixture", encoding="utf-8")
    (tmp_path / "outputs").mkdir()
    (tmp_path / "outputs/other_scope.txt").write_text("not reusable", encoding="utf-8")
    monkeypatch.setattr(production, "ROOT", tmp_path)
    monkeypatch.setattr(production, "STATE_DIR", tmp_path / ".runtime/replication_court")
    monkeypatch.setattr(production, "preflight", lambda *args: {
        "raw": {"raw_dir": str(tmp_path), "fingerprint": "fixture"}})
    monkeypatch.setattr(production, "configure", lambda *args: None)
    monkeypatch.setattr(production.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not dispatch"))
    with pytest.raises(production.ReplicationError, match="Premiere execution"):
        production.run_pipeline(tmp_path, "unused_R", "unused_browser")


def test_court_krt_stage_selects_exact_frozen_contract_rows(monkeypatch):
    """No estimator runs: test only the stage-to-worker boundary."""
    monkeypatch.setenv("LONGITUDINAL_REPLICATION_SCOPE", "court")
    contract = production.read_json(production.CONTRACT / "krt_replay_240.json")["entries"]
    expected = [row for row in contract if production.pair_key(row) in get_scope().pairs]
    calls = []
    monkeypatch.setattr(production, "activate_runtime_panel_hash", lambda: None)
    monkeypatch.setattr(production, "execute_krt_contract_rows", lambda rows: calls.append(rows))
    monkeypatch.setattr(production, "krt_manifest_map", lambda: {
        row["reference_run_id"]: (Path("fixture"), {"run_id": "fixture"}) for row in expected})
    monkeypatch.setattr(production, "write_json", lambda *args: None)
    production.worker("krt240")
    assert calls == [expected]
    assert len(calls[0]) == 13
    assert {production.pair_key(row) for row in calls[0]} == get_scope().pairs


@pytest.mark.parametrize("target", ["outputs", "panel/subfolder", "work", "deliverables/subfolder", "."])
def test_comparison_renderer_rejects_candidate_trees(tmp_path: Path, target):
    from reproducibility.render_scope_reference import validate_destination
    with pytest.raises(ValueError, match="overlaps|project root"):
        validate_destination(tmp_path / target, project_root=tmp_path)


def test_comparison_path_redirection_is_reversible_and_does_not_rewrite_functions(tmp_path: Path):
    from reproducibility import render_scope_reference as renderer
    module = ModuleType("isolated_fixture")
    module.ROOT = renderer.ROOT
    module.OUTPUT = renderer.ROOT / "outputs/fixture.parquet"
    module.SOURCES = {"nested": [renderer.ROOT / "work/fixture.csv"]}
    original_function = lambda: "unchanged scientific function"
    module.worker = original_function
    original_sources = module.SOURCES
    with pytest.raises(RuntimeError, match="fixture interruption"):
        with renderer.isolated_module_paths([module], tmp_path):
            assert module.ROOT == tmp_path
            assert module.OUTPUT == tmp_path / "outputs/fixture.parquet"
            assert module.SOURCES["nested"] == [tmp_path / "work/fixture.csv"]
            assert module.worker is original_function
            raise RuntimeError("fixture interruption")
    assert module.ROOT == renderer.ROOT
    assert module.OUTPUT == renderer.ROOT / "outputs/fixture.parquet"
    assert module.SOURCES is original_sources
    assert module.worker is original_function


def test_factored_production_status_matrix_retains_frozen_guard(monkeypatch):
    from code_longitudinal import build_professor_release_assets as assets
    monkeypatch.setenv("LONGITUDINAL_REPLICATION_SCOPE", "court")
    entries = assets.scope_reference_entries()
    frame = pd.DataFrame([{"election_id": row["election_id"], "scenario_id": row["scenario_id"],
                           "mcmc_status": row["reference_mcmc_status"]} for row in entries])
    summary = assets.krt_status_summary(frame)
    assert summary["total"].sum() == 13
    assert summary[["pass", "caveat", "fail"]].to_numpy().sum() == 13
    frame.loc[0, "mcmc_status"] = "corrupted"
    with pytest.raises(AssertionError, match="unexpected KRT status matrix"):
        assets.krt_status_summary(frame)


@pytest.mark.parametrize("function_name,expected_ast_sha256", [
    ("plot_trajectory", "5d9af7698c528ed0d5cc09a7ef6c31999a93a0b2a9e46505e70d6a5eaf101c20"),
    ("build_figures", "aa8058144abca89d2dab70f209065b9724a7fab6b601deed80ad92a86bf86989"),
    ("build_report_artifact", "63459b1f635413d57e2173ff223b85dafe4e040df1d13e0eed68a07b0a8f2ba3"),
])
def test_full_figure_report_producers_preserve_authoritative_technical_ast(function_name, expected_ast_sha256):
    """Pins come from CODE in technical ZIP ef6827bc3683...b30b4f67ae.

    Normalize only the full-scope constants and unreachable short-only guards;
    no plotting operations, statistical transforms, labels, or layout are ignored.
    The renamed family helper has the historical French output (tested below).
    """
    from code_longitudinal import build_professor_release_assets as assets

    class FullScopeView(ast.NodeTransformer):
        def visit_If(self, node):
            test = ast.unparse(node.test)
            if test == "not get_scope().is_full" or test.startswith("not get_scope().is_full and "):
                return None
            return self.generic_visit(node)

        def visit_Call(self, node):
            node = self.generic_visit(node)
            if isinstance(node.func, ast.Name) and node.func.id == "r_aggregate_election_family":
                node.func.id = "election_family"
            return node

        def visit_Attribute(self, node):
            if ast.unparse(node) == "get_scope().pair_count":
                return ast.copy_location(ast.Constant(value=240), node)
            return self.generic_visit(node)

    tree = ast.parse(inspect.getsource(getattr(assets, function_name)))
    normalized = FullScopeView().visit(tree.body[0])
    assert hashlib.sha256(ast.dump(normalized, include_attributes=False).encode()).hexdigest() == expected_ast_sha256


def test_historical_plot_family_alias_preserves_french_labels():
    from code_longitudinal import build_professor_release_assets as assets
    values = pd.Series(["leg_2022_r1", "pre_2022_r1"])
    assert list(assets.r_aggregate_election_family(values)) == ["legislative", "presidentielle"]
    assert list(assets.election_family(values)) == ["legislative", "presidential"]


def test_all_fourteen_historical_chart_ids_have_explicit_print_renderers(monkeypatch, tmp_path: Path):
    from code_longitudinal import repair_portable_report_from_template as portable
    contract = production.read_json(production.CONTRACT / "expected_results_610.json")
    paths = {entry["path"] for entry in contract["files"]}
    expected_ids = {"h0a_chart", "h1_chart", "cov_summary_chart", "krt_nls_chart", "gap_chart", "diagnostics_chart"}
    expected_ids |= {f"trajectory_{scenario}_chart" for scenario in ("H0B", "H0C", "H2", "H3", "H4", "H5", "H6", "H7")}
    assert set(portable.STATIC_CHARTS) | portable.TABULAR_CHARTS == expected_ids
    assert len(portable.STATIC_CHARTS) == 12
    calls = []

    def static_fixture(selected, figures_root, **kwargs):
        assert all("03_FIGURES/" + path in paths for path in selected)
        calls.append(selected)
        return "<fixture-static-image/>"

    monkeypatch.setattr(portable, "render_static_figures", static_fixture)
    for chart_id in sorted(expected_ids):
        rendered = portable.render_chart({"id": chart_id, "dataset": "fixture"}, {"fixture": [{"value": 1}]}, tmp_path)
        assert ("<fixture-static-image/>" in rendered) == (chart_id in portable.STATIC_CHARTS)
        if chart_id in portable.TABULAR_CHARTS:
            assert "<table>" in rendered
    assert len(calls) == 12
    with pytest.raises(ValueError, match="No historical print renderer"):
        portable.render_chart({"id": "unrecognized_required_chart", "dataset": "fixture"}, {}, tmp_path)


@pytest.mark.parametrize("name", ["full", "court"])
def test_density_summary_selection_is_explicit_and_within_scope(monkeypatch, name):
    from code_longitudinal import repair_portable_report_from_template as portable
    monkeypatch.setenv("LONGITUDINAL_REPLICATION_SCOPE", name)
    selected = portable.density_summary_paths()
    assert len(selected) == 4
    if name == "full":
        assert selected == portable.DENSITY_SUMMARIES
    for path in selected:
        _, method, scenario, family = path.split("/")
        family = family.removesuffix(".png")
        assert method in {"krt_python", "r_eipack"}
        assert any(scenario == s and family == ("legislative" if election.startswith("leg_") else "presidential")
                   for election, s in get_scope().pairs)


def test_missing_required_static_chart_is_not_replaced_by_tabular_fallback(tmp_path: Path):
    from code_longitudinal import repair_portable_report_from_template as portable
    with pytest.raises(FileNotFoundError):
        portable.render_chart({"id": "h1_chart", "dataset": "fixture"}, {}, tmp_path)


def test_composition_reuses_unchanged_published_script_at_explicit_isolated_root(monkeypatch, tmp_path: Path):
    """Dispatch-only: the tested helper must call the actual historical producer."""
    from code_longitudinal import build_professor_release_assets as assets
    script = production.ROOT / "reproducibility/presentation/compose_slide_figures.ps1"
    assert hashlib.sha256(script.read_bytes()).hexdigest() == "b544505af3c87e444dc24fe4b0b637de96c1183af4634146fcf05f35a3f5892b"
    calls = []
    monkeypatch.setattr(assets.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs)))
    assets.compose_slide_figures(project_root=tmp_path, script_path=script)
    assert calls[0][0] == ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                           str(script), "-ProjectRoot", str(tmp_path)]
    assert calls[0][1]["cwd"] == tmp_path
    assert calls[0][1]["check"] is True
    for function in (assets.main,):
        tree = ast.parse(inspect.getsource(function))
        calls_in_order = [node.value.func.id for node in tree.body[0].body
                          if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                          and isinstance(node.value.func, ast.Name)]
        assert calls_in_order.index("compose_slide_figures") == calls_in_order.index("build_figures") + 1


def test_assets_stage_dispatches_shared_composition_exactly_once(monkeypatch, tmp_path: Path):
    """No rendering/estimation: exercise the real assets main call ordering."""
    from code_longitudinal import build_professor_release_assets as assets
    calls = []
    monkeypatch.setattr(assets, "REPORT_BUILD", tmp_path / "report")
    monkeypatch.setattr(assets, "FIGURES", tmp_path / "figures")
    monkeypatch.setattr(production, "activate_runtime_panel_hash", lambda: None)
    monkeypatch.setattr(production, "external", lambda *args, **kwargs: pytest.fail("duplicate composition dispatch"))
    monkeypatch.setattr(assets, "safe_reset", lambda *args: None)
    monkeypatch.setattr(assets, "write_json", lambda *args: None)
    monkeypatch.setattr(assets, "build_main_tables", lambda: {})
    monkeypatch.setattr(assets, "build_panel_and_harmonisation", lambda: None)
    monkeypatch.setattr(assets, "build_diagnostics", lambda: None)
    monkeypatch.setattr(assets, "build_figures", lambda: calls.append("figures"))
    monkeypatch.setattr(assets, "compose_slide_figures", lambda: calls.append("compose"))
    monkeypatch.setattr(assets, "build_documentation", lambda *args: calls.append("documentation"))
    monkeypatch.setattr(assets, "build_report_artifact", lambda: Path("fixture_artifact.json"))
    monkeypatch.setattr(production, "module", lambda name, *args: assets.main()
                        if name == "build_professor_release_assets" else pytest.fail(name))
    production.worker("assets")
    assert calls == ["figures", "compose", "documentation"]
