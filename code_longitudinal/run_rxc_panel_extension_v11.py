from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
from reproducibility.replication_scope import get_scope
from reproducibility.estimation_recovery import BatchEstimationError, execute_estimation_batch
from reproducibility.estimation_process import run_supervised

from .paths import OUTPUT_DIR, ROOT
from .prepare_inputs import model_ready_path, n_columns, read_panel, x_columns, y_columns
from .run_nls_batch import run_nls
from .run_longitudinal_production import _require_nls_saved_outputs
from .run_registry import read_registry
from .spec_registry import ELECTION_BY_ID, SCENARIO_BY_ID
from .utils import file_sha256, write_json


DEFAULT_AUDIT = (
    ROOT
    / "work"
    / "longitudinal_2000_v1.0.2_H0A_H1_validated"
    / "03_panel_et_audit"
    / "rxc_ineligible_audit.csv"
)
DEFAULT_PANEL = ROOT / "panel" / "longitudinal_2000_v1.parquet"
DEFAULT_OUTPUT_DIR = (
    OUTPUT_DIR / "longitudinal_2000_v1" / "production" / "rxc_nls_panel_extension_v11"
)

REQUIRED_TRUE = (
    "panel_raw_closure_within_tolerance",
    "panel_model_ready_exact_closure",
)
EXPECTED_PANEL_SHA256 = "bde70c71660fce29610d7931461d8db6181dba874514a1866b63cf16a81cec4a"


def _as_bool(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series.dtype):
        return series.fillna(False)
    return series.astype("string").str.strip().str.lower().map(
        {"true": True, "1": True, "yes": True, "false": False, "0": False, "no": False}
    ).fillna(False)


def eligible_deferred_pairs(
    audit: pd.DataFrame, *, expected_pairs: frozenset[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
    """Validate the same closure audit for every deferred pair in the scope."""
    if expected_pairs is None:
        expected_pairs = get_scope().extension_nls_pairs
    required = {
        "election_id",
        "scenario_id",
        "in_panel_2000",
        *REQUIRED_TRUE,
        "mapping_status",
        "panel_scope_assessment",
        "execution_status",
    }
    missing = sorted(required.difference(audit.columns))
    if missing:
        raise ValueError(f"RxC audit missing columns: {missing}")
    normalized = audit.loc[
        [(str(election), str(scenario)) in expected_pairs
         for election, scenario in audit[["election_id", "scenario_id"]].itertuples(index=False, name=None)]
    ].copy()
    if normalized.empty and expected_pairs:
        raise ValueError("RxC audit is empty")
    if not expected_pairs:
        return []
    normalized["in_panel_2000"] = _as_bool(normalized["in_panel_2000"])
    for column in REQUIRED_TRUE:
        normalized[column] = _as_bool(normalized[column])

    bad = normalized.loc[
        normalized["in_panel_2000"]
        | ~normalized["panel_raw_closure_within_tolerance"]
        | ~normalized["panel_model_ready_exact_closure"]
        | normalized["mapping_status"].ne("no_mapping_error_detected")
        | normalized["panel_scope_assessment"].ne("potentially_admissible")
        | normalized["execution_status"].ne("deferred_to_v1.1")
        | ~normalized["scenario_id"].isin(["RXC1", "RXC2"])
    ]
    if not bad.empty:
        cols = ["election_id", "scenario_id", "unit_id"] if "unit_id" in bad else ["election_id", "scenario_id"]
        raise ValueError(f"RxC audit contains unsafe or ambiguous rows: {bad[cols].to_dict('records')}")

    pairs = sorted(
        normalized[["election_id", "scenario_id"]]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    )
    if len(normalized) != len(expected_pairs) or set(pairs) != expected_pairs:
        raise ValueError(
            f"expected exactly {len(expected_pairs)} scoped deferred rows and pairs, "
            f"observed rows={len(normalized)}, pairs={pairs}"
        )
    per_election = normalized.groupby("election_id")["scenario_id"].agg(lambda values: set(values))
    if not all(value == {"RXC1", "RXC2"} for value in per_election):
        raise ValueError("each deferred election must contain exactly RXC1 and RXC2")
    return [(str(election_id), str(scenario_id)) for election_id, scenario_id in pairs]


def validate_prepared_pair(
    election_id: str,
    scenario_id: str,
    *,
    panel_path: Path,
    sample_size: int = 2000,
) -> dict[str, object]:
    panel = read_panel(sample_size, panel_path=panel_path).sort_values("sample_rank")
    sample_id = str(panel["sample_id"].iloc[0])
    scenario = SCENARIO_BY_ID[scenario_id]
    prepared_path = model_ready_path(
        ELECTION_BY_ID[election_id], scenario, sample_id, sample_size=sample_size
    )
    if not prepared_path.exists():
        raise FileNotFoundError(f"model-ready output missing after NLS preparation: {prepared_path}")
    prepared = pd.read_parquet(prepared_path)
    prepared["unit_id"] = prepared["unit_id"].astype("string")
    panel_ids = panel["unit_id"].astype("string").tolist()
    prepared_ids = prepared.sort_values("sample_rank")["unit_id"].tolist()
    if len(prepared) != sample_size or prepared["unit_id"].nunique() != sample_size:
        raise AssertionError(
            f"{election_id}/{scenario_id}: expected {sample_size} unique rows, observed {len(prepared)}"
        )
    if prepared_ids != panel_ids:
        raise AssertionError(f"{election_id}/{scenario_id}: prepared unit_id/order differs from fixed panel")

    n = prepared["N_g"].astype("int64")
    social = prepared.loc[:, list(n_columns(scenario))].astype("int64")
    votes = prepared.loc[:, list(y_columns(scenario))].astype("int64")
    fractions = prepared.loc[:, list(x_columns(scenario))].astype(float)
    max_social_gap = int((social.sum(axis=1) - n).abs().max())
    max_vote_gap = int((votes.sum(axis=1) - n).abs().max())
    max_fraction_gap = float((fractions.sum(axis=1) - 1.0).abs().max())
    if (n <= 0).any() or (social < 0).any().any() or (votes < 0).any().any():
        raise AssertionError(f"{election_id}/{scenario_id}: non-positive denominator or negative count")
    if max_social_gap != 0 or max_vote_gap != 0 or max_fraction_gap > 1e-10:
        raise AssertionError(
            f"{election_id}/{scenario_id}: closure failure social={max_social_gap}, "
            f"vote={max_vote_gap}, fractions={max_fraction_gap}"
        )
    return {
        "model_ready_path": prepared_path.relative_to(ROOT).as_posix(),
        "model_ready_sha256": file_sha256(prepared_path),
        "n_rows": int(len(prepared)),
        "n_unique_unit_id": int(prepared["unit_id"].nunique()),
        "max_abs_social_sum_minus_N": max_social_gap,
        "max_abs_vote_sum_minus_N": max_vote_gap,
        "max_abs_x_sum_minus_one": max_fraction_gap,
    }


def _existing_success_run_id(election_id: str, scenario_id: str) -> str:
    registry = read_registry()
    if registry.empty:
        raise LookupError(f"no execution registry entry for {election_id}/{scenario_id}")
    matches = registry.loc[
        registry["stage"].eq("nls-longitudinal")
        & registry["status"].eq("success")
        & registry["election_id"].eq(election_id)
        & registry["scenario_id"].eq(scenario_id)
        & registry["model_key"].eq("rosen_nls")
        & registry["n_communes_requested"].eq("2000")
        & registry["n_communes_used"].eq("2000")
    ].sort_values("finished_at_utc")
    if matches.empty:
        raise LookupError(f"successful 2,000-commune NLS run not found for {election_id}/{scenario_id}")
    return str(matches.iloc[-1]["run_id"])


def _write_progress(rows: Iterable[dict[str, object]], output_dir: Path, *, status: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(list(rows))
    if frame.empty:
        frame = pd.DataFrame(columns=["election_id", "scenario_id", "run_id", "execution_status"])
    frame.to_csv(output_dir / "rxc_nls_panel_extension_progress.csv", index=False, encoding="utf-8-sig")
    frame.to_parquet(output_dir / "rxc_nls_panel_extension_progress.parquet", index=False)
    write_json(
        output_dir / "rxc_nls_panel_extension_status.json",
        {
            "status": status,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            "n_pairs_recorded": int(len(frame)),
            "n_success": int(frame.get("execution_status", pd.Series(dtype="string")).eq("success").sum()),
            "n_failed": int(frame.get("execution_status", pd.Series(dtype="string")).eq("failed").sum()),
            "public_270_results_modified": False,
        },
    )


def run_extension(
    *,
    audit_path: Path = DEFAULT_AUDIT,
    panel_path: Path = DEFAULT_PANEL,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    only_election_id: str | None = None,
    only_scenario_id: str | None = None,
    supervise: bool = False,
) -> list[dict[str, object]]:
    if file_sha256(panel_path) != EXPECTED_PANEL_SHA256:
        raise ValueError("fixed panel SHA-256 differs from the approved longitudinal panel")
    audit = pd.read_csv(audit_path, dtype={"unit_id": "string"})
    pairs = eligible_deferred_pairs(audit)
    if only_election_id:
        pairs = [pair for pair in pairs if pair[0] == only_election_id]
    if only_scenario_id:
        pairs = [pair for pair in pairs if pair[1] == only_scenario_id]
    if not pairs and get_scope().extension_nls_pairs:
        raise ValueError("filters select no audited deferred RxC pair")

    rows_by_pair: dict[tuple[str, str], dict[str, object]] = {}
    _write_progress([], output_dir, status="running")

    def run_one(pair):
        election_id, scenario_id = pair
        row: dict[str, object] = {
            "election_id": election_id,
            "scenario_id": scenario_id,
            "panel_sha256": EXPECTED_PANEL_SHA256,
            "execution_status": "running",
            "error": "",
        }
        rows_by_pair[pair] = row
        _write_progress(list(rows_by_pair.values()), output_dir, status="running")
        try:
            if supervise:
                key = election_id + "__" + scenario_id
                safe = re.sub(r"[^A-Za-z0-9_.-]", "_", key)
                state = ROOT / ".runtime" / ("replication_v2" if get_scope().is_full else "replication_court")
                log = state / "estimation_processes" / "nls_rxc" / f"{safe}.log"
                run_supervised(
                    [sys.executable, "-m", "reproducibility.replication_complete", "estimation-worker",
                     "--scope", get_scope().name, "--estimation-family", "nls_rxc", "--estimation-key", key],
                    family="nls_rxc", key=key, cwd=ROOT, stdout_path=log,
                    environment=os.environ.copy(),
                )
                success = _existing_success_run_id(election_id, scenario_id)
                result = {"status": "success", "run_id": success}
            else:
                result = run_nls(
                    ELECTION_BY_ID[election_id], SCENARIO_BY_ID[scenario_id],
                    sample_size=2000, panel_path=panel_path, force=False,
                )
            checks = validate_prepared_pair(
                election_id, scenario_id, panel_path=panel_path, sample_size=2000
            )
            row.update(result)
            if result.get("status") == "skipped_existing_success":
                row["run_id"] = _existing_success_run_id(election_id, scenario_id)
            if result.get("status") not in {"success", "skipped_existing_success"}:
                raise RuntimeError(f"RxC NLS returned unsuccessful status: {result}")
            _require_nls_saved_outputs(str(row.get("run_id", "")))
            row.update(checks)
            row["execution_status"] = "success" if result["status"] in {"success", "skipped_existing_success"} else str(result["status"])
        except Exception as exc:  # keep the other audited pairs independently runnable
            row["execution_status"] = "failed"
            row["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            _write_progress(list(rows_by_pair.values()), output_dir, status="running")
        return row

    scope = get_scope()
    try:
        rows = execute_estimation_batch(
            pairs, batch_name="nls_rxc_extension", key_fn=lambda pair: "__".join(pair), run=run_one,
            state_dir=ROOT / ".runtime" / ("replication_v2" if scope.is_full else "replication_court") / "estimation_failures",
            retry_failed=os.environ.get("LONGITUDINAL_RETRY_FAILED") == "1",
        )
    except BatchEstimationError:
        _write_progress(list(rows_by_pair.values()), output_dir, status="failed")
        raise

    final_status = "complete" if all(row["execution_status"] == "success" for row in rows) else "complete_with_failures"
    _write_progress(rows, output_dir, status=final_status)
    return rows


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the 22 panel-safe deferred RxC NLS pairs.")
    parser.add_argument("--audit-path", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--panel-path", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--election-id")
    parser.add_argument("--scenario-id", choices=["RXC1", "RXC2"])
    return parser


def main() -> None:
    args = _parser().parse_args()
    rows = run_extension(
        audit_path=args.audit_path,
        panel_path=args.panel_path,
        output_dir=args.output_dir,
        only_election_id=args.election_id,
        only_scenario_id=args.scenario_id,
    )
    print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
