from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any, Callable, Mapping

from .paths import ROOT, RUNS_DIR
from .release_scope import ReleaseScope
from .utils import file_sha256


def safe_clean_staging(path: Path, expected_name: str) -> None:
    work = (ROOT / "work").resolve()
    resolved = path.resolve()
    if resolved.parent != work or resolved.name != expected_name:
        raise ValueError(f"refusing to replace unexpected staging directory: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True)


def copy_file(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def _sanitize_string(value: str) -> str:
    normalized = value.replace(str(ROOT), ".").replace(ROOT.as_posix(), ".")
    candidate = Path(normalized)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            return f"external_required/{candidate.name}"
    return normalized.replace("\\", "/")


def sanitize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {_sanitize_string(str(key)): sanitize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, str):
        return _sanitize_string(value)
    return value


def copy_run_diagnostics(run_id: str, destination: Path, *, kind: str) -> None:
    source = RUNS_DIR / run_id
    files = (
        (
            "model_diagnostics.csv", "manifest.json", "mcmc_diagnostics_v2.json",
            "identification_diagnostics.json", "aggregate_comparison_v2.csv",
            "mcmc_variable_metrics_v2.csv", "mcmc_block_metrics_v2.csv",
        )
        if kind == "krt"
        else ("model_diagnostics.csv", "manifest.json", "nls_start_diagnostics.csv", "nls_coefficients.csv")
    )
    target = destination / "06_diagnostics_runs" / kind / run_id
    for filename in files:
        path = source / filename
        if not path.exists():
            continue
        if filename == "manifest.json":
            manifest = sanitize_value(json.loads(path.read_text(encoding="utf-8")))
            manifest["runtime_path"] = f"outputs/runs/{run_id}"
            manifest["delivery_path"] = f"06_diagnostics_runs/{kind}/{run_id}"
            manifest["delivery_included"] = True
            manifest["external_required"] = True
            write_json(target / filename, manifest)
        else:
            copy_file(path, target / filename)


def delivery_manifest(staging: Path, scope: ReleaseScope, archive_role: str) -> dict[str, Any]:
    files = []
    for path in sorted(staging.rglob("*")):
        if path.is_file() and path.name != "DELIVERY_MANIFEST.json":
            files.append({
                "delivery_path": path.relative_to(staging).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            })
    manifest = {
        "release_id": scope.release_id,
        "archive_role": archive_role,
        "ready": True,
        "ready_scope": scope.ready_scope,
        "delivery_root": ".",
        "contains_netcdf": False,
        "files": files,
    }
    write_json(staging / "DELIVERY_MANIFEST.json", manifest)
    return manifest


def zip_verify(
    staging: Path,
    zip_path: Path,
    *,
    scan: Callable[[Path], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = zip_path.with_suffix(".zip.tmp")
    if temporary.exists():
        temporary.unlink()
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(staging).as_posix())
    temporary.replace(zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise AssertionError(f"ZIP CRC failure: {bad}")
        verification_name = f"zip_reextract_{zip_path.stem}"
        extracted = ROOT / "work" / verification_name
        safe_clean_staging(extracted, verification_name)
        archive.extractall(extracted)
        manifest = json.loads((extracted / "DELIVERY_MANIFEST.json").read_text(encoding="utf-8"))
        for item in manifest["files"]:
            path = extracted / item["delivery_path"]
            if not path.exists() or file_sha256(path) != item["sha256"]:
                raise AssertionError(f"delivery hash mismatch after extraction: {item['delivery_path']}")
        if scan is not None:
            scan(extracted)
    digest = file_sha256(zip_path)
    write_text(zip_path.with_suffix(zip_path.suffix + ".sha256"), f"{digest}  {zip_path.name}\n")
    return {"path": str(zip_path), "sha256": digest, "size_bytes": zip_path.stat().st_size}


__all__ = [
    "copy_file",
    "copy_run_diagnostics",
    "delivery_manifest",
    "safe_clean_staging",
    "sanitize_value",
    "write_json",
    "write_text",
    "zip_verify",
]
