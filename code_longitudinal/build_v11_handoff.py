from __future__ import annotations

import argparse
import csv
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .paths import ROOT
from .release_scope import load_release_scope
from .utils import file_sha256, write_json
from .verify_v11_handoff import verify_handoff


RELEASE_CONFIG = ROOT / "config" / "releases" / "v1.1.json"
V102_ROOT = ROOT / "work" / "longitudinal_2000_v1.0.2_H0A_H1_validated"
PRODUCTION = (
    ROOT
    / "outputs"
    / "longitudinal_2000_v1"
    / "production"
    / "longitudinal_2000_v1.1_H0A_H1_H2_H3"
)
PANEL_ID = "longitudinal_2000_v1__strict_nested_3000__seed_20260803"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _copy_tree(source: Path, target: Path, *, excluded_names: set[str] | None = None) -> None:
    excluded = excluded_names or set()
    for path in source.rglob("*"):
        if not path.is_file() or any(part in excluded for part in path.relative_to(source).parts):
            continue
        _copy_file(path, target / path.relative_to(source))


def _portable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _portable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_portable(item) for item in value]
    if not isinstance(value, str):
        return value
    for prefix in (str(ROOT), ROOT.as_posix()):
        if value.startswith(prefix):
            return value[len(prefix) :].lstrip("\\/").replace("\\", "/")
    return value.replace("\\", "/") if ":\\" not in value else value


def _v11_run_dirs() -> list[Path]:
    selected: list[Path] = []
    for manifest_path in (ROOT / "outputs" / "runs").glob("*/manifest.json"):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        parameters = payload.get("parameters", {})
        if not isinstance(parameters, dict):
            continue
        if payload.get("scenario_id") not in {"H2", "H3"}:
            continue
        if parameters.get("panel_id", payload.get("panel_id")) != PANEL_ID:
            continue
        if parameters.get("release_id") != "longitudinal_2000_v1.1_H0A_H1_H2_H3":
            continue
        selected.append(manifest_path.parent)
    return sorted(selected)


def _copy_model_ready(staging: Path) -> list[str]:
    source_dir = ROOT / "outputs" / "model_ready"
    target_dir = staging / "outputs" / "model_ready"
    copied: list[str] = []
    token = f"__{PANEL_ID}__n2000"
    parquets = sorted(
        path
        for path in source_dir.glob("*.parquet")
        if token in path.name and ("__H2__" in path.name or "__H3__" in path.name)
    )
    if len(parquets) != 52:
        raise AssertionError(f"found {len(parquets)} fixed-panel H2/H3 model-ready files; expected 52")
    for parquet in parquets:
        manifest = parquet.with_name(parquet.stem + "__manifest.json")
        exclusions = parquet.with_name(parquet.stem + "__excluded.csv")
        if not manifest.is_file() or not exclusions.is_file():
            raise FileNotFoundError(f"model-ready sidecars missing for {parquet.name}")
        _copy_file(parquet, target_dir / parquet.name)
        _copy_file(exclusions, target_dir / exclusions.name)
        payload = _portable(json.loads(manifest.read_text(encoding="utf-8")))
        payload["output"] = f"outputs/model_ready/{parquet.name}"
        payload["panel_source"] = "panel/longitudinal_2000_v1.parquet"
        payload["output_sha256"] = file_sha256(parquet)
        payload["handoff_cache_policy"] = "explicit_opt_in_hash_and_margin_verified"
        write_json(target_dir / manifest.name, payload)
        copied.append(parquet.name)
    return copied


def _copy_runs(staging: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for source in _v11_run_dirs():
        target = staging / "outputs" / "runs" / source.name
        for path in source.iterdir():
            if not path.is_file() or path.name == "trace.nc":
                continue
            _copy_file(path, target / path.name)
        manifest_path = source / "manifest.json"
        payload = _portable(json.loads(manifest_path.read_text(encoding="utf-8")))
        preparation = payload.get("preparation_manifest", {})
        if isinstance(preparation, dict) and preparation.get("output"):
            model_name = Path(str(preparation["output"])).name
            portable_output = staging / "outputs" / "model_ready" / model_name
            preparation["output"] = f"outputs/model_ready/{model_name}"
            if portable_output.is_file():
                preparation["output_sha256"] = file_sha256(portable_output)
        payload["handoff_original_manifest_sha256"] = file_sha256(manifest_path)
        payload["handoff_trace_delivery_included"] = False
        payload["handoff_trace_external_required_for_resume"] = False
        write_json(target / "manifest.json", payload)
        rows.append(
            {
                "run_id": source.name,
                "election_id": payload.get("election_id", ""),
                "scenario_id": payload.get("scenario_id", ""),
                "status": payload.get("status", ""),
                "run_role": payload.get("parameters", {}).get("run_role", ""),
                "trace_included": False,
            }
        )
    return rows


def _status_documents(staging: Path, run_rows: list[dict[str, object]]) -> dict[str, object]:
    status_path = PRODUCTION / "h23_supervisor_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    evaluations_path = PRODUCTION / "h23_run_evaluations.csv"
    evaluations = pd.read_csv(evaluations_path) if evaluations_path.is_file() else pd.DataFrame()
    selections_path = PRODUCTION / "h23_canonical_selection_partial.csv"
    selections = pd.read_csv(selections_path) if selections_path.is_file() else pd.DataFrame()
    failed = []
    if not evaluations.empty and "pilot_pair_resolution" in evaluations:
        failed = evaluations.loc[
            evaluations["pilot_pair_resolution"].fillna("").eq(
                "unresolved_after_single_preregistered_rerun"
            ),
            ["election_id", "scenario_id", "run_id", "mcmc_status", "gate_reasons"],
        ].to_dict("records")
    pilot_columns = [
        "election_id",
        "scenario_id",
        "run_id",
        "run_type",
        "mcmc_status",
        "mcmc_substatus",
        "identification_status",
        "max_rhat",
        "min_ess_bulk",
        "min_ess_tail",
        "min_bfmi",
        "divergences",
        "max_treedepth_hits",
        "krt_contrast",
        "krt_q025",
        "krt_q975",
        "nls_contrast",
        "absolute_krt_nls_difference",
        "pilot_pair_resolution",
    ]
    if not evaluations.empty:
        pilot_frame = evaluations.reindex(columns=pilot_columns).astype(object)
        pilot_evaluations = pilot_frame.where(pd.notna(pilot_frame), None).to_dict("records")
    else:
        pilot_evaluations = []
    completed_pairs = sorted(
        {
            (str(row["election_id"]), str(row["scenario_id"]))
            for row in run_rows
            if row["status"] == "success"
        }
    )
    state: dict[str, object] = {
        "handoff_schema_version": "v11_continuation_handoff_v2",
        "created_at_utc": _utc_now(),
        "handoff_ready_for_continuation": status.get("status") == "paused_after_requested_pair",
        "scientific_release_ready": False,
        "ready_scope": "H0A-H1-H2-H3",
        "supervisor_status": status,
        "canonical_h23_pairs_selected": int(len(selections)),
        "completed_run_attempt_pairs": [list(pair) for pair in completed_pairs],
        "unresolved_pilot_pairs": failed,
        "pilot_evaluations": pilot_evaluations,
        "next_pair": None,
        "pilot_gate_status_counts": {"pass": 3, "hold": 3},
        "all_six_pilots_completed": True,
        "remaining_production_pairs_after_pilots": 46,
        "production_authorized": False,
        "production_block_reason": (
            "The preregistered pilot gate cannot pass while H3-1962, H3-1986 and H2-2022 "
            "remain MCMC fail after their single completed strengthened reruns. All six "
            "pilots are complete; obtain and preregister a scientific specification decision "
            "before rerunning pilots or starting the remaining 46 pairs."
        ),
        "technical_corrections_before_handoff": [
            "supervisor_timeout_now_uses_active_fit_time_and excludes detected Windows sleep",
            "standalone pilot gate now resolves compatible strengthened reruns exactly like the supervisor",
            "portable verified model-ready cache permits continuation without shipping 2+ GB raw archives",
        ],
        "source_test_suite": (
            "119 passed in the combined process; the 3 tests affected by the local Windows "
            "JAX DLL application-control policy passed in isolation; 6/6 targeted gate tests passed"
        ),
        "raw_archives_included": False,
        "raw_archives_required_to_rebuild_model_ready_from_sources": True,
        "verified_model_ready_cache_included": True,
        "netcdf_traces_included": False,
        "validated_v102_base_included": True,
    }
    write_json(staging / "HANDOFF_STATE.json", state)
    failures_text = "\n".join(
        f"- `{row['election_id']} × {row['scenario_id']}`: {row['mcmc_status']} "
        f"({row['gate_reasons']})."
        for row in failed
    ) or "- Aucun échec pilote enregistré."
    pilot_table = [
        "| Élection | Scénario | Run | MCMC | R-hat max | ESS bulk min | BFMI min | KRT contraste | NLS contraste | Écart | Décision |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in pilot_evaluations:
        def number(key: str, digits: int = 4) -> str:
            value = row.get(key)
            return "" if value is None or pd.isna(value) else f"{float(value):.{digits}f}"

        raw_decision = row.get("pilot_pair_resolution")
        decision = "selected" if raw_decision is None or pd.isna(raw_decision) else str(raw_decision)
        pilot_table.append(
            "| "
            + " | ".join(
                [
                    str(row.get("election_id", "")),
                    str(row.get("scenario_id", "")),
                    str(row.get("run_type", "")),
                    str(row.get("mcmc_status", "")),
                    number("max_rhat"),
                    number("min_ess_bulk", 1),
                    number("min_bfmi"),
                    number("krt_contrast"),
                    number("nls_contrast"),
                    number("absolute_krt_nls_difference"),
                    decision,
                ]
            )
            + " |"
        )
    pilot_table_text = "\n".join(pilot_table)
    plan = f"""# Continuer `longitudinal_2000_v1.1` sur un autre PC

## État au transfert

- La release v1.0.2 H0A/H1 est validée et incluse comme base immuable.
- Les 52 KRT H0A/H1 et les 270 NLS restent inchangés.
- Le panel fixe contient 2 000 communes et son SHA-256 est
  `bde70c71660fce29610d7931461d8db6181dba874514a1866b63cf16a81cec4a`.
- La production v1.1 est une candidate, jamais une release validée à ce stade.
- Runs H2/H3 canoniques actuellement sélectionnés : {len(selections)}.
- Les six pilotes sont terminés ; aucun nouveau couple n'est autorisé sous la spécification actuelle.
- Porte pilote formelle : `3 pass / 3 hold`, donc `go_for_remaining_46_runs=false`.

Pilotes non résolus après leur unique relance renforcée :

{failures_text}

### Tableau complet des pilotes déjà exécutés

{pilot_table_text}

H2-2022 a un contraste KRT très proche du NLS, mais son BFMI reste sous le seuil
de fail après la relance renforcée. Il est donc audité, non canonique. H3-2022 est
sélectionné après sa relance renforcée compatible, avec réserve MCMC explicite.

Le superviseur a également été corrigé pour que le plafond de 12 heures porte sur le
temps actif de calcul et non sur les heures de veille Windows. Le chronomètre conserve
séparément temps actif, temps mural, durée suspendue et nombre de suspensions.

## Démarrage sur Windows

1. Extraire le ZIP dans un chemin court, par exemple `D:\\ARE\\longitudinal_handoff`.
2. Ouvrir PowerShell dans le dossier extrait.
3. Exécuter `powershell -ExecutionPolicy Bypass -File .\\01_SETUP_WINDOWS.ps1`.
4. Exécuter `powershell -ExecutionPolicy Bypass -File .\\02_VERIFY_HANDOFF.ps1`.
5. Reproduire l'audit de la porte, sans lancer de nouveau modèle :
   `powershell -ExecutionPolicy Bypass -File .\\03_REEVALUATE_GATE.ps1`.
6. Le résultat doit rester `3 pass / 3 hold` et
   `go_for_remaining_46_runs=false` tant que la spécification n'a pas été révisée.
7. La commande sous-jacente est
   `.\\.venv\\Scripts\\python.exe -m code_longitudinal.v11_pipeline h23-gate --release-config config\\releases\\v1.1.json`.

## Porte scientifique obligatoire

Les six pilotes ont été calculés. Les 46 autres runs ne doivent pas être lancés sous cette
spécification tant que la porte pilote échoue. H3-1962, H3-1986 et H2-2022 ont échoué deux
fois sur les diagnostics MCMC, alors que leurs diagnostics d’identification écologique sont
stockés séparément. Une nouvelle paramétrisation ou une modification des priors doit être
préenregistrée sous une nouvelle version de spécification, puis les six pilotes doivent être
rejoués avant la production complète. La porte ne doit jamais être contournée en sélectionnant
les résultats substantifs les plus favorables.

## Données et portabilité

Les 52 matrices exactes H2/H3 sont incluses avec leurs hashes et leurs contrôles de marges.
Le script de reprise active explicitement leur réutilisation vérifiée. Les archives brutes
de plus de 2 Go ne sont pas incluses : elles restent nécessaires uniquement pour reconstruire
les matrices et l’audit depuis les sources. Les NetCDF ne sont pas inclus ; ils ne sont pas
nécessaires pour reprendre, car les résumés communaux, agrégats et diagnostics sont présents.

## Suite après une porte pilote valide

1. Exécuter les 46 autres runs séquentiellement et reprendre uniquement les interruptions.
2. Sélectionner exactement 104 runs canoniques H0A/H1/H2/H3.
3. Consolider 208 000 lignes communales et 312 agrégats.
4. Vérifier l’invariance numérique exacte de H0A/H1 par rapport à v1.0.2.
5. Produire figures, rapport HTML/PDF, audit final et deux ZIP v1.1.
6. Ne définir `ready=true` que pour `ready_scope=H0A-H1-H2-H3` après toutes les portes.

L’ordre scientifique ultérieur reste : `H6/H7 → H0B/H0C → H4/H5 → RxC 3×2 → RxC 3×5`.
"""
    (staging / "HANDOFF_PLAN_AND_STATE.md").write_text(plan, encoding="utf-8")
    return state


def _write_scripts(staging: Path) -> None:
    setup = r'''param([string]$PythonLauncher = "py")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root
& $PythonLauncher -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements-handoff-v1.1.txt
'''
    verify = r'''$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root
$env:LONGITUDINAL_PROJECT_ROOT = $root
$env:LONGITUDINAL_ALLOW_VERIFIED_MODEL_READY_CACHE = "1"
& .\.venv\Scripts\python.exe -m code_longitudinal.verify_v11_handoff --root $root
$stamp = Get-Date -Format "yyyyMMddTHHmmss"
& .\.venv\Scripts\python.exe -m pytest tests -q --basetemp (Join-Path $root "work\pytest_handoff_$stamp")
'''
    gate = r'''$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root
$env:LONGITUDINAL_PROJECT_ROOT = $root
$env:LONGITUDINAL_ALLOW_VERIFIED_MODEL_READY_CACHE = "1"
& .\.venv\Scripts\python.exe -m code_longitudinal.v11_pipeline h23-gate `
  --release-config config\releases\v1.1.json
'''
    (staging / "01_SETUP_WINDOWS.ps1").write_text(setup, encoding="utf-8")
    (staging / "02_VERIFY_HANDOFF.ps1").write_text(verify, encoding="utf-8")
    (staging / "03_REEVALUATE_GATE.ps1").write_text(gate, encoding="utf-8")


def _manifest_rows(staging: Path) -> list[dict[str, object]]:
    rows = []
    for path in sorted(item for item in staging.rglob("*") if item.is_file()):
        if path.name == "HANDOFF_MANIFEST_SHA256.csv":
            continue
        rows.append(
            {
                "delivery_path": path.relative_to(staging).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }
        )
    return rows


def _write_hash_manifest(staging: Path) -> None:
    rows = _manifest_rows(staging)
    with (staging / "HANDOFF_MANIFEST_SHA256.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["delivery_path", "bytes", "sha256"])
        writer.writeheader()
        writer.writerows(rows)


def build_handoff(staging: Path, output_zip: Path) -> dict[str, object]:
    staging = (staging if staging.is_absolute() else ROOT / staging).resolve()
    output_zip = (output_zip if output_zip.is_absolute() else ROOT / output_zip).resolve()
    scope = load_release_scope(RELEASE_CONFIG)
    supervisor_status = json.loads((PRODUCTION / "h23_supervisor_status.json").read_text(encoding="utf-8"))
    if supervisor_status.get("status") != "paused_after_requested_pair":
        raise RuntimeError("the supervisor has not paused cleanly after the requested pilot")
    if staging.exists() or output_zip.exists():
        raise FileExistsError("refusing to overwrite an existing handoff staging directory or ZIP")
    staging.mkdir(parents=True)
    for filename in (
        "README.md",
        "R_REQUIREMENTS.md",
        "requirements-dev.txt",
        "requirements-production-v101.txt",
        "requirements-handoff-v1.1.txt",
    ):
        _copy_file(ROOT / filename, staging / filename)
    _copy_tree(ROOT / "code_longitudinal", staging / "code_longitudinal", excluded_names={"__pycache__"})
    _copy_tree(ROOT / "tests", staging / "tests", excluded_names={"__pycache__"})
    _copy_tree(ROOT / "config", staging / "config")
    _copy_tree(ROOT / "panel", staging / "panel")
    if (ROOT / "r_replication").is_dir():
        _copy_tree(ROOT / "r_replication", staging / "r_replication")
    _copy_tree(V102_ROOT, staging / "work" / V102_ROOT.name, excluded_names={"__pycache__", ".pytest_cache"})
    audit = ROOT / "outputs" / "longitudinal_2000_v1" / "audit"
    _copy_tree(audit, staging / "outputs" / "longitudinal_2000_v1" / "audit")
    # Retained solely because the complete regression suite checks the legacy
    # one-row-per-commune/parameter consolidation contract against this file.
    _copy_file(
        ROOT / "outputs" / "commune_beta_estimates.parquet",
        staging / "outputs" / "commune_beta_estimates.parquet",
    )
    _copy_tree(PRODUCTION, staging / PRODUCTION.relative_to(ROOT), excluded_names={"trace.nc"})
    model_ready_names = _copy_model_ready(staging)
    run_rows = _copy_runs(staging)
    state = _status_documents(staging, run_rows)
    _write_scripts(staging)
    write_json(
        staging / "HANDOFF_MANIFEST.json",
        {
            "handoff_id": output_zip.stem,
            "created_at_utc": _utc_now(),
            "source_release_id": scope.release_id,
            "source_ready_scope": scope.ready_scope,
            "scientific_release_ready": False,
            "panel_sha256": scope.panel_sha256,
            "model_ready_pairs": len(model_ready_names),
            "run_directories": len(run_rows),
            "original_v102_professor_zip_sha256": "ccd4ad0ed7c75e3dece34f7ebe1c1a3afa1e6772e65e85a6fd46e2b50ff917f8",
            "original_v102_technical_zip_sha256": "db7bc3a04049f56b80dc40bc563044cbdc9ba4aa67b194b038b2e4c00e29bc97",
            "netcdf_included": False,
            "raw_archives_included": False,
            "portable_model_ready_cache": True,
        },
    )
    _write_hash_manifest(staging)
    verification = verify_handoff(staging)
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(item for item in staging.rglob("*") if item.is_file()):
            archive.write(path, path.relative_to(staging).as_posix())
    with zipfile.ZipFile(output_zip) as archive:
        if archive.testzip() is not None:
            raise AssertionError("handoff ZIP CRC validation failed")
    zip_hash = file_sha256(output_zip)
    output_zip.with_suffix(output_zip.suffix + ".sha256").write_text(
        f"{zip_hash}  {output_zip.name}\n",
        encoding="ascii",
    )
    receipt = {
        "status": "pass",
        "created_at_utc": _utc_now(),
        "zip_path": output_zip.relative_to(ROOT).as_posix(),
        "zip_bytes": output_zip.stat().st_size,
        "zip_sha256": zip_hash,
        "staging_path": staging.relative_to(ROOT).as_posix(),
        "internal_verification": verification,
        "handoff_state": state,
    }
    write_json(output_zip.with_suffix(".build_receipt.json"), receipt)
    return receipt


def finalize_existing_handoff(staging: Path, output_zip: Path) -> dict[str, object]:
    """Finish receipts and checks after a completed ZIP build."""
    staging = (staging if staging.is_absolute() else ROOT / staging).resolve()
    output_zip = (output_zip if output_zip.is_absolute() else ROOT / output_zip).resolve()
    if not staging.is_dir() or not output_zip.is_file():
        raise FileNotFoundError("existing staging directory and ZIP are both required")
    verification = verify_handoff(staging)
    with zipfile.ZipFile(output_zip) as archive:
        if archive.testzip() is not None:
            raise AssertionError("handoff ZIP CRC validation failed")
    zip_hash = file_sha256(output_zip)
    output_zip.with_suffix(output_zip.suffix + ".sha256").write_text(
        f"{zip_hash}  {output_zip.name}\n",
        encoding="ascii",
    )
    state = json.loads((staging / "HANDOFF_STATE.json").read_text(encoding="utf-8"))
    receipt = {
        "status": "pass",
        "created_at_utc": _utc_now(),
        "zip_path": output_zip.relative_to(ROOT).as_posix(),
        "zip_bytes": output_zip.stat().st_size,
        "zip_sha256": zip_hash,
        "staging_path": staging.relative_to(ROOT).as_posix(),
        "internal_verification": verification,
        "handoff_state": state,
        "finalized_from_existing_complete_zip": True,
    }
    write_json(output_zip.with_suffix(".build_receipt.json"), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the portable v1.1 continuation handoff ZIP.")
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--output-zip", type=Path, required=True)
    parser.add_argument("--finalize-existing", action="store_true")
    args = parser.parse_args()
    result = (
        finalize_existing_handoff(args.staging, args.output_zip)
        if args.finalize_existing
        else build_handoff(args.staging, args.output_zip)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
