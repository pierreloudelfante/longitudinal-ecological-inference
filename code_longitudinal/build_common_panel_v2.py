from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .balance_checks import balance_summary, compute_balance_checks
from .build_panel import load_settings
from .data_io import load_csp, load_election, load_reference_universe
from .paths import PANEL_DIR, RAW_ARCHIVES, ensure_runtime_dirs
from .spec_registry import CSP_GROUPS, ELECTION_BY_ID
from .utils import file_sha256, write_json


COMMON_ELECTION_IDS = ("leg_1962_r1", "leg_1986_r1", "leg_2022_r1")
DEFAULT_OUTPUT = PANEL_DIR / "panel_3000_common_1962_1986_2022_v2.csv"
DEFAULT_CHECKS = PANEL_DIR / "panel_3000_common_1962_1986_2022_v2_balance.csv"
DEFAULT_MANIFEST = PANEL_DIR / "panel_3000_common_1962_1986_2022_v2_manifest.json"


def _eligible_units(election_id: str) -> set[str]:
    """Return units usable by all four priority 2x2 scenarios for one election."""
    election = ELECTION_BY_ID[election_id]
    electoral = load_election(election).copy()
    electoral["unit_id"] = electoral["unit_id"].astype("string")
    required = [
        "inscrits",
        "votants",
        "exprimes",
        "voteG",
        "voteCG",
        "voteCD",
        "voteD",
    ]
    numeric = electoral[required].apply(pd.to_numeric, errors="coerce")
    left = numeric["voteG"] + numeric["voteCG"]
    right = numeric["voteCD"] + numeric["voteD"]
    electoral_ok = (
        numeric.notna().all(axis=1)
        & numeric["inscrits"].gt(0)
        & numeric["votants"].ge(0)
        & numeric["votants"].le(numeric["inscrits"])
        & numeric["exprimes"].gt(0)
        & left.ge(0)
        & left.le(numeric["exprimes"])
        & right.ge(0)
        & right.le(numeric["exprimes"])
    )

    csp = load_csp(election.year).copy()
    csp["unit_id"] = csp["unit_id"].astype("string")
    csp_numeric = csp[list(CSP_GROUPS)].apply(pd.to_numeric, errors="coerce")
    csp_ok = (
        csp_numeric.notna().all(axis=1)
        & csp_numeric.ge(0).all(axis=1)
        & csp_numeric.sum(axis=1).gt(0)
    )
    valid_electoral = set(electoral.loc[electoral_ok, "unit_id"].astype(str))
    valid_csp = set(csp.loc[csp_ok, "unit_id"].astype(str))
    return valid_electoral & valid_csp


def common_eligible_universe() -> tuple[pd.DataFrame, dict[str, int]]:
    reference = load_reference_universe(ELECTION_BY_ID["leg_2022_r1"]).copy()
    reference["unit_id"] = reference["unit_id"].astype("string")
    valid_sets = {election_id: _eligible_units(election_id) for election_id in COMMON_ELECTION_IDS}
    common = set.intersection(*valid_sets.values())
    eligible = reference.loc[reference["unit_id"].astype(str).isin(common)].copy()
    counts = {election_id: len(units) for election_id, units in valid_sets.items()}
    counts["common_in_reference_universe"] = len(eligible)
    return eligible.reset_index(drop=True), counts


def build_common_panel_v2(
    *,
    panel_size: int = 3000,
    initial_seed: int | None = None,
    max_attempts: int | None = None,
    output_path: Path = DEFAULT_OUTPUT,
) -> dict[str, object]:
    ensure_runtime_dirs()
    settings = load_settings()
    panel_settings = settings["panel"]
    seed0 = int(initial_seed if initial_seed is not None else panel_settings["panel_seed"])
    attempts_limit = int(max_attempts if max_attempts is not None else panel_settings["max_attempts"])
    max_smd = float(panel_settings["max_abs_smd"])
    max_gap = float(panel_settings["max_abs_category_gap"])

    full_reference = load_reference_universe(ELECTION_BY_ID["leg_2022_r1"]).copy()
    full_reference["unit_id"] = full_reference["unit_id"].astype("string")
    eligible, eligibility_counts = common_eligible_universe()
    if len(eligible) < panel_size:
        raise ValueError(
            f"Only {len(eligible)} common eligible units are available, fewer than {panel_size}."
        )

    attempts: list[dict[str, object]] = []
    selected: pd.DataFrame | None = None
    selected_seed: int | None = None
    selected_common_checks: pd.DataFrame | None = None
    selected_full_checks: pd.DataFrame | None = None
    for attempt in range(attempts_limit):
        seed = seed0 + attempt
        order = np.random.default_rng(seed).permutation(len(eligible))
        candidate = eligible.iloc[order[:panel_size]].copy()
        common_checks = compute_balance_checks(eligible, candidate)
        full_checks = compute_balance_checks(full_reference, candidate)
        common_status = balance_summary(common_checks, max_smd=max_smd, max_category_gap=max_gap)
        full_status = balance_summary(full_checks, max_smd=max_smd, max_category_gap=max_gap)
        accepted = bool(common_status["accepted"] and full_status["accepted"])
        attempts.append(
            {
                "attempt": attempt + 1,
                "seed": seed,
                "accepted": accepted,
                **{f"common_{key}": value for key, value in common_status.items()},
                **{f"full_2022_{key}": value for key, value in full_status.items()},
            }
        )
        if accepted:
            selected = candidate
            selected_seed = seed
            selected_common_checks = common_checks
            selected_full_checks = full_checks
            break
    if selected is None or selected_seed is None or selected_common_checks is None or selected_full_checks is None:
        raise RuntimeError("No balanced exact common panel was found within the configured attempts.")

    sample_id = f"panel_3000_common_1962_1986_2022_seed_{selected_seed}_v2"
    selected = selected.reset_index(drop=True)
    selected.insert(1, "sample_id", sample_id)
    selected.insert(2, "sample_seed", selected_seed)
    selected["sample_rank"] = np.arange(1, len(selected) + 1)
    selected["included_panel_3000_common_v2"] = True
    output_path.parent.mkdir(parents=True, exist_ok=True)
    selected.to_csv(output_path, index=False, encoding="utf-8-sig")

    common_out = selected_common_checks.copy()
    common_out.insert(0, "reference", "common_eligible_1962_1986_2022")
    full_out = selected_full_checks.copy()
    full_out.insert(0, "reference", "full_reference_2022")
    checks_path = output_path.with_name(output_path.stem + "_balance.csv")
    pd.concat([common_out, full_out], ignore_index=True).to_csv(
        checks_path, index=False, encoding="utf-8-sig"
    )
    attempts_path = output_path.with_name(output_path.stem + "_attempts.csv")
    pd.DataFrame(attempts).to_csv(attempts_path, index=False, encoding="utf-8-sig")

    common_status = balance_summary(selected_common_checks, max_smd=max_smd, max_category_gap=max_gap)
    full_status = balance_summary(selected_full_checks, max_smd=max_smd, max_category_gap=max_gap)
    manifest = {
        "schema_version": "2.0",
        "status": "accepted",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "sample_id": sample_id,
        "sample_size": len(selected),
        "sample_seed": selected_seed,
        "elections": list(COMMON_ELECTION_IDS),
        "priority_scenarios": ["H0A", "H1", "H2", "H4"],
        "eligibility_definition": (
            "stable unit in the 2022 reference universe; complete six-CSP base with nonnegative "
            "cell counts and a strictly positive six-CSP total; valid registered/expressed "
            "aggregate margins for H0A, H1, H2 and H4 in 1962, 1986 and 2022"
        ),
        "eligibility_counts": eligibility_counts,
        "reference_universe_2022_size": len(full_reference),
        "common_eligible_universe_size": len(eligible),
        "balance_common_eligible": common_status,
        "balance_full_reference_2022": full_status,
        "selection_is_outcome_blind_within_eligibility_frame": True,
        "selection_note": (
            "Within the eligible frame, random ordering and inclusion do not use vote levels. "
            "Observed aggregate margins are used only to verify availability and admissible ranges "
            "when constructing that frame."
        ),
        "source_sha256": {
            **{
                ELECTION_BY_ID[election_id].archive_name: file_sha256(
                    RAW_ARCHIVES / ELECTION_BY_ID[election_id].archive_name
                )
                for election_id in COMMON_ELECTION_IDS
            },
            "socio_csp_csv.zip": file_sha256(RAW_ARCHIVES / "socio_csp_csv.zip"),
        },
        "software_versions": {
            "numpy": np.__version__,
            "pandas": pd.__version__,
        },
        "output": str(output_path),
        "output_sha256": file_sha256(output_path),
        "balance_output": str(checks_path),
        "attempts_output": str(attempts_path),
        "preserves": [
            "panel/panel_3000.csv",
            "panel/panel_2000.csv",
            "panel/panel_manifest.json",
        ],
    }
    manifest_path = output_path.with_name(output_path.stem + "_manifest.json")
    write_json(manifest_path, manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a balanced exact 3,000-unit common panel for V2.")
    parser.add_argument("--panel-size", type=int, default=3000)
    parser.add_argument("--initial-seed", type=int)
    parser.add_argument("--max-attempts", type=int)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_common_panel_v2(
        panel_size=args.panel_size,
        initial_seed=args.initial_seed,
        max_attempts=args.max_attempts,
        output_path=args.output,
    )
    print(manifest)


if __name__ == "__main__":
    main()
