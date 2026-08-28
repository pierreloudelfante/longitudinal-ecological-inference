from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from .build_panel import load_settings
from .data_io import load_covariates, load_csp, load_election
from .paths import OUTPUT_DIR, PANEL_DIR, RAW_ARCHIVES, ensure_runtime_dirs
from .spec_registry import (
    CSP_GROUPS,
    ELECTIONS,
    HARMONIZATION_VERSION,
    SPEC_VERSION,
    ElectionSpec,
    ScenarioSpec,
    VOTE_BLOCKS,
    scenario_is_allowed,
)
from .utils import file_sha256, largest_remainder_round, write_json


def x_columns(spec: ScenarioSpec) -> tuple[str, ...]:
    return tuple(f"X__{label}" for label in spec.social_groups)


def n_columns(spec: ScenarioSpec) -> tuple[str, ...]:
    return tuple(f"N__{label}" for label in spec.social_groups)


def y_columns(spec: ScenarioSpec) -> tuple[str, ...]:
    return tuple(f"Y__{label}" for label in spec.vote_categories)


def model_ready_path(
    election: ElectionSpec,
    scenario: ScenarioSpec,
    sample_id: str,
    *,
    sample_size: int | None = None,
) -> Path:
    safe_sample = sample_id.replace(" ", "_")
    size_suffix = f"__n{sample_size}" if sample_size is not None else ""
    return OUTPUT_DIR / "model_ready" / f"{election.election_id}__{scenario.scenario_id}__{safe_sample}{size_suffix}.parquet"


def read_panel(sample_size: int = 3000, *, panel_path: Path | None = None) -> pd.DataFrame:
    path = panel_path or PANEL_DIR / ("panel_3000.csv" if sample_size > 2000 else "panel_2000.csv")
    if not path.exists():
        raise FileNotFoundError(f"panel missing: run --stage panel first ({path})")
    panel = (
        pd.read_parquet(path)
        if path.suffix.lower() == ".parquet"
        else pd.read_csv(path, dtype={"unit_id": "string"})
    )
    panel["unit_id"] = panel["unit_id"].astype("string")
    if "panel_id" not in panel and "sample_id" in panel:
        panel["panel_id"] = panel["sample_id"]
    if "sample_id" not in panel and "panel_id" in panel:
        panel["sample_id"] = panel["panel_id"]
    if "master_draw_order" not in panel and "sample_rank" in panel:
        panel["master_draw_order"] = panel["sample_rank"]
    if "sample_rank" not in panel and "master_draw_order" in panel:
        panel["sample_rank"] = panel["master_draw_order"]
    if len(panel) < sample_size:
        raise ValueError(f"panel {path} has {len(panel)} units, fewer than requested {sample_size}")
    if sample_size < len(panel):
        panel = panel.sort_values("master_draw_order").head(sample_size).copy()
    if panel["unit_id"].duplicated().any():
        raise ValueError("panel contains duplicate unit_id values")
    return panel


def _reason_append(reasons: pd.Series, mask: pd.Series, label: str) -> pd.Series:
    updated = reasons.copy()
    was_blank = updated.eq("")
    updated.loc[mask & was_blank] = label
    updated.loc[mask & ~was_blank] = updated.loc[mask & ~was_blank] + ";" + label
    return updated


def _validate_raw_political_partition(
    df: pd.DataFrame,
    election: ElectionSpec,
    scenario: ScenarioSpec,
    tolerance: float,
) -> dict[str, object]:
    """Validate the raw political margin actually used by a scenario.

    Binary scenarios define their second category as the electoral-denominator
    complement, so their raw requirement is that the target lies inside that
    denominator.  RXC scenarios consume all five source blocks and therefore
    require their raw sum to match expressed votes within the configured
    absolute tolerance before largest-remainder closure is allowed.
    """
    if scenario.vote_definition == "abstention":
        columns = ["inscrits", "votants"]
        complete = df[columns].notna().all(axis=1)
        denominator = df.loc[complete, "inscrits"].astype(float)
        target = df.loc[complete, "votants"].astype(float)
        rule = "votants_inside_inscrits"
    elif scenario.vote_definition == "left":
        columns = ["exprimes", "voteG", "voteCG"]
        complete = df[columns].notna().all(axis=1)
        denominator = df.loc[complete, "exprimes"].astype(float)
        target = df.loc[complete, ["voteG", "voteCG"]].sum(axis=1)
        rule = "voteG_plus_voteCG_inside_exprimes"
    elif scenario.vote_definition == "right":
        columns = ["exprimes", "voteCD", "voteD"]
        complete = df[columns].notna().all(axis=1)
        denominator = df.loc[complete, "exprimes"].astype(float)
        target = df.loc[complete, ["voteCD", "voteD"]].sum(axis=1)
        rule = "voteCD_plus_voteD_inside_exprimes"
    elif scenario.vote_definition == "centre":
        columns = ["exprimes", "voteC"]
        complete = df[columns].notna().all(axis=1)
        denominator = df.loc[complete, "exprimes"].astype(float)
        target = df.loc[complete, "voteC"].astype(float)
        rule = "voteC_inside_exprimes"
    elif scenario.vote_definition == "rn":
        columns = ["exprimes", *election.rn_columns]
        complete = df[columns].notna().all(axis=1)
        denominator = df.loc[complete, "exprimes"].astype(float)
        target = df.loc[complete, list(election.rn_columns)].sum(axis=1)
        rule = "declared_fn_rn_columns_inside_exprimes"
    elif scenario.vote_definition == "five_blocks":
        columns = ["exprimes", *VOTE_BLOCKS]
        complete = df[columns].notna().all(axis=1)
        denominator = df.loc[complete, "exprimes"].astype(float)
        block_sum = df.loc[complete, list(VOTE_BLOCKS)].sum(axis=1)
        gap = block_sum - denominator
        bad = gap.abs() > tolerance
        if bad.any():
            examples = df.loc[
                gap.index[bad], ["unit_id", "exprimes", *VOTE_BLOCKS]
            ].head(5).to_dict("records")
            raise ValueError(
                f"{election.election_id}/{scenario.scenario_id}: five-block partition "
                f"differs from exprimes by more than {tolerance}; examples={examples}"
            )
        return {
            "rule": "five_source_blocks_sum_to_exprimes",
            "tolerance_absolute_votes": tolerance,
            "complete_rows_checked": int(complete.sum()),
            "maximum_absolute_raw_gap": float(gap.abs().max()) if len(gap) else 0.0,
        }
    else:
        raise ValueError(f"unknown vote definition {scenario.vote_definition}")

    lower_bad = target < -tolerance
    upper_bad = target > denominator + tolerance
    if lower_bad.any() or upper_bad.any():
        bad_index = target.index[lower_bad | upper_bad]
        examples = df.loc[bad_index, ["unit_id", *columns]].head(5).to_dict("records")
        raise ValueError(
            f"{election.election_id}/{scenario.scenario_id}: target political margin "
            f"outside its denominator by more than {tolerance}; examples={examples}"
        )
    boundary_gap = np.maximum(-target, target - denominator).clip(lower=0)
    return {
        "rule": rule,
        "tolerance_absolute_votes": tolerance,
        "complete_rows_checked": int(complete.sum()),
        "maximum_absolute_raw_gap": float(boundary_gap.max()) if len(boundary_gap) else 0.0,
    }


def _validate_electoral_denominators(
    df: pd.DataFrame,
    election: ElectionSpec,
    tolerance: float,
    *,
    diagnostic_only_allow_order_violations: bool = False,
) -> dict[str, object]:
    """Require ``0 <= exprimes <= votants <= inscrits`` on selected units."""

    columns = ["inscrits", "votants", "exprimes"]
    complete = df[columns].notna().all(axis=1)
    numeric = df.loc[complete, columns].astype(float)
    nonnegative_bad = numeric.lt(-tolerance).any(axis=1)
    expressed_bad = numeric["exprimes"] > numeric["votants"] + tolerance
    voters_bad = numeric["votants"] > numeric["inscrits"] + tolerance
    order_bad = expressed_bad | voters_bad
    bad = nonnegative_bad | order_bad
    if nonnegative_bad.any() or (order_bad.any() and not diagnostic_only_allow_order_violations):
        examples = df.loc[
            numeric.index[bad], ["unit_id", *columns]
        ].head(10).to_dict("records")
        raise ValueError(
            f"{election.election_id}: electoral denominators violate "
            f"0 <= exprimes <= votants <= inscrits; examples={examples}"
        )
    maximum_expressed_over_voters = (
        (numeric["exprimes"] - numeric["votants"]).clip(lower=0).max()
        if len(numeric)
        else 0.0
    )
    maximum_voters_over_registered = (
        (numeric["votants"] - numeric["inscrits"]).clip(lower=0).max()
        if len(numeric)
        else 0.0
    )
    return {
        "rule": "zero_le_exprimes_le_votants_le_inscrits",
        "tolerance_absolute_votes": tolerance,
        "complete_rows_checked": int(complete.sum()),
        "maximum_expressed_over_voters": float(maximum_expressed_over_voters),
        "maximum_voters_over_registered": float(maximum_voters_over_registered),
        "order_violation_count": int(order_bad.sum()),
        "diagnostic_only_override_applied": bool(
            diagnostic_only_allow_order_violations and order_bad.any()
        ),
        "order_violation_examples": df.loc[
            numeric.index[order_bad], ["unit_id", *columns]
        ].head(10).to_dict("records"),
    }


def _vote_values(row: pd.Series, election: ElectionSpec, scenario: ScenarioSpec) -> np.ndarray:
    denominator = int(row["N_g"])
    if scenario.vote_definition == "abstention":
        raw = np.array([float(row["inscrits"] - row["votants"]), float(row["votants"])])
    elif scenario.vote_definition == "left":
        target = float(row["voteG"] + row["voteCG"])
        raw = np.array([target, float(row["exprimes"] - target)])
    elif scenario.vote_definition == "right":
        target = float(row["voteCD"] + row["voteD"])
        raw = np.array([target, float(row["exprimes"] - target)])
    elif scenario.vote_definition == "centre":
        target = float(row["voteC"])
        raw = np.array([target, float(row["exprimes"] - target)])
    elif scenario.vote_definition == "rn":
        target = float(sum(float(row[column]) for column in election.rn_columns))
        raw = np.array([target, float(row["exprimes"] - target)])
    elif scenario.vote_definition == "five_blocks":
        raw = row.loc[list(VOTE_BLOCKS)].astype(float).to_numpy()
    else:
        raise ValueError(f"unknown vote definition {scenario.vote_definition}")
    if np.any(~np.isfinite(raw)) or np.any(raw < -1e-8):
        raise ValueError(f"invalid political partition for {row['unit_id']}: {raw.tolist()}")
    return largest_remainder_round(raw, denominator)


def _social_values(row: pd.Series, scenario: ScenarioSpec) -> np.ndarray:
    group_values = [sum(float(row[component]) for component in components) for components in scenario.social_groups.values()]
    return largest_remainder_round(group_values, int(row["N_g"]))


def validate_model_ready(df: pd.DataFrame, scenario: ScenarioSpec) -> dict[str, float | int]:
    if df.empty:
        raise ValueError(f"{scenario.scenario_id}: model-ready table is empty")
    if df["unit_id"].duplicated().any():
        raise AssertionError(f"{scenario.scenario_id}: duplicate unit_id")
    n = df["N_g"].astype(int)
    x = df.loc[:, list(x_columns(scenario))].astype(float)
    social = df.loc[:, list(n_columns(scenario))].astype(int)
    votes = df.loc[:, list(y_columns(scenario))].astype(int)
    if (n <= 0).any() or (social < 0).any().any() or (votes < 0).any().any():
        raise AssertionError(f"{scenario.scenario_id}: non-positive denominator or negative counts")
    x_gap = (x.sum(axis=1) - 1.0).abs()
    social_gap = social.sum(axis=1) - n
    vote_gap = votes.sum(axis=1) - n
    if float(x_gap.max()) > 1e-10:
        raise AssertionError(f"{scenario.scenario_id}: social fractions do not sum to one")
    if int(social_gap.abs().max()) != 0:
        raise AssertionError(f"{scenario.scenario_id}: social counts do not close")
    if int(vote_gap.abs().max()) != 0:
        raise AssertionError(f"{scenario.scenario_id}: vote counts do not close")
    return {
        "rows": int(len(df)),
        "N_total": int(n.sum()),
        "max_abs_x_sum_minus_one": float(x_gap.max()),
        "max_abs_social_sum_minus_N": int(social_gap.abs().max()),
        "max_abs_vote_sum_minus_N": int(vote_gap.abs().max()),
    }


def _reuse_prepared_full_panel(
    election: ElectionSpec,
    scenario: ScenarioSpec,
    panel: pd.DataFrame,
    *,
    sample_size: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]] | None:
    """Reuse a verified n=3000 preparation for an identical nested panel.

    The full preparation has already validated the raw political partition.
    Reuse is accepted only while both raw-source hashes and the scenario
    definition recorded in its manifest still match the current registry.
    Every derived table is validated again before it is written.
    """
    main_panel = read_panel(3000).sort_values("sample_rank")
    main_sample_id = str(main_panel["sample_id"].iloc[0])
    full_path = model_ready_path(
        election, scenario, main_sample_id, sample_size=3000
    )
    full_manifest_path = full_path.with_name(full_path.stem + "__manifest.json")
    full_exclusions_path = full_path.with_name(full_path.stem + "__excluded.csv")
    if not full_path.exists() or not full_manifest_path.exists():
        return None

    full_manifest = json.loads(full_manifest_path.read_text(encoding="utf-8"))
    current_hashes = {
        election.archive_name: file_sha256(RAW_ARCHIVES / election.archive_name),
        "socio_csp_csv.zip": file_sha256(RAW_ARCHIVES / "socio_csp_csv.zip"),
    }
    definition_matches = bool(
        full_manifest.get("election_id") == election.election_id
        and full_manifest.get("scenario_id") == scenario.scenario_id
        and full_manifest.get("denominator") == scenario.denominator
        and full_manifest.get("social_groups")
        == {key: list(value) for key, value in scenario.social_groups.items()}
        and full_manifest.get("vote_categories") == list(scenario.vote_categories)
        and full_manifest.get("vote_definition") == scenario.vote_definition
        and full_manifest.get("rn_columns") == list(election.rn_columns)
        and full_manifest.get("source_sha256") == current_hashes
    )
    if not definition_matches:
        return None

    full = pd.read_parquet(full_path)
    full["unit_id"] = full["unit_id"].astype("string")
    allowed_units = set(panel["unit_id"].astype("string"))
    included = full.loc[full["unit_id"].isin(allowed_units)].copy()
    sample_id = str(panel["sample_id"].iloc[0])
    included["sample_id"] = sample_id
    included = included.sort_values("sample_rank").reset_index(drop=True)
    checks = validate_model_ready(included, scenario)

    if full_exclusions_path.exists():
        try:
            exclusions = pd.read_csv(
                full_exclusions_path, dtype={"unit_id": "string"}, low_memory=False
            )
        except pd.errors.EmptyDataError:
            exclusions = pd.DataFrame(
                columns=[
                    "sample_id",
                    "election_id",
                    "scenario_id",
                    "unit_id",
                    "sample_rank",
                    "exclusion_reason",
                    "stage",
                ]
            )
        exclusions = exclusions.loc[
            exclusions.get("unit_id", pd.Series(dtype="string"))
            .astype("string")
            .isin(allowed_units)
        ].copy()
        if not exclusions.empty:
            exclusions["sample_id"] = sample_id
    else:
        exclusions = pd.DataFrame()

    output_path = model_ready_path(
        election, scenario, sample_id, sample_size=sample_size
    )
    # For n=3000 this is the verified source itself; no rewrite is needed.
    if output_path.resolve() == full_path.resolve():
        return included, exclusions, full_manifest

    output_path.parent.mkdir(parents=True, exist_ok=True)
    included.to_parquet(output_path, index=False)
    included.to_csv(output_path.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    exclusions.to_csv(
        output_path.with_name(output_path.stem + "__excluded.csv"),
        index=False,
        encoding="utf-8-sig",
    )
    manifest = {
        **{
            key: full_manifest[key]
            for key in (
                "election_id",
                "scenario_id",
                "denominator",
                "social_groups",
                "vote_categories",
                "vote_definition",
                "rn_columns",
                "source_sha256",
            )
        },
        "sample_id": sample_id,
        "n_communes_requested": int(len(panel)),
        "n_communes_used": int(len(included)),
        "n_communes_excluded": int(len(exclusions)),
        "checks": checks,
        "output": str(output_path),
        "derived_from_verified_full_panel": str(full_path),
        "derived_from_sha256": file_sha256(full_path),
        "subset_rule": f"unit_id in first {sample_size} fixed panel ranks",
    }
    write_json(output_path.with_name(output_path.stem + "__manifest.json"), manifest)
    return included, exclusions, manifest


def _reuse_verified_exact_cache(
    election: ElectionSpec,
    scenario: ScenarioSpec,
    panel: pd.DataFrame,
    *,
    sample_size: int,
    panel_path: Path | None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    """Load a portable model-ready cache after strict, explicit verification.

    This mode is intended for the transfer bundle, where the 2+ GB source
    archive collection is deliberately not shipped. It is never enabled by
    default and refuses to fall back silently when any hash, definition, key,
    row count, or margin check differs from the recorded cache manifest.
    """
    sample_id = str(panel["sample_id"].iloc[0])
    output_path = model_ready_path(
        election,
        scenario,
        sample_id,
        sample_size=sample_size,
    )
    manifest_path = output_path.with_name(output_path.stem + "__manifest.json")
    exclusions_path = output_path.with_name(output_path.stem + "__excluded.csv")
    if not output_path.exists() or not manifest_path.exists():
        raise FileNotFoundError(
            f"verified model-ready cache missing for {election.election_id}/{scenario.scenario_id}: "
            f"{output_path}"
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    effective_panel_path = panel_path or PANEL_DIR / (
        "panel_3000.csv" if sample_size > 2000 else "panel_2000.csv"
    )
    expected = {
        "election_id": election.election_id,
        "scenario_id": scenario.scenario_id,
        "sample_id": sample_id,
        "panel_id": str(panel["panel_id"].iloc[0]),
        "spec_version": SPEC_VERSION,
        "harmonization_version": HARMONIZATION_VERSION,
        "n_communes_requested": int(sample_size),
        "denominator": scenario.denominator,
        "social_groups": {key: list(value) for key, value in scenario.social_groups.items()},
        "vote_categories": list(scenario.vote_categories),
        "vote_definition": scenario.vote_definition,
        "rn_columns": list(election.rn_columns),
        "panel_source_sha256": file_sha256(effective_panel_path),
    }
    mismatches = {
        key: {"expected": value, "observed": manifest.get(key)}
        for key, value in expected.items()
        if manifest.get(key) != value
    }
    recorded_output_hash = str(manifest.get("output_sha256", ""))
    observed_output_hash = file_sha256(output_path)
    if not recorded_output_hash:
        mismatches["output_sha256"] = {
            "expected": "non-empty hash supplied by transfer bundle",
            "observed": "",
        }
    elif recorded_output_hash != observed_output_hash:
        mismatches["output_sha256"] = {
            "expected": recorded_output_hash,
            "observed": observed_output_hash,
        }
    if mismatches:
        raise ValueError(
            f"verified model-ready cache metadata mismatch for "
            f"{election.election_id}/{scenario.scenario_id}: {mismatches}"
        )

    included = pd.read_parquet(output_path)
    included["unit_id"] = included["unit_id"].astype("string")
    included = included.sort_values("sample_rank").reset_index(drop=True)
    expected_units = panel.sort_values("sample_rank")["unit_id"].astype("string").tolist()
    observed_units = included["unit_id"].tolist()
    if observed_units != expected_units:
        raise AssertionError(
            f"verified model-ready cache unit order differs from the fixed panel for "
            f"{election.election_id}/{scenario.scenario_id}"
        )
    checks = validate_model_ready(included, scenario)
    if checks != manifest.get("checks"):
        raise AssertionError(
            f"verified model-ready cache checks differ from its manifest for "
            f"{election.election_id}/{scenario.scenario_id}"
        )

    if exclusions_path.exists():
        try:
            exclusions = pd.read_csv(exclusions_path, dtype={"unit_id": "string"})
        except pd.errors.EmptyDataError:
            exclusions = pd.DataFrame()
    else:
        exclusions = pd.DataFrame()
    runtime_manifest = {
        **manifest,
        "output": output_path.relative_to(OUTPUT_DIR.parent).as_posix(),
        "panel_source": effective_panel_path.relative_to(OUTPUT_DIR.parent).as_posix(),
        "runtime_cache_reuse": "verified_prebuilt_model_ready_explicit_opt_in",
    }
    return included, exclusions, runtime_manifest


def prepare_model_ready(
    election: ElectionSpec,
    scenario: ScenarioSpec,
    *,
    sample_size: int = 3000,
    panel_path: Path | None = None,
    settings_path: Path | None = None,
    diagnostic_only_allow_transversal_order_violations: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    ensure_runtime_dirs()
    if not scenario_is_allowed(scenario, election):
        raise ValueError(f"{scenario.scenario_id} is not allowed for {election.election_id}")
    settings = load_settings(settings_path)
    tolerance = float(settings["data"]["political_partition_tolerance"])
    panel = read_panel(sample_size, panel_path=panel_path).sort_values("sample_rank").copy()
    allow_verified_cache = os.environ.get(
        "LONGITUDINAL_ALLOW_VERIFIED_MODEL_READY_CACHE",
        "",
    ).strip().lower() in {"1", "true", "yes"}
    if allow_verified_cache:
        return _reuse_verified_exact_cache(
            election,
            scenario,
            panel,
            sample_size=sample_size,
            panel_path=panel_path,
        )
    if panel_path is None:
        reused = _reuse_prepared_full_panel(
            election, scenario, panel, sample_size=sample_size
        )
        if reused is not None:
            return reused
    panel = panel.rename(
        columns={
            "inscrits": "inscrits_reference_2022",
            "vbbm": "vbbm_reference_2022",
            "region13": "region13_reference_2022",
        }
    )
    sample_id = str(panel["sample_id"].iloc[0])
    electoral = load_election(election)
    selected_ids = set(panel["unit_id"].astype(str))
    electoral_selected = electoral.loc[
        electoral["unit_id"].astype(str).isin(selected_ids)
    ].copy()
    transversal_denominator_validation = _validate_electoral_denominators(
        electoral_selected,
        election,
        tolerance,
        diagnostic_only_allow_order_violations=diagnostic_only_allow_transversal_order_violations,
    )
    raw_partition_validation = _validate_raw_political_partition(
        electoral_selected, election, scenario, tolerance
    )
    csp = load_csp(election.year)
    covariates = load_covariates(election.year)

    merged = panel.merge(electoral, on="unit_id", how="left", validate="one_to_one", suffixes=("_panel", "_election"))
    merged = merged.merge(csp[["unit_id", *CSP_GROUPS]], on="unit_id", how="left", validate="one_to_one")
    merged = merged.merge(covariates, on="unit_id", how="left", validate="one_to_one")
    reasons = pd.Series("", index=merged.index, dtype="string")
    reasons = _reason_append(reasons, merged["inscrits"].isna(), "election_absent")
    denominator_col = "inscrits" if scenario.denominator == "registered" else "exprimes"
    reasons = _reason_append(reasons, pd.to_numeric(merged[denominator_col], errors="coerce").fillna(0).le(0), f"{denominator_col}_non_positive")
    reasons = _reason_append(reasons, merged[list(CSP_GROUPS)].isna().any(axis=1), "csp_missing")
    reasons = _reason_append(reasons, merged[list(CSP_GROUPS)].fillna(0).lt(0).any(axis=1), "csp_negative")
    reasons = _reason_append(reasons, merged[list(CSP_GROUPS)].sum(axis=1, min_count=len(CSP_GROUPS)).fillna(0).le(0), "csp_total_non_positive")
    if scenario.vote_definition == "rn":
        reasons = _reason_append(reasons, merged[list(election.rn_columns)].isna().any(axis=1), "rn_vote_missing")
    merged["exclusion_reason"] = reasons
    included = merged.loc[merged["exclusion_reason"].eq("")].copy()
    included["N_g"] = included[denominator_col].round().astype("int64")

    social_matrix = np.vstack([_social_values(row, scenario) for _, row in included.iterrows()])
    vote_matrix = np.vstack([_vote_values(row, election, scenario) for _, row in included.iterrows()])
    for idx, (x_col, n_col) in enumerate(zip(x_columns(scenario), n_columns(scenario))):
        included[n_col] = social_matrix[:, idx]
        included[x_col] = included[n_col] / included["N_g"]
    for idx, y_col in enumerate(y_columns(scenario)):
        included[y_col] = vote_matrix[:, idx]

    included["election_id"] = election.election_id
    included["election_type"] = election.election_type
    included["year"] = election.year
    included["round"] = election.round
    included["scenario_id"] = scenario.scenario_id
    included["sample_id"] = sample_id
    included["panel_id"] = str(panel["panel_id"].iloc[0])
    included["master_draw_order"] = included["sample_rank"]
    included["social_margin_strategy"] = "six_csp_shares_rescaled_to_electoral_denominator_largest_remainder"
    included["political_partition_strategy"] = "raw_validated_then_largest_remainder"
    keep = [
        "unit_id",
        "sample_id",
        "panel_id",
        "master_draw_order",
        "sample_rank",
        "election_id",
        "election_type",
        "year",
        "round",
        "scenario_id",
        "N_g",
        *x_columns(scenario),
        *n_columns(scenario),
        *y_columns(scenario),
        "vbbm",
        "vbbm_reference_year",
        "vbbm_source_column",
        "vbbm_status",
        "revenue",
        "revenue_reference_year",
        "revenue_source_column",
        "revenue_status",
        "capital",
        "capital_reference_year",
        "capital_source_column",
        "capital_status",
        "foreign_share",
        "foreign_share_reference_year",
        "foreign_share_source_column",
        "foreign_share_status",
        "region13",
        "ne_vs_se",
        "social_margin_strategy",
        "political_partition_strategy",
    ]
    included = included.loc[:, keep].sort_values("sample_rank").reset_index(drop=True)
    checks = validate_model_ready(included, scenario)

    exclusions = merged.loc[merged["exclusion_reason"].ne(""), ["unit_id", "sample_rank", "exclusion_reason"]].copy()
    exclusions.insert(0, "sample_id", sample_id)
    exclusions.insert(1, "election_id", election.election_id)
    exclusions.insert(2, "scenario_id", scenario.scenario_id)
    exclusions["stage"] = "prepare_inputs"

    output_path = model_ready_path(election, scenario, sample_id, sample_size=sample_size)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    included.to_parquet(output_path, index=False)
    included.to_csv(output_path.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    exclusions.to_csv(output_path.with_name(output_path.stem + "__excluded.csv"), index=False, encoding="utf-8-sig")
    manifest = {
        "election_id": election.election_id,
        "scenario_id": scenario.scenario_id,
        "sample_id": sample_id,
        "panel_id": str(panel["panel_id"].iloc[0]),
        "spec_version": SPEC_VERSION,
        "harmonization_version": HARMONIZATION_VERSION,
        "n_communes_requested": int(len(panel)),
        "n_communes_used": int(len(included)),
        "n_communes_excluded": int(len(exclusions)),
        "denominator": scenario.denominator,
        "social_groups": {key: list(value) for key, value in scenario.social_groups.items()},
        "vote_categories": list(scenario.vote_categories),
        "vote_definition": scenario.vote_definition,
        "rn_columns": list(election.rn_columns),
        "raw_partition_validation": raw_partition_validation,
        "transversal_denominator_validation": transversal_denominator_validation,
        "diagnostic_only_allow_transversal_order_violations": bool(
            diagnostic_only_allow_transversal_order_violations
        ),
        "checks": checks,
        "source_sha256": {
            election.archive_name: file_sha256(RAW_ARCHIVES / election.archive_name),
            "socio_csp_csv.zip": file_sha256(RAW_ARCHIVES / "socio_csp_csv.zip"),
        },
        "panel_source": str(panel_path) if panel_path is not None else str(
            PANEL_DIR / ("panel_3000.csv" if sample_size > 2000 else "panel_2000.csv")
        ),
        "panel_source_sha256": file_sha256(panel_path) if panel_path is not None else file_sha256(
            PANEL_DIR / ("panel_3000.csv" if sample_size > 2000 else "panel_2000.csv")
        ),
        "output": str(output_path),
    }
    write_json(output_path.with_name(output_path.stem + "__manifest.json"), manifest)
    return included, exclusions, manifest


def build_presence_ledger(sample_size: int = 3000) -> pd.DataFrame:
    panel = read_panel(sample_size).sort_values("sample_rank")
    rows: list[pd.DataFrame] = []
    for election in ELECTIONS:
        available = set(load_election(election)["unit_id"].astype(str))
        part = panel[["unit_id", "sample_id", "sample_rank"]].copy()
        part["election_id"] = election.election_id
        part["election_type"] = election.election_type
        part["year"] = election.year
        part["round"] = election.round
        part["available_at_election"] = part["unit_id"].astype(str).isin(available)
        part["absence_reason"] = np.where(part["available_at_election"], "", "not_in_election_archive_after_stable_id_policy")
        rows.append(part)
    out = pd.concat(rows, ignore_index=True)
    out.to_csv(PANEL_DIR / "panel_election_presence.csv", index=False, encoding="utf-8-sig")
    return out
