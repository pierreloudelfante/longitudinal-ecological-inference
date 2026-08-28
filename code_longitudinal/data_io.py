from __future__ import annotations

import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .paths import RAW_ARCHIVES
from .spec_registry import CSP_GROUPS, ELECTIONS, ElectionSpec, VOTE_BLOCKS
from .utils import PLM_ARM_TO_WHOLE, PLM_WHOLE, apply_plm_whole, is_valid_unit_id, normalize_unit_id, plm_parent


REGION_DEPARTMENTS = {
    "01_guadeloupe": {"971"},
    "02_martinique": {"972"},
    "03_guyane": {"973"},
    "04_la_reunion": {"974"},
    "06_mayotte": {"976"},
    "11_ile_de_france": {"75", "77", "78", "91", "92", "93", "94", "95"},
    "24_centre_val_de_loire": {"18", "28", "36", "37", "41", "45"},
    "27_bourgogne_franche_comte": {"21", "25", "39", "58", "70", "71", "89", "90"},
    "28_normandie": {"14", "27", "50", "61", "76"},
    "32_hauts_de_france": {"02", "59", "60", "62", "80"},
    "44_grand_est": {"08", "10", "51", "52", "54", "55", "57", "67", "68", "88"},
    "52_pays_de_la_loire": {"44", "49", "53", "72", "85"},
    "53_bretagne": {"22", "29", "35", "56"},
    "75_nouvelle_aquitaine": {"16", "17", "19", "23", "24", "33", "40", "47", "64", "79", "86", "87"},
    "76_occitanie": {"09", "11", "12", "30", "31", "32", "34", "46", "48", "65", "66", "81", "82"},
    "84_auvergne_rhone_alpes": {"01", "03", "07", "15", "26", "38", "42", "43", "63", "69", "73", "74"},
    "93_provence_alpes_cote_azur": {"04", "05", "06", "13", "83", "84"},
    "94_corse": {"2A", "2B"},
}
DEPARTMENT_TO_REGION = {department: region for region, departments in REGION_DEPARTMENTS.items() for department in departments}
COUNT_INTEGER_TOLERANCE = 1e-4


def normalize_department(value: object) -> str:
    """Normalize a department code while preserving Corsica and overseas codes."""
    if pd.isna(value):
        return ""
    text = str(value).strip().upper()
    if text.endswith(".0"):
        text = text[:-2]
    if text in {"2A", "2B"}:
        return text
    if text.isdigit():
        return text.zfill(2) if len(text) <= 2 else text.zfill(3)
    return text


def department_from_unit_id(value: object) -> str:
    """Fallback parser used only when a geographic reference is unavailable."""
    unit_id = normalize_unit_id(value)
    if unit_id.startswith(("2A", "2B")):
        return unit_id[:2]
    if unit_id.startswith(("97", "98")):
        return unit_id[:3]
    return unit_id[:2]


def region_from_unit_id(value: object) -> str | None:
    return DEPARTMENT_TO_REGION.get(department_from_unit_id(value))


def _apply_plm_non_additive(df: pd.DataFrame, *, value_column: str, mode: str) -> pd.DataFrame:
    """Aggregate PLM attributes without incorrectly summing ratios/categories."""
    out = df[["unit_id", value_column]].copy()
    out["unit_id"] = out["unit_id"].map(normalize_unit_id)
    parents = out["unit_id"].map(plm_parent)
    whole_present = set(out.loc[out["unit_id"].isin(PLM_WHOLE), "unit_id"])
    drop_arm = out["unit_id"].isin(PLM_ARM_TO_WHOLE) & parents.isin(whole_present)
    out = out.loc[~drop_arm].copy()
    out["unit_id"] = out["unit_id"].map(plm_parent)
    if mode == "mode":
        aggregate = lambda values: values.mode().iloc[0] if not values.mode().empty else values.iloc[0]
    elif mode == "mean":
        aggregate = "mean"
    else:  # pragma: no cover - internal callers use the two declared modes
        raise ValueError(f"unknown non-additive PLM aggregation mode: {mode}")
    return out.groupby("unit_id", as_index=False).agg({value_column: aggregate})


def _archive_member(archive: Path, member_name: str) -> str:
    with zipfile.ZipFile(archive) as zipped:
        matches = [
            name
            for name in zipped.namelist()
            if "__MACOSX" not in name and Path(name).name.casefold() == member_name.casefold()
        ]
    if len(matches) != 1:
        raise FileNotFoundError(f"expected one {member_name!r} in {archive}, found {matches}")
    return matches[0]


def read_zip_csv(
    archive_name: str,
    member_name: str,
    *,
    usecols: Iterable[str] | None = None,
) -> pd.DataFrame:
    archive = RAW_ARCHIVES / archive_name
    if not archive.exists():
        raise FileNotFoundError(archive)
    member = _archive_member(archive, member_name)
    with zipfile.ZipFile(archive) as zipped, zipped.open(member) as handle:
        return pd.read_csv(handle, usecols=usecols, low_memory=False)


def zip_csv_columns(archive_name: str, member_name: str) -> list[str]:
    archive = RAW_ARCHIVES / archive_name
    member = _archive_member(archive, member_name)
    with zipfile.ZipFile(archive) as zipped, zipped.open(member) as handle:
        return pd.read_csv(handle, nrows=0).columns.astype(str).tolist()


def _stable_unit_id(df: pd.DataFrame) -> pd.Series:
    base = df["codecommune"].map(normalize_unit_id)
    if "codecommune2" not in df:
        return base
    mapped = df["codecommune2"].map(normalize_unit_id)
    return mapped.where(mapped.map(is_valid_unit_id), base)


def _canonicalize_near_integer_counts(df: pd.DataFrame) -> pd.DataFrame:
    """Remove harmless float32 residue from source electoral count totals."""
    result = df.copy()
    for column in ("inscrits", "votants", "exprimes"):
        values = pd.to_numeric(result[column], errors="coerce")
        rounded = values.round()
        near_integer = values.notna() & values.sub(rounded).abs().le(COUNT_INTEGER_TOLERANCE)
        result.loc[near_integer, column] = rounded.loc[near_integer]
    return result


@lru_cache(maxsize=None)
def load_election(spec: ElectionSpec) -> pd.DataFrame:
    columns = zip_csv_columns(spec.archive_name, spec.member_name)
    requested = [
        "codecommune",
        "codecommune2",
        "dep",
        "nomcommune",
        "inscrits",
        "votants",
        "exprimes",
        *VOTE_BLOCKS,
        *spec.rn_columns,
    ]
    usecols = [column for column in requested if column in columns]
    required = {"codecommune", "inscrits", "votants", "exprimes", *VOTE_BLOCKS}
    missing = required.difference(usecols)
    if missing:
        raise ValueError(f"{spec.election_id}: missing electoral columns {sorted(missing)}")
    df = read_zip_csv(spec.archive_name, spec.member_name, usecols=usecols)
    raw_rows = int(len(df))
    raw_ids = df["codecommune"].map(normalize_unit_id)
    raw_valid_ids = raw_ids.map(is_valid_unit_id)
    raw_duplicate_ids = int(raw_ids.loc[raw_valid_ids].duplicated(keep=False).sum())
    df["unit_id"] = _stable_unit_id(df)
    numeric = ["inscrits", "votants", "exprimes", *VOTE_BLOCKS, *spec.rn_columns]
    for column in numeric:
        if column in df:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.loc[df["unit_id"].map(is_valid_unit_id)].copy()
    df = apply_plm_whole(df, unit_col="unit_id")
    df = _canonicalize_near_integer_counts(df)
    if df["unit_id"].duplicated().any():
        duplicates = df.loc[df["unit_id"].duplicated(), "unit_id"].head(10).tolist()
        raise ValueError(f"{spec.election_id}: duplicate stable unit ids {duplicates}")
    df.attrs.update(
        {
            "source_rows": raw_rows,
            "source_valid_raw_ids": int(raw_valid_ids.sum()),
            "source_duplicate_raw_ids": raw_duplicate_ids,
        }
    )
    return df


@lru_cache(maxsize=None)
def load_csp(year: int) -> pd.DataFrame:
    columns = ["codecommune", "dep", "nomcommune", *[f"{group}{year}" for group in CSP_GROUPS]]
    df = read_zip_csv("socio_csp_csv.zip", "cspcommunes.csv", usecols=columns)
    df["unit_id"] = df["codecommune"].map(normalize_unit_id)
    renames = {f"{group}{year}": group for group in CSP_GROUPS}
    df = df.rename(columns=renames)
    for group in CSP_GROUPS:
        df[group] = pd.to_numeric(df[group], errors="coerce")
    df = df.loc[df["unit_id"].map(is_valid_unit_id), ["unit_id", "dep", "nomcommune", *CSP_GROUPS]].copy()
    return apply_plm_whole(df, unit_col="unit_id")


@lru_cache(maxsize=None)
def load_geography_reference(reference_year: int = 2022) -> pd.DataFrame:
    """Build the canonical stable-id geography from source reference fields.

    Department and region are source-backed attributes.  Parsing ``unit_id``
    is retained only as an explicit fallback for records whose source
    department is absent.
    """
    csp = load_csp(reference_year)[["unit_id", "dep", "nomcommune"]].copy()
    csp = csp.rename(columns={"dep": "department_csp", "nomcommune": "commune_name_csp"})
    election_candidates = [item for item in ELECTIONS if item.year == reference_year]
    electoral_frames: list[pd.DataFrame] = []
    for election in election_candidates:
        electoral = load_election(election)
        columns = [column for column in ("unit_id", "dep", "nomcommune") if column in electoral]
        if "unit_id" not in columns:
            continue
        part = electoral[columns].copy()
        part = part.rename(columns={"dep": "department_election", "nomcommune": "commune_name_election"})
        electoral_frames.append(part)
    if electoral_frames:
        electoral = pd.concat(electoral_frames, ignore_index=True).drop_duplicates("unit_id", keep="first")
        out = csp.merge(electoral, on="unit_id", how="outer", validate="one_to_one")
    else:
        out = csp
        out["department_election"] = ""
        out["commune_name_election"] = ""
    source_department = out["department_csp"].map(normalize_department)
    election_department = out["department_election"].map(normalize_department)
    out["department"] = source_department.where(source_department.ne(""), election_department)
    fallback = out["unit_id"].map(department_from_unit_id)
    out["geography_source"] = np.where(out["department"].ne(""), "source_reference", "unit_id_fallback")
    out["department"] = out["department"].where(out["department"].ne(""), fallback)
    csp_name = out["commune_name_csp"].fillna("").astype(str).str.strip()
    election_name = out["commune_name_election"].fillna("").astype(str).str.strip()
    out["commune_name"] = csp_name.where(csp_name.ne(""), election_name)
    out["region13"] = out["department"].map(DEPARTMENT_TO_REGION)
    return out[["unit_id", "department", "region13", "commune_name", "geography_source"]].sort_values("unit_id").reset_index(drop=True)


@lru_cache(maxsize=None)
def load_vbbm(year: int) -> pd.DataFrame:
    column = f"vbbm{year}"
    available = zip_csv_columns("socio_agl_csv.zip", "popcommunesvbbm.csv")
    if column not in available:
        raise ValueError(f"VBBM unavailable for {year}")
    df = read_zip_csv("socio_agl_csv.zip", "popcommunesvbbm.csv", usecols=["codecommune", column])
    df["unit_id"] = df["codecommune"].map(normalize_unit_id)
    df["vbbm"] = pd.to_numeric(df[column], errors="coerce")
    out = _apply_plm_non_additive(df[["unit_id", "vbbm"]], value_column="vbbm", mode="mode")
    out["vbbm_reference_year"] = year
    out["vbbm_source_column"] = column
    out["vbbm_status"] = "unknown"
    return out


def _load_optional_year_value(
    archive: str,
    member: str,
    candidates: Iterable[str],
    output: str,
    *,
    reference_year: int,
    normalize_share: bool = False,
) -> pd.DataFrame:
    available = zip_csv_columns(archive, member)
    selected = next((column for column in candidates if column in available), None)
    if selected is None:
        return pd.DataFrame(
            columns=[
                "unit_id",
                output,
                f"{output}_reference_year",
                f"{output}_source_column",
                f"{output}_status",
            ]
        )
    df = read_zip_csv(archive, member, usecols=["codecommune", selected])
    df["unit_id"] = df["codecommune"].map(normalize_unit_id)
    df[output] = pd.to_numeric(df[selected], errors="coerce")
    if normalize_share:
        finite = df[output].dropna()
        if not finite.empty and float(finite.min()) < 0:
            raise ValueError(f"{selected}: negative share values")
        maximum = float(finite.max()) if not finite.empty else 0.0
        if maximum <= 1.0 + 1e-12:
            normalization = "fraction_0_1"
        elif maximum <= 100.0 + 1e-12:
            df[output] = df[output] / 100.0
            normalization = "percent_divided_by_100"
        else:
            raise ValueError(f"{selected}: unrecognized_unit (maximum={maximum})")
        if not df[output].dropna().between(0, 1).all():
            raise ValueError(f"{selected}: normalized share outside [0, 1]")
    else:
        normalization = "source_scale"
    out = _apply_plm_non_additive(df[["unit_id", output]], value_column=output, mode="mean")
    out[f"{output}_reference_year"] = reference_year
    out[f"{output}_source_column"] = selected
    out[f"{output}_status"] = "unknown"
    out[f"{output}_normalization"] = normalization
    return out


@lru_cache(maxsize=None)
def load_covariates(year: int) -> pd.DataFrame:
    frames = [load_vbbm(year)]
    frames.append(_load_optional_year_value("socio_rev_csv.zip", "revcommunes.csv", [f"revratio{year}", f"revmoy{year}"], "revenue", reference_year=year))
    frames.append(_load_optional_year_value("socio_cap_csv.zip", "capitalimmobiliercommunes.csv", [f"capitalratio{year}", f"capitalimmo{year}"], "capital", reference_year=year))
    frames.append(_load_optional_year_value("socio_nat_csv.zip", "etrangerscommunes.csv", [f"petranger{year}"], "foreign_share", reference_year=year, normalize_share=True))
    out = frames[0]
    for frame in frames[1:]:
        out = out.merge(frame, on="unit_id", how="outer", validate="one_to_one")
    geography = load_geography_reference(2022)[["unit_id", "department", "region13"]]
    out = out.merge(geography, on="unit_id", how="left", validate="one_to_one")
    northeast = {"32_hauts_de_france", "44_grand_est"}
    southeast = {"84_auvergne_rhone_alpes", "93_provence_alpes_cote_azur", "94_corse"}
    out["ne_vs_se"] = np.where(out["region13"].isin(northeast), 1.0, np.where(out["region13"].isin(southeast), 0.0, np.nan))
    # Compatibility alias for historical code paths only. Public v1.0.1 tables
    # expose ``foreign_share`` and document that the source concept is the
    # Canonical foreign-resident share. Its identity with
    # etranger/(etranger+francais) is audited in the v1.0.1 release; the
    # distinct peretranger series is not interpreted because its exact
    # transformation is not documented locally.
    out["immigrant_share"] = out.get("foreign_share")
    return out


def load_reference_universe(election_2022: ElectionSpec) -> pd.DataFrame:
    electoral = load_election(election_2022)[["unit_id", "inscrits"]]
    csp = load_csp(2022)
    vbbm = load_vbbm(2022)
    out = electoral.merge(csp, on="unit_id", how="inner", validate="one_to_one")
    out = out.merge(vbbm, on="unit_id", how="inner", validate="one_to_one")
    geography = load_geography_reference(2022)
    out = out.merge(geography, on="unit_id", how="left", validate="one_to_one")
    out["csp_total"] = out[list(CSP_GROUPS)].sum(axis=1, min_count=len(CSP_GROUPS))
    valid = (
        out["unit_id"].map(is_valid_unit_id)
        & pd.to_numeric(out["inscrits"], errors="coerce").gt(0)
        & out[list(CSP_GROUPS)].notna().all(axis=1)
        & out[list(CSP_GROUPS)].ge(0).all(axis=1)
        & out["csp_total"].gt(0)
        & out["vbbm"].notna()
        & out["region13"].notna()
    )
    out = out.loc[valid].copy()
    out = out.loc[out["vbbm"].isin([1, 2, 3, 4])].copy()
    out["log1p_inscrits"] = np.log1p(out["inscrits"].astype(float))
    for group in ("ouvr", "empl", "cadr"):
        out[f"share_{group}"] = out[group] / out["csp_total"]
    out["share_agri_indp"] = (out["agri"] + out["indp"]) / out["csp_total"]
    keep = [
        "unit_id",
        "department",
        "commune_name",
        "geography_source",
        "inscrits",
        "region13",
        "vbbm",
        "log1p_inscrits",
        "share_ouvr",
        "share_empl",
        "share_cadr",
        "share_agri_indp",
    ]
    return out[keep].sort_values("unit_id").reset_index(drop=True)
