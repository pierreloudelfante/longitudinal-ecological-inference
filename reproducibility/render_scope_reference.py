"""Comparison-only rendering of a declared subset of the fixed reference ZIP.

This is not a replication or an estimator. Only the plotting/document workers
are called, on historical reference tables. Nothing from this module is written
to the candidate's outputs, panel, work, or deliverables directories. Numeric
certification must still compare candidate tables directly with the fixed ZIP.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import ModuleType
import zipfile

from reproducibility.replication_scope import ENVIRONMENT_KEY, get_scope

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "scope_comparison_reference_v1"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def validate_destination(destination: Path, *, project_root: Path = ROOT) -> Path:
    """Reject overlapping trees, including paths reached through symlinks."""
    destination = destination.expanduser().resolve()
    project_root = project_root.resolve()
    protected = [project_root / name for name in ("outputs", "panel", "work", "deliverables")]
    if destination == Path(destination.anchor) or project_root.is_relative_to(destination):
        raise ValueError("Comparison destination cannot be a filesystem/project root or its ancestor")
    for tree in protected:
        tree = tree.resolve()
        if destination.is_relative_to(tree) or tree.is_relative_to(destination):
            raise ValueError("Comparison destination overlaps candidate scientific outputs: " + str(tree))
    return destination


def _redirect_path_value(value, destination: Path):
    if isinstance(value, Path):
        try:
            return destination / value.relative_to(ROOT)
        except ValueError:
            return value
    if isinstance(value, dict):
        return {key: _redirect_path_value(item, destination) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_redirect_path_value(item, destination) for item in value)
    if isinstance(value, list):
        return [_redirect_path_value(item, destination) for item in value]
    return value


@contextmanager
def isolated_module_paths(modules: list[ModuleType], destination: Path, overrides=None):
    """Redirect path constants only; never replace a calculation or estimator.

    Used in a dedicated rendering process. Original globals are restored even
    after an error, so reference paths cannot leak into later candidate work.
    """
    saved = []
    try:
        for module in modules:
            for name, value in list(vars(module).items()):
                if name.isupper() and isinstance(value, (Path, dict, tuple, list)):
                    replacement = _redirect_path_value(value, destination)
                    if replacement != value:
                        saved.append((module, name, value))
                        setattr(module, name, replacement)
        for module, name, value in overrides or ():
            saved.append((module, name, getattr(module, name)))
            setattr(module, name, value)
        yield
    finally:
        for module, name, value in reversed(saved):
            setattr(module, name, value)


@contextmanager
def _environment(values: dict[str, str]):
    previous = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def _arguments(arguments: list[str]):
    previous = sys.argv
    try:
        sys.argv = arguments
        yield
    finally:
        sys.argv = previous


def _reference_tables(archive: Path, scratch: Path, scope) -> tuple[dict[str, int], list[dict]]:
    import pandas as pd
    from reproducibility.replication_complete import result_contract_for_scope
    light = scratch / "work/longitudinal_2000_release_professeur_candidate"
    row_counts = {}
    inputs = []
    with zipfile.ZipFile(archive) as stream:
        for entry in result_contract_for_scope()["files"]:
            if "parquet" not in entry:
                continue
            raw = stream.read(entry["path"])
            if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                raise ValueError("Fixed reference member hash mismatch: " + entry["path"])
            frame = scope.filter_frame(pd.read_parquet(io.BytesIO(raw)))
            if len(frame) != entry["parquet"]["rows"]:
                raise ValueError("Projected reference table row count mismatch: " + entry["path"])
            output = light / entry["path"]
            output.parent.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(output, index=False)
            row_counts[output.name] = len(frame)
            inputs.append({"fixed_zip_member": entry["path"], "source_sha256": entry["sha256"],
                           "projected_rows": len(frame), "projected_sha256": sha256(output)})
        path = "06_DOCUMENTATION/MODEL_SCENARIOS.csv"
        frame = scope.filter_frame(pd.read_csv(io.BytesIO(stream.read(path))))
        output = scratch / "reference_inputs/MODEL_SCENARIOS.csv"
        output.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(output, index=False, encoding="utf-8-sig")
    return row_counts, inputs


def _render_workers(scratch: Path, rscript: Path, browser: Path, row_counts: dict[str, int]) -> None:
    import pandas as pd
    from code_longitudinal import build_professor_release_assets as assets
    from code_longitudinal import build_full240_professor_release as full
    from code_longitudinal import compare_python_r_ei_full_240 as comparison
    from code_longitudinal import export_density_pair_inputs as export
    from code_longitudinal import finalize_density_bundle as density
    from code_longitudinal import build_density_report_atlas as atlas
    from code_longitudinal import repair_portable_report_from_template as portable
    from reproducibility import replication_complete as production

    light = scratch / "work/longitudinal_2000_release_professeur_candidate"
    tables = light / "02_TABLES_PRINCIPALES"
    transparent = scratch / "work/longitudinal_2000_v1_full_240_professeur_candidate/02_BASE_TRANSPARENTE"
    transparent.mkdir(parents=True, exist_ok=True)
    comparison_path = transparent / "comparaison_python_r.parquet"
    # The final R table contains metadata joined by the production asset worker.
    # _normalize_results performs the same join; remove only its two join
    # columns from this isolated input to recover the upstream table interface.
    r_upstream = scratch / "reference_inputs/r_aggregate_before_metadata_join.parquet"
    pd.read_parquet(tables / "longitudinal_r_ei_aggregate.parquet").drop(
        columns=["year", "round"]).to_parquet(r_upstream, index=False)
    overrides = [
        (assets, "KRT_AGG", tables / "longitudinal_krt_aggregate.parquet"),
        (assets, "KRT_COMMUNE", tables / "longitudinal_krt_commune.parquet"),
        (assets, "R_AGG", tables / "longitudinal_r_ei_aggregate.parquet"),
        (assets, "R_COMMUNE", tables / "longitudinal_r_ei_commune.parquet"),
        (assets, "NLS", tables / "longitudinal_nls.parquet"),
        (assets, "NLS_COV", tables / "longitudinal_nls_covariates.parquet"),
        (assets, "NLS_COV_COEFFICIENTS", tables / "longitudinal_nls_covariate_coefficients.parquet"),
        (assets, "SCENARIOS", scratch / "reference_inputs/MODEL_SCENARIOS.csv"),
        (comparison, "PYTHON_AGGREGATE", tables / "longitudinal_krt_aggregate.parquet"),
        (comparison, "R_AGGREGATE", tables / "longitudinal_r_ei_aggregate.parquet"),
        (full, "PYTHON_AGGREGATE", tables / "longitudinal_krt_aggregate.parquet"),
        (full, "R_AGGREGATE", r_upstream),
        (full, "NLS_RESULTS", tables / "longitudinal_nls.parquet"),
        (full, "COMPARISON_AGGREGATE", comparison_path),
        (production, "STATE_DIR", scratch / ".runtime/render_pdf"),
    ]
    modules = [assets, full, comparison, export, density, atlas, portable, production]
    with isolated_module_paths(modules, scratch, overrides):
        print("COMPARISON ONLY: production normalization of fixed reference subset", flush=True)
        comparison._build_aggregate_comparison().to_parquet(comparison_path, index=False)
        base, _, _, _ = full._normalize_results()
        base.to_parquet(transparent / "base_resultats_long.parquet", index=False)
        assets.DIAG_DIR.mkdir(parents=True, exist_ok=True)
        assets.krt_status_summary(pd.read_parquet(assets.KRT_AGG)).to_csv(
            assets.DIAG_DIR / "diagnostics_KRT_par_hypothese.csv", index=False, encoding="utf-8-sig")

        print("COMPARISON ONLY: production figures, documentation, and report artifact", flush=True)
        assets.build_figures()
        assets.compose_slide_figures(project_root=scratch,
                                    script_path=ROOT / "reproducibility/presentation/compose_slide_figures.ps1")
        assets.build_documentation(row_counts)
        assets.build_report_artifact()

        print("COMPARISON ONLY: production R densities and atlas", flush=True)
        export.main()
        subprocess.run([str(rscript), "--vanilla", str(ROOT / "r_replication/generate_all_pair_density_figures.R"),
                        str(scratch)], cwd=scratch, env=os.environ.copy(), check=True,
                       stdout=sys.stdout, stderr=sys.stderr)
        original_write = density.write_json
        def truthful_qa(path, payload):
            if isinstance(payload, dict) and "visual_samples_inspected" in payload:
                payload = dict(payload, visual_samples_inspected=0, visual_samples=[],
                               visual_inspection_complete_for_samples=False,
                               qa_scope="automated_file_and_dimension_checks_only")
            original_write(path, payload)
        density.write_json = truthful_qa
        try:
            density.main()
        finally:
            density.write_json = original_write
        with _arguments(["build_density_report_atlas", "--output", str(light)]):
            atlas.main()
        print("COMPARISON ONLY: production portable HTML and PDF", flush=True)
        with _arguments(["repair_portable_report_from_template", "--template-zip",
                         str(ROOT / "reproducibility/report/RAPPORT_LONGITUDINAL.template.html")]):
            portable.main()
        production.render_pdf(light / "01_RAPPORT/RAPPORT_LONGITUDINAL.html",
                              light / "01_RAPPORT/RAPPORT_LONGITUDINAL.pdf", str(browser))


def render_scope_reference(reference_zip: Path, destination: Path, *, rscript: Path, browser: Path,
                           scope_name: str = "court") -> dict:
    scope = get_scope(scope_name)
    if scope.is_full:
        raise ValueError("The complete campaign compares directly with its fixed reference artifacts")
    destination = validate_destination(destination)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Comparison destination must be empty; preserve previous rendering evidence")
    for executable in (rscript, browser):
        if not Path(executable).is_file():
            raise FileNotFoundError(executable)
    from reproducibility.replication_complete import validate_reference_archive
    from reproducibility.certify_reproduction import (
        COMPARISON_REFERENCE_RECEIPT, projection_artifact_paths, projection_code_hashes,
    )
    from reproducibility.result_scope import project_result_contract
    reference_zip = reference_zip.expanduser().resolve()
    reference = validate_reference_archive(reference_zip)
    contract = json.loads((ROOT / "reproducibility/contract_v2/expected_results_610.json").read_text(encoding="utf-8"))
    expected = projection_artifact_paths([entry["path"] for entry in project_result_contract(contract, scope)["files"]])
    code_hashes = projection_code_hashes()
    renderer_hash = sha256(Path(__file__))
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Edge's PDF output remains sensitive to long Windows paths even when
    # Python can write them. Keep the isolated sibling's name short; the full
    # production work/report subtree below it is deliberately unchanged.
    scratch = Path(tempfile.mkdtemp(prefix="ref_", dir=destination.parent)).resolve()
    validate_destination(scratch)
    for relative in ("reproducibility/contract_v2/krt_replay_240.json",
                     "code_longitudinal/export_density_pair_inputs.py",
                     "r_replication/generate_all_pair_density_figures.R"):
        target = scratch / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    log_path = scratch / "comparison_render.log"
    env = {ENVIRONMENT_KEY: scope.name, "MPLBACKEND": "Agg", "MPLCONFIGDIR": str(scratch / ".cache/matplotlib"),
           "R_LIBS_USER": str(ROOT / ".cache/R/library"), "R_LIBS": "", "R_LIBS_SITE": "",
           "PYTHONHASHSEED": "0", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
           "OPENBLAS_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1"}
    try:
        with _environment(env), log_path.open("w", encoding="utf-8") as log, redirect_stdout(log), redirect_stderr(log):
            row_counts, inputs = _reference_tables(reference_zip, scratch, scope)
            _render_workers(scratch, Path(rscript).resolve(), Path(browser).resolve(), row_counts)
        if projection_code_hashes() != code_hashes or sha256(Path(__file__)) != renderer_hash:
            raise RuntimeError("Rendering code changed during comparison reference generation")
        light = scratch / "work/longitudinal_2000_release_professeur_candidate"
        missing = sorted(path for path in expected if not (light / path).is_file())
        if missing:
            raise RuntimeError("Production comparison rendering missing artifacts: " + ", ".join(missing))
        destination.mkdir(parents=True, exist_ok=True)
        files = []
        for relative in sorted(expected):
            source, target = light / relative, destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            files.append({"path": relative, "bytes": target.stat().st_size, "sha256": sha256(target)})
        receipt = {"schema_version": SCHEMA_VERSION, "source_archive_sha256": reference["sha256"],
                   "scope": scope.as_dict(), "renderer_code_sha256": renderer_hash,
                   "production_code_hashes": code_hashes, "comparison_only": True,
                   "derived_from_fixed_reference": True, "candidate_outputs_used": False,
                   "generated_at_utc": datetime.now(timezone.utc).isoformat(), "files": files,
                   "scratch_evidence_path": str(scratch), "render_log_sha256": sha256(log_path),
                   "reference_inputs": inputs,
                   "numeric_tables_comparison": "direct_filtered_fixed_archive_not_this_rendering",
                   "estimators_executed": False, "replication_claim": False}
        _write_json(destination / COMPARISON_REFERENCE_RECEIPT, receipt)
        _write_json(scratch / "COMPARISON_RENDER_COMPLETE.json", receipt)
        return receipt
    except BaseException as exc:
        _write_json(scratch / "COMPARISON_RENDER_FAILURE.json", {
            "status": "failed", "comparison_only": True, "error": str(exc),
            "source_archive_sha256": reference["sha256"], "scope": scope.as_dict(),
            "log": str(log_path), "candidate_outputs_used": False})
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-results", type=Path, required=True)
    parser.add_argument("--destination", type=Path, default=ROOT / ".runtime/replication_court/comparison_reference")
    parser.add_argument("--rscript", type=Path, required=True)
    parser.add_argument("--browser", type=Path, required=True)
    args = parser.parse_args()
    receipt = render_scope_reference(args.reference_results, args.destination, rscript=args.rscript, browser=args.browser)
    print(json.dumps({"status": "comparison_reference_rendered_not_replication", "destination": str(args.destination),
                      "files": len(receipt["files"]), "source_archive_sha256": receipt["source_archive_sha256"]}))


if __name__ == "__main__":
    main()
