from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from code_longitudinal import targeted_rerun_remaining as module


def _scope() -> SimpleNamespace:
    return SimpleNamespace(release_id="test_release", krt_scenarios=("H0B",))


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "outputs"


def test_pass_initial_is_not_rerun(monkeypatch) -> None:
    monkeypatch.setattr(module, "load_release_scope", lambda _: _scope())
    monkeypatch.setattr(module, "_production_dir", lambda _: OUTPUT_DIR)
    monkeypatch.setattr(
        module,
        "evaluate_krt_run",
        lambda *_args, **_kwargs: {
            "run_id": "initial-pass",
            "mcmc_status": "pass",
            "mcmc_substatus": "pass",
        },
    )
    monkeypatch.setattr(
        module,
        "_select_pair",
        lambda *_args, **_kwargs: (
            {
                "election_id": "leg_1962_r1",
                "scenario_id": "H0B",
                "run_id": "initial-pass",
                "panel_id": "panel",
                "mcmc_status": "pass",
                "mcmc_substatus": "pass",
                "identification_status": "caveat",
            },
            {
                "selection_reason": "initial_pass",
                "replaces_run_id": "",
                "compatibility": {},
            },
        ),
    )
    result = module.rerun_pair_if_required(Path("scope.json"), "leg_1962_r1", "H0B")
    assert result["status"] == "not_required"
    assert result["selected_run_id"] == "initial-pass"
    (OUTPUT_DIR / "targeted_rerun__leg_1962_r1__H0B.json").unlink(missing_ok=True)
    (OUTPUT_DIR / "targeted_rerun_supervisor_status.json").unlink(missing_ok=True)
    (OUTPUT_DIR / "targeted_rerun_logs").rmdir()


def test_severe_initial_uses_single_pair_selection(monkeypatch) -> None:
    monkeypatch.setattr(module, "load_release_scope", lambda _: _scope())
    monkeypatch.setattr(module, "_production_dir", lambda _: OUTPUT_DIR)
    monkeypatch.setattr(
        module,
        "evaluate_krt_run",
        lambda *_args, **_kwargs: {
            "run_id": "initial-severe",
            "mcmc_status": "caveat",
            "mcmc_substatus": "caveat_severe",
        },
    )
    monkeypatch.setattr(
        module,
        "_select_pair",
        lambda *_args, **_kwargs: (
            {
                "election_id": "leg_1962_r1",
                "scenario_id": "H0B",
                "run_id": "rerun-pass",
                "panel_id": "panel",
                "mcmc_status": "pass",
                "mcmc_substatus": "pass",
                "identification_status": "caveat",
            },
            {
                "selection_reason": "strengthened_rerun_after_caveat_severe",
                "replaces_run_id": "initial-severe",
                "compatibility": {"compatible": True},
            },
        ),
    )
    result = module.rerun_pair_if_required(Path("scope.json"), "leg_1962_r1", "H0B")
    assert result["status"] == "selected"
    assert result["selected_run_id"] == "rerun-pass"
    assert result["compatibility"]["compatible"] is True
    (OUTPUT_DIR / "targeted_rerun__leg_1962_r1__H0B.json").unlink(missing_ok=True)
    (OUTPUT_DIR / "targeted_rerun_supervisor_status.json").unlink(missing_ok=True)
    (OUTPUT_DIR / "targeted_rerun_logs").rmdir()


def test_missing_initial_is_recovered(monkeypatch) -> None:
    monkeypatch.setattr(module, "load_release_scope", lambda _: _scope())
    monkeypatch.setattr(module, "_production_dir", lambda _: OUTPUT_DIR)
    recovered = {
        "run_id": "recovered-initial",
        "mcmc_status": "pass",
        "mcmc_substatus": "pass",
    }
    evaluations = iter((None, recovered))
    monkeypatch.setattr(module, "evaluate_krt_run", lambda *_args, **_kwargs: next(evaluations))
    monkeypatch.setattr(
        module,
        "_select_pair",
        lambda *_args, **_kwargs: (
            {
                "election_id": "leg_1962_r1",
                "scenario_id": "H0B",
                "run_id": "recovered-initial",
                "panel_id": "panel",
                "mcmc_status": "pass",
                "mcmc_substatus": "pass",
                "identification_status": "caveat",
            },
            {
                "selection_reason": "initial_pass",
                "replaces_run_id": "",
                "compatibility": {},
            },
        ),
    )
    result = module.rerun_pair_if_required(Path("scope.json"), "leg_1962_r1", "H0B")
    assert result["status"] == "initial_recovered"
    assert result["selected_run_id"] == "recovered-initial"
    (OUTPUT_DIR / "targeted_rerun__leg_1962_r1__H0B.json").unlink(missing_ok=True)
    (OUTPUT_DIR / "targeted_rerun_supervisor_status.json").unlink(missing_ok=True)
    (OUTPUT_DIR / "targeted_rerun_logs").rmdir()
