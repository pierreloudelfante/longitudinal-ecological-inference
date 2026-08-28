from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .audit_longitudinal import AUDIT_MANIFEST_PATH, PRESENCE_PATH, build_longitudinal_audit
from .balance_checks import balance_summary, compute_balance_checks
from .build_panel import load_settings
from .data_io import load_reference_universe
from .paths import CONFIG_DIR, PANEL_DIR, ensure_runtime_dirs
from .spec_registry import ELECTION_BY_ID, HARMONIZATION_VERSION, SPEC_VERSION
from .utils import file_sha256, write_json


PANEL_PATH = PANEL_DIR / f"{SPEC_VERSION}.parquet"
PANEL_CSV_PATH = PANEL_DIR / f"{SPEC_VERSION}.csv"
STRICT_SUBPANEL_PATH = PANEL_DIR / f"{SPEC_VERSION}_strict_subpanel.parquet"
BALANCE_PATH = PANEL_DIR / f"{SPEC_VERSION}_balance.parquet"
BALANCE_BY_ELECTION_PATH = PANEL_DIR / f"{SPEC_VERSION}_balance_by_election.parquet"
ATTEMPTS_PATH = PANEL_DIR / f"{SPEC_VERSION}_attempts.parquet"
PANEL_MANIFEST_PATH = PANEL_DIR / f"{SPEC_VERSION}_manifest.json"


def _summarize(
    checks: pd.DataFrame,
    *,
    max_smd: float,
    max_category_gap: float,
) -> dict[str, object]:
    return balance_summary(checks, max_smd=max_smd, max_category_gap=max_category_gap)


def _candidate_checks(
    candidate: pd.DataFrame,
    sampling_universe: pd.DataFrame,
    reference_universe: pd.DataFrame,
    *,
    primary_size: int,
    max_smd: float,
    max_category_gap: float,
) -> tuple[bool, list[pd.DataFrame], dict[str, object]]:
    scopes = {"master": candidate, "primary_2000": candidate.head(primary_size)}
    comparisons = {"sampling_universe": sampling_universe, "reference_2022": reference_universe}
    detail: list[pd.DataFrame] = []
    summaries: dict[str, object] = {}
    accepted = True
    for sample_scope, sample in scopes.items():
        for comparison, universe in comparisons.items():
            checks = compute_balance_checks(universe, sample)
            checks.insert(0, "comparison", comparison)
            checks.insert(1, "sample_scope", sample_scope)
            summary = _summarize(checks, max_smd=max_smd, max_category_gap=max_category_gap)
            summaries[f"{sample_scope}__{comparison}"] = summary
            accepted = accepted and bool(summary["accepted"])
            detail.append(checks)
    return accepted, detail, summaries


def _draw_balanced_panel(
    sampling_universe: pd.DataFrame,
    reference_universe: pd.DataFrame,
    *,
    master_size: int,
    primary_size: int,
    initial_seed: int,
    max_attempts: int,
    max_smd: float,
    max_category_gap: float,
) -> tuple[pd.DataFrame | None, pd.DataFrame, pd.DataFrame, dict[str, object]]:
    attempts: list[dict[str, object]] = []
    for attempt in range(max_attempts):
        seed = initial_seed + attempt
        order = np.random.default_rng(seed).permutation(len(sampling_universe))
        candidate = sampling_universe.iloc[order[:master_size]].copy().reset_index(drop=True)
        candidate["master_draw_order"] = np.arange(1, len(candidate) + 1)
        accepted, detail, summaries = _candidate_checks(
            candidate,
            sampling_universe,
            reference_universe,
            primary_size=primary_size,
            max_smd=max_smd,
            max_category_gap=max_category_gap,
        )
        attempt_row: dict[str, object] = {"attempt": attempt + 1, "seed": seed, "accepted": accepted}
        for key, summary in summaries.items():
            attempt_row[f"{key}__max_abs_smd"] = summary["max_abs_smd"]
            attempt_row[f"{key}__max_abs_category_gap"] = summary["max_abs_category_gap"]
        attempts.append(attempt_row)
        if accepted:
            return candidate, pd.concat(detail, ignore_index=True), pd.DataFrame(attempts), summaries
    return None, pd.DataFrame(), pd.DataFrame(attempts), {}


def _balance_by_election(panel: pd.DataFrame, presence: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    primary_ids = set(panel.loc[panel["included_primary_2000"], "unit_id"].astype(str))
    for election_id, universe in presence.loc[presence["panel_core_admissible"]].groupby("election_id", sort=True):
        sample = universe.loc[universe["unit_id"].astype(str).isin(primary_ids)]
        if sample.empty:
            continue
        checks = compute_balance_checks(universe, sample)
        checks.insert(0, "election_id", election_id)
        checks.insert(1, "universe_n_at_election", len(universe))
        checks.insert(2, "panel_n_at_election", len(sample))
        rows.append(checks)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def build_longitudinal_panel(settings_path: Path | None = None) -> dict[str, object]:
    ensure_runtime_dirs()
    settings_path = settings_path or CONFIG_DIR / "run_settings.json"
    settings = load_settings(settings_path)
    panel_settings = settings["panel"]
    if not PRESENCE_PATH.exists() or not AUDIT_MANIFEST_PATH.exists():
        build_longitudinal_audit(settings_path)
    presence = pd.read_parquet(PRESENCE_PATH)
    reference = load_reference_universe(ELECTION_BY_ID["leg_2022_r1"])
    per_unit = presence.groupby("unit_id", sort=False)["panel_core_admissible"].all()
    strict_ids = set(per_unit.index[per_unit].astype(str))
    strict_universe = reference.loc[reference["unit_id"].astype(str).isin(strict_ids)].copy()
    primary_size = int(panel_settings["primary_panel_size"])
    initial_seed = int(panel_settings["panel_seed"])
    max_attempts = int(panel_settings["max_attempts"])
    max_smd = float(panel_settings["max_abs_smd"])
    max_category_gap = float(panel_settings["max_abs_category_gap"])

    if len(strict_universe) >= 3000:
        initial_mode = "strict_nested_3000"
        master_size = int(panel_settings["master_panel_size"])
        sampling_universe = strict_universe
    elif len(strict_universe) >= primary_size:
        initial_mode = "strict_2000"
        master_size = primary_size
        sampling_universe = strict_universe
    else:
        initial_mode = "master_2022_with_availability"
        master_size = primary_size
        sampling_universe = reference

    candidate, balance, attempts, summaries = _draw_balanced_panel(
        sampling_universe,
        reference,
        master_size=master_size,
        primary_size=primary_size,
        initial_seed=initial_seed,
        max_attempts=max_attempts,
        max_smd=max_smd,
        max_category_gap=max_category_gap,
    )
    mode = initial_mode
    if candidate is None and initial_mode.startswith("strict"):
        mode = "master_2022_with_availability"
        candidate, balance, fallback_attempts, summaries = _draw_balanced_panel(
            reference,
            reference,
            master_size=primary_size,
            primary_size=primary_size,
            initial_seed=initial_seed,
            max_attempts=max_attempts,
            max_smd=max_smd,
            max_category_gap=max_category_gap,
        )
        if not fallback_attempts.empty:
            fallback_attempts.insert(0, "draw_mode", mode)
        if not attempts.empty:
            attempts.insert(0, "draw_mode", initial_mode)
        attempts = pd.concat([attempts, fallback_attempts], ignore_index=True, sort=False)
    elif not attempts.empty:
        attempts.insert(0, "draw_mode", mode)
    if candidate is None:
        raise RuntimeError("no balanced longitudinal panel found within the configured attempt limit")

    accepted_seed = int(attempts.loc[attempts["accepted"].astype(bool), "seed"].iloc[-1])
    panel_id = f"{SPEC_VERSION}__{mode}__seed_{accepted_seed}"
    candidate.insert(1, "panel_id", panel_id)
    candidate.insert(2, "sample_id", panel_id)
    candidate["sample_seed"] = accepted_seed
    candidate["sample_rank"] = candidate["master_draw_order"]
    candidate["panel_mode"] = mode
    candidate["included_primary_2000"] = candidate["master_draw_order"].le(primary_size)
    candidate["spec_version"] = SPEC_VERSION
    candidate["harmonization_version"] = HARMONIZATION_VERSION
    panel_columns = [
        "unit_id",
        "panel_id",
        "sample_id",
        "sample_seed",
        "master_draw_order",
        "sample_rank",
        "panel_mode",
        "included_primary_2000",
        "department",
        "region13",
        "commune_name",
        "geography_source",
        "inscrits",
        "vbbm",
        "log1p_inscrits",
        "share_ouvr",
        "share_empl",
        "share_cadr",
        "share_agri_indp",
        "spec_version",
        "harmonization_version",
    ]
    candidate = candidate.reindex(columns=panel_columns).sort_values("master_draw_order").reset_index(drop=True)
    candidate.to_parquet(PANEL_PATH, index=False)
    candidate.to_csv(PANEL_CSV_PATH, index=False, encoding="utf-8-sig")
    balance.insert(0, "panel_id", panel_id)
    balance.to_parquet(BALANCE_PATH, index=False)
    attempts.to_parquet(ATTEMPTS_PATH, index=False)
    by_election = _balance_by_election(candidate, presence)
    if not by_election.empty:
        by_election.insert(0, "panel_id", panel_id)
    by_election.to_parquet(BALANCE_BY_ELECTION_PATH, index=False)

    strict_subpanel = candidate.loc[candidate["unit_id"].astype(str).isin(strict_ids)].copy()
    strict_subpanel.to_parquet(STRICT_SUBPANEL_PATH, index=False)
    manifest = {
        "schema_version": "longitudinal_panel_v1",
        "panel_id": panel_id,
        "panel_mode": mode,
        "sample_seed": accepted_seed,
        "strict_universe_size": int(len(strict_universe)),
        "reference_universe_size": int(len(reference)),
        "master_panel_size": int(len(candidate)),
        "primary_panel_size": int(candidate["included_primary_2000"].sum()),
        "strict_subpanel_size": int(len(strict_subpanel)),
        "balance_thresholds": {"max_abs_smd": max_smd, "max_abs_category_gap": max_category_gap},
        "balance_summaries": summaries,
        "spec_version": SPEC_VERSION,
        "harmonization_version": HARMONIZATION_VERSION,
        "audit_sha256": file_sha256(PRESENCE_PATH),
        "panel_path": PANEL_PATH.relative_to(PANEL_DIR.parent).as_posix(),
        "panel_sha256": file_sha256(PANEL_PATH),
        "selection_is_outcome_blind": True,
    }
    write_json(PANEL_MANIFEST_PATH, manifest)
    return manifest


def load_longitudinal_panel_manifest() -> dict[str, object]:
    return json.loads(PANEL_MANIFEST_PATH.read_text(encoding="utf-8"))


__all__ = [
    "ATTEMPTS_PATH",
    "BALANCE_BY_ELECTION_PATH",
    "BALANCE_PATH",
    "PANEL_MANIFEST_PATH",
    "PANEL_PATH",
    "STRICT_SUBPANEL_PATH",
    "build_longitudinal_panel",
    "load_longitudinal_panel_manifest",
]
