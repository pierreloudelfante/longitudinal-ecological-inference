from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from reproducibility.replication_scope import get_scope

from .consolidation_core import build_nls
from .paths import OUTPUT_DIR, ROOT, RUNS_DIR
from .run_rxc_panel_extension_v11 import DEFAULT_OUTPUT_DIR, EXPECTED_PANEL_SHA256
from .spec_registry import SCENARIO_BY_ID
from .utils import file_sha256, write_json


BASE_NLS = (
    OUTPUT_DIR
    / "longitudinal_2000_v1"
    / "final"
    / "longitudinal_2000_v1.0.2_H0A_H1"
    / "longitudinal_nls.parquet"
)
PUBLIC_SCHEMA_VERSION = "longitudinal_public_schema_v1.0.2"


def _selected_runs(
    progress: pd.DataFrame, *, expected_pairs: frozenset[tuple[str, str]] | None = None,
) -> list[tuple[Path, dict[str, Any]]]:
    if expected_pairs is None:
        expected_pairs = get_scope().extension_nls_pairs
    required = {"election_id", "scenario_id", "run_id", "execution_status"}
    missing = sorted(required.difference(progress.columns))
    if missing:
        raise ValueError(f"extension progress missing columns: {missing}")
    observed_pairs = set(progress[["election_id", "scenario_id"]].itertuples(index=False, name=None))
    if len(progress) != len(expected_pairs) or observed_pairs != expected_pairs:
        raise ValueError(f"extension progress must contain exactly the {len(expected_pairs)} scoped unique pairs")
    if not progress["execution_status"].eq("success").all():
        raise ValueError("all scoped extension executions must be successful before consolidation")

    selected: list[tuple[Path, dict[str, Any]]] = []
    for row in progress.itertuples(index=False):
        run_dir = RUNS_DIR / str(row.run_id)
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(manifest_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        parameters = manifest.get("parameters", {})
        if manifest.get("status") != "success":
            raise ValueError(f"selected extension run is not successful: {row.run_id}")
        if parameters.get("election_id") != row.election_id or parameters.get("scenario_id") != row.scenario_id:
            raise ValueError(f"manifest pair differs from progress row: {row.run_id}")
        if parameters.get("model_key") != "rosen_nls" or int(parameters.get("sample_size", 0)) != 2000:
            raise ValueError(f"unexpected model or sample size in {row.run_id}")
        if parameters.get("panel_sha256") != EXPECTED_PANEL_SHA256:
            raise ValueError(f"panel hash differs in {row.run_id}")
        selected.append((run_dir, manifest))
    return selected


def _diagnostics(selected: list[tuple[Path, dict[str, Any]]]) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for run_dir, manifest in selected:
        path = run_dir / "model_diagnostics.csv"
        if not path.exists():
            raise FileNotFoundError(path)
        frame = pd.read_csv(path)
        if len(frame) != 1:
            raise ValueError(f"expected one diagnostic row: {path}")
        frame.insert(0, "manifest_status", manifest["status"])
        frame["panel_sha256"] = manifest["parameters"]["panel_sha256"]
        frame["margin_validation_status"] = "pass_exact_panel_closure"
        frame["release_assessment"] = frame["diagnostic_status"].map(
            {"pass": "eligible_after_r_replication", "warning": "caveat", "fail": "not_validated_conditioning_or_rank"}
        ).fillna("unknown")
        rows.append(frame)
    result = pd.concat(rows, ignore_index=True)
    if result[["election_id", "scenario_id"]].duplicated().any():
        raise AssertionError("diagnostic pair keys are not unique")
    return result.sort_values(["election_id", "scenario_id"]).reset_index(drop=True)


def _expected_nls_rows(pairs: frozenset[tuple[str, str]]) -> int:
    total = 0
    for _, scenario_id in pairs:
        scenario = SCENARIO_BY_ID[scenario_id]
        total += len(scenario.social_groups) * len(scenario.vote_categories)
        total += int(scenario.model_family == "2x2")
    return total


def consolidate(
    *,
    progress_path: Path = DEFAULT_OUTPUT_DIR / "rxc_nls_panel_extension_progress.csv",
    base_nls_path: Path = BASE_NLS,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, object]:
    scope = get_scope()
    progress = pd.read_csv(progress_path, dtype="string")
    selected = _selected_runs(progress, expected_pairs=scope.extension_nls_pairs)
    base = pd.read_parquet(base_nls_path)
    extension = build_nls(selected) if selected else base.iloc[0:0].copy()
    extension["public_schema_version"] = PUBLIC_SCHEMA_VERSION

    extension_pairs = extension[["election_id", "scenario_id"]].drop_duplicates()
    base_pairs = base[["election_id", "scenario_id"]].drop_duplicates()
    overlap = extension_pairs.merge(base_pairs, on=["election_id", "scenario_id"], how="inner")
    if not overlap.empty:
        raise AssertionError(f"extension overlaps existing base pairs: {overlap.to_dict('records')}")
    observed_extension_pairs = set(extension_pairs.itertuples(index=False, name=None))
    if observed_extension_pairs != scope.extension_nls_pairs or len(extension) != _expected_nls_rows(scope.extension_nls_pairs):
        raise AssertionError(
            f"unexpected scoped extension pairs/rows: {len(extension_pairs)} and {len(extension)}"
        )
    expected_rows = {
        scenario: _expected_nls_rows(frozenset(pair for pair in scope.extension_nls_pairs if pair[1] == scenario))
        for scenario in sorted({pair[1] for pair in scope.extension_nls_pairs})
    }
    if extension.groupby("scenario_id").size().to_dict() != expected_rows:
        raise AssertionError("unexpected RxC extension row counts")
    if extension["n_communes"].astype(int).ne(2000).any():
        raise AssertionError("extension contains a run outside the fixed 2,000-commune panel")
    if not extension["estimate"].between(0, 1).all():
        raise AssertionError("extension contains a probability outside [0,1]")
    extension_keys = ["election_id", "scenario_id", "estimand_type", "social_group", "vote_category"]
    if extension.duplicated(extension_keys).any():
        raise AssertionError("extension public keys are not unique")

    extension = extension.reindex(columns=base.columns)
    combined = pd.concat([base, extension], ignore_index=True)
    combined_pairs = combined[["election_id", "scenario_id"]].drop_duplicates()
    if (set(base_pairs.itertuples(index=False, name=None)) != scope.base_nls_pairs
            or set(combined_pairs.itertuples(index=False, name=None)) != scope.nls_pairs
            or len(combined) != _expected_nls_rows(scope.nls_pairs)):
        raise AssertionError(
            f"unexpected consolidation counts: base_pairs={len(base_pairs)}, "
            f"combined_pairs={len(combined_pairs)}, rows={len(combined)}"
        )
    pd.testing.assert_frame_equal(
        combined.iloc[: len(base)].reset_index(drop=True),
        base.reset_index(drop=True),
        check_exact=True,
        check_dtype=True,
    )
    if combined.duplicated(extension_keys).any():
        raise AssertionError("combined scoped public keys are not unique")

    diagnostics = _diagnostics(selected) if selected else pd.DataFrame(
        columns=["election_id", "scenario_id", "diagnostic_status"])
    diagnostic_counts = diagnostics["diagnostic_status"].value_counts().to_dict()
    if (sum(diagnostic_counts.values()) != len(scope.extension_nls_pairs)
            or set(diagnostic_counts) - {"pass", "warning", "fail"}):
        raise AssertionError(f"missing or unknown diagnostic results: {diagnostic_counts}")

    output_dir.mkdir(parents=True, exist_ok=True)
    extension_path = output_dir / "longitudinal_nls_rxc_extension_22.parquet"
    combined_path = output_dir / "longitudinal_nls_292_candidate.parquet"
    diagnostics_path = output_dir / "rxc_nls_extension_diagnostics.csv"
    extension.to_parquet(extension_path, index=False)
    combined.to_parquet(combined_path, index=False)
    diagnostics.to_csv(diagnostics_path, index=False, encoding="utf-8-sig")
    diagnostics.to_parquet(diagnostics_path.with_suffix(".parquet"), index=False)

    result = {
        "status": "candidate_requires_r_replication_and_diagnostic_review",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "panel_sha256": EXPECTED_PANEL_SHA256,
        "base_pairs_unchanged": len(base_pairs),
        "extension_pairs": len(extension_pairs),
        "combined_pairs": len(combined_pairs),
        "extension_rows": len(extension),
        "combined_rows": len(combined),
        "extension_diagnostic_counts": diagnostic_counts,
        "ready_for_public_release": False,
        "outputs": {
            "extension": {
                "path": extension_path.relative_to(ROOT).as_posix(),
                "sha256": file_sha256(extension_path),
            },
            "combined_candidate": {
                "path": combined_path.relative_to(ROOT).as_posix(),
                "sha256": file_sha256(combined_path),
            },
            "diagnostics": {
                "path": diagnostics_path.relative_to(ROOT).as_posix(),
                "sha256": file_sha256(diagnostics_path),
            },
        },
    }
    write_json(output_dir / "rxc_nls_extension_consolidation.json", result)
    return result


def main() -> None:
    result = consolidate()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
