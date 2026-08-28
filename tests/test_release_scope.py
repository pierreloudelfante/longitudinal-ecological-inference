from __future__ import annotations

from pathlib import Path

import pytest

from code_longitudinal.release_scope import (
    caveat_severity,
    krt_parameterization_matches,
    load_release_scope,
)


ROOT = Path(__file__).resolve().parents[1]


def test_release_counts_are_derived_from_scope() -> None:
    v102 = load_release_scope(ROOT / "config" / "releases" / "v1.0.2.json")
    assert v102.expected_krt_pairs == 52
    assert v102.expected_krt_commune_rows == 104_000
    assert v102.expected_krt_aggregate_rows == 156

    v11 = load_release_scope(ROOT / "config" / "releases" / "v1.1.json")
    assert v11.expected_krt_pairs == 104
    assert v11.expected_krt_commune_rows == 208_000
    assert v11.expected_krt_aggregate_rows == 312
    assert v11.mcmc.sampler_backend == "numpyro"
    assert v11.mcmc.execution_cores == 1
    assert v11.krt_model.king_lambda == 0.5
    assert v11.krt_model.parameterization_version == (
        "king99_beta_binomial_independent_beta_random_effects_v1"
    )
    assert len(v11.pilot_pairs) == 6

    fallback = load_release_scope(ROOT / "config" / "releases" / "v1.1_pymc_fallback.json")
    assert fallback.mcmc.sampler_backend == "pymc"
    assert fallback.mcmc.execution_cores == 1


def test_seed_derivation_is_stable_distinct_and_bounded() -> None:
    scope = load_release_scope(ROOT / "config" / "releases" / "v1.1.json")
    seed = scope.run_seed("H2", "leg_1962_r1")
    assert seed == scope.run_seed("H2", "leg_1962_r1")
    assert seed != scope.run_seed("H3", "leg_1962_r1")
    assert seed != scope.run_seed("H2", "leg_1986_r1")
    assert seed != scope.run_seed("H2", "leg_1962_r1", rerun=True)
    assert 1 <= seed < 2**31 - 1


def test_krt_parameterization_accepts_verified_legacy_and_rejects_wrong_tag() -> None:
    scope = load_release_scope(ROOT / "config" / "releases" / "v1.1.json")
    assert krt_parameterization_matches({}, scope)
    assert krt_parameterization_matches(
        {"krt_parameterization_version": scope.krt_model.parameterization_version}, scope
    )
    assert not krt_parameterization_matches(
        {"krt_parameterization_version": "different_model_v9"}, scope
    )


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"official_status": "pass"}, "pass"),
        ({"official_status": "fail"}, "fail"),
        (
            {
                "official_status": "caveat",
                "max_rhat": 1.02,
                "min_ess": 250,
                "min_bfmi": 0.30,
                "divergences": 0,
                "treedepth_saturated": 0,
            },
            "caveat_modere",
        ),
        (
            {
                "official_status": "caveat",
                "max_rhat": 1.031,
                "min_ess": 250,
                "min_bfmi": 0.30,
                "divergences": 0,
                "treedepth_saturated": 0,
            },
            "caveat_severe",
        ),
        ({"official_status": "caveat"}, "caveat_severe"),
    ],
)
def test_caveat_severity(kwargs: dict[str, object], expected: str) -> None:
    complete = {
        "max_rhat": None,
        "min_ess": None,
        "min_bfmi": None,
        "divergences": None,
        "treedepth_saturated": None,
        **kwargs,
    }
    assert caveat_severity(**complete) == expected
