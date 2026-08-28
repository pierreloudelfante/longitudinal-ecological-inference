from __future__ import annotations

from typing import Any

import pandas as pd

from .audit_longitudinal import PRESENCE_PATH, RUN_PLAN_PATH
from .build_longitudinal_panel import BALANCE_BY_ELECTION_PATH, PANEL_PATH, load_longitudinal_panel_manifest
from .paths import OUTPUT_DIR
from .spec_registry import SPEC_VERSION
from .utils import file_sha256, write_json


VALIDATION_DIR = OUTPUT_DIR / SPEC_VERSION / "audit"
PANEL_QUALITY_PATH = VALIDATION_DIR / "panel_election_quality.parquet"
PANEL_QUALITY_MANIFEST_PATH = VALIDATION_DIR / "panel_exact_validation.json"
REQUIRED_FLAGS = (
    "source_present",
    "harmonized_present",
    "electoral_margins_complete",
    "electoral_counts_nonnegative",
    "denominators_valid",
    "social_margins_available",
    "social_margins_valid",
    "h0a_admissible",
    "h1_admissible",
    "panel_core_admissible",
)


def validate_longitudinal_panel() -> dict[str, Any]:
    panel_manifest = load_longitudinal_panel_manifest()
    panel = pd.read_parquet(PANEL_PATH)
    primary = panel.loc[panel["included_primary_2000"].astype(bool)].copy()
    primary["unit_id"] = primary["unit_id"].astype("string")
    if len(primary) != 2000 or primary["unit_id"].nunique() != 2000:
        raise AssertionError("primary longitudinal panel must contain 2,000 unique unit_id values")

    expected_ids = frozenset(primary["unit_id"].tolist())
    presence = pd.read_parquet(PRESENCE_PATH)
    presence["unit_id"] = presence["unit_id"].astype("string")
    selected = presence.loc[presence["unit_id"].isin(expected_ids)].copy()
    elections = sorted(selected["election_id"].unique().tolist())
    if len(elections) != 26 or len(selected) != 52_000:
        raise AssertionError("panel presence must contain exactly 2,000 x 26 rows")

    balance = pd.read_parquet(BALANCE_BY_ELECTION_PATH)
    quality_rows: list[dict[str, object]] = []
    for election_id, frame in selected.groupby("election_id", sort=True):
        ids = frozenset(frame["unit_id"].tolist())
        numeric = frame[["inscrits", "votants", "exprimes"]].apply(pd.to_numeric, errors="coerce")
        election_balance = balance.loc[balance["election_id"].eq(election_id)]
        smd = election_balance["standardized_mean_difference"].abs().dropna()
        category_gap = election_balance["proportion_difference"].abs().dropna()
        row = {
            "panel_id": panel_manifest["panel_id"],
            "election_id": election_id,
            "n_rows": int(len(frame)),
            "n_unique_unit_id": int(frame["unit_id"].nunique()),
            "exact_master_code_set": ids == expected_ids,
            "negative_count_rows": int(numeric.lt(0).any(axis=1).sum()),
            "exprimes_gt_votants_rows": int(numeric["exprimes"].gt(numeric["votants"]).sum()),
            "votants_gt_inscrits_rows": int(numeric["votants"].gt(numeric["inscrits"]).sum()),
            "missing_count_rows": int(numeric.isna().any(axis=1).sum()),
            "missing_geography_rows": int(frame[["department", "region13", "geography_source"]].isna().any(axis=1).sum()),
            "max_abs_smd": float(smd.max()) if len(smd) else 0.0,
            "max_abs_category_gap": float(category_gap.max()) if len(category_gap) else 0.0,
        }
        for flag in REQUIRED_FLAGS:
            row[f"invalid_{flag}_rows"] = int((~frame[flag].astype(bool)).sum())
        quality_rows.append(row)

    quality = pd.DataFrame(quality_rows)
    integer_checks = [
        "negative_count_rows",
        "exprimes_gt_votants_rows",
        "votants_gt_inscrits_rows",
        "missing_count_rows",
        "missing_geography_rows",
        *[f"invalid_{flag}_rows" for flag in REQUIRED_FLAGS],
    ]
    no_quality_violations = bool(quality[integer_checks].eq(0).all().all())
    exact_codes = bool(quality["exact_master_code_set"].all())
    exact_sizes = bool(quality["n_rows"].eq(2000).all() and quality["n_unique_unit_id"].eq(2000).all())
    balance_pass = bool(
        quality["max_abs_smd"].le(0.10).all()
        and quality["max_abs_category_gap"].le(0.02).all()
    )
    run_plan = pd.read_parquet(RUN_PLAN_PATH)
    classified_pairs = int(len(run_plan))
    admissible_pairs = int(run_plan["preparation_status"].eq("admissible").sum())
    invalid_pairs = int(run_plan["preparation_status"].eq("ineligible").sum())
    ready = bool(
        exact_codes
        and exact_sizes
        and no_quality_violations
        and balance_pass
        and classified_pairs == 292
        and admissible_pairs == 270
        and invalid_pairs == 22
    )
    if not ready:
        raise AssertionError("longitudinal panel exact validation failed")

    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    quality.to_parquet(PANEL_QUALITY_PATH, index=False)
    result = {
        "schema_version": "longitudinal_panel_exact_validation_v1",
        "ready": ready,
        "panel_id": panel_manifest["panel_id"],
        "panel_sha256": file_sha256(PANEL_PATH),
        "primary_panel_rows": int(len(primary)),
        "primary_unique_unit_id": int(primary["unit_id"].nunique()),
        "elections": len(elections),
        "unit_election_rows": int(len(selected)),
        "exact_same_code_set_all_elections": exact_codes,
        "exact_2000_rows_and_codes_each_election": exact_sizes,
        "all_margin_join_and_admissibility_checks_pass": no_quality_violations,
        "max_abs_smd_all_elections": float(quality["max_abs_smd"].max()),
        "max_abs_category_gap_all_elections": float(quality["max_abs_category_gap"].max()),
        "balance_pass": balance_pass,
        "classified_pairs": classified_pairs,
        "admissible_pairs": admissible_pairs,
        "ineligible_pairs": invalid_pairs,
        "quality_path": PANEL_QUALITY_PATH.relative_to(OUTPUT_DIR.parent).as_posix(),
    }
    write_json(PANEL_QUALITY_MANIFEST_PATH, result)
    return result


__all__ = [
    "PANEL_QUALITY_MANIFEST_PATH",
    "PANEL_QUALITY_PATH",
    "validate_longitudinal_panel",
]
