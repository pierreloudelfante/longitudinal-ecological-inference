from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .balance_checks import balance_summary, compute_balance_checks
from .build_longitudinal_panel import PANEL_PATH
from .build_panel import load_settings
from .data_io import load_csp, load_election, load_geography_reference, load_reference_universe
from .paths import CONFIG_DIR, OUTPUT_DIR, ROOT
from .prepare_inputs import model_ready_path, n_columns, x_columns, y_columns
from .spec_registry import (
    CSP_GROUPS,
    ELECTIONS,
    ELECTION_BY_ID,
    HARMONIZATION_VERSION,
    SCENARIO_BY_ID,
    SPEC_VERSION,
    VOTE_BLOCKS,
)
from .utils import PLM_ARM_TO_WHOLE, PLM_WHOLE, file_sha256, portable_path, write_json


INTEGRITY_DIR = OUTPUT_DIR / SPEC_VERSION / "audit" / "panel_2000_integrity"
ELECTION_CHECKS_PATH = INTEGRITY_DIR / "panel_2000_election_checks.parquet"
SCENARIO_CHECKS_PATH = INTEGRITY_DIR / "panel_2000_h0a_h1_checks.parquet"
INTEGRITY_MANIFEST_PATH = INTEGRITY_DIR / "panel_2000_integrity_manifest.json"


def _primary_panel(panel_path: Path = PANEL_PATH) -> pd.DataFrame:
    panel = pd.read_parquet(panel_path)
    panel["unit_id"] = panel["unit_id"].astype("string")
    if "included_primary_2000" in panel:
        panel = panel.loc[panel["included_primary_2000"].astype(bool)].copy()
    else:
        panel = panel.sort_values("master_draw_order").head(2000).copy()
    return panel.sort_values("master_draw_order").reset_index(drop=True)


def _model_ready_integrity(
    frame: pd.DataFrame,
    *,
    expected_unit_ids: set[str],
    expected_denominator: pd.Series,
    scenario_id: str,
) -> dict[str, object]:
    """Evaluate the materialized table independently of its saved manifest."""
    scenario = SCENARIO_BY_ID[scenario_id]
    observed_ids = set(frame["unit_id"].astype(str)) if "unit_id" in frame else set()
    n = pd.to_numeric(frame.get("N_g"), errors="coerce")
    social = frame.reindex(columns=list(n_columns(scenario))).apply(pd.to_numeric, errors="coerce")
    votes = frame.reindex(columns=list(y_columns(scenario))).apply(pd.to_numeric, errors="coerce")
    fractions = frame.reindex(columns=list(x_columns(scenario))).apply(pd.to_numeric, errors="coerce")
    denominator_lookup = expected_denominator.copy()
    denominator_lookup.index = denominator_lookup.index.astype(str)
    expected = frame["unit_id"].astype(str).map(denominator_lookup) if "unit_id" in frame else pd.Series(dtype=float)
    social_gap = social.sum(axis=1, min_count=len(social.columns)) - n
    vote_gap = votes.sum(axis=1, min_count=len(votes.columns)) - n
    fraction_gap = fractions.sum(axis=1, min_count=len(fractions.columns)) - 1.0
    negative_rows = (
        social.lt(0).any(axis=1)
        | votes.lt(0).any(axis=1)
        | n.le(0)
    )
    return {
        "rows": int(len(frame)),
        "duplicate_unit_rows": int(frame["unit_id"].astype(str).duplicated(keep=False).sum()) if "unit_id" in frame else int(len(frame)),
        "missing_expected_units": int(len(expected_unit_ids - observed_ids)),
        "unexpected_units": int(len(observed_ids - expected_unit_ids)),
        "denominator_mismatch_rows": int((n != expected).fillna(True).sum()),
        "negative_or_nonpositive_rows": int(negative_rows.fillna(True).sum()),
        "social_closure_anomaly_rows": int(social_gap.fillna(np.inf).abs().gt(0).sum()),
        "vote_closure_anomaly_rows": int(vote_gap.fillna(np.inf).abs().gt(0).sum()),
        "social_fraction_anomaly_rows": int(fraction_gap.fillna(np.inf).abs().gt(1e-10).sum()),
        "max_abs_social_closure_gap": float(social_gap.abs().max()) if len(social_gap) else np.nan,
        "max_abs_vote_closure_gap": float(vote_gap.abs().max()) if len(vote_gap) else np.nan,
        "max_abs_social_fraction_gap": float(fraction_gap.abs().max()) if len(fraction_gap) else np.nan,
    }


def _edge_counts(unit_ids: pd.Series) -> dict[str, int]:
    ids = unit_ids.astype(str)
    return {
        "plm_whole_count": int(ids.isin(PLM_WHOLE).sum()),
        "plm_arm_count": int(ids.isin(PLM_ARM_TO_WHOLE).sum()),
        "corsica_count": int(ids.str.startswith(("2A", "2B")).sum()),
        "overseas_count": int(ids.str.startswith(("971", "972", "973", "974", "976")).sum()),
    }


def _eligible_universe_for_election(reference: pd.DataFrame, election_id: str, tolerance: float) -> pd.DataFrame:
    election = ELECTION_BY_ID[election_id]
    electoral = load_election(election)
    csp = load_csp(election.year)[["unit_id", *CSP_GROUPS]]
    merged = reference[["unit_id", "region13", "vbbm"]].merge(
        electoral[["unit_id", "inscrits", "votants", "exprimes", *VOTE_BLOCKS]],
        on="unit_id",
        how="inner",
        validate="one_to_one",
    )
    merged = merged.merge(csp, on="unit_id", how="inner", validate="one_to_one")
    electoral_numeric = merged[["inscrits", "votants", "exprimes", *VOTE_BLOCKS]].apply(pd.to_numeric, errors="coerce")
    csp_numeric = merged[list(CSP_GROUPS)].apply(pd.to_numeric, errors="coerce")
    csp_total = csp_numeric.sum(axis=1, min_count=len(CSP_GROUPS))
    left = electoral_numeric[["voteG", "voteCG"]].sum(axis=1, min_count=2)
    valid = (
        electoral_numeric.notna().all(axis=1)
        & electoral_numeric.ge(-tolerance).all(axis=1)
        & electoral_numeric["inscrits"].gt(0)
        & electoral_numeric["exprimes"].gt(0)
        & electoral_numeric["exprimes"].le(electoral_numeric["votants"] + tolerance)
        & electoral_numeric["votants"].le(electoral_numeric["inscrits"] + tolerance)
        & left.ge(-tolerance)
        & left.le(electoral_numeric["exprimes"] + tolerance)
        & csp_numeric.notna().all(axis=1)
        & csp_numeric.ge(-tolerance).all(axis=1)
        & csp_total.gt(0)
    )
    out = merged.loc[valid, ["unit_id", "region13", "vbbm", "inscrits", *CSP_GROUPS]].copy()
    out["log1p_inscrits"] = np.log1p(pd.to_numeric(out["inscrits"], errors="coerce"))
    total = out[list(CSP_GROUPS)].sum(axis=1)
    out["share_ouvr"] = out["ouvr"] / total
    out["share_empl"] = out["empl"] / total
    out["share_cadr"] = out["cadr"] / total
    out["share_agri_indp"] = (out["agri"] + out["indp"]) / total
    return out


def _critical_anomaly_total(elections: pd.DataFrame, scenarios: pd.DataFrame) -> int:
    election_columns = [
        "join_row_expansion",
        "missing_election_rows",
        "missing_csp_rows",
        "unit_set_mismatch_count",
        "negative_electoral_rows",
        "denominator_order_anomaly_rows",
        "h0a_partition_anomaly_rows",
        "h1_partition_anomaly_rows",
        "negative_social_rows",
        "social_partition_anomaly_rows",
        "geography_mismatch_rows",
        "source_duplicate_stable_ids",
        "source_plm_arm_ids_remaining",
    ]
    scenario_columns = [
        "missing_table",
        "row_count_anomaly",
        "duplicate_unit_rows",
        "missing_expected_units",
        "unexpected_units",
        "denominator_mismatch_rows",
        "negative_or_nonpositive_rows",
        "social_closure_anomaly_rows",
        "vote_closure_anomaly_rows",
        "social_fraction_anomaly_rows",
    ]
    return int(elections[election_columns].sum().sum() + scenarios[scenario_columns].sum().sum())


def audit_panel_2000_integrity(
    *,
    panel_path: Path = PANEL_PATH,
    settings_path: Path | None = None,
) -> dict[str, object]:
    settings_path = settings_path or CONFIG_DIR / "run_settings.json"
    settings = load_settings(settings_path)
    tolerance = float(settings["data"]["political_partition_tolerance"])
    max_smd = float(settings["panel"]["max_abs_smd"])
    max_category_gap = float(settings["panel"]["max_abs_category_gap"])
    panel = _primary_panel(panel_path)
    panel_ids = set(panel["unit_id"].astype(str))
    panel_id_values = panel["panel_id"].astype(str).unique().tolist()
    panel_id = panel_id_values[0] if len(panel_id_values) == 1 else ""
    reference = load_reference_universe(ELECTION_BY_ID["leg_2022_r1"])
    geography = load_geography_reference(2022)[["unit_id", "department", "region13", "geography_source"]]
    geo_check = panel.merge(geography, on="unit_id", how="left", validate="one_to_one", suffixes=("_panel", "_reference"))
    geography_mismatch = (
        geo_check["department_panel"].astype("string").ne(geo_check["department_reference"].astype("string"))
        | geo_check["region13_panel"].astype("string").ne(geo_check["region13_reference"].astype("string"))
        | geo_check["geography_source_reference"].isna()
    )

    election_rows: list[dict[str, object]] = []
    scenario_rows: list[dict[str, object]] = []
    for election in ELECTIONS:
        electoral = load_election(election).copy()
        csp = load_csp(election.year)[["unit_id", *CSP_GROUPS]].copy()
        source_duplicates = int(electoral["unit_id"].astype(str).duplicated(keep=False).sum())
        panel_electoral = panel[["unit_id", "master_draw_order"]].merge(
            electoral,
            on="unit_id",
            how="left",
            validate="one_to_one",
            indicator="_election_merge",
        )
        joined = panel_electoral.merge(csp, on="unit_id", how="left", validate="one_to_one", indicator="_csp_merge")
        numeric = joined[["inscrits", "votants", "exprimes", *VOTE_BLOCKS]].apply(pd.to_numeric, errors="coerce")
        social = joined[list(CSP_GROUPS)].apply(pd.to_numeric, errors="coerce")
        social_total = social.sum(axis=1, min_count=len(CSP_GROUPS))
        social_target = social[["ouvr", "empl"]].sum(axis=1, min_count=2)
        social_complement = social[["agri", "indp", "cadr", "pint"]].sum(axis=1, min_count=4)
        left = numeric[["voteG", "voteCG"]].sum(axis=1, min_count=2)
        h0a_closure_gap = (numeric["inscrits"] - numeric["votants"]) + numeric["votants"] - numeric["inscrits"]
        h1_closure_gap = left + (numeric["exprimes"] - left) - numeric["exprimes"]
        social_gap = social_target + social_complement - social_total
        negative_electoral = numeric.lt(-tolerance).any(axis=1) | numeric.isna().any(axis=1)
        denominator_bad = (
            numeric["inscrits"].le(0)
            | numeric["exprimes"].le(0)
            | numeric["exprimes"].gt(numeric["votants"] + tolerance)
            | numeric["votants"].gt(numeric["inscrits"] + tolerance)
        )
        h0a_bad = (
            (numeric["inscrits"] - numeric["votants"]).lt(-tolerance)
            | numeric["votants"].lt(-tolerance)
            | h0a_closure_gap.abs().gt(tolerance)
        )
        h1_bad = left.lt(-tolerance) | left.gt(numeric["exprimes"] + tolerance) | h1_closure_gap.abs().gt(tolerance)
        negative_social = social.lt(-tolerance).any(axis=1) | social.isna().any(axis=1) | social_total.le(0)
        social_partition_bad = social_gap.fillna(np.inf).abs().gt(tolerance)

        eligible = _eligible_universe_for_election(reference, election.election_id, tolerance)
        balance_sample = eligible.loc[eligible["unit_id"].astype(str).isin(panel_ids)].copy()
        checks = compute_balance_checks(eligible, balance_sample)
        balance = balance_summary(checks, max_smd=max_smd, max_category_gap=max_category_gap)
        observed_ids = set(joined.loc[joined["_election_merge"].eq("both") & joined["_csp_merge"].eq("both"), "unit_id"].astype(str))
        edge = _edge_counts(electoral["unit_id"])
        election_rows.append(
            {
                "election_id": election.election_id,
                "year": election.year,
                "election_type": election.election_type,
                "panel_id": panel_id,
                "expected_panel_rows": 2000,
                "joined_rows": int(len(joined)),
                "join_row_expansion": int(max(len(joined) - len(panel), 0)),
                "missing_election_rows": int(joined["_election_merge"].ne("both").sum()),
                "missing_csp_rows": int(joined["_csp_merge"].ne("both").sum()),
                "unit_set_mismatch_count": int(len(panel_ids.symmetric_difference(observed_ids))),
                "source_duplicate_stable_ids": source_duplicates,
                "source_plm_arm_ids_remaining": edge["plm_arm_count"],
                "source_plm_whole_count": edge["plm_whole_count"],
                "source_corsica_count": edge["corsica_count"],
                "source_overseas_count": edge["overseas_count"],
                "negative_electoral_rows": int(negative_electoral.sum()),
                "denominator_order_anomaly_rows": int(denominator_bad.fillna(True).sum()),
                "h0a_partition_anomaly_rows": int(h0a_bad.fillna(True).sum()),
                "h1_partition_anomaly_rows": int(h1_bad.fillna(True).sum()),
                "negative_social_rows": int(negative_social.sum()),
                "social_partition_anomaly_rows": int(social_partition_bad.sum()),
                "geography_mismatch_rows": int(geography_mismatch.sum()),
                "eligible_universe_rows": int(len(eligible)),
                "balance_panel_rows": int(len(balance_sample)),
                "balance_max_abs_smd": balance["max_abs_smd"],
                "balance_max_abs_category_gap": balance["max_abs_category_gap"],
                "balance_no_empty_category": balance["no_empty_category"],
                "balance_accepted": balance["accepted"],
                "spec_version": SPEC_VERSION,
                "harmonization_version": HARMONIZATION_VERSION,
            }
        )

        source_by_id = joined.set_index(joined["unit_id"].astype(str))
        for scenario_id, denominator_column in (("H0A", "inscrits"), ("H1", "exprimes")):
            scenario = SCENARIO_BY_ID[scenario_id]
            prepared_path = model_ready_path(election, scenario, panel_id, sample_size=2000)
            row: dict[str, object] = {
                "election_id": election.election_id,
                "scenario_id": scenario_id,
                "panel_id": panel_id,
                "model_ready_path": portable_path(prepared_path, root=ROOT),
                "missing_table": int(not prepared_path.exists()),
            }
            if prepared_path.exists():
                prepared = pd.read_parquet(prepared_path)
                prepared["unit_id"] = prepared["unit_id"].astype("string")
                denominator = pd.to_numeric(source_by_id[denominator_column], errors="coerce").round()
                model_checks = _model_ready_integrity(
                    prepared,
                    expected_unit_ids=panel_ids,
                    expected_denominator=denominator,
                    scenario_id=scenario_id,
                )
                row.update(model_checks)
                row["row_count_anomaly"] = int(len(prepared) != 2000)
            else:
                row.update(
                    {
                        "rows": 0,
                        "row_count_anomaly": 1,
                        "duplicate_unit_rows": 0,
                        "missing_expected_units": 2000,
                        "unexpected_units": 0,
                        "denominator_mismatch_rows": 0,
                        "negative_or_nonpositive_rows": 0,
                        "social_closure_anomaly_rows": 0,
                        "vote_closure_anomaly_rows": 0,
                        "social_fraction_anomaly_rows": 0,
                        "max_abs_social_closure_gap": np.nan,
                        "max_abs_vote_closure_gap": np.nan,
                        "max_abs_social_fraction_gap": np.nan,
                    }
                )
            scenario_rows.append(row)

    elections = pd.DataFrame(election_rows).sort_values(["year", "election_type", "election_id"]).reset_index(drop=True)
    scenarios = pd.DataFrame(scenario_rows).sort_values(["scenario_id", "election_id"]).reset_index(drop=True)
    panel_edge = _edge_counts(panel["unit_id"])
    panel_shape_anomalies = {
        "primary_panel_size_anomaly": int(len(panel) != 2000),
        "primary_panel_duplicate_rows": int(panel["unit_id"].duplicated(keep=False).sum()),
        "primary_panel_rank_anomalies": int(
            panel["master_draw_order"].astype(int).tolist() != list(range(1, 2001))
        ),
        "primary_panel_id_cardinality_anomaly": int(len(panel_id_values) != 1),
    }
    critical_anomalies = _critical_anomaly_total(elections, scenarios) + sum(panel_shape_anomalies.values())
    balance_failures = int((~elections["balance_accepted"].astype(bool)).sum())
    status = "pass" if critical_anomalies == 0 and balance_failures == 0 and len(elections) == 26 and len(scenarios) == 52 else "fail"

    INTEGRITY_DIR.mkdir(parents=True, exist_ok=True)
    elections.to_parquet(ELECTION_CHECKS_PATH, index=False)
    scenarios.to_parquet(SCENARIO_CHECKS_PATH, index=False)
    manifest = {
        "schema_version": "panel_2000_integrity_audit_v1",
        "status": status,
        "panel_id": panel_id,
        "panel_path": portable_path(panel_path, root=ROOT),
        "panel_sha256": file_sha256(panel_path),
        "grain_checked": "unit_id × election_id",
        "elections_checked": int(len(elections)),
        "expected_elections": 26,
        "primary_panel_rows": int(len(panel)),
        "expected_primary_panel_rows": 2000,
        "unit_election_rows_checked": int(len(panel) * len(elections)),
        "h0a_h1_tables_checked": int(len(scenarios)),
        "critical_anomaly_count": int(critical_anomalies),
        "balance_failure_count": balance_failures,
        "maximum_balance_abs_smd": float(elections["balance_max_abs_smd"].max()),
        "maximum_balance_abs_category_gap": float(elections["balance_max_abs_category_gap"].max()),
        "balance_thresholds": {"max_abs_smd": max_smd, "max_abs_category_gap": max_category_gap},
        "panel_edge_coverage": panel_edge,
        "panel_geography_source_counts": panel["geography_source"].astype(str).value_counts().to_dict(),
        "panel_shape_anomalies": panel_shape_anomalies,
        "anomaly_totals": {
            "join_row_expansion": int(elections["join_row_expansion"].sum()),
            "missing_election_rows": int(elections["missing_election_rows"].sum()),
            "missing_csp_rows": int(elections["missing_csp_rows"].sum()),
            "unit_set_mismatch_count": int(elections["unit_set_mismatch_count"].sum()),
            "negative_electoral_rows": int(elections["negative_electoral_rows"].sum()),
            "denominator_order_anomaly_rows": int(elections["denominator_order_anomaly_rows"].sum()),
            "h0a_partition_anomaly_rows": int(elections["h0a_partition_anomaly_rows"].sum()),
            "h1_partition_anomaly_rows": int(elections["h1_partition_anomaly_rows"].sum()),
            "negative_social_rows": int(elections["negative_social_rows"].sum()),
            "social_partition_anomaly_rows": int(elections["social_partition_anomaly_rows"].sum()),
            "geography_mismatch_rows": int(elections["geography_mismatch_rows"].sum()),
            "model_ready_anomaly_rows": int(_critical_anomaly_total(elections.assign(**{column: 0 for column in [
                "join_row_expansion", "missing_election_rows", "missing_csp_rows", "unit_set_mismatch_count",
                "negative_electoral_rows", "denominator_order_anomaly_rows", "h0a_partition_anomaly_rows",
                "h1_partition_anomaly_rows", "negative_social_rows", "social_partition_anomaly_rows",
                "geography_mismatch_rows", "source_duplicate_stable_ids", "source_plm_arm_ids_remaining",
            ]}), scenarios)),
        },
        "interpretation": {
            "H0A": "abstention = inscrits - votants, participation = votants, denominator = inscrits",
            "H1": "gauche = voteG + voteCG, complement = exprimes - gauche, denominator = exprimes",
            "social": "ouvriers + employes versus the other four CSP; CSP shares are rescaled to the electoral denominator by largest remainder",
        },
        "documentary_limits": [
            "The audit confirms source column names, numeric domain rules, closures and reproducible code mappings; it does not replace an external official data dictionary certifying the substantive coding of each political block.",
            "CSP counts are not observed on the registered-voter or expressed-vote denominator. Their rescaling is an explicit modeling assumption, not a source-data identity.",
            "The random primary panel contains Corsican communes but no Paris/Lyon/Marseille whole commune and no overseas commune. Their harmonization code paths are checked at source level, but they cannot be empirically rechecked inside this exact 2,000-unit sample.",
        ],
        "outputs": {
            "election_checks": portable_path(ELECTION_CHECKS_PATH, root=ROOT),
            "scenario_checks": portable_path(SCENARIO_CHECKS_PATH, root=ROOT),
        },
        "spec_version": SPEC_VERSION,
        "harmonization_version": HARMONIZATION_VERSION,
    }
    write_json(INTEGRITY_MANIFEST_PATH, manifest)
    return manifest


def main() -> None:
    manifest = audit_panel_2000_integrity()
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if manifest["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()


__all__ = [
    "ELECTION_CHECKS_PATH",
    "INTEGRITY_MANIFEST_PATH",
    "SCENARIO_CHECKS_PATH",
    "audit_panel_2000_integrity",
]
