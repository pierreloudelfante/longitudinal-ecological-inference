from code_longitudinal.h23_pilot_gate import (
    _nls_contrast,
    intervals_compatible,
    method_sensitivity_assessment,
    resolve_pilot_pair_for_gate,
)
from code_longitudinal.h23_supervisor import _write_pilot_gate
from code_longitudinal.paths import ROOT
from code_longitudinal.release_scope import load_release_scope


def test_pilot_pairs_are_exact() -> None:
    scope = load_release_scope(ROOT / "config" / "releases" / "v1.1.json")
    assert scope.pilot_pairs == (
        ("leg_1962_r1", "H2"),
        ("leg_1962_r1", "H3"),
        ("leg_1986_r1", "H2"),
        ("leg_1986_r1", "H3"),
        ("leg_2022_r1", "H2"),
        ("leg_2022_r1", "H3"),
    )


def test_interval_compatibility_requires_overlap_without_supported_sign_inversion() -> None:
    initial = {"krt_q025": -0.10, "krt_q975": 0.20}
    compatible = {"krt_q025": 0.05, "krt_q975": 0.30}
    incompatible = {"krt_q025": 0.21, "krt_q975": 0.40}
    assert intervals_compatible(initial, compatible)["compatible"] is True
    assert intervals_compatible(initial, incompatible)["compatible"] is False


def test_interval_compatibility_rejects_sustained_sign_inversion() -> None:
    initial = {"krt_q025": 0.02, "krt_q975": 0.10}
    rerun = {"krt_q025": -0.12, "krt_q975": -0.01}
    result = intervals_compatible(initial, rerun)
    assert result["sustained_sign_inversion"] is True
    assert result["compatible"] is False


def test_nls_gate_reads_the_canonical_public_table() -> None:
    assert abs(_nls_contrast("leg_1962_r1", "H2") - 0.041946760210619216) < 1e-15


def test_nls_gate_uses_the_scenario_specific_target_vote() -> None:
    expected = {
        ("leg_1962_r1", "H0A"): -0.10876859896446558,  # abstention
        ("leg_1986_r1", "H4"): 0.11003811651873863,   # droite
        ("leg_1986_r1", "H5"): 0.006829416514754101,  # centre
        ("leg_1997_r1", "H6"): 0.1234508471186412,    # FN/RN
    }
    for (election_id, scenario_id), estimate in expected.items():
        assert abs(_nls_contrast(election_id, scenario_id) - estimate) < 1e-15


def test_gate_selects_a_compatible_strengthened_caveat() -> None:
    initial = {
        "run_id": "initial",
        "mcmc_status": "caveat",
        "mcmc_substatus": "caveat_severe",
        "core_gate_pass": True,
        "gate_reasons": "strengthened_rerun_required",
        "krt_q025": -0.10,
        "krt_q975": 0.20,
    }
    rerun = {
        "run_id": "rerun",
        "mcmc_status": "caveat",
        "mcmc_substatus": "caveat_severe",
        "core_gate_pass": True,
        "gate_reasons": "",
        "krt_q025": -0.05,
        "krt_q975": 0.15,
    }
    resolved = resolve_pilot_pair_for_gate(initial, rerun)
    assert resolved["gate_status"] == "pass"
    assert resolved["selected_run_id"] == "rerun"
    assert resolved["replaces_run_id"] == "initial"


def test_gate_holds_a_strengthened_rerun_that_still_fails() -> None:
    initial = {
        "run_id": "initial",
        "mcmc_status": "fail",
        "mcmc_substatus": "fail",
        "core_gate_pass": False,
        "gate_reasons": "mcmc_not_fail|strengthened_rerun_required",
        "krt_q025": -0.10,
        "krt_q975": 0.20,
    }
    rerun = {
        "run_id": "rerun",
        "mcmc_status": "fail",
        "mcmc_substatus": "fail",
        "core_gate_pass": False,
        "gate_reasons": "mcmc_not_fail",
        "krt_q025": -0.05,
        "krt_q975": 0.15,
    }
    resolved = resolve_pilot_pair_for_gate(initial, rerun)
    assert resolved["gate_status"] == "hold"
    assert resolved["selected_run_id"] == ""
    assert "strengthened_rerun_mcmc_fail" in resolved["gate_reasons"]


def test_explicit_run_level_continuation_does_not_claim_pilot_gate_success(tmp_path) -> None:
    result = _write_pilot_gate(
        tmp_path,
        selections=[],
        evaluations=[],
        pilot_pairs=(("leg_1962_r1", "H2"),),
        allow_run_level_continuation=True,
    )
    assert result["go_for_remaining_runs"] is False
    assert result["run_level_continuation_authorized"] is True
    assert (tmp_path / "h23_pilot_gate_supervised.json").is_file()


def test_krt_nls_alert_is_not_an_mcmc_failure() -> None:
    result = method_sensitivity_assessment(
        absolute_difference=0.20,
        sustained_sign_opposition=False,
    )
    assert result["method_sensitivity_status"] == "alert"
    assert result["krt_nls_distance_le_0_15"] is False
    assert "mcmc" not in result["method_sensitivity_reasons"]
