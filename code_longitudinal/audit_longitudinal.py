from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .build_panel import load_settings
from .data_io import (
    load_csp,
    load_election,
    load_geography_reference,
    load_reference_universe,
)
from .paths import CONFIG_DIR, OUTPUT_DIR, RAW_ARCHIVES, ensure_runtime_dirs
from .spec_registry import (
    CSP_GROUPS,
    ELECTIONS,
    ELECTION_BY_ID,
    HARMONIZATION_VERSION,
    SCENARIOS,
    SPEC_VERSION,
    VOTE_BLOCKS,
    ElectionSpec,
    ScenarioSpec,
    scenario_is_allowed,
)
from .utils import file_sha256, write_json


AUDIT_DIR = OUTPUT_DIR / SPEC_VERSION / "audit"
INVENTORY_PATH = AUDIT_DIR / "all_elections_inventory.parquet"
PRESENCE_PATH = AUDIT_DIR / "election_presence_and_harmonisation.parquet"
RUN_PLAN_PATH = AUDIT_DIR / "longitudinal_run_plan.parquet"
AUDIT_MANIFEST_PATH = AUDIT_DIR / "audit_manifest.json"


def _semicolon_reasons(items: list[tuple[pd.Series, str]], index: pd.Index) -> pd.Series:
    reasons = pd.Series("", index=index, dtype="string")
    for mask, label in items:
        mask = mask.reindex(index, fill_value=False).fillna(False)
        blank = reasons.eq("")
        reasons.loc[mask & blank] = label
        reasons.loc[mask & ~blank] = reasons.loc[mask & ~blank] + ";" + label
    return reasons


def _scenario_political_valid(
    frame: pd.DataFrame,
    election: ElectionSpec,
    scenario: ScenarioSpec,
    tolerance: float,
) -> tuple[pd.Series, pd.Series]:
    index = frame.index
    expressed = pd.to_numeric(frame["exprimes"], errors="coerce")
    registered = pd.to_numeric(frame["inscrits"], errors="coerce")
    voters = pd.to_numeric(frame["votants"], errors="coerce")
    if scenario.vote_definition == "abstention":
        complete = registered.notna() & voters.notna()
        gap = pd.Series(0.0, index=index)
        valid = complete & voters.ge(-tolerance) & voters.le(registered + tolerance)
    elif scenario.vote_definition == "left":
        target = frame[["voteG", "voteCG"]].apply(pd.to_numeric, errors="coerce").sum(axis=1, min_count=2)
        complete = expressed.notna() & target.notna()
        gap = np.maximum(-target, target - expressed).clip(lower=0)
        valid = complete & target.ge(-tolerance) & target.le(expressed + tolerance)
    elif scenario.vote_definition == "right":
        target = frame[["voteCD", "voteD"]].apply(pd.to_numeric, errors="coerce").sum(axis=1, min_count=2)
        complete = expressed.notna() & target.notna()
        gap = np.maximum(-target, target - expressed).clip(lower=0)
        valid = complete & target.ge(-tolerance) & target.le(expressed + tolerance)
    elif scenario.vote_definition == "centre":
        target = pd.to_numeric(frame["voteC"], errors="coerce")
        complete = expressed.notna() & target.notna()
        gap = np.maximum(-target, target - expressed).clip(lower=0)
        valid = complete & target.ge(-tolerance) & target.le(expressed + tolerance)
    elif scenario.vote_definition == "rn":
        if not election.rn_columns:
            return pd.Series(False, index=index), pd.Series(np.nan, index=index)
        target = frame[list(election.rn_columns)].apply(pd.to_numeric, errors="coerce").sum(
            axis=1, min_count=len(election.rn_columns)
        )
        complete = expressed.notna() & target.notna()
        gap = np.maximum(-target, target - expressed).clip(lower=0)
        valid = complete & target.ge(-tolerance) & target.le(expressed + tolerance)
    elif scenario.vote_definition == "five_blocks":
        blocks = frame[list(VOTE_BLOCKS)].apply(pd.to_numeric, errors="coerce")
        block_sum = blocks.sum(axis=1, min_count=len(VOTE_BLOCKS))
        complete = expressed.notna() & block_sum.notna()
        gap = (block_sum - expressed).abs()
        valid = complete & gap.le(tolerance) & blocks.ge(-tolerance).all(axis=1)
    else:  # pragma: no cover - registry construction prevents this
        raise ValueError(f"unknown vote definition: {scenario.vote_definition}")
    return valid.fillna(False), pd.Series(gap, index=index, dtype=float)


def _raw_source_summary(electoral: pd.DataFrame) -> dict[str, int]:
    return {
        "source_rows": int(electoral.attrs.get("source_rows", len(electoral))),
        "source_valid_raw_ids": int(electoral.attrs.get("source_valid_raw_ids", len(electoral))),
        "source_duplicate_raw_ids": int(electoral.attrs.get("source_duplicate_raw_ids", 0)),
    }


def _audit_one_election(
    universe: pd.DataFrame,
    geography: pd.DataFrame,
    election: ElectionSpec,
    *,
    tolerance: float,
) -> tuple[pd.DataFrame, dict[str, object], list[dict[str, object]]]:
    electoral = load_election(election).copy()
    csp = load_csp(election.year)[["unit_id", *CSP_GROUPS]].copy()
    merged = universe[["unit_id", "vbbm"]].merge(
        electoral,
        on="unit_id",
        how="left",
        validate="one_to_one",
        indicator="_electoral_merge",
    )
    merged = merged.merge(csp, on="unit_id", how="left", validate="one_to_one", indicator="_csp_merge")
    merged = merged.merge(
        geography[["unit_id", "department", "region13", "commune_name", "geography_source"]],
        on="unit_id",
        how="left",
        validate="one_to_one",
    )
    source_present = merged["_electoral_merge"].eq("both")
    csp_present = merged["_csp_merge"].eq("both")
    electoral_columns = ["inscrits", "votants", "exprimes", *VOTE_BLOCKS]
    complete_margins = merged[electoral_columns].notna().all(axis=1)
    numeric_margins = merged[electoral_columns].apply(pd.to_numeric, errors="coerce")
    nonnegative = numeric_margins.ge(-tolerance).all(axis=1)
    denominators_valid = (
        complete_margins
        & nonnegative
        & numeric_margins["exprimes"].le(numeric_margins["votants"])
        & numeric_margins["votants"].le(numeric_margins["inscrits"])
    )
    csp_numeric = merged[list(CSP_GROUPS)].apply(pd.to_numeric, errors="coerce")
    csp_complete = csp_present & csp_numeric.notna().all(axis=1)
    csp_nonnegative = csp_numeric.ge(-tolerance).all(axis=1)
    csp_total = csp_numeric.sum(axis=1, min_count=len(CSP_GROUPS))
    social_valid = csp_complete & csp_nonnegative & csp_total.gt(0)

    allowed_scenarios: list[str] = []
    unit_scenario_valid: dict[str, pd.Series] = {}
    run_rows: list[dict[str, object]] = []
    for scenario in SCENARIOS:
        if not scenario_is_allowed(scenario, election):
            continue
        allowed_scenarios.append(scenario.scenario_id)
        political_valid, raw_gap = _scenario_political_valid(merged, election, scenario, tolerance)
        denominator_positive = (
            pd.to_numeric(merged["inscrits" if scenario.denominator == "registered" else "exprimes"], errors="coerce")
            .fillna(0)
            .gt(0)
        )
        valid = source_present & denominators_valid & social_valid & denominator_positive & political_valid
        unit_scenario_valid[scenario.scenario_id] = valid
        source_partition_valid = True
        preparation_reason = ""
        if scenario.vote_definition == "five_blocks" and bool((raw_gap.loc[source_present] > tolerance).any()):
            source_partition_valid = False
            preparation_reason = "source_five_block_partition_gap_exceeds_tolerance"
        run_rows.append(
            {
                "election_id": election.election_id,
                "election_type": election.election_type,
                "year": election.year,
                "round": election.round,
                "scenario_id": scenario.scenario_id,
                "model_family": scenario.model_family,
                "registry_allowed": True,
                "source_partition_valid": source_partition_valid,
                "preparation_status": "admissible" if source_partition_valid and int(valid.sum()) > 0 else "ineligible",
                "preparation_reason": preparation_reason if preparation_reason else ("" if int(valid.sum()) > 0 else "no_admissible_units"),
                "n_scenario_admissible": int(valid.sum()),
                "maximum_raw_partition_gap": float(raw_gap.loc[source_present].max()) if source_present.any() and raw_gap.notna().any() else np.nan,
                "spec_version": SPEC_VERSION,
                "harmonization_version": HARMONIZATION_VERSION,
            }
        )

    h0a_valid = unit_scenario_valid["H0A"]
    h1_valid = unit_scenario_valid["H1"]
    panel_core = h0a_valid & h1_valid
    admissible_text = pd.Series("", index=merged.index, dtype="string")
    for scenario_id in allowed_scenarios:
        mask = unit_scenario_valid[scenario_id]
        blank = admissible_text.eq("")
        admissible_text.loc[mask & blank] = scenario_id
        admissible_text.loc[mask & ~blank] = admissible_text.loc[mask & ~blank] + ";" + scenario_id
    reasons = _semicolon_reasons(
        [
            (~source_present, "election_absent_after_stable_id_policy"),
            (source_present & ~complete_margins, "electoral_margins_incomplete"),
            (complete_margins & ~nonnegative, "negative_electoral_count"),
            (complete_margins & ~denominators_valid, "denominator_order_invalid"),
            (~csp_present, "csp_absent"),
            (csp_present & ~csp_complete, "csp_incomplete"),
            (csp_complete & ~csp_nonnegative, "csp_negative"),
            (csp_complete & ~csp_total.gt(0), "csp_total_non_positive"),
            (denominators_valid & social_valid & ~h0a_valid, "h0a_partition_invalid"),
            (denominators_valid & social_valid & ~h1_valid, "h1_partition_invalid"),
        ],
        merged.index,
    )
    out = pd.DataFrame(
        {
            "unit_id": merged["unit_id"].astype("string"),
            "election_id": election.election_id,
            "election_type": election.election_type,
            "year": election.year,
            "round": election.round,
            "source_present": source_present,
            "harmonized_present": source_present,
            "electoral_margins_complete": complete_margins,
            "electoral_counts_nonnegative": nonnegative,
            "denominators_valid": denominators_valid,
            "social_margins_available": csp_complete,
            "social_margins_valid": social_valid,
            "h0a_admissible": h0a_valid,
            "h1_admissible": h1_valid,
            "panel_core_admissible": panel_core,
            "admissible_scenarios": admissible_text,
            "exclusion_reason": reasons,
            "inscrits": pd.to_numeric(merged["inscrits"], errors="coerce"),
            "votants": pd.to_numeric(merged["votants"], errors="coerce"),
            "exprimes": pd.to_numeric(merged["exprimes"], errors="coerce"),
            "log1p_inscrits": np.log1p(pd.to_numeric(merged["inscrits"], errors="coerce").clip(lower=0)),
            "share_ouvr": csp_numeric["ouvr"] / csp_total,
            "share_empl": csp_numeric["empl"] / csp_total,
            "share_cadr": csp_numeric["cadr"] / csp_total,
            "share_agri_indp": (csp_numeric["agri"] + csp_numeric["indp"]) / csp_total,
            "department": merged["department"],
            "region13": merged["region13"],
            "vbbm": merged["vbbm"],
            "geography_source": merged["geography_source"],
            "spec_version": SPEC_VERSION,
            "harmonization_version": HARMONIZATION_VERSION,
        }
    )
    raw_summary = _raw_source_summary(electoral)
    inventory = {
        "election_id": election.election_id,
        "election_type": election.election_type,
        "year": election.year,
        "round": election.round,
        "source_archive": election.archive_name,
        "source_member": election.member_name,
        "source_sha256": file_sha256(RAW_ARCHIVES / election.archive_name),
        **raw_summary,
        "harmonized_rows": int(len(electoral)),
        "reference_units_present": int(source_present.sum()),
        "valid_denominator_rows": int(denominators_valid.sum()),
        "denominator_anomaly_rows": int((source_present & ~denominators_valid).sum()),
        "valid_social_margin_rows": int(social_valid.sum()),
        "panel_core_admissible_rows": int(panel_core.sum()),
        "registry_scenarios": ";".join(allowed_scenarios),
        "source_valid_scenarios": ";".join(
            row["scenario_id"] for row in run_rows if row["preparation_status"] == "admissible"
        ),
        "spec_version": SPEC_VERSION,
        "harmonization_version": HARMONIZATION_VERSION,
    }
    return out, inventory, run_rows


def build_longitudinal_audit(settings_path: Path | None = None) -> dict[str, object]:
    ensure_runtime_dirs()
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    settings_path = settings_path or CONFIG_DIR / "run_settings.json"
    settings = load_settings(settings_path)
    tolerance = float(settings["data"]["political_partition_tolerance"])
    universe = load_reference_universe(ELECTION_BY_ID["leg_2022_r1"])
    geography = load_geography_reference(2022)
    audit_parts: list[pd.DataFrame] = []
    inventory_rows: list[dict[str, object]] = []
    run_rows: list[dict[str, object]] = []
    for election in ELECTIONS:
        audit, inventory, election_runs = _audit_one_election(
            universe,
            geography,
            election,
            tolerance=tolerance,
        )
        audit_parts.append(audit)
        inventory_rows.append(inventory)
        run_rows.extend(election_runs)
    presence = pd.concat(audit_parts, ignore_index=True)
    inventory = pd.DataFrame(inventory_rows).sort_values(["year", "election_type", "election_id"])
    run_plan = pd.DataFrame(run_rows).sort_values(["year", "election_type", "election_id", "scenario_id"])
    if len(inventory) != 26:
        raise AssertionError(f"expected 26 elections, found {len(inventory)}")
    if len(run_plan) != 292:
        raise AssertionError(f"expected 292 registered election-scenario pairs, found {len(run_plan)}")
    if presence.duplicated(["unit_id", "election_id"]).any():
        raise AssertionError("audit contains duplicate unit_id/election_id keys")
    presence.to_parquet(PRESENCE_PATH, index=False)
    inventory.to_parquet(INVENTORY_PATH, index=False)
    inventory.to_csv(INVENTORY_PATH.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    run_plan.to_parquet(RUN_PLAN_PATH, index=False)
    run_plan.to_csv(RUN_PLAN_PATH.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    strict_units = int(
        presence.groupby("unit_id", sort=False)["panel_core_admissible"].agg(lambda values: bool(values.all())).sum()
    )
    manifest = {
        "schema_version": "longitudinal_audit_v1",
        "spec_version": SPEC_VERSION,
        "harmonization_version": HARMONIZATION_VERSION,
        "reference_universe": "valid 2022 communes with complete CSP, VBBM and source-backed geography",
        "reference_universe_size": int(len(universe)),
        "elections": int(len(inventory)),
        "registered_election_scenario_pairs": int(len(run_plan)),
        "source_valid_pairs": int(run_plan["preparation_status"].eq("admissible").sum()),
        "strict_panel_core_units": strict_units,
        "outputs": {
            "inventory": INVENTORY_PATH.relative_to(OUTPUT_DIR.parent).as_posix(),
            "presence": PRESENCE_PATH.relative_to(OUTPUT_DIR.parent).as_posix(),
            "run_plan": RUN_PLAN_PATH.relative_to(OUTPUT_DIR.parent).as_posix(),
        },
        "settings_sha256": file_sha256(settings_path),
    }
    write_json(AUDIT_MANIFEST_PATH, manifest)
    return manifest


def load_audit_manifest() -> dict[str, object]:
    return json.loads(AUDIT_MANIFEST_PATH.read_text(encoding="utf-8"))


__all__ = [
    "AUDIT_MANIFEST_PATH",
    "INVENTORY_PATH",
    "PRESENCE_PATH",
    "RUN_PLAN_PATH",
    "build_longitudinal_audit",
    "load_audit_manifest",
]
