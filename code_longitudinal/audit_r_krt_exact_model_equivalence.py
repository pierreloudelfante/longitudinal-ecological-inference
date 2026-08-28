from __future__ import annotations

import inspect
import json
from datetime import datetime, timezone
from pathlib import Path

from .audit_all_2x2_model_ready import MANIFEST_PATH as MODEL_READY_AUDIT_PATH
from .paths import OUTPUT_DIR, ROOT
from .spec_registry import SPEC_VERSION
from .utils import file_sha256, portable_path, write_json


STAN_PATH = ROOT / "r_replication" / "king99_pyei_exact.stan"
STAN_RUNNER_PATH = ROOT / "r_replication" / "run_krt_replication.R"
NIMBLE_RUNNER_PATH = ROOT / "r_replication" / "run_krt_replication_nimble.R"
STAN_ATTEMPT_PATH = (
    OUTPUT_DIR
    / SPEC_VERSION
    / "r_replication"
    / "krt_runs"
    / "leg_1962_r1__H0A"
    / "chains"
    / "king99_pyei_exact-202608111333-1-3289de.csv"
)
OUTPUT_PATH = (
    OUTPUT_DIR / SPEC_VERSION / "r_replication" / "r_krt_exact_model_equivalence_audit.json"
)


def _require_tokens(label: str, source: str, tokens: tuple[str, ...]) -> list[str]:
    missing = [token for token in tokens if token not in source]
    if missing:
        raise AssertionError(f"{label} is missing required model tokens: {missing}")
    return list(tokens)


def audit() -> dict[str, object]:
    import pyei.two_by_two as two_by_two

    pyei_source = inspect.getsource(two_by_two.ei_beta_binom_model)
    stan_source = STAN_PATH.read_text(encoding="utf-8")
    nimble_source = NIMBLE_RUNNER_PATH.read_text(encoding="utf-8")
    stan_runner_source = STAN_RUNNER_PATH.read_text(encoding="utf-8")
    model_ready_audit = json.loads(MODEL_READY_AUDIT_PATH.read_text(encoding="utf-8-sig"))
    if model_ready_audit.get("ready_for_estimation") is not True:
        raise AssertionError("the 240 model-ready inputs have not passed their audit")

    checks = {
        "pyei": _require_tokens(
            "PyEI",
            pyei_source,
            (
                'pm.Exponential("c_1", lmbda)',
                'pm.Exponential("d_1", lmbda)',
                'pm.Exponential("c_2", lmbda)',
                'pm.Exponential("d_2", lmbda)',
                'pm.Beta("b_1", alpha=c_1, beta=d_1',
                'pm.Beta("b_2", alpha=c_2, beta=d_2',
                "theta = group_fraction * b_1 + (1 - group_fraction) * b_2",
                'pm.Binomial("votes_count", n=precinct_pops, p=theta, observed=votes_count_obs)',
            ),
        ),
        "stan": _require_tokens(
            "Stan",
            stan_source,
            (
                "c_1 ~ exponential(king_lambda);",
                "d_1 ~ exponential(king_lambda);",
                "c_2 ~ exponential(king_lambda);",
                "d_2 ~ exponential(king_lambda);",
                "b_1 ~ beta(c_1, d_1);",
                "b_2 ~ beta(c_2, d_2);",
                "vector[P] theta = x .* b_1 + (1 - x) .* b_2;",
                "Y ~ binomial(N, theta);",
            ),
        ),
        "nimble": _require_tokens(
            "NIMBLE",
            nimble_source,
            (
                "c_1 ~ dexp(rate = king_lambda)",
                "d_1 ~ dexp(rate = king_lambda)",
                "c_2 ~ dexp(rate = king_lambda)",
                "d_2 ~ dexp(rate = king_lambda)",
                "b_1[i] ~ dbeta(c_1, d_1)",
                "b_2[i] ~ dbeta(c_2, d_2)",
                "theta[i] <- x[i] * b_1[i] + (1 - x[i]) * b_2[i]",
                "Y[i] ~ dbin(prob = theta[i], size = N[i])",
            ),
        ),
        "dynamic_2x2_partition_stan": _require_tokens(
            "Stan R runner",
            stan_runner_source,
            (
                'grep("^X__", names(frame), value = TRUE)',
                'grep("^N__", names(frame), value = TRUE)',
                'grep("^Y__", names(frame), value = TRUE)',
            ),
        ),
        "dynamic_2x2_partition_nimble": _require_tokens(
            "NIMBLE R runner",
            nimble_source,
            (
                'grep("^X__", names(frame), value = TRUE)',
                'grep("^N__", names(frame), value = TRUE)',
                'grep("^Y__", names(frame), value = TRUE)',
            ),
        ),
    }
    stan_attempt_lines = STAN_ATTEMPT_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    stan_noncomment = [line for line in stan_attempt_lines if line and not line.startswith("#")]
    stan_draw_rows = max(0, len(stan_noncomment) - 1)
    stan_start_line = next(
        line for line in stan_attempt_lines if line.startswith("# start_datetime = ")
    )
    stan_started = datetime.strptime(
        stan_start_line.removeprefix("# start_datetime = ").removesuffix(" UTC"),
        "%Y-%m-%d %H:%M:%S",
    ).replace(tzinfo=timezone.utc)
    stan_last_write = datetime.fromtimestamp(STAN_ATTEMPT_PATH.stat().st_mtime, tz=timezone.utc)
    stan_observed_hours = (stan_last_write - stan_started).total_seconds() / 3600
    result = {
        "schema_version": "longitudinal_r_krt_exact_model_equivalence_audit_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "mathematical_model_identical": True,
        "sampler_identical": False,
        "samplers": {
            "python": "PyMC NUTS used through the PyEI King99 model builder",
            "r_stan": "CmdStan NUTS",
            "r_nimble": "compiled NIMBLE slice hyperparameter samplers and adaptive b1/b2 RW blocks",
        },
        "engine_selection": {
            "primary_engine": "R_NIMBLE",
            "status": "provisional_until_first_full_2000_commune_nimble_fit",
            "reason": (
                "The exact CmdStan implementation is retained as a reference, but its interrupted "
                "one-chain trial produced only 113 retained draws after about 7.64 hours. "
                "It is therefore not a feasible primary engine for 240 full fits on this machine."
            ),
            "stan_reference_attempt": {
                "path": portable_path(STAN_ATTEMPT_PATH, root=ROOT),
                "sha256": file_sha256(STAN_ATTEMPT_PATH),
                "requested_warmup": 1000,
                "requested_draws": 1000,
                "requested_chains": 1,
                "retained_draw_rows": stan_draw_rows,
                "observed_elapsed_hours": stan_observed_hours,
                "complete": False,
            },
            "nimble_full_panel_pilot": "queued_after_python_240_attempts",
        },
        "equivalent_hierarchy": {
            "hyperpriors": "c1,d1,c2,d2 iid Exponential(rate=king_lambda)",
            "commune_priors": "b1_i~Beta(c1,d1); b2_i~Beta(c2,d2)",
            "mixture": "theta_i=x_i*b1_i+(1-x_i)*b2_i",
            "likelihood": "Y_i~Binomial(N_i,theta_i)",
            "king_lambda": 0.5,
        },
        "integer_likelihood_note": (
            "PyEI receives the exactly reconstructed fraction Y/N and internally multiplies it by N; "
            "the R implementations receive the audited integer Y directly."
        ),
        "model_ready_audit": {
            "path": portable_path(MODEL_READY_AUDIT_PATH, root=ROOT),
            "sha256": file_sha256(MODEL_READY_AUDIT_PATH),
            "audited_pairs": model_ready_audit["audited_pairs"],
            "valid_pairs": model_ready_audit["valid_pairs"],
            "maximum_social_closure_gap": model_ready_audit["maximum_social_closure_gap"],
            "maximum_political_closure_gap": model_ready_audit["maximum_political_closure_gap"],
            "maximum_parquet_csv_numeric_gap": model_ready_audit[
                "maximum_parquet_csv_numeric_gap"
            ],
            "parquet_csv_scientific_equivalence_all_pairs": model_ready_audit[
                "parquet_csv_scientific_equivalence_all_pairs"
            ],
        },
        "sources": {
            "pyei_module": portable_path(Path(two_by_two.__file__), root=ROOT),
            "pyei_module_sha256": file_sha256(Path(two_by_two.__file__)),
            "stan_model": portable_path(STAN_PATH, root=ROOT),
            "stan_model_sha256": file_sha256(STAN_PATH),
            "stan_runner": portable_path(STAN_RUNNER_PATH, root=ROOT),
            "stan_runner_sha256": file_sha256(STAN_RUNNER_PATH),
            "nimble_runner": portable_path(NIMBLE_RUNNER_PATH, root=ROOT),
            "nimble_runner_sha256": file_sha256(NIMBLE_RUNNER_PATH),
        },
        "checks": checks,
        "ready_for_exact_r_sampling": True,
    }
    write_json(OUTPUT_PATH, result)
    return result


def main() -> None:
    print(json.dumps(audit(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
