from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .spec_registry import ELECTIONS, ELECTION_BY_ID, SCENARIO_BY_ID


SEED_DERIVATION_VERSION = "sha256_first8_mod_int31_v1"
KRT_PARAMETERIZATION_V1 = "king99_beta_binomial_independent_beta_random_effects_v1"


@dataclass(frozen=True)
class MCMCSettings:
    chains: int
    warmup: int
    draws: int
    target_accept: float
    max_treedepth: int
    sampler_backend: str
    initial_base_seed: int
    rerun_base_seed: int
    seed_derivation_version: str
    execution_cores: int


@dataclass(frozen=True)
class KRTModelSettings:
    model_key: str
    parameterization_version: str
    likelihood: str
    hyperpriors: str
    commune_priors: str
    aggregate_estimand_version: str
    observed_count_roundtrip_version: str
    king_lambda: float


@dataclass(frozen=True)
class ReleaseScope:
    release_id: str
    ready_scope: str
    public_schema_version: str
    spec_version: str
    krt_scenarios: tuple[str, ...]
    panel_size: int
    panel_sha256: str
    expected_elections: int
    expected_nls_pairs: int
    aggregate_estimands_per_pair: int
    expected_krt_status_counts: Mapping[str, Mapping[str, int]]
    pilot_pairs: tuple[tuple[str, str], ...]
    krt_model: KRTModelSettings
    mcmc: MCMCSettings

    @property
    def expected_krt_pairs(self) -> int:
        return self.expected_elections * len(self.krt_scenarios)

    @property
    def expected_krt_commune_rows(self) -> int:
        return self.expected_krt_pairs * self.panel_size

    @property
    def expected_krt_aggregate_rows(self) -> int:
        return self.expected_krt_pairs * self.aggregate_estimands_per_pair

    def run_seed(self, scenario_id: str, election_id: str, *, rerun: bool = False) -> int:
        base_seed = self.mcmc.rerun_base_seed if rerun else self.mcmc.initial_base_seed
        return stable_run_seed(
            base_seed=base_seed,
            spec_version=self.spec_version,
            scenario_id=scenario_id,
            election_id=election_id,
            derivation_version=self.mcmc.seed_derivation_version,
        )


def krt_parameterization_matches(
    parameters: Mapping[str, Any], scope: ReleaseScope
) -> bool:
    """Match native tags and the verified pre-tagging King99 runs.

    Runs created before the public v1.0.2 schema did not persist a
    parameterization label. They are accepted only for the one King99 model
    version whose likelihood, priors and lambda were already fixed and audited.
    New runs persist the version explicitly.
    """
    recorded = str(parameters.get("krt_parameterization_version", "")).strip()
    if recorded:
        return recorded == scope.krt_model.parameterization_version
    return scope.krt_model.parameterization_version == KRT_PARAMETERIZATION_V1


def stable_run_seed(
    *,
    base_seed: int,
    spec_version: str,
    scenario_id: str,
    election_id: str,
    derivation_version: str = SEED_DERIVATION_VERSION,
) -> int:
    if derivation_version != SEED_DERIVATION_VERSION:
        raise ValueError(f"Unknown seed derivation version: {derivation_version}")
    payload = f"{int(base_seed)}|{spec_version}|{scenario_id}|{election_id}"
    value = int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")
    return value % (2**31 - 1) or 1


def caveat_severity(
    *,
    official_status: str,
    max_rhat: float | None,
    min_ess: float | None,
    min_bfmi: float | None,
    divergences: int | None,
    treedepth_saturated: int | None,
) -> str:
    status = str(official_status).strip().lower()
    if status == "pass":
        return "pass"
    if status == "fail":
        return "fail"
    if status != "caveat":
        raise ValueError(f"Unknown official MCMC status: {official_status}")
    metrics = (max_rhat, min_ess, min_bfmi, divergences, treedepth_saturated)
    if any(value is None for value in metrics):
        return "caveat_severe"
    moderate = (
        float(max_rhat) <= 1.03
        and float(min_ess) >= 200.0
        and float(min_bfmi) >= 0.25
        and int(divergences) == 0
        and int(treedepth_saturated) == 0
    )
    return "caveat_modere" if moderate else "caveat_severe"


def _require(mapping: Mapping[str, Any], key: str) -> Any:
    if key not in mapping:
        raise ValueError(f"Missing release configuration field: {key}")
    return mapping[key]


def release_scope_from_mapping(raw: Mapping[str, Any]) -> ReleaseScope:
    mcmc_raw = _require(raw, "mcmc")
    if not isinstance(mcmc_raw, Mapping):
        raise ValueError("mcmc must be an object")
    krt_raw = _require(raw, "krt_model")
    if not isinstance(krt_raw, Mapping):
        raise ValueError("krt_model must be an object")
    scenarios = tuple(str(value) for value in _require(raw, "krt_scenarios"))
    if not scenarios or len(set(scenarios)) != len(scenarios):
        raise ValueError("krt_scenarios must contain unique scenario identifiers")
    unknown = sorted(set(scenarios).difference(SCENARIO_BY_ID))
    if unknown:
        raise ValueError(f"Unknown KRT scenarios: {unknown}")

    status_counts_raw = raw.get("expected_krt_status_counts", {})
    if not isinstance(status_counts_raw, Mapping):
        raise ValueError("expected_krt_status_counts must be an object")
    status_counts = {
        str(scenario_id): {str(status): int(count) for status, count in counts.items()}
        for scenario_id, counts in status_counts_raw.items()
    }
    pilot_raw = _require(raw, "pilot_pairs")
    if not isinstance(pilot_raw, list):
        raise ValueError("pilot_pairs must be an array")
    pilot_pairs: list[tuple[str, str]] = []
    for item in pilot_raw:
        if not isinstance(item, Mapping):
            raise ValueError("each pilot_pairs item must be an object")
        pilot_pairs.append((str(_require(item, "election_id")), str(_require(item, "scenario_id"))))
    if len(set(pilot_pairs)) != len(pilot_pairs):
        raise ValueError("pilot_pairs must contain unique election/scenario pairs")
    scope = ReleaseScope(
        release_id=str(_require(raw, "release_id")),
        ready_scope=str(_require(raw, "ready_scope")),
        public_schema_version=str(_require(raw, "public_schema_version")),
        spec_version=str(_require(raw, "spec_version")),
        krt_scenarios=scenarios,
        panel_size=int(_require(raw, "panel_size")),
        panel_sha256=str(_require(raw, "panel_sha256")),
        expected_elections=int(_require(raw, "expected_elections")),
        expected_nls_pairs=int(_require(raw, "expected_nls_pairs")),
        aggregate_estimands_per_pair=int(_require(raw, "aggregate_estimands_per_pair")),
        expected_krt_status_counts=status_counts,
        pilot_pairs=tuple(pilot_pairs),
        krt_model=KRTModelSettings(
            model_key=str(_require(krt_raw, "model_key")),
            parameterization_version=str(_require(krt_raw, "parameterization_version")),
            likelihood=str(_require(krt_raw, "likelihood")),
            hyperpriors=str(_require(krt_raw, "hyperpriors")),
            commune_priors=str(_require(krt_raw, "commune_priors")),
            aggregate_estimand_version=str(_require(krt_raw, "aggregate_estimand_version")),
            observed_count_roundtrip_version=str(_require(krt_raw, "observed_count_roundtrip_version")),
            king_lambda=float(_require(krt_raw, "king_lambda")),
        ),
        mcmc=MCMCSettings(
            chains=int(_require(mcmc_raw, "chains")),
            warmup=int(_require(mcmc_raw, "warmup")),
            draws=int(_require(mcmc_raw, "draws")),
            target_accept=float(_require(mcmc_raw, "target_accept")),
            max_treedepth=int(_require(mcmc_raw, "max_treedepth")),
            sampler_backend=str(mcmc_raw.get("sampler_backend", "numpyro")),
            initial_base_seed=int(_require(mcmc_raw, "initial_base_seed")),
            rerun_base_seed=int(_require(mcmc_raw, "rerun_base_seed")),
            seed_derivation_version=str(_require(mcmc_raw, "seed_derivation_version")),
            execution_cores=int(mcmc_raw.get("execution_cores", 1)),
        ),
    )
    if scope.expected_elections != len(ELECTIONS):
        raise ValueError(
            f"expected_elections={scope.expected_elections}, registry contains {len(ELECTIONS)}"
        )
    if scope.panel_size <= 0 or scope.expected_nls_pairs <= 0:
        raise ValueError("Panel size and NLS pair count must be positive")
    if len(scope.panel_sha256) != 64:
        raise ValueError("panel_sha256 must contain 64 hexadecimal characters")
    int(scope.panel_sha256, 16)
    if scope.mcmc.seed_derivation_version != SEED_DERIVATION_VERSION:
        raise ValueError(
            f"Unsupported seed derivation version: {scope.mcmc.seed_derivation_version}"
        )
    if scope.mcmc.sampler_backend not in {"numpyro", "pymc"}:
        raise ValueError(f"Unsupported sampler backend: {scope.mcmc.sampler_backend}")
    if not 1 <= scope.mcmc.execution_cores <= scope.mcmc.chains:
        raise ValueError("mcmc.execution_cores must be between 1 and mcmc.chains")
    if scope.krt_model.model_key != "krt_beta_binomial":
        raise ValueError("krt_model.model_key must be krt_beta_binomial")
    if not scope.krt_model.parameterization_version.strip():
        raise ValueError("krt_model.parameterization_version must be explicit")
    if not math.isfinite(scope.krt_model.king_lambda) or scope.krt_model.king_lambda <= 0:
        raise ValueError("krt_model.king_lambda must be finite and positive")
    for election_id, scenario_id in scope.pilot_pairs:
        if election_id not in ELECTION_BY_ID:
            raise ValueError(f"Unknown pilot election: {election_id}")
        if scenario_id not in scope.krt_scenarios:
            raise ValueError(f"Pilot scenario outside release scope: {scenario_id}")
    return scope


def load_release_scope(path: Path | str) -> ReleaseScope:
    config_path = Path(path)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError("Release configuration root must be an object")
    return release_scope_from_mapping(raw)
