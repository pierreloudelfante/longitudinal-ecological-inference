from __future__ import annotations

import argparse
import csv
import json
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .package_current_progress_snapshot import create_stage
from .paths import ROOT, RUNS_DIR
from .utils import file_sha256, write_json


EXPECTED_PANEL_SHA256 = "bde70c71660fce29610d7931461d8db6181dba874514a1866b63cf16a81cec4a"
EXPECTED_KRT_PAIRS = 240
EXPECTED_NLS_PAIRS = 292
PANEL_ID = "longitudinal_2000_v1__strict_nested_3000__seed_20260803"
SELECTION_SOURCE = (
    ROOT
    / "outputs"
    / "longitudinal_2000_v1"
    / "production"
    / "all_2x2_candidate"
    / "krt_240_candidate_selection.csv"
)
R_PLAN_SOURCE = (
    ROOT
    / "outputs"
    / "longitudinal_2000_v1"
    / "r_replication"
    / "krt_exact_nimble_plan_240.csv"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _copy(source: Path, target: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _copy_tree(
    source: Path,
    target: Path,
    *,
    excluded_names: set[str] | None = None,
    excluded_suffixes: set[str] | None = None,
) -> None:
    names = excluded_names or set()
    suffixes = {value.lower() for value in (excluded_suffixes or set())}
    if not source.is_dir():
        return
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if any(part in names for part in relative.parts):
            continue
        if path.suffix.lower() in suffixes:
            continue
        _copy(path, target / relative)


def _portable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _portable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_portable(item) for item in value]
    if not isinstance(value, str):
        return value
    normalized = value.replace("\\", "/")
    root_values = (str(ROOT).replace("\\", "/"), ROOT.as_posix())
    for prefix in root_values:
        if normalized.lower().startswith(prefix.lower()):
            return normalized[len(prefix) :].lstrip("/")
    return normalized


def _copy_project_sources(stage: Path) -> None:
    for filename in (
        "README.md",
        "R_REQUIREMENTS.md",
        "requirements-dev.txt",
        "requirements-handoff-v1.1.txt",
        "requirements-production-v101.txt",
    ):
        source = ROOT / filename
        if source.is_file():
            _copy(source, stage / filename)
    for source in ROOT.glob("*.ps1"):
        _copy(source, stage / "technical" / "historical_runtime_scripts" / source.name)
    for dirname in ("code_longitudinal", "config", "tests", "docs", "legacy", "r_replication"):
        _copy_tree(
            ROOT / dirname,
            stage / dirname,
            excluded_names={"__pycache__", ".pytest_cache"},
            excluded_suffixes={".pyc", ".pyo", ".nc"},
        )
    _copy_tree(ROOT / "panel", stage / "panel", excluded_suffixes={".nc"})


def _copy_model_ready(stage: Path, plan: pd.DataFrame) -> list[dict[str, Any]]:
    destination = stage / "outputs" / "model_ready"
    rows: list[dict[str, Any]] = []
    if len(plan) != EXPECTED_KRT_PAIRS:
        raise AssertionError(f"R plan has {len(plan)} rows; expected {EXPECTED_KRT_PAIRS}")
    for item in plan.to_dict("records"):
        csv_source = ROOT / str(item["input_csv"])
        if not csv_source.is_file():
            raise FileNotFoundError(csv_source)
        observed_csv_hash = file_sha256(csv_source)
        stem = csv_source.stem
        required = (
            csv_source,
            csv_source.with_suffix(".parquet"),
            csv_source.with_name(stem + "__excluded.csv"),
            csv_source.with_name(stem + "__manifest.json"),
        )
        for source in required:
            if not source.is_file():
                raise FileNotFoundError(source)
            target = destination / source.name
            if source.name.endswith("__manifest.json"):
                payload = _portable(json.loads(source.read_text(encoding="utf-8")))
                parquet_name = csv_source.with_suffix(".parquet").name
                payload["output"] = f"outputs/model_ready/{parquet_name}"
                payload["output_sha256"] = file_sha256(csv_source.with_suffix(".parquet"))
                payload["panel_source"] = "panel/longitudinal_2000_v1.parquet"
                payload["handoff_cache_policy"] = "hash_and_margin_verified_portable_cache"
                write_json(target, payload)
            else:
                _copy(source, target)
        csv_frame = pd.read_csv(csv_source)
        parquet_frame = pd.read_parquet(csv_source.with_suffix(".parquet"))
        if len(csv_frame) != 2000 or len(parquet_frame) != 2000:
            raise AssertionError(f"model-ready row count is not 2,000: {csv_source.name}")
        if not csv_frame["unit_id"].astype(str).equals(parquet_frame["unit_id"].astype(str)):
            raise AssertionError(f"CSV/Parquet unit_id mismatch: {csv_source.name}")
        model_columns = [
            column
            for column in csv_frame.columns
            if column == "N_g" or column.startswith(("X__", "N__", "Y__"))
        ]
        if set(model_columns) != {
            column
            for column in parquet_frame.columns
            if column == "N_g" or column.startswith(("X__", "N__", "Y__"))
        }:
            raise AssertionError(f"CSV/Parquet model column mismatch: {csv_source.name}")
        max_abs_diff = 0.0
        for column in model_columns:
            left = pd.to_numeric(csv_frame[column], errors="raise")
            right = pd.to_numeric(parquet_frame[column], errors="raise")
            difference = (left - right).abs().max()
            max_abs_diff = max(max_abs_diff, 0.0 if pd.isna(difference) else float(difference))
        if max_abs_diff > 5e-15:
            raise AssertionError(
                f"CSV/Parquet model matrix difference exceeds tolerance for {csv_source.name}: "
                f"{max_abs_diff:.17g}"
            )
        rows.append(
            {
                "election_id": item["election_id"],
                "scenario_id": item["scenario_id"],
                "input_csv": f"outputs/model_ready/{csv_source.name}",
                "input_csv_sha256": observed_csv_hash,
                "input_csv_plan_sha256_before_handoff": str(item["input_sha256"]),
                "input_csv_plan_hash_status_before_handoff": (
                    "match" if observed_csv_hash == str(item["input_sha256"]) else "stale_hash"
                ),
                "input_parquet": f"outputs/model_ready/{csv_source.with_suffix('.parquet').name}",
                "input_parquet_sha256": file_sha256(csv_source.with_suffix(".parquet")),
                "csv_parquet_model_matrix_max_abs_diff": max_abs_diff,
                "csv_parquet_unit_id_status": "exact_match",
            }
        )
    return rows


def _synchronize_staged_r_plan(stage: Path, plan: pd.DataFrame, model_rows: list[dict[str, Any]]) -> int:
    destination_dir = stage / "outputs" / "longitudinal_2000_v1" / "r_replication"
    plan_path = destination_dir / "krt_exact_nimble_plan_240.csv"
    original_plan_path = destination_dir / "krt_exact_nimble_plan_240_before_handoff_sync.csv"
    if plan_path.is_file():
        shutil.copy2(plan_path, original_plan_path)
    observed = {
        (str(row["election_id"]), str(row["scenario_id"])): str(row["input_csv_sha256"])
        for row in model_rows
    }
    synchronized = plan.copy()
    stale = 0
    for index, row in synchronized.iterrows():
        key = (str(row["election_id"]), str(row["scenario_id"]))
        actual = observed[key]
        stale += int(str(row["input_sha256"]) != actual)
        synchronized.at[index, "input_sha256"] = actual
    synchronized.to_csv(plan_path, index=False, encoding="utf-8-sig")
    audit = pd.DataFrame(model_rows)[
        [
            "election_id",
            "scenario_id",
            "input_csv",
            "input_csv_plan_sha256_before_handoff",
            "input_csv_sha256",
            "input_csv_plan_hash_status_before_handoff",
            "csv_parquet_model_matrix_max_abs_diff",
            "csv_parquet_unit_id_status",
        ]
    ]
    audit.to_csv(destination_dir / "krt_exact_nimble_plan_hash_sync_audit.csv", index=False, encoding="utf-8-sig")
    manifest_path = destination_dir / "krt_exact_nimble_plan_240.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    manifest.update(
        {
            "handoff_synchronized_at_utc": _utc_now(),
            "plan_sha256": file_sha256(plan_path),
            "pairs_planned": len(synchronized),
            "stale_input_hashes_corrected_for_handoff": stale,
            "synchronization_reason": (
                "Some model-ready CSV files were rewritten after the waiting R process first "
                "materialized its plan. The handoff plan records the delivered bytes. CSV and "
                "Parquet model matrices were checked pair-by-pair with exact unit_id order and "
                "maximum absolute numeric tolerance 5e-15."
            ),
            "pre_handoff_plan_copy": (
                "outputs/longitudinal_2000_v1/r_replication/"
                "krt_exact_nimble_plan_240_before_handoff_sync.csv"
            ),
        }
    )
    write_json(manifest_path, manifest)
    return stale


def _copy_selected_runs(stage: Path, selection: pd.DataFrame) -> list[dict[str, Any]]:
    if selection.duplicated(["election_id", "scenario_id"]).any():
        raise AssertionError("selected KRT pairs are not unique")
    rows: list[dict[str, Any]] = []
    for item in selection.to_dict("records"):
        run_id = str(item["run_id"])
        source = RUNS_DIR / run_id
        manifest_source = source / "manifest.json"
        if not manifest_source.is_file():
            raise FileNotFoundError(manifest_source)
        payload = json.loads(manifest_source.read_text(encoding="utf-8"))
        if payload.get("status") != "success":
            raise AssertionError(f"selected run is not successful: {run_id}")
        target = stage / "outputs" / "runs" / run_id
        for path in source.iterdir():
            if not path.is_file() or path.suffix.lower() == ".nc":
                continue
            if path.name == "manifest.json":
                continue
            _copy(path, target / path.name)
        portable = _portable(payload)
        preparation = portable.get("preparation_manifest", {})
        if isinstance(preparation, dict) and preparation.get("output"):
            model_name = Path(str(preparation["output"])).name
            model_path = stage / "outputs" / "model_ready" / model_name
            if not model_path.is_file():
                raw_preparation = payload.get("preparation_manifest", {})
                raw_output = raw_preparation.get("output") if isinstance(raw_preparation, dict) else None
                if not raw_output:
                    raise FileNotFoundError(model_path)
                raw_model = Path(str(raw_output))
                if not raw_model.is_absolute():
                    raw_model = ROOT / raw_model
                if not raw_model.is_file():
                    raise FileNotFoundError(raw_model)
                raw_stem = raw_model.stem
                for extra in raw_model.parent.glob(raw_stem + "*"):
                    if not extra.is_file() or extra.suffix.lower() == ".nc":
                        continue
                    extra_target = stage / "outputs" / "model_ready" / extra.name
                    if extra.name.endswith("__manifest.json"):
                        extra_payload = _portable(json.loads(extra.read_text(encoding="utf-8")))
                        extra_payload["output"] = f"outputs/model_ready/{raw_model.name}"
                        extra_payload["output_sha256"] = file_sha256(raw_model)
                        extra_payload["panel_source"] = "panel/longitudinal_2000_v1.parquet"
                        write_json(extra_target, extra_payload)
                    else:
                        _copy(extra, extra_target)
                if not model_path.is_file():
                    raise FileNotFoundError(model_path)
            preparation["output"] = f"outputs/model_ready/{model_name}"
            preparation["output_sha256"] = file_sha256(model_path)
        portable["handoff_original_manifest_sha256"] = file_sha256(manifest_source)
        portable["handoff_trace_included"] = False
        portable["handoff_resume_from_summaries_supported"] = True
        write_json(target / "manifest.json", portable)
        commune = target / "commune_latent_summaries.parquet"
        aggregate = target / "aggregate_comparison_v2.csv"
        diagnostics = target / "model_diagnostics.csv"
        if not all(path.is_file() for path in (commune, aggregate, diagnostics)):
            raise AssertionError(f"required durable outputs missing for {run_id}")
        if len(pd.read_parquet(commune)) != 2000:
            raise AssertionError(f"commune row count is not 2,000 for {run_id}")
        rows.append(
            {
                "election_id": item["election_id"],
                "scenario_id": item["scenario_id"],
                "run_id": run_id,
                "selection_status": item.get("selection_status", "current_candidate"),
                "mcmc_status": item.get("mcmc_status", ""),
                "identification_status": item.get("identification_status", ""),
                "release_id": payload.get("parameters", {}).get("release_id", ""),
                "sampler_backend": payload.get("parameters", {}).get("sampler_backend", ""),
                "random_seed": payload.get("parameters", {}).get("random_seed", ""),
                "trace_included": False,
            }
        )
    return rows


def _copy_runtime_outputs(stage: Path) -> None:
    base = ROOT / "outputs" / "longitudinal_2000_v1"
    for dirname in ("audit", "final", "production", "r_replication"):
        _copy_tree(
            base / dirname,
            stage / "outputs" / "longitudinal_2000_v1" / dirname,
            excluded_names={"__pycache__"},
            excluded_suffixes={".nc"},
        )


def _write_continuation_config(stage: Path) -> None:
    source = ROOT / "config" / "releases" / "v1.1_pymc_fallback.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["krt_scenarios"] = ["H2", "H3"]
    payload["ready_scope"] = "H2-H3-pymc-fallback-continuation"
    payload["handoff_note"] = (
        "Continuation-only scope. It intentionally excludes H0A/H1 so the validated v1.0.2 "
        "runs are never recalculated under the fallback release id."
    )
    write_json(stage / "config" / "releases" / "v1.1_pymc_h2_h3_continuation.json", payload)


def _write_scripts(stage: Path) -> None:
    scripts = stage / "CONTINUE_ON_OTHER_PC"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "01_SETUP_WINDOWS.ps1").write_text(
        r'''param([switch]$InstallRPackages)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python launcher 'py' absent. Installer Python 3.12 puis relancer."
}
& py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements-handoff-v1.1.txt
if ($InstallRPackages) {
    $rscript = Get-Command Rscript -ErrorAction SilentlyContinue
    if (-not $rscript) { throw "Rscript absent du PATH. Installer R 4.6.x." }
    & $rscript.Source -e 'install.packages(c("jsonlite","digest","data.table","nimble","coda"), repos="https://cloud.r-project.org")'
}
Write-Host "Installation terminee. Lancer 02_VERIFY_HANDOFF.ps1."
''',
        encoding="utf-8-sig",
    )
    (scripts / "02_VERIFY_HANDOFF.ps1").write_text(
        r'''$ErrorActionPreference = "Stop"
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
& $python (Join-Path $PSScriptRoot "VERIFY_HANDOFF.py") --root $projectRoot
if ($LASTEXITCODE -ne 0) { throw "Verification du handoff echouee." }
''',
        encoding="utf-8-sig",
    )
    (scripts / "03_RESUME_PYTHON_KRT.ps1").write_text(
        r'''$ErrorActionPreference = "Stop"
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Executer d'abord 01_SETUP_WINDOWS.ps1." }
$initialScopes = @(
  "config\releases\v1.1_pymc_h2_h3_continuation.json",
  "config\releases\v1.2_pymc_h6_h7.json",
  "config\releases\v1.3_pymc_h0b_h0c.json",
  "config\releases\v1.4_pymc_h4_h5.json"
)
foreach ($scope in $initialScopes) {
    & $python -m code_longitudinal.v11_pipeline krt --release-config $scope --cores 1
    if ($LASTEXITCODE -ne 0) { throw "Echec du scope initial $scope" }
}
foreach ($scope in $initialScopes) {
    & $python -m code_longitudinal.targeted_rerun_scope --release-config $scope
    if ($LASTEXITCODE -ne 0) { throw "Echec du scope de relance $scope" }
}
& $python -m code_longitudinal.consolidate_current_krt_all_2x2
& $python -m code_longitudinal.build_current_estimation_coverage
Write-Host "Production Python et relances terminees. Passer au script R exact."
''',
        encoding="utf-8-sig",
    )
    (scripts / "04_RUN_R_NIMBLE_EXACT.ps1").write_text(
        r'''param([string]$RscriptPath = "")
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Executer d'abord 01_SETUP_WINDOWS.ps1." }
if ($RscriptPath) { $env:LONGITUDINAL_RSCRIPT = $RscriptPath }
& $python -m code_longitudinal.run_r_krt_exact_all_2x2
if ($LASTEXITCODE -ne 0) { throw "La production R/NIMBLE a signale une erreur." }
Write-Host "R/NIMBLE termine; consolidation et comparaison Python/R executees automatiquement."
''',
        encoding="utf-8-sig",
    )
    (scripts / "05_REFRESH_SNAPSHOT.ps1").write_text(
        r'''$ErrorActionPreference = "Stop"
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
& $python -m code_longitudinal.consolidate_current_krt_all_2x2
& $python -m code_longitudinal.build_current_estimation_coverage
& $python -m code_longitudinal.package_current_progress_snapshot
''',
        encoding="utf-8-sig",
    )
    (scripts / "VERIFY_HANDOFF.py").write_text(
        '''from __future__ import annotations
import argparse, csv, hashlib, json
from pathlib import Path

PANEL_HASH = "bde70c71660fce29610d7931461d8db6181dba874514a1866b63cf16a81cec4a"
def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()
def main(root: Path) -> None:
    failures = []
    manifest = root / "FILE_MANIFEST.csv"
    with manifest.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        path = root / row["delivery_path"]
        if not path.is_file() or sha(path) != row["sha256"]:
            failures.append(row["delivery_path"])
    panel = root / "panel" / "longitudinal_2000_v1.parquet"
    if sha(panel) != PANEL_HASH:
        failures.append("panel/longitudinal_2000_v1.parquet")
    plan_path = root / "outputs" / "longitudinal_2000_v1" / "r_replication" / "krt_exact_nimble_plan_240.csv"
    with plan_path.open(encoding="utf-8-sig", newline="") as stream:
        plan = list(csv.DictReader(stream))
    if len(plan) != 240:
        failures.append("R plan does not contain 240 pairs")
    for row in plan:
        source = root / row["input_csv"]
        if not source.is_file() or sha(source) != row["input_sha256"]:
            failures.append(row["input_csv"])
    state = json.loads((root / "HANDOFF_STATE.json").read_text(encoding="utf-8"))
    selection = root / state["selection_path"]
    with selection.open(encoding="utf-8-sig", newline="") as stream:
        selected = list(csv.DictReader(stream))
    if len(selected) != int(state["krt_python_pairs_included"]):
        failures.append("selected run count mismatch")
    for row in selected:
        run = root / "outputs" / "runs" / row["run_id"]
        for name in ("manifest.json", "commune_latent_summaries.parquet", "aggregate_comparison_v2.csv", "model_diagnostics.csv"):
            if not (run / name).is_file(): failures.append(f"{run.name}/{name}")
    if failures:
        raise SystemExit("HANDOFF INVALID:\\n- " + "\\n- ".join(failures[:50]))
    print(json.dumps({"status":"pass","files_verified":len(rows),"r_inputs":len(plan),"python_runs":len(selected)}, indent=2))
if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, required=True)
    main(parser.parse_args().root.resolve())
''',
        encoding="utf-8",
    )


def _write_docs(
    stage: Path,
    *,
    state: dict[str, Any],
    selection_rows: list[dict[str, Any]],
) -> None:
    counts = pd.DataFrame(selection_rows).groupby("scenario_id").size().to_dict()
    count_lines = "\n".join(f"- `{key}` : {counts.get(key, 0)}" for key in ("H0A", "H1", "H2", "H3", "H0B", "H0C", "H4", "H5", "H6", "H7"))
    readme = f"""# Handoff complet — estimations longitudinales

Cette archive permet de reprendre la production sur un autre PC sans recalculer les succès compatibles déjà inclus.

## État figé

- KRT Python inclus : **{state['krt_python_pairs_included']}/240**.
- KRT initiaux restant dans le plan : **{state['krt_python_initial_pairs_remaining']}**.
- NLS : **292/292**.
- Entrées préparées : **240 CSV + 240 Parquet**, toutes hashées.
- Panel fixe : **2 000 communes**, SHA-256 `{EXPECTED_PANEL_SHA256}`.
- Réplication exacte R/NIMBLE : plan de 240 couples inclus; production encore en attente de la fin de Python.
- Les traces NetCDF ne sont pas livrées : les résumés communaux, agrégats et diagnostics durables suffisent à la reprise et à la consolidation.

Couverture incluse par hypothèse :

{count_lines}

## Reprise Windows

1. Extraire le ZIP dans un chemin court, par exemple `D:\\ARE_longitudinal`.
2. Ouvrir PowerShell dans `CONTINUE_ON_OTHER_PC`.
3. Exécuter `01_SETUP_WINDOWS.ps1` (ajouter `-InstallRPackages` si nécessaire).
4. Exécuter `02_VERIFY_HANDOFF.ps1`.
5. Exécuter `03_RESUME_PYTHON_KRT.ps1`.
6. Après Python, exécuter `04_RUN_R_NIMBLE_EXACT.ps1`.
7. Utiliser `05_REFRESH_SNAPSHOT.ps1` pour produire un nouvel audit ZIP.

Le script Python ne doit pas être lancé deux fois en parallèle sur le même dossier. Chaque succès validé et conforme au scope est repris depuis son manifeste. Les H0A/H1 validés ne sont pas recalculés : le scope H2/H3 de continuation les exclut explicitement.

## Contenu important

- `CURRENT_PROGRESS_SNAPSHOT/` : audit lisible de l'état au moment du gel.
- `outputs/runs/` : sorties durables de chaque KRT Python inclus.
- `outputs/model_ready/` : toutes les matrices nécessaires aux 240 KRT Python et R.
- `outputs/longitudinal_2000_v1/` : audits, résultats H0A/H1, NLS, journaux et plan R.
- `code_longitudinal/`, `config/`, `tests/`, `r_replication/` : code et paramètres.
- `HANDOFF_STATE.json` et `FILE_MANIFEST.csv` : état exact et intégrité.

## Prudence scientifique

Un `fail` MCMC peut provenir d'un ESS, R-hat ou BFMI insuffisant même avec zéro divergence. Il doit recevoir au plus une relance préenregistrée. Le diagnostic MCMC, l'identification écologique et l'écart KRT–NLS restent séparés. H2/H3 ne forment pas une différence postérieure jointe ouvriers–employés.
"""
    (stage / "README_CONTINUATION.md").write_text(readme, encoding="utf-8")
    (stage / "PLAN_TO_FINISH.md").write_text(
        f"""# Plan de continuation

## Phase 1 — Python KRT

1. Vérifier l'archive et le panel.
2. Terminer les {state['krt_python_initial_pairs_remaining']} couples initiaux absents parmi les 240 prévus.
3. Pour chaque `caveat_severe` ou `fail`, exécuter une seule relance à 2 000 warmup et 2 000 draws, base de graine 20260817.
4. Consolider exactement un candidat par couple et conserver les trois diagnostics séparés.

## Phase 2 — R exact

1. Charger R 4.6.x, NIMBLE 1.4.2 et coda.
2. Exécuter les 240 couples avec le même panel, les mêmes matrices, likelihood, priors, king_lambda=0.5 et graines déterministes.
3. Consolider les sorties R et produire la comparaison Python/R.

## Phase 3 — Release

1. Sélectionner exactement un run canonique par couple.
2. Vérifier 480 000 lignes communales pour 240 couples si les dix hypothèses sont toutes livrées ensemble.
3. Régénérer Parquet, figures, rapport professeur, dictionnaires, lineage, manifestes et ZIP.
4. Ne définir `ready=true` que pour le périmètre effectivement contrôlé.

## Après ce périmètre

RxC 3×2 ciblé → RxC 3×5 → covariables documentées → source alternative.
""",
        encoding="utf-8",
    )


def _file_manifest(stage: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for path in sorted(value for value in stage.rglob("*") if value.is_file() and value.name != "FILE_MANIFEST.csv"):
        rows.append(
            {
                "delivery_path": path.relative_to(stage).as_posix(),
                "sha256": file_sha256(path),
                "size_bytes": path.stat().st_size,
            }
        )
    frame = pd.DataFrame(rows)
    frame.to_csv(stage / "FILE_MANIFEST.csv", index=False, encoding="utf-8-sig")
    return frame


def _verify_stage(stage: Path) -> dict[str, Any]:
    manifest = pd.read_csv(stage / "FILE_MANIFEST.csv")
    failures = []
    for row in manifest.to_dict("records"):
        path = stage / str(row["delivery_path"])
        if not path.is_file() or file_sha256(path) != str(row["sha256"]):
            failures.append(str(row["delivery_path"]))
    if failures:
        raise AssertionError(f"stage hash failures: {failures[:10]}")
    state = json.loads((stage / "HANDOFF_STATE.json").read_text(encoding="utf-8"))
    selection = pd.read_csv(stage / str(state["selection_path"]))
    if len(selection) != int(state["krt_python_pairs_included"]):
        raise AssertionError("stage selection count mismatch")
    if file_sha256(stage / "panel" / "longitudinal_2000_v1.parquet") != EXPECTED_PANEL_SHA256:
        raise AssertionError("stage panel hash mismatch")
    return {"status": "pass", "files": len(manifest), "python_runs": len(selection)}


def _zip(stage: Path, output: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        for path in sorted(value for value in stage.rglob("*") if value.is_file()):
            archive.write(path, path.relative_to(stage).as_posix())
    with zipfile.ZipFile(output) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise AssertionError(f"ZIP CRC failure: {bad}")
        names = archive.namelist()
        if any(Path(name).is_absolute() or ".." in Path(name).parts for name in names):
            raise AssertionError("unsafe ZIP member")
        if any(name.lower().endswith(".nc") for name in names):
            raise AssertionError("NetCDF included in transfer ZIP")
    digest = file_sha256(output)
    sidecar = output.with_suffix(output.suffix + ".sha256")
    sidecar.write_text(f"{digest}  {output.name}\n", encoding="ascii")
    return {"path": str(output), "sha256": digest, "size_bytes": output.stat().st_size, "sidecar": str(sidecar)}


def build(output: Path | None = None) -> dict[str, Any]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    selection = pd.read_csv(SELECTION_SOURCE)
    plan = pd.read_csv(R_PLAN_SOURCE)
    snapshot_source = create_stage()
    snapshot_selection = pd.read_csv(snapshot_source / "diagnostics" / "CURRENT_RUN_SELECTION_PROVISIONAL.csv")
    if set(zip(selection.election_id, selection.scenario_id, selection.run_id)) != set(
        zip(snapshot_selection.election_id, snapshot_selection.scenario_id, snapshot_selection.run_id)
    ):
        selection = snapshot_selection
    # Keep staging paths deliberately short on Windows: copied diagnostic trees contain
    # deeply nested run names and can otherwise exceed the legacy MAX_PATH boundary.
    stage = ROOT / "work" / f"handoff_{stamp}"
    if stage.exists():
        raise FileExistsError(stage)
    stage.mkdir(parents=True)
    _copy_project_sources(stage)
    _copy_tree(snapshot_source, stage / "CURRENT_PROGRESS_SNAPSHOT", excluded_suffixes={".nc"})
    model_rows = _copy_model_ready(stage, plan)
    run_rows = _copy_selected_runs(stage, selection)
    _copy_runtime_outputs(stage)
    stale_r_plan_hashes = _synchronize_staged_r_plan(stage, plan, model_rows)
    _write_continuation_config(stage)
    _write_scripts(stage)

    selection_path = "CURRENT_PROGRESS_SNAPSHOT/diagnostics/CURRENT_RUN_SELECTION_PROVISIONAL.csv"
    state: dict[str, Any] = {
        "schema_version": "longitudinal_full_continuation_handoff_v1",
        "created_at_utc": _utc_now(),
        "status": "portable_continuation_snapshot",
        "ready": False,
        "scientific_release_ready": False,
        "panel_id": PANEL_ID,
        "panel_size": 2000,
        "panel_sha256": EXPECTED_PANEL_SHA256,
        "krt_python_pairs_expected": EXPECTED_KRT_PAIRS,
        "krt_python_pairs_included": len(run_rows),
        "krt_python_initial_pairs_remaining": EXPECTED_KRT_PAIRS - len(run_rows),
        "nls_pairs_included": EXPECTED_NLS_PAIRS,
        "r_exact_pairs_planned": len(plan),
        "r_exact_pairs_completed": 0,
        "r_plan_stale_input_hashes_corrected_in_handoff": stale_r_plan_hashes,
        "selection_path": selection_path,
        "model_ready_index_path": "MODEL_READY_INDEX_240.csv",
        "included_run_index_path": "PYTHON_KRT_RUNS_INCLUDED.csv",
        "netcdf_included": False,
        "raw_source_archives_included": False,
        "raw_source_archives_required_to_rebuild_model_ready": True,
        "verified_model_ready_cache_included": True,
        "resume_entrypoint": "CONTINUE_ON_OTHER_PC/03_RESUME_PYTHON_KRT.ps1",
        "r_entrypoint": "CONTINUE_ON_OTHER_PC/04_RUN_R_NIMBLE_EXACT.ps1",
        "important_note": (
            "The snapshot selection is authoritative for the included-state timestamp. "
            "The source PC continued computing after this freeze."
        ),
    }
    pd.DataFrame(model_rows).to_csv(stage / "MODEL_READY_INDEX_240.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(run_rows).to_csv(stage / "PYTHON_KRT_RUNS_INCLUDED.csv", index=False, encoding="utf-8-sig")
    write_json(stage / "HANDOFF_STATE.json", state)
    _write_docs(stage, state=state, selection_rows=run_rows)
    _file_manifest(stage)
    stage_verification = _verify_stage(stage)
    output = output or ROOT / "deliverables" / f"longitudinal_2000_full_continuation_{stamp}.zip"
    archive = _zip(stage, output)

    # Use the OS temporary directory for the independent extraction audit. Some
    # managed Windows workspaces apply restrictive ACLs to newly-created work children.
    receipt = {
        "created_at_utc": _utc_now(),
        "stage": str(stage),
        "snapshot_source": str(snapshot_source),
        "archive": archive,
        "stage_verification": stage_verification,
        "zip_crc_and_member_verification": "pass",
        "independent_extraction_verification": (
            "Run after build with PowerShell Expand-Archive because the managed Python "
            "subprocess cannot create extraction subdirectories under the local ACL policy."
        ),
        "krt_python_pairs_included": len(run_rows),
        "krt_python_initial_pairs_remaining": EXPECTED_KRT_PAIRS - len(run_rows),
        "r_model_ready_pairs": len(model_rows),
    }
    receipt_path = output.with_suffix(".receipt.json")
    write_json(receipt_path, receipt)
    receipt["receipt_path"] = str(receipt_path)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a full, verified, portable continuation handoff.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = build(args.output.resolve() if args.output else None)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
