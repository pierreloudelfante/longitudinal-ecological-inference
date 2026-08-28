"""Build the quality-repaired common panel while preserving the V2 draw order."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .balance_checks import balance_summary, compute_balance_checks
from .build_common_panel_v2 import COMMON_ELECTION_IDS, common_eligible_universe
from .build_panel import load_settings
from .data_io import load_election, load_reference_universe
from .paths import PANEL_DIR, RAW_ARCHIVES, ensure_runtime_dirs
from .spec_registry import ELECTION_BY_ID
from .utils import file_sha256, write_json


BASE_PANEL = PANEL_DIR / "panel_3000_common_1962_1986_2022_v2.csv"
DEFAULT_OUTPUT = PANEL_DIR / "panel_3000_common_1962_1986_2022_v3.csv"
SAMPLE_SEED = 20260802
TOLERANCE = 0.01


def denominator_audit() -> tuple[pd.DataFrame, dict[str, set[str]]]:
    """List source violations and return valid unit identifiers by election."""

    base = pd.read_csv(BASE_PANEL, dtype={"unit_id": "string"})
    base_ids = set(base["unit_id"].astype(str))
    rows: list[dict[str, object]] = []
    valid: dict[str, set[str]] = {}
    for election_id in COMMON_ELECTION_IDS:
        spec = ELECTION_BY_ID[election_id]
        frame = load_election(spec).copy()
        frame["unit_id"] = frame["unit_id"].astype("string")
        numeric = frame[["inscrits", "votants", "exprimes"]].apply(
            pd.to_numeric, errors="coerce"
        )
        bad_nonnegative = numeric.lt(-TOLERANCE).any(axis=1)
        bad_expressed = numeric["exprimes"] > numeric["votants"] + TOLERANCE
        bad_voters = numeric["votants"] > numeric["inscrits"] + TOLERANCE
        bad = bad_nonnegative | bad_expressed | bad_voters
        valid[election_id] = set(frame.loc[~bad, "unit_id"].astype(str))
        for idx in frame.index[bad]:
            unit_id = str(frame.at[idx, "unit_id"])
            archival_verification = ""
            if election_id == "leg_1986_r1" and unit_id == "02643":
                archival_verification = (
                    "official archive image00167.jpg inspected: 383 registered, "
                    "415 voters, 23 invalid ballots and 392 expressed; the source "
                    "record remains internally impossible"
                )
            rows.append(
                {
                    "election_id": election_id,
                    "year": spec.year,
                    "unit_id": unit_id,
                    "commune_name": str(frame.at[idx, "nomcommune"])
                    if "nomcommune" in frame.columns
                    else "",
                    "inscrits": numeric.at[idx, "inscrits"],
                    "votants": numeric.at[idx, "votants"],
                    "exprimes": numeric.at[idx, "exprimes"],
                    "expressed_minus_voters": numeric.at[idx, "exprimes"]
                    - numeric.at[idx, "votants"],
                    "voters_minus_registered": numeric.at[idx, "votants"]
                    - numeric.at[idx, "inscrits"],
                    "in_panel_v2": unit_id in base_ids,
                    "v3_action": "excluded_from_sampling_frame",
                    "source_archive": spec.archive_name,
                    "source_sha256": file_sha256(RAW_ARCHIVES / spec.archive_name),
                    "validation_rule": "0 <= exprimes <= votants <= inscrits",
                    "tolerance_absolute_votes": TOLERANCE,
                    "archival_verification": archival_verification,
                }
            )
    return pd.DataFrame(rows), valid


def build_common_panel_v3(output_path: Path = DEFAULT_OUTPUT) -> dict[str, object]:
    """Repair V2 by filtering its seeded order and continuing to 3,000 units."""

    ensure_runtime_dirs()
    settings = load_settings()
    max_smd = float(settings["panel"]["max_abs_smd"])
    max_gap = float(settings["panel"]["max_abs_category_gap"])
    base_panel = pd.read_csv(BASE_PANEL, dtype={"unit_id": "string"}).sort_values(
        "sample_rank"
    )
    base_eligible, base_counts = common_eligible_universe()
    base_eligible["unit_id"] = base_eligible["unit_id"].astype("string")
    audit, valid_by_election = denominator_audit()
    valid_all = set.intersection(*(valid_by_election[eid] for eid in COMMON_ELECTION_IDS))
    corrected_eligible = base_eligible.loc[
        base_eligible["unit_id"].astype(str).isin(valid_all)
    ].copy()

    seeded_order = np.random.default_rng(SAMPLE_SEED).permutation(len(base_eligible))
    ordered = base_eligible.iloc[seeded_order].copy()
    selected = ordered.loc[ordered["unit_id"].astype(str).isin(valid_all)].head(3000).copy()
    if len(selected) != 3000:
        raise RuntimeError("fewer than 3,000 units remain after denominator validation")

    old_ids = set(base_panel["unit_id"].astype(str))
    new_ids = set(selected["unit_id"].astype(str))
    removed = base_panel.loc[
        ~base_panel["unit_id"].astype(str).isin(new_ids), "unit_id"
    ].astype(str).tolist()
    added = selected.loc[
        ~selected["unit_id"].astype(str).isin(old_ids), "unit_id"
    ].astype(str).tolist()
    if len(removed) != len(added):
        raise RuntimeError("one-for-one panel repair failed")

    sample_id = "panel_3000_common_1962_1986_2022_seed_20260802_v3_quality_repair"
    selected = selected.reset_index(drop=True)
    selected.insert(1, "sample_id", sample_id)
    selected.insert(2, "sample_seed", SAMPLE_SEED)
    selected["sample_rank"] = np.arange(1, 3001)
    # The V2 compatibility flag is retained for the production runner contract.
    selected["included_panel_3000_common_v2"] = True
    selected["included_panel_3000_common_v3"] = True
    selected["panel_revision_reason"] = (
        "transversal_electoral_denominator_quality_screen"
    )

    full_reference = load_reference_universe(ELECTION_BY_ID["leg_2022_r1"]).copy()
    full_reference["unit_id"] = full_reference["unit_id"].astype("string")
    common_checks = compute_balance_checks(corrected_eligible, selected)
    full_checks = compute_balance_checks(full_reference, selected)
    common_status = balance_summary(
        common_checks, max_smd=max_smd, max_category_gap=max_gap
    )
    full_status = balance_summary(full_checks, max_smd=max_smd, max_category_gap=max_gap)
    if not common_status["accepted"] or not full_status["accepted"]:
        raise RuntimeError(
            f"repaired panel fails balance thresholds: common={common_status}, "
            f"full={full_status}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    selected.to_csv(output_path, index=False, encoding="utf-8-sig")
    checks_path = output_path.with_name(output_path.stem + "_balance.csv")
    common_out = common_checks.copy()
    common_out.insert(0, "reference", "corrected_common_eligible_1962_1986_2022")
    full_out = full_checks.copy()
    full_out.insert(0, "reference", "full_reference_2022")
    pd.concat([common_out, full_out], ignore_index=True).to_csv(
        checks_path, index=False, encoding="utf-8-sig"
    )
    audit_path = output_path.with_name(output_path.stem + "_denominator_audit.csv")
    audit.to_csv(audit_path, index=False, encoding="utf-8-sig")
    attempts_path = output_path.with_name(output_path.stem + "_attempts.csv")
    pd.DataFrame(
        [
            {
                "attempt": 1,
                "seed": SAMPLE_SEED,
                "accepted": True,
                "method": "continue_v2_seeded_order_after_expanded_quality_screen",
                "removed_units": ";".join(removed),
                "added_units": ";".join(added),
                "common_max_abs_smd": common_status["max_abs_smd"],
                "common_max_abs_category_gap": common_status["max_abs_category_gap"],
                "full_2022_max_abs_smd": full_status["max_abs_smd"],
                "full_2022_max_abs_category_gap": full_status["max_abs_category_gap"],
            }
        ]
    ).to_csv(attempts_path, index=False, encoding="utf-8-sig")

    relative = lambda path: str(path.relative_to(PANEL_DIR.parent)).replace("\\", "/")
    manifest = {
        "schema_version": "3.0",
        "status": "accepted",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "sample_id": sample_id,
        "sample_size": 3000,
        "sample_seed": SAMPLE_SEED,
        "elections": list(COMMON_ELECTION_IDS),
        "priority_scenarios": ["H0A", "H1"],
        "eligibility_definition": (
            "V2 common eligibility plus transversal rule "
            "0 <= exprimes <= votants <= inscrits in 1962, 1986 and 2022 "
            f"with absolute floating tolerance {TOLERANCE}"
        ),
        "repair_method": (
            "preserve the V2 seeded ordering; remove invalid units; continue along "
            "the same ordering until exactly 3,000 valid units are retained"
        ),
        "base_panel": relative(BASE_PANEL),
        "base_panel_sha256": file_sha256(BASE_PANEL),
        "removed_units": removed,
        "added_units": added,
        "eligibility_counts_v2": base_counts,
        "corrected_common_eligible_universe_size": len(corrected_eligible),
        "source_violations_total": int(len(audit)),
        "source_violations_in_panel_v2": int(audit["in_panel_v2"].sum()),
        "balance_corrected_common_eligible": common_status,
        "balance_full_reference_2022": full_status,
        "selection_is_outcome_blind_within_eligibility_frame": True,
        "king_lambda": 0.5,
        "source_sha256": {
            **{
                ELECTION_BY_ID[eid].archive_name: file_sha256(
                    RAW_ARCHIVES / ELECTION_BY_ID[eid].archive_name
                )
                for eid in COMMON_ELECTION_IDS
            },
            "socio_csp_csv.zip": file_sha256(RAW_ARCHIVES / "socio_csp_csv.zip"),
        },
        "outputs": {
            "panel": relative(output_path),
            "balance": relative(checks_path),
            "attempts": relative(attempts_path),
            "denominator_audit": relative(audit_path),
        },
    }
    manifest_path = output_path.with_name(output_path.stem + "_manifest.json")
    write_json(manifest_path, manifest)
    manifest["output_sha256"] = file_sha256(output_path)
    write_json(manifest_path, manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the quality-repaired 3,000-unit common panel V3."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(build_common_panel_v3(args.output))


if __name__ == "__main__":
    main()
