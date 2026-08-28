from __future__ import annotations

import argparse
import json
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import psutil

from .paths import OUTPUT_DIR, ROOT
from .run_2x2_batch import stable_vote_fractions
from .utils import file_sha256, write_json


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def benchmark_numpyro_king(
    *,
    model_ready_path: Path,
    output_path: Path,
    tune: int = 5,
    draws: int = 5,
    random_seed: int = 1710020224,
) -> dict[str, Any]:
    model_ready_path = model_ready_path.resolve()
    frame = pd.read_parquet(model_ready_path)
    required = {"unit_id", "X__target_group", "Y__gauche", "N_g"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"model-ready benchmark input misses columns: {missing}")
    if len(frame) != 2000 or frame["unit_id"].astype("string").nunique() != 2000:
        raise AssertionError("backend benchmark requires exactly 2,000 unique communes")
    x = frame["X__target_group"].astype(float).to_numpy()
    n = frame["N_g"].astype(int).to_numpy()
    y_count = frame["Y__gauche"].astype(int).to_numpy()
    y = stable_vote_fractions(y_count, n)
    from pyei.two_by_two import TwoByTwoEI

    process = psutil.Process()
    memory_before = process.memory_info().rss / (1024**2)
    started = time.perf_counter()
    result: dict[str, Any] = {
        "benchmark_schema_version": "v1",
        "run_role": "diagnostic_only",
        "backend": "numpyro",
        "model_key": "krt_beta_binomial",
        "king_lambda": 0.5,
        "n_communes": len(frame),
        "chains": 1,
        "tune": tune,
        "draws": draws,
        "target_accept": 0.99,
        "max_treedepth": 14,
        "random_seed": random_seed,
        "model_ready_path": model_ready_path.relative_to(ROOT).as_posix(),
        "model_ready_sha256": file_sha256(model_ready_path),
        "created_at_utc": _utc_now(),
    }
    try:
        model = TwoByTwoEI("king99", lmbda=0.5)
        model.fit(
            x,
            y,
            n,
            tune=tune,
            draws=draws,
            chains=1,
            cores=1,
            random_seed=random_seed,
            progressbar=False,
            target_accept=0.99,
            nuts={"max_tree_depth": 14},
        )
        elapsed = time.perf_counter() - started
        sizes = model.sim_trace.posterior.sizes
        result.update(
            {
                "status": "pass",
                "recommended_backend": "numpyro",
                "recommendation_reason": "The exact 2,000-commune King graph compiled and sampled with NumPyro.",
                "elapsed_seconds": elapsed,
                "saved_chains": int(sizes.get("chain", 0)),
                "saved_draws_per_chain": int(sizes.get("draw", 0)),
                "memory_before_mb": memory_before,
                "memory_after_mb": process.memory_info().rss / (1024**2),
                "error_type": "",
                "error": "",
            }
        )
    except Exception as exc:  # diagnostic evidence must survive a backend failure
        result.update(
            {
                "status": "fail",
                "recommended_backend": "pymc",
                "recommendation_reason": "NumPyro failed on the exact 2,000-commune King graph; use the PyMC fallback.",
                "elapsed_seconds": time.perf_counter() - started,
                "saved_chains": 0,
                "saved_draws_per_chain": 0,
                "memory_before_mb": memory_before,
                "memory_after_mb": process.memory_info().rss / (1024**2),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback_tail": traceback.format_exc().splitlines()[-12:],
            }
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(output_path, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnostic-only NumPyro benchmark for the 2,000-commune King model.")
    parser.add_argument("--model-ready", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_DIR / "longitudinal_2000_v1" / "production" / "backend_benchmark_2000.json",
    )
    parser.add_argument("--tune", type=int, default=5)
    parser.add_argument("--draws", type=int, default=5)
    parser.add_argument("--random-seed", type=int, default=1710020224)
    args = parser.parse_args()
    result = benchmark_numpyro_king(
        model_ready_path=args.model_ready,
        output_path=args.output,
        tune=args.tune,
        draws=args.draws,
        random_seed=args.random_seed,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
