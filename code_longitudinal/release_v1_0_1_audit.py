from __future__ import annotations

import argparse
import json
import re
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .data_io import (
    _apply_plm_non_additive,
    _stable_unit_id,
    department_from_unit_id,
    load_election,
    load_geography_reference,
    normalize_department,
    read_zip_csv,
    zip_csv_columns,
)
from .paths import RAW_ARCHIVES, ROOT
from .spec_registry import (
    ELECTIONS,
    SCENARIO_BY_ID,
    SCENARIOS,
    VOTE_BLOCKS,
    scenario_is_allowed,
)
from .utils import file_sha256, is_valid_unit_id, largest_remainder_round, normalize_unit_id, plm_parent


RELEASE_ID = "longitudinal_2000_v1.0.1_H0A_H1"
ORIGINAL_ZIP = ROOT / "deliverables" / "longitudinal_2000_v1_H0A_H1_complet_20260816.zip"
ORIGINAL_SHA256 = "ed80a7dfb14653ec0be943c811317c6786651fa8d97e12870f366dde1df74446"
CANDIDATE_DIR = ROOT / "work" / f"{RELEASE_ID}_candidate"
PANEL_PATH = ROOT / "panel" / "longitudinal_2000_v1.parquet"
PANEL_SHA256 = "bde70c71660fce29610d7931461d8db6181dba874514a1866b63cf16a81cec4a"
OLD_PANEL_V2 = ROOT / "panel" / "panel_3000_common_1962_1986_2022_v2.csv"
OLD_PANEL_V2_SHA256 = "d70810a1add048d4823274e182f3adf8735d6f881bd32564a550c78988e8cd3f"
AUDIT_DIR = ROOT / "outputs" / "longitudinal_2000_v1" / "audit"
PRESENCE_PATH = AUDIT_DIR / "election_presence_and_harmonisation.parquet"
RUN_PLAN_PATH = AUDIT_DIR / "longitudinal_run_plan.parquet"
SOURCE_DOC = "Cage-Piketty, Une histoire du conflit politique, annexes methodologiques v1.1.5"
SOURCE_DOC_URL = "https://www.unehistoireduconflitpolitique.fr/"
LOCAL_VARIABLE_DOC = "../documentation_variables_sociales_ie_v2/inventaires/variables_sociales_prudence_ou_contexte.csv"
TOLERANCE = 0.01


def _assert_inputs() -> None:
    if not CANDIDATE_DIR.exists():
        raise FileNotFoundError(f"candidate release is missing: {CANDIDATE_DIR}")
    actual_original = file_sha256(ORIGINAL_ZIP)
    if actual_original != ORIGINAL_SHA256:
        raise AssertionError(f"original ZIP hash changed: {actual_original}")
    if file_sha256(PANEL_PATH) != PANEL_SHA256:
        raise AssertionError("longitudinal panel hash changed")
    if file_sha256(OLD_PANEL_V2) != OLD_PANEL_V2_SHA256:
        raise AssertionError("estimated legacy V2 panel hash changed")


def _out(directory: str, name: str) -> Path:
    path = CANDIDATE_DIR / directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _raw_election(election: Any) -> pd.DataFrame:
    columns = zip_csv_columns(election.archive_name, election.member_name)
    requested = [
        "codecommune",
        "codecommune2",
        "dep",
        "nomdep",
        "nomcommune",
        "inscrits",
        "votants",
        "exprimes",
        *VOTE_BLOCKS,
        *election.rn_columns,
    ]
    return read_zip_csv(
        election.archive_name,
        election.member_name,
        usecols=[column for column in requested if column in columns],
    )


def _substantive_mask(frame: pd.DataFrame) -> pd.Series:
    fields = [
        column
        for column in ("inscrits", "votants", "exprimes", *VOTE_BLOCKS)
        if column in frame
    ]
    if not fields:
        return pd.Series(False, index=frame.index)
    numeric = frame[fields].apply(pd.to_numeric, errors="coerce")
    return numeric.notna().any(axis=1)


def _raw_department(frame: pd.DataFrame) -> pd.Series:
    if "dep" in frame:
        source = frame["dep"].map(normalize_department)
    else:
        source = pd.Series("", index=frame.index, dtype="string")
    raw_id = frame["codecommune"].map(normalize_unit_id)
    fallback = raw_id.map(department_from_unit_id)
    return source.where(source.astype(str).str.len().gt(0), fallback)


def _stable_raw_ids(frame: pd.DataFrame) -> pd.Series:
    ids = _stable_unit_id(frame)
    return ids.map(plm_parent)


def build_department_coverage() -> pd.DataFrame:
    presence = pd.read_parquet(PRESENCE_PATH)
    presence["unit_id"] = presence["unit_id"].astype("string")
    geography = load_geography_reference(2022)[["unit_id", "department"]].copy()
    geography["unit_id"] = geography["unit_id"].astype("string")
    geo_department = geography.set_index("unit_id")["department"]

    strict_flags = presence.groupby("unit_id", sort=False)["panel_core_admissible"].all()
    strict_ids = set(strict_flags.index[strict_flags].astype(str))
    strict = geography.loc[geography["unit_id"].isin(strict_ids)]
    strict_counts = strict.groupby("department")["unit_id"].nunique()

    panel = pd.read_parquet(PANEL_PATH)
    panel["unit_id"] = panel["unit_id"].astype("string")
    master_counts = panel.groupby("department")["unit_id"].nunique()
    primary_counts = panel.loc[panel["included_primary_2000"]].groupby("department")["unit_id"].nunique()
    departments = sorted(set(geography["department"].dropna().astype(str)))

    rows: list[dict[str, Any]] = []
    for election in ELECTIONS:
        raw = _raw_election(election).copy()
        raw["raw_department"] = _raw_department(raw)
        raw["stable_unit_id"] = _stable_raw_ids(raw)
        raw["source_substantive"] = _substantive_mask(raw)
        source_rows = raw.groupby("raw_department").size()
        source_substantive = (
            raw.loc[raw["source_substantive"]]
            .groupby("raw_department")["stable_unit_id"]
            .nunique()
        )
        substantive_ids = set(
            raw.loc[
                raw["source_substantive"] & raw["stable_unit_id"].map(is_valid_unit_id),
                "stable_unit_id",
            ].astype(str)
        )

        harmonized = load_election(election).copy()
        harmonized["unit_id"] = harmonized["unit_id"].astype("string")
        harmonized = harmonized.loc[harmonized["unit_id"].isin(substantive_ids)].copy()
        harmonized["department"] = harmonized["unit_id"].map(geo_department)
        harmonized_counts = harmonized.groupby("department")["unit_id"].nunique()
        numeric = harmonized[["inscrits", "votants", "exprimes"]].apply(pd.to_numeric, errors="coerce")
        valid_margin = (
            numeric.notna().all(axis=1)
            & numeric.ge(0).all(axis=1)
            & numeric["exprimes"].le(numeric["votants"] + TOLERANCE)
            & numeric["votants"].le(numeric["inscrits"] + TOLERANCE)
        )
        margin_counts = harmonized.loc[valid_margin].groupby("department")["unit_id"].nunique()

        election_departments = sorted(
            set(departments)
            | set(source_rows.index.astype(str))
            | set(harmonized_counts.index.dropna().astype(str))
        )
        for department in election_departments:
            n_source_substantive = int(source_substantive.get(department, 0))
            n_harmonized = int(harmonized_counts.get(department, 0))
            n_margin_valid = int(margin_counts.get(department, 0))
            n_strict = int(strict_counts.get(department, 0))
            n_master = int(master_counts.get(department, 0))
            n_primary = int(primary_counts.get(department, 0))
            if election.election_id == "pre_1988_r1" and department == "54":
                reason = "official_1988_source_has_589_code_only_rows;54602_fails_csp_total_non_positive"
            elif n_source_substantive == 0:
                reason = "no_substantive_source_rows"
            elif n_harmonized < n_source_substantive:
                reason = "loss_during_stable_id_harmonisation"
            elif n_margin_valid < n_harmonized:
                reason = "invalid_or_missing_electoral_margins"
            elif n_strict == 0:
                reason = "excluded_from_26_election_strict_intersection"
            elif n_primary == 0:
                reason = "eligible_but_not_selected_in_panel"
            else:
                reason = "retained"
            rows.append(
                {
                    "election_id": election.election_id,
                    "year": election.year,
                    "election_type": election.election_type,
                    "department": department,
                    "n_source_rows": int(source_rows.get(department, 0)),
                    "n_source_substantive": n_source_substantive,
                    "n_harmonized": n_harmonized,
                    "n_margin_valid": n_margin_valid,
                    "n_strict_universe": n_strict,
                    "n_master_3000": n_master,
                    "n_panel_2000": n_primary,
                    "harmonization_rate": n_harmonized / n_source_substantive if n_source_substantive else np.nan,
                    "margin_valid_rate": n_margin_valid / n_harmonized if n_harmonized else np.nan,
                    "panel_rate_from_strict": n_primary / n_strict if n_strict else np.nan,
                    "main_loss_reason": reason,
                }
            )
    result = pd.DataFrame(rows).sort_values(["election_id", "department"])
    result.to_csv(_out("03_panel_et_audit", "coverage_by_election_department.csv"), index=False, encoding="utf-8-sig")
    return result


def build_department54_evidence() -> pd.DataFrame:
    election = next(item for item in ELECTIONS if item.election_id == "pre_1988_r1")
    raw = _raw_election(election).copy()
    raw_code = raw["codecommune"].map(normalize_unit_id)
    part = raw.loc[raw_code.str.startswith("54")].copy()
    part.insert(0, "source_archive", election.archive_name)
    part.insert(1, "source_member", "pres1988_csv/pres1988comm.csv")
    part.insert(2, "source_archive_sha256", file_sha256(RAW_ARCHIVES / election.archive_name))
    part.insert(3, "retrieval_date", date.today().isoformat())
    part.insert(4, "columns_verified", "inscrits;votants;exprimes;voteG;voteCG;voteC;voteCD;voteD")
    part["source_substantive"] = _substantive_mask(part)
    part["stable_unit_id"] = _stable_raw_ids(part)
    part["strict_exclusion_reason"] = np.where(
        part["stable_unit_id"].astype(str).eq("54602"),
        "csp_total_non_positive",
        "no_substantive_electoral_result",
    )
    if len(part) != 590 or int(part["source_substantive"].sum()) != 1:
        raise AssertionError("unexpected department 54 evidence counts")
    part.to_csv(_out("03_panel_et_audit", "department54_pre1988_rows.csv"), index=False, encoding="utf-8-sig")
    return part


def build_rxc_audit() -> pd.DataFrame:
    run_plan = pd.read_parquet(RUN_PLAN_PATH)
    blocked = run_plan.loc[
        run_plan["scenario_id"].isin(["RXC1", "RXC2"])
        & run_plan["preparation_status"].eq("ineligible")
    ].copy()
    panel = pd.read_parquet(PANEL_PATH)
    panel["unit_id"] = panel["unit_id"].astype("string")
    primary = set(panel.loc[panel["included_primary_2000"], "unit_id"].astype(str))
    master = set(panel["unit_id"].astype(str))
    rows: list[dict[str, Any]] = []
    for election_id, election_rows in blocked.groupby("election_id"):
        election = next(item for item in ELECTIONS if item.election_id == election_id)
        electoral = load_election(election).copy()
        electoral["unit_id"] = electoral["unit_id"].astype("string")
        gap = electoral[list(VOTE_BLOCKS)].sum(axis=1) - electoral["exprimes"]
        offenders = electoral.loc[gap.abs().gt(TOLERANCE), ["unit_id", "exprimes", *VOTE_BLOCKS]].copy()
        offenders["absolute_source_gap"] = gap.loc[offenders.index].abs().to_numpy()
        panel_rows = electoral.loc[electoral["unit_id"].isin(primary)].copy()
        panel_gap = panel_rows[list(VOTE_BLOCKS)].sum(axis=1) - panel_rows["exprimes"]
        raw_panel_pass = bool(panel_gap.abs().le(TOLERANCE).all())
        exact_closed = True
        for _, row in panel_rows.iterrows():
            denominator = int(round(float(row["exprimes"])))
            rounded = largest_remainder_round(row[list(VOTE_BLOCKS)].astype(float).to_numpy(), denominator)
            if int(rounded.sum()) != denominator:
                exact_closed = False
                break
        for scenario_id in election_rows["scenario_id"].astype(str):
            for offender in offenders.to_dict("records"):
                rows.append(
                    {
                        "election_id": election_id,
                        "scenario_id": scenario_id,
                        "unit_id": offender["unit_id"],
                        "exprimes": offender["exprimes"],
                        **{column: offender[column] for column in VOTE_BLOCKS},
                        "absolute_source_gap": offender["absolute_source_gap"],
                        "tolerance_absolute_counts": TOLERANCE,
                        "in_master_3000": offender["unit_id"] in master,
                        "in_panel_2000": offender["unit_id"] in primary,
                        "panel_max_absolute_raw_gap": float(panel_gap.abs().max()) if len(panel_gap) else 0.0,
                        "panel_raw_closure_within_tolerance": raw_panel_pass,
                        "panel_model_ready_exact_closure": exact_closed,
                        "mapping_status": "no_mapping_error_detected",
                        "panel_scope_assessment": "potentially_admissible" if raw_panel_pass and exact_closed else "ineligible",
                        "execution_status": "deferred_to_v1.1",
                    }
                )
    result = pd.DataFrame(rows).sort_values(["election_id", "scenario_id", "unit_id"])
    if result[["election_id", "scenario_id"]].drop_duplicates().shape[0] != 22:
        raise AssertionError("RxC audit does not cover exactly 22 pairs")
    if result["in_panel_2000"].any() or result["in_master_3000"].any():
        raise AssertionError("an RxC source offender unexpectedly belongs to a panel")
    result.to_csv(_out("03_panel_et_audit", "rxc_ineligible_audit.csv"), index=False, encoding="utf-8-sig")
    return result


def _political_formula(scenario: Any, election: Any) -> tuple[str, str]:
    if scenario.vote_definition == "abstention":
        return "abstention=inscrits-votants", "participation=votants"
    if scenario.vote_definition == "left":
        return "gauche=voteG+voteCG", "non_gauche=exprimes-gauche"
    if scenario.vote_definition == "right":
        return "droite=voteCD+voteD", "reste=exprimes-droite"
    if scenario.vote_definition == "centre":
        return "centre=voteC", "non_centre=exprimes-centre"
    if scenario.vote_definition == "rn":
        source = "+".join(election.rn_columns)
        return f"fn_rn={source}", "non_fn_rn=exprimes-fn_rn"
    return "cinq_blocs=voteG+voteCG+voteC+voteCD+voteD", "somme_cinq_blocs=exprimes"


def build_political_harmonisation() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for election in ELECTIONS:
        for scenario in SCENARIOS:
            if not scenario_is_allowed(scenario, election):
                continue
            formula, complement = _political_formula(scenario, election)
            rows.append(
                {
                    "election_id": election.election_id,
                    "scenario_id": scenario.scenario_id,
                    "model_family": scenario.model_family,
                    "source_columns": ";".join(("inscrits", "votants") if scenario.vote_definition == "abstention" else ("exprimes", *VOTE_BLOCKS)),
                    "target_formula": formula,
                    "complement_formula": complement,
                    "denominator": scenario.denominator,
                    "closure_tolerance_absolute_counts": TOLERANCE,
                    "admissible_methods": ";".join(scenario.models),
                    "harmonization_version": "stable_unit_geography_v1.0.1",
                    "comment": "Binary complements are constructed from the documented electoral denominator; RxC execution remains deferred in v1.0.1.",
                }
            )
    result = pd.DataFrame(rows).sort_values(["election_id", "scenario_id"])
    if len(result) != 292:
        raise AssertionError(f"expected 292 harmonisation rows, got {len(result)}")
    result.to_csv(_out("03_panel_et_audit", "HARMONISATION_POLITIQUE.csv"), index=False, encoding="utf-8-sig")
    return result


def build_covariate_provenance() -> pd.DataFrame:
    mappings = {
        "vbbm": ("socio_agl_csv.zip", "popcommunesvbbm.csv", "vbbm", "categorical_1_4"),
        "revenue": ("socio_rev_csv.zip", "revcommunes.csv", "revratio", "source_ratio"),
        "capital": ("socio_cap_csv.zip", "capitalimmobiliercommunes.csv", "capitalratio", "source_ratio"),
        "foreign_share": ("socio_nat_csv.zip", "etrangerscommunes.csv", "petranger", "fraction_0_1"),
    }
    rows: list[dict[str, Any]] = []
    for election in ELECTIONS:
        for variable, (archive, member, prefix, unit) in mappings.items():
            candidates = [f"{prefix}{election.year}"]
            if variable == "revenue":
                candidates.append(f"revmoy{election.year}")
            if variable == "capital":
                candidates.append(f"capitalimmo{election.year}")
            available = set(zip_csv_columns(archive, member))
            selected = next((column for column in candidates if column in available), "")
            match = re.search(r"(\d{4})$", selected)
            reference_year = int(match.group(1)) if match else np.nan
            rows.append(
                {
                    "election_id": election.election_id,
                    "variable": variable,
                    "source_archive": archive,
                    "source_member": member,
                    "source_column": selected,
                    "reference_year": reference_year,
                    "status": "unknown",
                    "documentation_source": LOCAL_VARIABLE_DOC if variable == "foreign_share" else SOURCE_DOC,
                    "documentation_url": "" if variable == "foreign_share" else SOURCE_DOC_URL,
                    "unit": unit,
                    "normalization": "validate_range_then_keep" if variable == "foreign_share" else "none",
                    "comment": (
                        "petranger is verified against etranger/(etranger+francais); peretranger is a distinct transformed series whose formula is undocumented locally and is excluded without assigning it a percentile interpretation"
                        if variable == "foreign_share"
                        else "No observed/reconstructed/interpolated status assigned without column-year documentary evidence"
                    ),
                }
            )
    result = pd.DataFrame(rows).sort_values(["election_id", "variable"])
    if result["source_column"].eq("").any():
        missing = result.loc[result["source_column"].eq(""), ["election_id", "variable"]].to_dict("records")
        raise AssertionError(f"missing covariate source columns: {missing}")
    result.to_csv(_out("03_panel_et_audit", "COVARIATE_PROVENANCE.csv"), index=False, encoding="utf-8-sig")
    return result


def build_foreign_share_source_validation() -> pd.DataFrame:
    years = sorted({election.year for election in ELECTIONS})
    columns = [
        "codecommune",
        *[name for year in years for name in (
            f"etranger{year}", f"francais{year}", f"petranger{year}", f"peretranger{year}"
        )],
    ]
    raw = read_zip_csv("socio_nat_csv.zip", "etrangerscommunes.csv", usecols=columns)
    rows: list[dict[str, Any]] = []
    for year in years:
        foreign = pd.to_numeric(raw[f"etranger{year}"], errors="coerce")
        french = pd.to_numeric(raw[f"francais{year}"], errors="coerce")
        share = pd.to_numeric(raw[f"petranger{year}"], errors="coerce")
        transformed = pd.to_numeric(raw[f"peretranger{year}"], errors="coerce")
        denominator = foreign + french
        valid = foreign.notna() & french.notna() & share.notna() & denominator.gt(0)
        expected = foreign.loc[valid] / denominator.loc[valid]
        difference = (share.loc[valid] - expected).abs()
        maximum = float(difference.max()) if len(difference) else np.nan
        rows.append(
            {
                "reference_year": year,
                "source_archive": "socio_nat_csv.zip",
                "source_member": "etrangerscommunes.csv",
                "foreign_count_column": f"etranger{year}",
                "french_count_column": f"francais{year}",
                "canonical_share_column": f"petranger{year}",
                "excluded_transformed_column": f"peretranger{year}",
                "n_formula_rows": int(valid.sum()),
                "max_abs_petranger_minus_count_ratio": maximum,
                "formula_identity_tolerance": 1e-6,
                "formula_identity_pass": bool(np.isfinite(maximum) and maximum <= 1e-6),
                "petranger_min": float(share.min(skipna=True)),
                "petranger_max": float(share.max(skipna=True)),
                "peretranger_min": float(transformed.min(skipna=True)),
                "peretranger_max": float(transformed.max(skipna=True)),
                "peretranger_documentary_status": "unknown",
                "peretranger_exclusion_reason": "unknown_transformation_not_labeled_percentile",
                "documentation_source": LOCAL_VARIABLE_DOC,
                "documentation_note": "Local catalogue says the exact formula must be recovered before interpretation; no percentile claim is made.",
            }
        )
    result = pd.DataFrame(rows)
    if not result["formula_identity_pass"].all():
        raise AssertionError("petranger does not reproduce etranger/(etranger+francais) within tolerance")
    result.to_csv(_out("03_panel_et_audit", "foreign_share_source_validation.csv"), index=False, encoding="utf-8-sig")
    return result


def _foreign_share_by_year() -> dict[int, pd.DataFrame]:
    years = sorted({election.year for election in ELECTIONS})
    columns = ["codecommune", *[f"petranger{year}" for year in years]]
    raw = read_zip_csv("socio_nat_csv.zip", "etrangerscommunes.csv", usecols=columns)
    raw["unit_id"] = raw["codecommune"].map(normalize_unit_id)
    result: dict[int, pd.DataFrame] = {}
    for year in years:
        column = f"petranger{year}"
        values = pd.to_numeric(raw[column], errors="coerce")
        finite = values.dropna()
        if not finite.empty and float(finite.min()) < 0:
            raise AssertionError(f"{column}: negative values")
        maximum = float(finite.max()) if not finite.empty else 0.0
        if maximum <= 1.0 + 1e-12:
            normalized = values
        elif maximum <= 100.0 + 1e-12:
            normalized = values / 100.0
        else:
            raise ValueError(f"{column}: unrecognized_unit")
        temp = pd.DataFrame({"unit_id": raw["unit_id"], "foreign_share": normalized})
        harmonized = _apply_plm_non_additive(temp, value_column="foreign_share", mode="mean")
        if not harmonized["foreign_share"].dropna().between(0, 1).all():
            raise AssertionError(f"{column}: normalized values outside [0, 1]")
        result[year] = harmonized
    return result


def rebuild_commune_metadata(provenance: pd.DataFrame) -> pd.DataFrame:
    path = _out("01_resultats_python", "longitudinal_krt_commune.parquet")
    commune = pd.read_parquet(path)
    if len(commune) != 104000:
        raise AssertionError("unexpected KRT commune row count before metadata rebuild")
    drop = [
        column
        for column in commune.columns
        if column.startswith("immigrant_share")
        or column in {
            "foreign_share",
            "foreign_share_reference_year",
            "foreign_share_status",
            "foreign_share_source_column",
            "vbbm_status",
            "vbbm_source_column",
            "revenue_status",
            "revenue_source_column",
            "capital_status",
            "capital_source_column",
        }
    ]
    commune = commune.drop(columns=drop, errors="ignore")
    foreign = _foreign_share_by_year()
    parts: list[pd.DataFrame] = []
    for election_id, part in commune.groupby("election_id", sort=False):
        year = int(part["year"].iloc[0])
        part = part.merge(foreign[year], on="unit_id", how="left", validate="many_to_one")
        source_rows = provenance.loc[provenance["election_id"].eq(election_id)].set_index("variable")
        for variable in ("vbbm", "revenue", "capital", "foreign_share"):
            row = source_rows.loc[variable]
            present = part[variable].notna()
            part[f"{variable}_reference_year"] = np.where(present, int(row["reference_year"]), np.nan)
            part[f"{variable}_status"] = np.where(present, str(row["status"]), "unknown")
            part[f"{variable}_source_column"] = np.where(present, str(row["source_column"]), "")
        parts.append(part)
    result = pd.concat(parts, ignore_index=True)
    uncertainty = [
        "b1_sd", "b1_q025", "b1_q50", "b1_q975",
        "b2_sd", "b2_q025", "b2_q50", "b2_q975",
    ]
    if result[uncertainty].isna().any().any():
        raise AssertionError("communal uncertainty fields were lost")
    if not result["foreign_share"].dropna().between(0, 1).all():
        raise AssertionError("foreign_share is outside [0, 1]")
    result.to_parquet(path, index=False)
    return result


def build_canonical_selection() -> pd.DataFrame:
    aggregate = pd.read_parquet(_out("01_resultats_python", "longitudinal_krt_aggregate.parquet"))
    selection = aggregate.loc[aggregate["scenario_id"].isin(["H0A", "H1"]), [
        "election_id", "scenario_id", "run_id", "panel_id", "model_key", "mcmc_status", "identification_status"
    ]].drop_duplicates()
    if len(selection) != 52 or selection[["election_id", "scenario_id"]].duplicated().any():
        raise AssertionError("canonical KRT selection must contain exactly 52 pairs")
    selection["run_role"] = "canonical"
    selection["selected_reason"] = "v1.0_canonical_pending_v1.0.1_targeted_rule"
    selection["replaces_run_id"] = ""
    selection["selection_rule_version"] = "canonical_selection_v1.0.1"
    selection = selection.sort_values(["scenario_id", "election_id"])
    selection.to_csv(_out("02_syntheses", "canonical_run_selection.csv"), index=False, encoding="utf-8-sig")
    return selection


def _definition(column: str) -> str:
    definitions = {
        "panel_id": "Identifiant versionne du panel communal.",
        "election_id": "Identifiant stable du scrutin et du tour.",
        "scenario_id": "Identifiant de l'hypothese politique et sociale.",
        "run_id": "Identifiant immuable du run statistique.",
        "unit_id": "Code communal harmonise utilise pour les jointures.",
        "foreign_share": "Part des residents etrangers, issue de petrangerYYYY et normalisee dans [0,1].",
        "mcmc_status": "Diagnostic numerique de convergence MCMC: pass, caveat ou fail.",
        "identification_status": "Diagnostic distinct d'identification ecologique.",
        "b1_mean": "Moyenne posterieure communale de beta1.",
        "b2_mean": "Moyenne posterieure communale de beta2.",
        "estimate_stability_status": "Stabilite des estimations entre run initial et relance ciblee, distincte de la convergence et de l'identification.",
        "execution_status": "Statut d'execution du couple dans le perimetre de release.",
        "fit_status": "Statut d'execution numerique du solveur ou de l'echantillonneur.",
        "diagnostic_status": "Synthese diagnostique historique; utiliser les dimensions MCMC et identification lorsqu'elles sont disponibles.",
    }
    if column in definitions:
        return definitions[column]
    if column.endswith("_reference_year"):
        return "Annee extraite du suffixe de la colonne source effectivement utilisee."
    if column in {"vbbm_status", "revenue_status", "capital_status", "foreign_share_status"}:
        return "Statut documentaire: observed, reconstructed, interpolated ou unknown."
    if column.endswith("_status"):
        return "Statut propre au controle indique par le nom du champ; voir la table et le rapport."
    if column.endswith("_source_column"):
        return "Nom exact de la colonne de la source brute."
    if column.endswith(("_q025", "_q50", "_q975")):
        return "Quantile de la distribution posterieure communale."
    if column.endswith("_sd"):
        return "Ecart-type posterieur communal."
    return "Champ technique documente par son nom et son type; voir le rapport pour le contexte analytique."


def build_data_dictionary(extra_paths: list[Path]) -> pd.DataFrame:
    sources = [
        _out("01_resultats_python", "longitudinal_krt_commune.parquet"),
        _out("01_resultats_python", "longitudinal_krt_aggregate.parquet"),
        _out("01_resultats_python", "longitudinal_nls.parquet"),
        *extra_paths,
    ]
    rows: list[dict[str, Any]] = []
    for path in sources:
        frame = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path, nrows=1000)
        for column in frame.columns:
            rows.append(
                {
                    "table": path.name,
                    "field": column,
                    "dtype": str(frame[column].dtype),
                    "definition": _definition(column),
                    "unit_or_scale": "fraction_0_1" if column == "foreign_share" else "see_definition",
                    "nullable": bool(frame[column].isna().any()),
                    "key_role": "public_key" if column in {"panel_id", "election_id", "scenario_id", "run_id", "unit_id"} else "",
                    "provenance_rule": "source-backed" if any(token in column for token in ("reference_year", "source_column", "status", "foreign_share")) else "derived_or_model_output",
                }
            )
    result = pd.DataFrame(rows).drop_duplicates(["table", "field"]).sort_values(["table", "field"])
    result.to_csv(_out("03_panel_et_audit", "DATA_DICTIONARY.csv"), index=False, encoding="utf-8-sig")
    return result


def write_release_configuration() -> None:
    settings = json.loads((ROOT / "config" / "run_settings.json").read_text(encoding="utf-8"))
    payload = {
        "release_id": RELEASE_ID,
        "ready": False,
        "ready_scope": "H0A-H1",
        "panel_seed": settings["panel"]["panel_seed"],
        "primary_panel_size": settings["panel"]["primary_panel_size"],
        "master_panel_size": settings["panel"]["master_panel_size"],
        "nls_seed": settings["nls"]["random_seed"],
        "mcmc_original_seed": settings["mcmc"]["original_seed"],
        "mcmc_rerun_seed": settings["mcmc"]["rerun_seed"],
        "legacy_estimated_panel_v2_sha256": OLD_PANEL_V2_SHA256,
        "panel_sha256": PANEL_SHA256,
        "runtime_root": "parent_repository",
        "runtime_path": "outputs",
        "delivery_path": ".",
        "delivery_included": True,
        "external_required": True,
        "external_requirement": "Full reproduction requires the parent repository and raw source archives.",
        "historical_only": settings["historical_only"],
    }
    _out("05_methodologie_et_code", "release_configuration_v1.0.1.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build v1.0.1 audit and metadata artifacts without refitting KRT models.")
    parser.parse_args()
    _assert_inputs()
    coverage = build_department_coverage()
    department54 = build_department54_evidence()
    rxc = build_rxc_audit()
    political = build_political_harmonisation()
    foreign_validation = build_foreign_share_source_validation()
    provenance = build_covariate_provenance()
    commune = rebuild_commune_metadata(provenance)
    canonical = build_canonical_selection()
    write_release_configuration()
    dictionary = build_data_dictionary([
        _out("03_panel_et_audit", "coverage_by_election_department.csv"),
        _out("03_panel_et_audit", "COVARIATE_PROVENANCE.csv"),
        _out("03_panel_et_audit", "HARMONISATION_POLITIQUE.csv"),
        _out("03_panel_et_audit", "rxc_ineligible_audit.csv"),
        _out("03_panel_et_audit", "foreign_share_source_validation.csv"),
    ])
    summary = {
        "release_id": RELEASE_ID,
        "original_zip_sha256": file_sha256(ORIGINAL_ZIP),
        "panel_sha256": file_sha256(PANEL_PATH),
        "legacy_panel_v2_sha256": file_sha256(OLD_PANEL_V2),
        "coverage_rows": len(coverage),
        "department54_rows": len(department54),
        "rxc_pairs_audited": rxc[["election_id", "scenario_id"]].drop_duplicates().shape[0],
        "political_harmonisation_rows": len(political),
        "covariate_provenance_rows": len(provenance),
        "foreign_share_validation_years": len(foreign_validation),
        "commune_rows": len(commune),
        "canonical_krt_pairs": len(canonical),
        "dictionary_rows": len(dictionary),
        "status": "candidate",
    }
    _out("03_panel_et_audit", "audit_v1.0.1_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
