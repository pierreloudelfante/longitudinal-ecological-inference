from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import io
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import numpy as np
import pandas as pd
from PIL import Image


IDENTIFIER_COLUMNS = {
    "unit_id",
    "election_id",
    "scenario_id",
    "model_key",
    "panel_id",
    "sample_id",
    "run_id",
    "spec_id",
    "source_panel_id",
}

COMPARISON_REFERENCE_RECEIPT = "comparison_reference_receipt.json"
PROJECTION_RENDERER = "reproducibility/render_scope_reference.py"
PROJECTION_PRODUCTION_FILES = (
    "reproducibility/certify_reproduction.py",
    "reproducibility/replication_complete.py",
    "reproducibility/replication_scope.py",
    "reproducibility/result_scope.py",
    "reproducibility/contract_v2/krt_replay_240.json",
    "reproducibility/reference/rxc_ineligible_audit.csv",
    "reproducibility/presentation/compose_slide_figures.ps1",
    "reproducibility/report/RAPPORT_LONGITUDINAL.template.html",
    "code_longitudinal/build_full240_professor_release.py",
    "code_longitudinal/compare_python_r_ei_full_240.py",
    "code_longitudinal/spec_registry.py",
    "code_longitudinal/build_professor_release_assets.py",
    "code_longitudinal/export_density_pair_inputs.py",
    "code_longitudinal/finalize_density_bundle.py",
    "code_longitudinal/build_density_report_atlas.py",
    "code_longitudinal/repair_portable_report_from_template.py",
    "r_replication/generate_all_pair_density_figures.R",
)
PROJECTED_DENSITY_CATALOGUE = "06_DOCUMENTATION/CATALOGUE_DENSITES_COMPLET.csv"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_path(value: str) -> str:
    return str(PurePosixPath(value.replace("\\", "/")))


def sha256_stream(chunks: Iterable[bytes]) -> str:
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(chunk)
    return digest.hexdigest()


def file_sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return sha256_stream(iter(lambda: handle.read(1024 * 1024), b""))


@dataclass
class Artifact:
    path: Path

    def __post_init__(self) -> None:
        self.path = self.path.resolve()
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        self._zip: zipfile.ZipFile | None = None
        if self.path.is_file():
            self._zip = zipfile.ZipFile(self.path)

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()

    def files(self) -> list[str]:
        if self._zip is not None:
            return sorted(
                normalize_path(item.filename)
                for item in self._zip.infolist()
                if not item.is_dir()
            )
        return sorted(
            normalize_path(str(item.relative_to(self.path)))
            for item in self.path.rglob("*")
            if item.is_file()
        )

    def read_bytes(self, relative_path: str) -> bytes:
        if self._zip is not None:
            return self._zip.read(relative_path)
        return (self.path / Path(relative_path)).read_bytes()

    def sha256(self, relative_path: str) -> str:
        if self._zip is not None:
            with self._zip.open(relative_path) as handle:
                return sha256_stream(iter(lambda: handle.read(1024 * 1024), b""))
        return file_sha256(self.path / Path(relative_path))

    def crc_ok(self) -> bool | None:
        if self._zip is None:
            return None
        return self._zip.testzip() is None


def read_table(payload: bytes, path: str) -> pd.DataFrame:
    if path.lower().endswith(".parquet"):
        return pd.read_parquet(io.BytesIO(payload))
    if path.lower().endswith(".csv"):
        header = pd.read_csv(io.BytesIO(payload), nrows=0)
        dtype = {column: "string" for column in IDENTIFIER_COLUMNS if column in header.columns}
        return pd.read_csv(io.BytesIO(payload), dtype=dtype)
    raise ValueError(f"Unsupported table type: {path}")


def series_equal(left: pd.Series, right: pd.Series) -> np.ndarray:
    if len(left) != len(right):
        raise ValueError("series length mismatch")
    # Table alignment is controlled by compare_table's declared scientific
    # keys.  Pandas otherwise compares Series index labels, which can differ
    # after a comparison-only scope projection even when the aligned values
    # and order are identical.
    left_text = left.astype("string").reset_index(drop=True)
    right_text = right.astype("string").reset_index(drop=True)
    return ((left_text == right_text) | (left_text.isna() & right_text.isna())).fillna(False).to_numpy()


def apply_identifier_aliases(
    path: str,
    column: str,
    reference: pd.DataFrame,
    candidate: pd.DataFrame,
    matches: np.ndarray,
    policy: dict[str, Any],
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """Apply only preregistered, row-scoped provenance aliases.

    Alias use is reported and later conditioned on a successful comparison of
    the declared proof table.  Unknown aliases, wrong scientific keys, or a
    changed canonical panel identifier therefore remain hard failures.
    """
    accepted = matches.copy()
    applications: list[dict[str, Any]] = []
    for rule in policy.get("identifier_aliases", []):
        if rule.get("path") != path or rule.get("column") != column:
            continue
        required = {"id", "reference", "candidate", "where", "requires_table"}
        missing = sorted(required - set(rule))
        if missing:
            raise ValueError(f"Malformed identifier alias {rule.get('id', '<unnamed>')}: missing {missing}")
        if not isinstance(rule["where"], dict) or not rule["where"]:
            raise ValueError(f"Identifier alias {rule['id']} must have a non-empty where clause")
        row_mask = ~accepted
        ref_values = reference[column].astype("string").reset_index(drop=True)
        cand_values = candidate[column].astype("string").reset_index(drop=True)
        row_mask &= (ref_values == str(rule["reference"])).fillna(False).to_numpy()
        row_mask &= (cand_values == str(rule["candidate"])).fillna(False).to_numpy()
        for condition_column, expected in rule["where"].items():
            if condition_column not in reference.columns or condition_column not in candidate.columns:
                raise ValueError(
                    f"Identifier alias {rule['id']} condition column missing: {condition_column}"
                )
            ref_condition = reference[condition_column].astype("string").reset_index(drop=True)
            cand_condition = candidate[condition_column].astype("string").reset_index(drop=True)
            row_mask &= (ref_condition == str(expected)).fillna(False).to_numpy()
            row_mask &= (cand_condition == str(expected)).fillna(False).to_numpy()
        count = int(row_mask.sum())
        if count:
            accepted |= row_mask
            applications.append({
                "id": rule["id"],
                "column": column,
                "reference": rule["reference"],
                "candidate": rule["candidate"],
                "where": rule["where"],
                "requires_table": rule["requires_table"],
                "normalized_rows": count,
            })
    return accepted, applications


def numeric_comparison(
    reference: pd.DataFrame,
    candidate: pd.DataFrame,
    column: str,
    rule: dict[str, Any],
) -> dict[str, Any]:
    ref = pd.to_numeric(reference[column], errors="coerce").to_numpy(dtype=float)
    cand = pd.to_numeric(candidate[column], errors="coerce").to_numpy(dtype=float)
    both_nan = np.isnan(ref) & np.isnan(cand)
    one_nan = np.isnan(ref) ^ np.isnan(cand)
    invalid_numeric = ((reference[column].notna().to_numpy() & np.isnan(ref))
                       | (candidate[column].notna().to_numpy() & np.isnan(cand)))
    same_infinity = np.isinf(ref) & np.isinf(cand) & (np.sign(ref) == np.sign(cand))
    finite = np.isfinite(ref) & np.isfinite(cand)
    diff = np.full(ref.shape, np.inf, dtype=float)
    diff[finite] = np.abs(cand[finite] - ref[finite])
    diff[both_nan | same_infinity] = 0.0

    atol = float(rule.get("atol", 0.0))
    rtol = float(rule.get("rtol", 0.0))
    allowed = np.zeros(ref.shape, dtype=float)
    allowed[finite] = atol + rtol * np.abs(ref[finite])
    width_columns = rule.get("width_columns")
    if width_columns:
        lower = pd.to_numeric(reference[width_columns[0]], errors="coerce").to_numpy(dtype=float)
        upper = pd.to_numeric(reference[width_columns[1]], errors="coerce").to_numpy(dtype=float)
        width_allowed = float(rule.get("width_fraction", 0.0)) * np.abs(upper - lower)
        width_allowed = np.where(np.isfinite(width_allowed), width_allowed, 0.0)
        allowed = np.maximum(allowed, width_allowed)

    passed = (both_nan | same_infinity | (finite & (diff <= allowed))) & ~invalid_numeric
    sign_mismatch = np.zeros(ref.shape, dtype=bool)
    if rule.get("preserve_sign", False):
        sign_mismatch = finite & (np.sign(ref) != np.sign(cand)) & (np.abs(ref) > allowed) & (np.abs(cand) > allowed)
        passed &= ~sign_mismatch
    denominator = np.maximum(np.abs(ref), np.finfo(float).eps)
    relative = np.full(ref.shape, np.nan)
    relative[finite] = diff[finite] / denominator[finite]
    mismatch_indexes = np.flatnonzero(~passed)
    examples = []
    for index in mismatch_indexes[:5]:
        examples.append(
            {
                "row": int(index),
                "reference": None if math.isnan(ref[index]) else float(ref[index]),
                "candidate": None if math.isnan(cand[index]) else float(cand[index]),
                "absolute_difference": None if not math.isfinite(diff[index]) else float(diff[index]),
                "allowed_difference": None if not math.isfinite(allowed[index]) else float(allowed[index]),
            }
        )
    return {
        "column": column,
        "pass": bool(np.all(passed)),
        "mismatch_count": int((~passed).sum()),
        "sign_mismatch_count": int(sign_mismatch.sum()),
        "matching_null_count": int(both_nan.sum()),
        "one_sided_null_count": int(one_nan.sum()),
        "invalid_numeric_value_count": int(invalid_numeric.sum()),
        "matching_infinity_count": int(same_infinity.sum()),
        "max_absolute_difference": float(np.nanmax(np.where(np.isfinite(diff), diff, np.nan)))
        if np.isfinite(diff).any()
        else None,
        "max_relative_difference": float(np.nanmax(relative)) if np.isfinite(relative).any() else None,
        "examples": examples,
    }


def validate_run_provenance(frame: pd.DataFrame, configured: dict[str, Any]) -> dict[str, Any]:
    """Check changing execution labels without treating them as scientific values."""
    pair_keys = configured["pair_keys"]
    columns = [*pair_keys, "run_id"]
    if configured.get("run_key_column"):
        columns.append(configured["run_key_column"])
    missing = [name for name in columns if name not in frame]
    if missing:
        return {"pass": False, "issues": ["missing_provenance_columns:" + ",".join(missing)], "pairs": []}
    source = frame[columns].drop_duplicates().astype("string")
    issues = []
    if source[pair_keys + ["run_id"]].isna().any().any():
        issues.append("missing_pair_or_run_id")
    for run_id in source["run_id"].dropna().unique():
        if re.fullmatch(r"\d{8}T\d{6}Z__[0-9a-f]{12}", run_id) is None:
            issues.append("invalid_run_id_format:" + run_id)
            continue
        try:
            datetime.strptime(run_id.split("__")[0], "%Y%m%dT%H%M%SZ")
        except ValueError:
            issues.append("invalid_run_id_timestamp:" + run_id)
    groups = source.groupby(pair_keys, dropna=False)
    if not groups["run_id"].nunique(dropna=False).eq(1).all():
        issues.append("multiple_runs_within_pair")
    pairs = source.drop_duplicates(pair_keys + ["run_id"])
    if pairs["run_id"].duplicated().any():
        issues.append("run_id_reused_across_pairs")
    key_column = configured.get("run_key_column")
    if key_column:
        if not groups[key_column].nunique(dropna=False).eq(1).all():
            issues.append("inconsistent_run_key_within_pair")
        keyed = source.loc[source[key_column].notna(), ["run_id", key_column]].drop_duplicates()
        valid_keys = keyed[key_column].str.fullmatch(r"[0-9a-f]{64}").fillna(False)
        prefix_matches = keyed["run_id"].str[-12:] == keyed[key_column].str[:12]
        if not (valid_keys & prefix_matches).all():
            issues.append("invalid_run_key_or_run_id_prefix")
    return {"pass": not issues, "issues": issues, "family": configured["family"],
            "pair_count": len(pairs), "pairs": pairs.astype(object).where(pairs.notna(), None).to_dict("records")}


def compare_table(
    path: str,
    reference_payload: bytes,
    candidate_payload: bytes,
    policy: dict[str, Any],
    *,
    reference_frame: pd.DataFrame | None = None,
) -> dict[str, Any]:
    reference = read_table(reference_payload, path) if reference_frame is None else reference_frame.copy()
    candidate = read_table(candidate_payload, path)
    result: dict[str, Any] = {
        "path": path,
        "reference_rows": len(reference),
        "candidate_rows": len(candidate),
        "reference_columns": list(reference.columns),
        "candidate_columns": list(candidate.columns),
        "issues": [],
        "column_results": [],
        "identifier_aliases": [],
    }
    if list(reference.columns) != list(candidate.columns):
        result["issues"].append("column_order_or_membership_mismatch")
        result["pass"] = False
        return result
    if len(reference) != len(candidate):
        result["issues"].append("row_count_mismatch")
        result["pass"] = False
        return result

    configured = policy.get("tables", {}).get(path, {})
    keys = configured.get("keys", [])
    ignored = set(configured.get("ignore_columns", []))
    rules = configured.get("numeric_rules", {})
    default_rule = policy.get("default_numeric", {"atol": 0.0, "rtol": 0.0})
    provenance = configured.get("run_provenance")

    missing_keys = [key for key in keys if key not in reference.columns]
    if missing_keys:
        result["issues"].append({"missing_key_columns": missing_keys})
        result["pass"] = False
        return result

    if keys:
        ref_key = reference[keys].astype("string")
        cand_key = candidate[keys].astype("string")
        if ref_key.duplicated().any() or cand_key.duplicated().any():
            result["issues"].append("duplicate_table_keys")
            result["pass"] = False
            return result
        reference = reference.assign(
            __sort_key=ref_key.fillna("<NA>").agg("\x1f".join, axis=1)
        ).sort_values("__sort_key", kind="stable").drop(columns="__sort_key").reset_index(drop=True)
        candidate = candidate.assign(
            __sort_key=cand_key.fillna("<NA>").agg("\x1f".join, axis=1)
        ).sort_values("__sort_key", kind="stable").drop(columns="__sort_key").reset_index(drop=True)
        key_match = np.ones(len(reference), dtype=bool)
        for key in keys:
            key_match &= series_equal(reference[key], candidate[key])
        if not np.all(key_match):
            result["issues"].append(
                {"table_key_mismatch_count": int((~key_match).sum())}
            )
            result["pass"] = False
            return result

    provenance_columns = set()
    if provenance:
        reference_provenance = validate_run_provenance(reference, provenance)
        candidate_provenance = validate_run_provenance(candidate, provenance)
        result["run_provenance"] = {"reference": reference_provenance, "candidate": candidate_provenance}
        if not reference_provenance["pass"] or not candidate_provenance["pass"]:
            result["issues"].append("invalid_run_provenance")
        provenance_columns.add("run_id")
        key_column = provenance.get("run_key_column")
        if key_column:
            provenance_columns.add(key_column)
            if key_column in reference and not reference[key_column].isna().equals(candidate[key_column].isna()):
                result["issues"].append("run_key_missingness_changed")
    for column in reference.columns:
        if column in provenance_columns:
            continue
        if column in ignored:
            continue
        ref_col = reference[column]
        cand_col = candidate[column]
        is_numeric = pd.api.types.is_numeric_dtype(ref_col.dtype) and not pd.api.types.is_bool_dtype(ref_col.dtype)
        if is_numeric:
            rule = rules.get(column, rules.get("*", default_rule))
            result["column_results"].append(
                numeric_comparison(reference, candidate, column, rule)
            )
        else:
            matches = series_equal(ref_col, cand_col)
            matches, alias_applications = apply_identifier_aliases(
                path, column, reference, candidate, matches, policy,
            )
            result["identifier_aliases"].extend(alias_applications)
            mismatch_indexes = np.flatnonzero(~matches)
            result["column_results"].append(
                {
                    "column": column,
                    "pass": bool(np.all(matches)),
                    "mismatch_count": int((~matches).sum()),
                    "identifier_aliases_applied": alias_applications,
                    "examples": [
                        {
                            "row": int(index),
                            "reference": None if pd.isna(ref_col.iloc[index]) else str(ref_col.iloc[index]),
                            "candidate": None if pd.isna(cand_col.iloc[index]) else str(cand_col.iloc[index]),
                        }
                        for index in mismatch_indexes[:5]
                    ],
                }
            )

    interval_results = []
    for lower_column, upper_column in configured.get("interval_classifications", []):
        ref_lower = pd.to_numeric(reference[lower_column], errors="coerce").to_numpy(dtype=float)
        ref_upper = pd.to_numeric(reference[upper_column], errors="coerce").to_numpy(dtype=float)
        cand_lower = pd.to_numeric(candidate[lower_column], errors="coerce").to_numpy(dtype=float)
        cand_upper = pd.to_numeric(candidate[upper_column], errors="coerce").to_numpy(dtype=float)
        finite = np.isfinite(ref_lower) & np.isfinite(ref_upper) & np.isfinite(cand_lower) & np.isfinite(cand_upper)
        ref_class = np.where(ref_lower > 0, 1, np.where(ref_upper < 0, -1, 0))
        cand_class = np.where(cand_lower > 0, 1, np.where(cand_upper < 0, -1, 0))
        mismatch = finite & (ref_class != cand_class)
        interval_results.append({
            "columns": [lower_column, upper_column],
            "pass": bool(not mismatch.any()),
            "compared_rows": int(finite.sum()),
            "classification_mismatch_count": int(mismatch.sum()),
        })

    result["interval_classification_results"] = interval_results

    result["pass"] = not result["issues"] and all(
        item["pass"] for item in result["column_results"]
    ) and all(item["pass"] for item in interval_results)
    result["ignored_columns"] = sorted(ignored)
    return result


def compare_png(path: str, reference_payload: bytes, candidate_payload: bytes,
                policy: dict[str, Any]) -> dict[str, Any]:
    rule = policy.get("non_table_artifacts", {}).get("png", {})
    with Image.open(io.BytesIO(reference_payload)) as ref_image, Image.open(io.BytesIO(candidate_payload)) as cand_image:
        ref_image.load(); cand_image.load()
        result: dict[str, Any] = {
            "path": path,
            "kind": "png_visual",
            "reference_size": list(ref_image.size),
            "candidate_size": list(cand_image.size),
        }
        if ref_image.size != cand_image.size:
            result.update({"pass": False, "issues": ["image_dimensions_mismatch"]})
            return result
        reference = np.asarray(ref_image.convert("RGBA"), dtype=np.float32)
        candidate = np.asarray(cand_image.convert("RGBA"), dtype=np.float32)
    difference = np.abs(candidate - reference) / 255.0
    rgb_max = difference[..., :3].max(axis=2)
    mean_absolute_error = float(difference.mean())
    root_mean_square_error = float(np.sqrt(np.mean(np.square(difference))))
    changed_pixel_fraction = float(np.mean(rgb_max > float(rule.get("pixel_change_threshold", 8 / 255))))
    limits = {
        "mean_absolute_error": float(rule.get("max_mean_absolute_error", 0.01)),
        "root_mean_square_error": float(rule.get("max_root_mean_square_error", 0.08)),
        "changed_pixel_fraction": float(rule.get("max_changed_pixel_fraction", 0.15)),
    }
    result.update({
        "mean_absolute_error": mean_absolute_error,
        "root_mean_square_error": root_mean_square_error,
        "changed_pixel_fraction": changed_pixel_fraction,
        "limits": limits,
        "pass": (
            mean_absolute_error <= limits["mean_absolute_error"]
            and root_mean_square_error <= limits["root_mean_square_error"]
            and changed_pixel_fraction <= limits["changed_pixel_fraction"]
        ),
    })
    return result


NUMBER_PATTERN = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")
ISO_TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}[T ][0-9:.+-]+Z?")
SHA256_PATTERN = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])")
PORTABLE_PAYLOAD_ID = "data-analytics-portable-artifact-payload-source"
PORTABLE_PAYLOAD_PATTERN = re.compile(
    r'(<template\b(?=[^>]*\bid=["\']' + PORTABLE_PAYLOAD_ID + r'["\'])[^>]*>)(.*?)(</template>)',
    re.IGNORECASE | re.DOTALL,
)


def decode_portable_html(text: str) -> tuple[str, str | None, int]:
    """Expose every embedded data value for comparison, ignoring encoding bytes.

    Only the two generation timestamps and the matching page-header timestamp
    are normalized. Dataset dates, identifiers and other payload text stay intact.
    """
    matches = list(PORTABLE_PAYLOAD_PATTERN.finditer(text))
    openings = re.findall(
        r'<template\b(?=[^>]*\bid=["\']' + PORTABLE_PAYLOAD_ID + r'["\'])[^>]*>',
        text, re.IGNORECASE,
    )
    if not matches and not openings:
        return text, None, 0
    if len(matches) != 1 or len(openings) != 1:
        raise ValueError("portable report must contain exactly one complete artifact payload")
    encoded = re.sub(r"\s+", "", matches[0].group(2))
    compressed = base64.b64decode(encoded, validate=True)
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        decoded = stream.read(64 * 1024 * 1024 + 1)
    if len(decoded) > 64 * 1024 * 1024:
        raise ValueError("portable artifact exceeds 64 MiB decoded limit")

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate portable JSON key: " + key)
            result[key] = value
        return result

    artifact = json.loads(decoded, object_pairs_hook=unique_keys)
    if (not isinstance(artifact, dict)
            or not isinstance(artifact.get("manifest"), dict)
            or not isinstance(artifact.get("snapshot"), dict)
            or not isinstance(artifact["snapshot"].get("datasets"), dict)):
        raise ValueError("invalid portable artifact structure")
    generated = artifact["manifest"].get("generatedAt")
    for section in ("manifest", "snapshot"):
        timestamp = artifact[section].get("generatedAt")
        if not isinstance(timestamp, str):
            raise ValueError("missing portable generation timestamp")
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        artifact[section]["generatedAt"] = "<GENERATION_TIMESTAMP>"

    execution_timestamp_count = 0
    sources = artifact.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("portable artifact sources must be a list")
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("portable artifact source must be an object")
        query = source.get("query")
        if query is None:
            continue
        if not isinstance(query, dict):
            raise ValueError("portable artifact source query must be an object")
        if "executed_at" not in query:
            continue
        timestamp = query["executed_at"]
        if not isinstance(timestamp, str):
            raise ValueError("portable source query executed_at must be an ISO timestamp string")
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        query["executed_at"] = "<EXECUTION_TIMESTAMP>"
        execution_timestamp_count += 1

    # Only the renderer's source-query receipt is volatile.  An identically
    # named field anywhere under snapshot.datasets remains scientific content.
    # Match only the renderer's generation-date header, not dates in results.
    header = ('<div class="portable-page-meta"><time datetime="' + generated + '">'
              + generated + '</time></div>')
    text = text.replace(header, '<div class="portable-page-meta"><time datetime="<GENERATION_TIMESTAMP>"><GENERATION_TIMESTAMP></time></div>')
    canonical = json.dumps(artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    text = PORTABLE_PAYLOAD_PATTERN.sub(
        lambda match: match.group(1) + "__DECODED_PORTABLE_PAYLOAD__" + match.group(3), text,
    )
    return text, canonical, execution_timestamp_count


def normalize_text_artifact(payload: bytes, kind: str) -> tuple[str, dict[str, Any]]:
    text = payload.decode("utf-8-sig", errors="replace").replace("\r\n", "\n")
    portable_json = None
    metadata: dict[str, Any] = {}
    if kind == "html":
        text, portable_json, execution_timestamp_count = decode_portable_html(text)
        metadata["portable_query_execution_timestamps_ignored"] = execution_timestamp_count
    text = ISO_TIMESTAMP_PATTERN.sub("<TIMESTAMP>", text)
    text = SHA256_PATTERN.sub("<SHA256>", text)
    text = re.sub(r"[A-Za-z]:[/\\][^\"'<>\r\n]+", "<ABSOLUTE_PATH>", text)
    if kind == "svg":
        text = re.sub(r"<metadata\b.*?</metadata>", "", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'\bid="[^"]+"', 'id="<ID>"', text)
        text = re.sub(r"url\(#[^)]+\)", "url(#<ID>)", text)
        text = re.sub(r'(["\'])#[^"\']+\1', r'\1#<ID>\1', text)
    elif kind == "html":
        text = re.sub(r"data:image/[^;]+;base64,[A-Za-z0-9+/=\s]+", "<EMBEDDED_IMAGE>", text)
        if portable_json is not None:
            # Insert after broad display-text normalization so scientific dates,
            # hashes and paths inside the decoded artifact are not discarded.
            text = text.replace("__DECODED_PORTABLE_PAYLOAD__", portable_json, 1)
    return re.sub(r"\s+", " ", text).strip(), metadata


def compare_numeric_text(path: str, reference_payload: bytes, candidate_payload: bytes,
                         kind: str, policy: dict[str, Any]) -> dict[str, Any]:
    rule = policy.get("non_table_artifacts", {}).get(kind, {})
    try:
        reference, reference_metadata = normalize_text_artifact(reference_payload, kind)
        candidate, candidate_metadata = normalize_text_artifact(candidate_payload, kind)
    except (ValueError, TypeError, OSError, EOFError, UnicodeError) as exc:
        return {"path": path, "kind": f"{kind}_semantic_text", "pass": False,
                "issues": [f"text_or_portable_payload_parse_error: {type(exc).__name__}: {exc}"]}
    ref_numbers_text = NUMBER_PATTERN.findall(reference)
    cand_numbers_text = NUMBER_PATTERN.findall(candidate)
    ref_skeleton = NUMBER_PATTERN.sub("<N>", reference)
    cand_skeleton = NUMBER_PATTERN.sub("<N>", candidate)
    result: dict[str, Any] = {
        "path": path,
        "kind": f"{kind}_semantic_text",
        "reference_numeric_tokens": len(ref_numbers_text),
        "candidate_numeric_tokens": len(cand_numbers_text),
        "text_skeleton_match": ref_skeleton == cand_skeleton,
    }
    if kind == "html" and PORTABLE_PAYLOAD_ID.encode() in reference_payload:
        result["portable_payload_comparison"] = "decoded_json_with_existing_html_numeric_policy"
        result["portable_generation_fields_ignored"] = [
            "manifest.generatedAt", "snapshot.generatedAt", "matching_page_header_time",
            "sources[*].query.executed_at",
        ]
        result["portable_query_execution_timestamps_ignored"] = {
            "reference": reference_metadata.get("portable_query_execution_timestamps_ignored", 0),
            "candidate": candidate_metadata.get("portable_query_execution_timestamps_ignored", 0),
        }
    if ref_skeleton != cand_skeleton or len(ref_numbers_text) != len(cand_numbers_text):
        result.update({"pass": False, "issues": ["text_structure_or_numeric_token_count_mismatch"]})
        return result
    if not ref_numbers_text:
        result["pass"] = True
        return result
    ref_numbers = np.asarray([float(value) for value in ref_numbers_text], dtype=float)
    cand_numbers = np.asarray([float(value) for value in cand_numbers_text], dtype=float)
    atol = float(rule.get("atol", 0.0))
    rtol = float(rule.get("rtol", 0.0))
    finite = np.isfinite(ref_numbers) & np.isfinite(cand_numbers)
    allowed = np.zeros(ref_numbers.shape, dtype=float)
    allowed[finite] = atol + rtol * np.abs(ref_numbers[finite])
    differences = np.full(ref_numbers.shape, np.inf)
    differences[finite] = np.abs(cand_numbers[finite] - ref_numbers[finite])
    # HTML/JS can contain number-like identifiers beyond float range. Preserve
    # their exact text; two different overflowing tokens must never compare equal.
    identical_overflow_tokens = ~finite & np.asarray([
        left == right for left, right in zip(ref_numbers_text, cand_numbers_text)
    ])
    differences[identical_overflow_tokens] = 0.0
    passed = differences <= allowed
    if kind in {"html", "md"} and rule.get("integers_exact", True):
        integer_tokens = np.asarray([
            re.fullmatch(r"[-+]?\d+", value) is not None for value in ref_numbers_text
        ]) & np.asarray([
            re.fullmatch(r"[-+]?\d+", value) is not None for value in cand_numbers_text
        ])
        for index in np.flatnonzero(integer_tokens):
            passed[index] = int(ref_numbers_text[index]) == int(cand_numbers_text[index])
    sign_mismatch = finite & (np.sign(ref_numbers) != np.sign(cand_numbers)) & (np.abs(ref_numbers) > allowed) & (np.abs(cand_numbers) > allowed)
    passed &= ~sign_mismatch
    mismatch = np.flatnonzero(~passed)
    result.update({
        "atol": atol,
        "rtol": rtol,
        "numeric_mismatch_count": int((~passed).sum()),
        "sign_mismatch_count": int(sign_mismatch.sum()),
        "max_absolute_difference": float(np.max(differences[np.isfinite(differences)])) if np.isfinite(differences).any() else None,
        "overflow_tokens_compared_exactly": int((~finite).sum()),
        "examples": [
            {
                "token": int(index),
                "reference": float(ref_numbers[index]) if np.isfinite(ref_numbers[index]) else ref_numbers_text[index],
                "candidate": float(cand_numbers[index]) if np.isfinite(cand_numbers[index]) else cand_numbers_text[index],
                "allowed_difference": float(allowed[index]),
            }
            for index in mismatch[:5]
        ],
        "pass": bool(np.all(passed)),
    })
    return result


VOLATILE_JSON_KEYS = {
    "bytes", "created_at", "created_at_utc", "elapsed_seconds", "finished_at",
    "finished_at_utc", "generated_at", "generated_at_utc", "mtime_ns", "run_id",
    "sha256", "source_manifest", "started_at", "started_at_utc",
}


def normalize_json_artifact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: normalize_json_artifact(item)
            for key, item in sorted(value.items())
            if key.lower() not in VOLATILE_JSON_KEYS
        }
    if isinstance(value, list):
        return [normalize_json_artifact(item) for item in value]
    return value


def compare_json(path: str, reference_payload: bytes, candidate_payload: bytes) -> dict[str, Any]:
    try:
        reference = normalize_json_artifact(json.loads(reference_payload.decode("utf-8-sig")))
        candidate = normalize_json_artifact(json.loads(candidate_payload.decode("utf-8-sig")))
        passed = reference == candidate
        return {
            "path": path,
            "kind": "json_semantic",
            "ignored_volatile_keys": sorted(VOLATILE_JSON_KEYS),
            "pass": passed,
            "issues": [] if passed else ["nonvolatile_json_content_mismatch"],
        }
    except Exception as exc:
        return {"path": path, "kind": "json_semantic", "pass": False,
                "issues": [f"json_parse_error: {type(exc).__name__}: {exc}"]}


def validate_generated_provenance(
    path: str,
    payload: bytes,
    reference: Artifact,
    candidate: Artifact,
    contract: dict[str, Any] | None,
    scope=None,
) -> dict[str, Any] | None:
    """Validate new run receipts against their own outputs, not old QA assertions.

    All scientific artifacts remain subject to the independent comparisons below.
    Only these two explicitly versioned run-receipt schemas take this route.
    """
    schemas = {
        "06_DOCUMENTATION/DELIVERY_MANIFEST.json": "longitudinal_results_recalculated_v2",
        "06_DOCUMENTATION/REPORT_QA.json": "replication_report_qa_v2",
    }
    if path not in schemas:
        return None
    value = json.loads(payload.decode("utf-8-sig"))
    if not isinstance(value, dict) or value.get("schema_version") != schemas[path]:
        if scope is not None and not scope.is_full:
            return {"path": path, "kind": "generated_run_provenance", "pass": False,
                    "issues": ["scoped_run_requires_new_scoped_receipt_not_historical_qa"]}
        return None
    issues: list[str] = []
    if scope is not None and not scope.is_full and value.get("scope") != scope.as_dict():
        issues.append("missing_or_incorrect_run_receipt_scope")
    result: dict[str, Any] = {
        "path": path, "kind": "generated_run_provenance", "issues": issues,
        "qualification": "This validates this run's receipt, not historical visual inspection or independent execution provenance.",
    }
    try:
        datetime.fromisoformat(value["created_at_utc"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError, AttributeError):
        issues.append("invalid_created_at_utc")

    if path.endswith("DELIVERY_MANIFEST.json"):
        expected_paths = set(candidate.files()) - {path}
        records = value.get("files", [])
        if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
            return {**result, "pass": False, "issues": ["invalid_manifest_records"]}
        recorded_paths = [item.get("path") for item in records]
        if any(not isinstance(item, str) for item in recorded_paths):
            return {**result, "pass": False, "issues": ["invalid_manifest_paths"]}
        if len(recorded_paths) != len(set(recorded_paths)):
            issues.append("duplicate_manifest_paths")
        if set(recorded_paths) != expected_paths:
            issues.append("manifest_paths_do_not_match_candidate_excluding_self")
        expected_reference_hash = (
            file_sha256(reference.path) if reference.path.is_file()
            else (contract or {}).get("source_archive_sha256")
        )
        if not expected_reference_hash or value.get("source_reference_sha256") != expected_reference_hash:
            issues.append("reference_archive_sha256_mismatch_or_unavailable")
        if value.get("not_a_claim_of_bitwise_or_monte_carlo_equality") is not True:
            issues.append("missing_noncertification_qualification")
        verified = 0
        for record in records:
            relative = record["path"]
            if relative not in expected_paths:
                continue
            content = candidate.read_bytes(relative)
            if record.get("bytes") != len(content) or record.get("sha256") != hashlib.sha256(content).hexdigest():
                issues.append("manifest_size_or_hash_mismatch:" + relative)
            else:
                verified += 1
            if "parquet" in record:
                import pyarrow.parquet as pq
                metadata = pq.ParquetFile(io.BytesIO(content))
                declared = record["parquet"]
                if (not isinstance(declared, dict)
                        or declared.get("rows") != metadata.metadata.num_rows
                        or set(declared.get("columns", [])) != set(metadata.schema_arrow.names)):
                    issues.append("manifest_parquet_metadata_mismatch:" + relative)
        verification = value.get("verification", {})
        if (not isinstance(verification, dict)
                or verification.get("status") != "complete_structure_not_numerical_equality"
                or verification.get("expected_files") != len(candidate.files())
                or verification.get("pending_generated_manifest") is not True):
            issues.append("invalid_structure_verification_receipt")
        result.update({"verified_file_hashes": verified, "manifest_excludes_itself": True})
    else:
        required = {
            "pdf_origin": "rendered_from_newly_generated_html_not_copied_from_reference",
            "visual_inspection_performed": False,
            "numeric_equality_to_historical_results": "not_certified",
            "reference_statistics_in_static_narrative": "historical_context_not_new_validation",
            "coverage_contract": "expected_results_610.json",
        }
        if scope is not None and not scope.is_full:
            required["coverage_contract"] = "projection of expected_results_610.json for declared scope"
        scope_fields = {"scope"} if scope is not None and not scope.is_full else set()
        if set(value) != {"schema_version", "created_at_utc", *required, *scope_fields}:
            issues.append("unexpected_or_missing_report_qa_fields")
        for key, expected in required.items():
            if type(value.get(key)) is not type(expected) or value.get(key) != expected:
                issues.append("invalid_report_qa_claim:" + key)
        html_path = "01_RAPPORT/RAPPORT_LONGITUDINAL.html"
        pdf_path = "01_RAPPORT/RAPPORT_LONGITUDINAL.pdf"
        if not {html_path, pdf_path}.issubset(candidate.files()):
            issues.append("candidate_report_outputs_missing")
        else:
            html = candidate.read_bytes(html_path).decode("utf-8-sig")
            pdf = candidate.read_bytes(pdf_path)
            if "<html" not in html.lower() or "</html>" not in html.lower():
                issues.append("invalid_candidate_html_container")
            if not pdf.startswith(b"%PDF-") or b"%%EOF" not in pdf[-2048:]:
                issues.append("invalid_candidate_pdf_container")
        result.update({
            "visual_inspection_verified": False,
            "rendering_origin_is_self_reported": True,
            "scientific_report_content_compared_separately": True,
        })
    result["pass"] = not issues
    return result


def compare_pdf(path: str, reference_payload: bytes, candidate_payload: bytes,
                policy: dict[str, Any]) -> dict[str, Any]:
    rule = policy.get("non_table_artifacts", {}).get("pdf", {})
    page_pattern = re.compile(rb"/Type\s*/Page(?!s)\b")
    ref_pages = len(page_pattern.findall(reference_payload))
    cand_pages = len(page_pattern.findall(candidate_payload))
    valid_ref = reference_payload.startswith(b"%PDF-") and b"%%EOF" in reference_payload[-2048:]
    valid_cand = candidate_payload.startswith(b"%PDF-") and b"%%EOF" in candidate_payload[-2048:]
    size_ratio_difference = abs(len(candidate_payload) - len(reference_payload)) / max(len(reference_payload), 1)
    max_size_ratio_difference = float(rule.get("max_size_ratio_difference", 0.20))
    passed = valid_ref and valid_cand and ref_pages > 0 and ref_pages == cand_pages and size_ratio_difference <= max_size_ratio_difference
    return {
        "path": path,
        "kind": "derived_pdf_validity",
        "reference_pages": ref_pages,
        "candidate_pages": cand_pages,
        "reference_valid_pdf": valid_ref,
        "candidate_valid_pdf": valid_cand,
        "size_ratio_difference": size_ratio_difference,
        "max_size_ratio_difference": max_size_ratio_difference,
        "pass": passed,
        "qualification": "The scientific report source is checked separately as HTML; this test checks the derived PDF container and pagination.",
    }


def compare_non_table(path: str, reference_payload: bytes, candidate_payload: bytes,
                      policy: dict[str, Any]) -> dict[str, Any]:
    extension = PurePosixPath(path).suffix.lower()
    if extension == ".png":
        return compare_png(path, reference_payload, candidate_payload, policy)
    if extension == ".svg":
        return compare_numeric_text(path, reference_payload, candidate_payload, "svg", policy)
    if extension == ".html":
        return compare_numeric_text(path, reference_payload, candidate_payload, "html", policy)
    if extension == ".md":
        return compare_numeric_text(path, reference_payload, candidate_payload, "md", policy)
    if extension == ".json":
        return compare_json(path, reference_payload, candidate_payload)
    if extension == ".pdf":
        return compare_pdf(path, reference_payload, candidate_payload, policy)
    return {"path": path, "kind": "unsupported", "pass": False,
            "issues": [f"unsupported_non_table_extension: {extension}"]}


def compare_cross_table_provenance(table_results: list[dict[str, Any]]) -> dict[str, Any]:
    issues = []
    checked = {}
    for side in ("reference", "candidate"):
        seen = {}
        for table in table_results:
            provenance = table.get("run_provenance", {}).get(side)
            if not provenance:
                continue
            for pair in provenance["pairs"]:
                key = (provenance["family"], pair["election_id"], pair["scenario_id"])
                previous = seen.get(key)
                if previous and previous[0] != pair["run_id"]:
                    issues.append({"artifact": side, "family": key[0], "election_id": key[1],
                                   "scenario_id": key[2], "paths": [previous[1], table["path"]],
                                   "issue": "different_run_ids_for_same_pair_across_tables"})
                seen[key] = (pair["run_id"], table["path"])
        checked[side] = len(seen)
    return {"pass": not issues, "checked_family_pairs": checked, "issues": issues}


def validate_identifier_alias_requirements(table_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Require every accepted provenance alias to be backed by a passing table."""
    by_path = {item.get("path"): item for item in table_results}
    applications = []
    issues = []
    for table in table_results:
        for alias in table.get("identifier_aliases", []):
            record = {"path": table.get("path"), **alias}
            applications.append(record)
            proof_path = alias["requires_table"]
            proof = by_path.get(proof_path)
            if proof is None:
                issues.append({
                    "path": table.get("path"), "alias": alias["id"],
                    "issue": "required_proof_table_missing", "requires_table": proof_path,
                })
            elif proof.get("pass") is not True:
                issues.append({
                    "path": table.get("path"), "alias": alias["id"],
                    "issue": "required_proof_table_failed", "requires_table": proof_path,
                })
    return {
        "pass": not issues,
        "normalized_rows": sum(int(item["normalized_rows"]) for item in applications),
        "applications": applications,
        "issues": issues,
    }


def project_reference_table(path: str, frame: pd.DataFrame, scope, reference: Artifact) -> pd.DataFrame:
    """Comparison-only projection; candidate data never enters this function.

Pair-level values are selected, never repaired or recomputed. Two coverage
summaries and dictionary nullability are structural reductions of the selected
reference rows, not statistics borrowed to fill missing candidate results.
"""
    selected = scope.filter_frame(frame)
    coverage_paths = {
        "04_PANEL_ET_HARMONISATION/coverage_by_election.csv",
        "05_DIAGNOSTICS/matrice_couverture_modeles.csv",
    }
    if path in coverage_paths:
        def source_table(name):
            relative = "02_TABLES_PRINCIPALES/" + name
            return scope.filter_frame(read_table(reference.read_bytes(relative), relative))

        krt = source_table("longitudinal_krt_aggregate.parquet")
        r_ei = source_table("longitudinal_r_ei_aggregate.parquet")
        nls = source_table("longitudinal_nls.parquet")
        krt_counts = krt.groupby("election_id")["scenario_id"].nunique()
        r_counts = r_ei.groupby("election_id")["scenario_id"].nunique()
        nls = nls[["election_id", "scenario_id", "diagnostic_status"]].drop_duplicates()
        nls_counts = nls.groupby("election_id")["scenario_id"].nunique()
        nls_passes = nls.groupby("election_id")["diagnostic_status"].agg(lambda s: int(s.eq("pass").sum()))
        counts = {
            "expected_scenarios": krt_counts, "python_krt_successes": krt_counts,
            "r_ei_successes": r_counts, "nls_scenarios": nls_counts, "nls_passes": nls_passes,
        }
        for column, values in counts.items():
            selected[column] = selected["election_id"].map(values)
        if "python_complete" in selected:
            selected["python_complete"] = selected["python_krt_successes"].eq(selected["expected_scenarios"])
        if "r_complete" in selected:
            selected["r_complete"] = selected["r_ei_successes"].eq(selected["expected_scenarios"])
    elif path == "06_DOCUMENTATION/DATA_DICTIONARY.csv":
        for name, indexes in selected.groupby("table").groups.items():
            relative = "02_TABLES_PRINCIPALES/" + str(name)
            table = scope.filter_frame(read_table(reference.read_bytes(relative), relative))
            selected.loc[indexes, "nullable"] = selected.loc[indexes, "column"].map(table.isna().any()).to_numpy()
    return selected


def projection_artifact_paths(paths: Iterable[str]) -> set[str]:
    """Only presentation outputs may come from the isolated reference renderer.

Neither model estimates nor any diagnostic, coverage or panel table can be
replaced by this artifact. The catalogue exception contains renderer bandwidths
whose domain changes with the selected elections; its source metadata is checked
separately against the fixed historical tables.
"""
    return {path for path in paths if PurePosixPath(path).suffix.lower() in {
        ".png", ".svg", ".html", ".pdf", ".md",
    } or path == PROJECTED_DENSITY_CATALOGUE}


def projection_code_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    return {relative: file_sha256(root / relative) for relative in PROJECTION_PRODUCTION_FILES}


def validate_comparison_reference(
    projection: Artifact, reference: Artifact, candidate: Artifact,
    expected_paths: set[str], contract: dict[str, Any], scope,
) -> dict[str, Any]:
    """Authenticate the comparison-only artifact, without writing any outputs."""
    result: dict[str, Any] = {
        "path": str(projection.path), "pass": False, "issues": [],
        "qualification": "This verifies source/code/output receipts, not independent execution provenance.",
    }
    issues = result["issues"]
    try:
        if (projection.path == candidate.path or projection.path.is_relative_to(candidate.path)
                or candidate.path.is_relative_to(projection.path)):
            issues.append("comparison_reference_must_be_disjoint_from_candidate")
        names = projection.files()
        if len(names) != len(set(names)):
            issues.append("duplicate_comparison_reference_paths")
        allowed = projection_artifact_paths(expected_paths)
        if set(names) != allowed | {COMPARISON_REFERENCE_RECEIPT}:
            issues.append("comparison_reference_inventory_mismatch")
        if projection.crc_ok() is False:
            issues.append("comparison_reference_crc_failure")
        receipt = json.loads(projection.read_bytes(COMPARISON_REFERENCE_RECEIPT).decode("utf-8-sig"))
        required_claims = {
            "schema_version": "scope_comparison_reference_v1",
            "source_archive_sha256": contract["source_archive_sha256"],
            "scope": scope.as_dict(), "comparison_only": True,
            "derived_from_fixed_reference": True, "candidate_outputs_used": False,
        }
        for key, expected in required_claims.items():
            if type(receipt.get(key)) is not type(expected) or receipt.get(key) != expected:
                issues.append("invalid_comparison_reference_claim:" + key)
        datetime.fromisoformat(receipt["generated_at_utc"].replace("Z", "+00:00"))
        if not reference.path.is_file() or file_sha256(reference.path) != contract["source_archive_sha256"]:
            issues.append("comparison_source_is_not_the_complete_fixed_reference_zip")
        root = Path(__file__).resolve().parents[1]
        if receipt.get("renderer_code_sha256") != file_sha256(root / PROJECTION_RENDERER):
            issues.append("comparison_renderer_code_sha256_mismatch")
        expected_code = projection_code_hashes()
        if receipt.get("production_code_hashes") != expected_code:
            issues.append("comparison_production_code_hashes_mismatch")
        records = receipt.get("files")
        if not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
            issues.append("invalid_comparison_reference_file_records")
            records = []
        recorded = [row.get("path") for row in records]
        if (any(not isinstance(path, str) for path in recorded)
                or len(recorded) != len(set(recorded)) or set(recorded) != allowed):
            issues.append("comparison_reference_receipt_inventory_mismatch")
        verified = 0
        for row in records:
            if row.get("path") not in allowed:
                continue
            payload = projection.read_bytes(row["path"])
            if row.get("bytes") != len(payload) or row.get("sha256") != hashlib.sha256(payload).hexdigest():
                issues.append("comparison_reference_size_or_hash_mismatch:" + row["path"])
            else:
                verified += 1
        if PROJECTED_DENSITY_CATALOGUE in allowed:
            path = PROJECTED_DENSITY_CATALOGUE
            historical = scope.filter_frame(read_table(reference.read_bytes(path), path))
            rendered = read_table(projection.read_bytes(path), path)
            # Bandwidths must be recomputed on the selected domain. All remaining
            # catalogue fields still have the fixed historical source as oracle.
            keys = ["method", "election_id", "scenario_id"]
            historical = historical.drop(columns=["bandwidth_b1", "bandwidth_b2"]).sort_values(keys).reset_index(drop=True)
            rendered = rendered.drop(columns=["bandwidth_b1", "bandwidth_b2"]).sort_values(keys).reset_index(drop=True)
            payload = rendered.to_csv(index=False).encode("utf-8")
            metadata_check = compare_table(path, b"", payload, {"tables": {path: {"keys": keys}}},
                                           reference_frame=historical)
            result["catalogue_source_metadata_check"] = metadata_check
            if not metadata_check["pass"]:
                issues.append("comparison_reference_catalogue_source_metadata_mismatch")
        result.update({"verified_file_hashes": verified, "expected_files": len(allowed),
                       "renderer_code_verified": "comparison_renderer_code_sha256_mismatch" not in issues,
                       "production_code_verified": receipt.get("production_code_hashes") == expected_code})
    except Exception as exc:
        issues.append(f"comparison_reference_validation_error: {type(exc).__name__}: {exc}")
    result["pass"] = not issues
    return result


def scoped_reference_projection_gaps(paths: Iterable[str]) -> list[dict[str, str]]:
    """Do not mistake full-history renders for same-domain scoped references."""
    gaps = []
    for path in sorted(projection_artifact_paths(paths)):
        reason = (
            "density_bandwidth_and_atlas_depend_on_full_election_domain"
            if "/densites_completes/" in path or "/atlas_densites_resumes/" in path or path == PROJECTED_DENSITY_CATALOGUE
            else "full_history_render_is_not_a_scoped_rendered_reference"
        )
        gaps.append({"path": path, "issue": reason})
    return gaps


def compare_artifacts(
    reference_path: Path,
    candidate_path: Path,
    policy_path: Path,
    expected_contract_path: Path | None,
    scope=None,
    comparison_reference_path: Path | None = None,
) -> dict[str, Any]:
    # Certification never silently follows the worker environment's scope.
    from reproducibility.replication_scope import get_scope
    from reproducibility.result_scope import project_result_contract

    scope = get_scope("full") if scope is None else get_scope(scope) if isinstance(scope, str) else scope
    if scope.is_full and comparison_reference_path is not None:
        raise ValueError("Full certification must compare against the fixed whole reference, not a projection")
    if not scope.is_full and expected_contract_path is None:
        raise ValueError("Scoped certification requires the complete frozen reference contract")
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    reference = Artifact(reference_path)
    candidate = Artifact(candidate_path)
    comparison_reference = None
    try:
        reference_files = reference.files()
        candidate_files = candidate.files()
        reference_set = set(reference_files)
        candidate_set = set(candidate_files)
        expected_contract_result: dict[str, Any] | None = None
        contract: dict[str, Any] | None = None
        projected_contract: dict[str, Any] | None = None
        expected_set = reference_set
        if expected_contract_path is not None:
            contract = json.loads(expected_contract_path.read_text(encoding="utf-8"))
            expected = {item["path"]: item for item in contract["files"]}
            contract_missing = sorted(set(expected) - reference_set)
            contract_unexpected = sorted(reference_set - set(expected))
            contract_hash_mismatches = []
            for path in sorted(set(expected) & reference_set):
                actual = reference.sha256(path)
                if actual != expected[path]["sha256"]:
                    contract_hash_mismatches.append(path)
            expected_contract_result = {
                "pass": not contract_missing and not contract_unexpected and not contract_hash_mismatches,
                "missing": contract_missing,
                "unexpected": contract_unexpected,
                "sha256_mismatches": contract_hash_mismatches,
            }
            if not scope.is_full:
                archive_hash_matches = (reference.path.is_file()
                                        and file_sha256(reference.path) == contract.get("source_archive_sha256"))
                expected_contract_result["complete_reference_archive_sha256_matches"] = archive_hash_matches
                expected_contract_result["pass"] &= archive_hash_matches
                projected_contract = project_result_contract(contract, scope)
                expected_set = {item["path"] for item in projected_contract["files"]}

        missing = sorted(expected_set - candidate_set)
        unexpected = sorted(candidate_set - expected_set)
        common = sorted(expected_set & reference_set & candidate_set)
        projection_gaps = [] if scope.is_full else scoped_reference_projection_gaps(expected_set)
        comparison_reference_check = None
        projected_paths: set[str] = set()
        if comparison_reference_path is not None:
            try:
                comparison_reference = Artifact(comparison_reference_path)
                comparison_reference_check = validate_comparison_reference(
                    comparison_reference, reference, candidate, expected_set, contract, scope,
                )
                if comparison_reference_check["pass"]:
                    projected_paths = projection_artifact_paths(expected_set)
                    projection_gaps = []
            except Exception as exc:
                comparison_reference_check = {"pass": False, "issues": [
                    f"comparison_reference_open_error: {type(exc).__name__}: {exc}"]}

        exact_matches: list[str] = []
        exact_mismatches: list[str] = []
        table_results: list[dict[str, Any]] = []
        artifact_results: list[dict[str, Any]] = []
        binary_differences: list[str] = []
        projected_hash_matches: list[str] = []
        table_extensions = {".csv", ".parquet"}

        for path in common:
            ref_hash = reference.sha256(path)
            candidate_hash = candidate.sha256(path)
            uses_projected_reference = path in projected_paths
            if uses_projected_reference and comparison_reference.sha256(path) == candidate_hash:
                projected_hash_matches.append(path)
            is_table = PurePosixPath(path).suffix.lower() in table_extensions
            if ref_hash == candidate_hash:
                exact_matches.append(path)
                if is_table and scope.is_full:
                    table_result = {"path": path, "pass": True, "exact_hash_match": True}
                    provenance_rule = policy.get("tables", {}).get(path, {}).get("run_provenance")
                    if provenance_rule:
                        receipt = validate_run_provenance(read_table(candidate.read_bytes(path), path), provenance_rule)
                        table_result["run_provenance"] = {"reference": receipt, "candidate": receipt}
                        table_result["pass"] = receipt["pass"]
                    table_results.append(table_result)
                scoped_receipt = not scope.is_full and path in {
                    "06_DOCUMENTATION/DELIVERY_MANIFEST.json", "06_DOCUMENTATION/REPORT_QA.json",
                }
                if scope.is_full or (not is_table and not scoped_receipt and not uses_projected_reference):
                    continue
            else:
                exact_mismatches.append(path)
            if is_table:
                try:
                    comparison_source = comparison_reference if uses_projected_reference else reference
                    ref_payload = comparison_source.read_bytes(path)
                    ref_frame = None
                    if not scope.is_full and not uses_projected_reference:
                        ref_frame = project_reference_table(path, read_table(ref_payload, path), scope, reference)
                    table_result = compare_table(
                        path,
                        ref_payload,
                        candidate.read_bytes(path),
                        policy,
                        reference_frame=ref_frame,
                    )
                    table_result["exact_hash_match"] = ref_hash == candidate_hash
                    if ref_frame is not None:
                        table_result["reference_projection"] = "comparison_only_selected_reference_rows_and_structural_summaries"
                    elif uses_projected_reference:
                        table_result["reference_projection"] = "validated_comparison_only_rendered_density_catalogue"
                    table_results.append(table_result)
                except Exception as exc:  # keep a complete audit report
                    table_results.append(
                        {
                            "path": path,
                            "pass": False,
                            "exact_hash_match": False,
                            "issues": [f"comparison_error: {type(exc).__name__}: {exc}"],
                        }
                    )
            else:
                if ref_hash != candidate_hash:
                    binary_differences.append(path)
                try:
                    candidate_payload = candidate.read_bytes(path)
                    artifact_result = validate_generated_provenance(
                        path, candidate_payload, reference, candidate, contract, scope,
                    )
                    if artifact_result is None:
                        comparison_source = comparison_reference if uses_projected_reference else reference
                        artifact_result = compare_non_table(
                            path, comparison_source.read_bytes(path), candidate_payload, policy,
                        )
                    artifact_result["exact_hash_match"] = ref_hash == candidate_hash
                    artifact_result["comparison_reference_origin"] = (
                        "validated_comparison_only_projection" if uses_projected_reference else "fixed_whole_reference"
                    )
                    artifact_results.append(artifact_result)
                except Exception as exc:
                    artifact_results.append({
                        "path": path,
                        "pass": False,
                        "exact_hash_match": False,
                        "issues": [f"comparison_error: {type(exc).__name__}: {exc}"],
                    })

        crc_pass = reference.crc_ok() is not False and candidate.crc_ok() is not False
        contract_pass = expected_contract_result is None or expected_contract_result["pass"]
        reference_duplicates = len(reference_files) - len(reference_set)
        candidate_duplicates = len(candidate_files) - len(candidate_set)
        structure_pass = (not missing and not unexpected and crc_pass and contract_pass
                          and not reference_duplicates and not candidate_duplicates
                          and (comparison_reference_check is None or comparison_reference_check["pass"]))
        exact_replay_pass = scope.is_full and structure_pass and not exact_mismatches
        cross_table_provenance = compare_cross_table_provenance(table_results)
        identifier_alias_check = validate_identifier_alias_requirements(table_results)
        semantic_tables_pass = (structure_pass and all(item["pass"] for item in table_results)
                                and cross_table_provenance["pass"]
                                and identifier_alias_check["pass"])
        semantic_artifacts_pass = structure_pass and all(item["pass"] for item in artifact_results)
        scientific_equivalence_pass = semantic_tables_pass and semantic_artifacts_pass and not projection_gaps
        certification_level = (
            "exact_replay"
            if exact_replay_pass
            else ("scientific_equivalence" if scope.is_full else "scoped_scientific_equivalence")
            if scientific_equivalence_pass
            else "failed"
        )
        return {
            "schema_version": 1,
            "created_at_utc": utc_now(),
            "reference": str(reference_path.resolve()),
            "candidate": str(candidate_path.resolve()),
            "reference_crc_ok": reference.crc_ok(),
            "candidate_crc_ok": candidate.crc_ok(),
            "reference_file_count": len(reference_files),
            "candidate_file_count": len(candidate_files),
            "expected_file_count": len(expected_set),
            "compared_file_count": len(common),
            "scope": scope.as_dict(),
            "verification_scope": "complete_campaign" if scope.is_full else "selected_estimates_only",
            "full_campaign_certified": scope.is_full and (exact_replay_pass or scientific_equivalence_pass),
            "reference_projection_gaps": projection_gaps,
            "reference_projection_complete": not projection_gaps,
            "comparison_reference_check": comparison_reference_check,
            "comparison_reference_file_count": len(projected_paths),
            "projected_render_hash_matches": len(projected_hash_matches),
            "scope_inventory_projection": (projected_contract or {}).get("scope_projection"),
            "reference_duplicate_path_count": reference_duplicates,
            "candidate_duplicate_path_count": candidate_duplicates,
            "missing_paths": missing,
            "unexpected_paths": unexpected,
            "exact_hash_matches": len(exact_matches),
            "exact_hash_mismatch_count": len(exact_mismatches),
            "exact_hash_mismatches": exact_mismatches,
            "binary_or_rendered_differences": binary_differences,
            "table_results": table_results,
            "cross_table_run_provenance": cross_table_provenance,
            "identifier_alias_check": identifier_alias_check,
            "artifact_results": artifact_results,
            "reference_contract_check": expected_contract_result,
            "structure_pass": structure_pass,
            "exact_replay_pass": exact_replay_pass,
            "semantic_tables_pass": semantic_tables_pass,
            "main_tables_pass": structure_pass and all(item["pass"] for item in table_results if item["path"].startswith("02_TABLES_PRINCIPALES/")),
            "diagnostic_tables_pass": structure_pass and all(item["pass"] for item in table_results if item["path"].startswith("05_DIAGNOSTICS/")),
            "semantic_non_table_artifacts_pass": semantic_artifacts_pass,
            "scientific_equivalence_pass": scientific_equivalence_pass,
            "status": certification_level,
            "certification_level": certification_level,
            "qualification": (
                "Scientific-equivalence thresholds are policy choices, not proof of identical Monte Carlo draws."
                + ("" if scope.is_full else " Scoped verification is not certification of the complete campaign; "
                   "rendered-domain projection gaps block certification even when selected tables match.")
            ),
        }
    finally:
        reference.close()
        candidate.close()
        if comparison_reference is not None:
            comparison_reference.close()


def resolve_raw_candidate(raw_dir: Path, source: dict[str, Any]) -> tuple[Path | None, list[str]]:
    names = {source["name"]}
    for key in ("download_name", "official_name", "alias"):
        value = source.get(key)
        if isinstance(value, str) and value:
            names.add(value)
    matches = [path for path in raw_dir.rglob("*") if path.is_file() and path.name in names]
    valid = []
    for path in matches:
        if path.stat().st_size != int(source["bytes"]):
            continue
        if file_sha256(path) == source["required_sha256"]:
            valid.append(path)
    return (valid[0] if len(valid) == 1 else None), [str(path) for path in matches]


def verify_raw_inputs(raw_dir: Path, manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources = manifest["raw_sources"]
    records = []
    for source in sources:
        valid, matches = resolve_raw_candidate(raw_dir, source)
        records.append(
            {
                "name": source["name"],
                "expected_bytes": source["bytes"],
                "expected_sha256": source["required_sha256"],
                "resolved_path": str(valid) if valid is not None else None,
                "candidate_paths": matches,
                "pass": valid is not None,
            }
        )
    return {
        "schema_version": 1,
        "created_at_utc": utc_now(),
        "raw_dir": str(raw_dir.resolve()),
        "manifest": str(manifest_path.resolve()),
        "expected_archives": len(sources),
        "expected_bytes": sum(int(item["bytes"]) for item in sources),
        "verified_archives": sum(bool(item["pass"]) for item in records),
        "pass": all(item["pass"] for item in records),
        "archives": records,
    }


def command_output(command: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
        return {
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"command": command, "error": f"{type(exc).__name__}: {exc}"}


def capture_environment() -> dict[str, Any]:
    packages = command_output([sys.executable, "-m", "pip", "freeze"])
    rscript = shutil.which("Rscript")
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    return {
        "schema_version": 1,
        "created_at_utc": utc_now(),
        "platform": platform.platform(),
        "python": {
            "executable": sys.executable,
            "version": sys.version,
            "implementation": platform.python_implementation(),
            "packages": packages,
        },
        "r": command_output([rscript, "--version"]) if rscript else {"error": "Rscript not found"},
        "powershell": command_output(
            [powershell, "-NoProfile", "-Command", "$PSVersionTable | ConvertTo-Json -Compress"]
        )
        if powershell
        else {"error": "PowerShell not found"},
        "environment_variables": {
            key: os.environ.get(key)
            for key in ["PYTHONHASHSEED", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"]
        },
    }


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Certify a longitudinal replication run.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    compare = subparsers.add_parser("compare", help="Compare a candidate artifact with the reference.")
    compare.add_argument("--reference", type=Path, required=True)
    compare.add_argument("--candidate", type=Path, required=True)
    compare.add_argument("--policy", type=Path, required=True)
    compare.add_argument("--expected-contract", type=Path)
    compare.add_argument("--scope", choices=("full", "court"), default="full")
    compare.add_argument("--comparison-reference", type=Path)
    compare.add_argument("--output", type=Path, required=True)

    raw = subparsers.add_parser("verify-inputs", help="Verify all raw archives by size and SHA-256.")
    raw.add_argument("--raw-dir", type=Path, required=True)
    raw.add_argument("--manifest", type=Path, required=True)
    raw.add_argument("--output", type=Path, required=True)

    environment = subparsers.add_parser("capture-environment", help="Capture the execution environment.")
    environment.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "compare":
        report = compare_artifacts(args.reference, args.candidate, args.policy, args.expected_contract,
                                   scope=args.scope, comparison_reference_path=args.comparison_reference)
        write_report(report, args.output)
        return 0 if report["status"] != "failed" else 1
    if args.command == "verify-inputs":
        report = verify_raw_inputs(args.raw_dir, args.manifest)
        write_report(report, args.output)
        return 0 if report["pass"] else 1
    if args.command == "capture-environment":
        write_report(capture_environment(), args.output)
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
