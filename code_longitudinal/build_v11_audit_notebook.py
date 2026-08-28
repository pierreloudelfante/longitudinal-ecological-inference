from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from .release_scope import load_release_scope


def _markdown(source: str) -> dict[str, Any]:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


def _code(source: str) -> dict[str, Any]:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


def _validate_structure(notebook: dict[str, Any]) -> None:
    if notebook.get("nbformat") != 4 or not isinstance(notebook.get("cells"), list):
        raise AssertionError("invalid notebook v4 structure")
    for index, cell in enumerate(notebook["cells"]):
        if cell.get("cell_type") not in {"markdown", "code"}:
            raise AssertionError(f"unsupported cell type at index {index}")
        if not isinstance(cell.get("source"), list):
            raise AssertionError(f"cell source is not a list at index {index}")
        if cell["cell_type"] == "code" and not isinstance(cell.get("outputs"), list):
            raise AssertionError(f"code outputs are not a list at index {index}")


def _execute_cells(notebook: dict[str, Any], release_root: Path) -> None:
    namespace: dict[str, Any] = {
        "__name__": "__main__",
        "display": lambda value: print(value.to_string(index=False) if hasattr(value, "to_string") else value),
    }
    previous = Path.cwd()
    os.chdir(release_root)
    try:
        execution_count = 0
        for cell in notebook["cells"]:
            if cell["cell_type"] != "code":
                continue
            execution_count += 1
            source = "".join(cell["source"])
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exec(compile(source, f"AUDIT_NOTEBOOK_v1.1.ipynb:cell_{execution_count}", "exec"), namespace)
            cell["execution_count"] = execution_count
            outputs = []
            if stdout.getvalue():
                outputs.append({"name": "stdout", "output_type": "stream", "text": stdout.getvalue().splitlines(keepends=True)})
            if stderr.getvalue():
                outputs.append({"name": "stderr", "output_type": "stream", "text": stderr.getvalue().splitlines(keepends=True)})
            cell["outputs"] = outputs
    finally:
        os.chdir(previous)


def build_and_execute_notebook(release_root: Path, config_path: Path, output_path: Path) -> dict[str, Any]:
    scope = load_release_scope(config_path)
    validation = json.loads((release_root / "VALIDATION_v1.1.json").read_text(encoding="utf-8"))
    diagnostics = pd.read_csv(release_root / "02_syntheses" / "diagnostics_krt_par_election.csv")
    status_counts = diagnostics["mcmc_status"].value_counts().to_dict()
    notebook: dict[str, Any] = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.12"},
        },
    }
    notebook["cells"] = [
        _markdown(
            "# Audit reproductible de la release v1.1\n\n"
            "Ce notebook centralise les controles de qualite des trois tables publiques; il ne relance aucun modele."
        ),
        _markdown(
            "## tl;dr\n\n"
            f"La release valide {validation['actual']['krt_pairs']} couples KRT, "
            f"{validation['actual']['commune_rows']:,} lignes communales et "
            f"{validation['actual']['nls_pairs']} couples NLS. Diagnostics KRT canoniques: "
            f"{status_counts.get('pass', 0)} pass, {status_counts.get('caveat', 0)} caveat, "
            f"{status_counts.get('fail', 0)} fail. L'invariance H0A/H1 avec la v1.0.2 est exacte."
        ),
        _markdown(
            "## Context & Methods\n\n"
            "Grain principal: `unit_id x election_id x scenario_id`. Les controles portent sur les effectifs derives de la configuration, "
            "l'unicite des cles, la completude des huit champs d'incertitude, les domaines des probabilites et contrastes, "
            "l'absence de fail MCMC canonique et la preuve d'invariance H0A/H1.\n\n"
            "### Key Assumptions\n\n"
            "- Le notebook est execute avec le dossier racine de la release comme repertoire courant.\n"
            "- `ready=true` est interprete uniquement dans le perimetre H0A-H1-H2-H3.\n"
            "- Les diagnostics MCMC et d'identification ecologique restent distincts."
        ),
        _markdown("## Data\n\n### 1. Charger les tables et les preuves de validation"),
        _code(
            "from pathlib import Path\n"
            "import json\n"
            "import pandas as pd\n\n"
            "release_root = Path.cwd()\n"
            "results = release_root / '01_resultats_python'\n"
            "syntheses = release_root / '02_syntheses'\n"
            "audit = release_root / '03_panel_et_audit'\n\n"
            "commune = pd.read_parquet(results / 'longitudinal_krt_commune.parquet')\n"
            "aggregate = pd.read_parquet(results / 'longitudinal_krt_aggregate.parquet')\n"
            "nls = pd.read_parquet(results / 'longitudinal_nls.parquet')\n"
            "selection = pd.read_csv(syntheses / 'canonical_run_selection.csv', dtype='string')\n"
            "diagnostics = pd.read_csv(syntheses / 'diagnostics_krt_par_election.csv')\n"
            "validation = json.loads((release_root / 'VALIDATION_v1.1.json').read_text(encoding='utf-8'))\n"
            "invariance = json.loads((audit / 'NUMERICAL_INVARIANCE_v1.0.2_to_v1.1.json').read_text(encoding='utf-8'))\n"
            "print('shapes', commune.shape, aggregate.shape, nls.shape)"
        ),
        _markdown("## Results\n\n### 2. Verifier le grain, les domaines et les effectifs"),
        _code(
            f"EXPECTED_ELECTIONS = {scope.expected_elections}\n"
            f"EXPECTED_SCENARIOS = {list(scope.krt_scenarios)!r}\n"
            f"EXPECTED_KRT_PAIRS = {scope.expected_krt_pairs}\n"
            f"EXPECTED_COMMUNE_ROWS = {scope.expected_krt_commune_rows}\n"
            f"EXPECTED_AGGREGATE_ROWS = {scope.expected_krt_aggregate_rows}\n"
            f"EXPECTED_NLS_PAIRS = {scope.expected_nls_pairs}\n"
            "uncertainty = ['b1_sd','b1_q025','b1_q50','b1_q975','b2_sd','b2_q025','b2_q50','b2_q975']\n\n"
            "checks = {\n"
            "    'krt_pairs_exact': len(aggregate[['election_id','scenario_id']].drop_duplicates()) == EXPECTED_KRT_PAIRS,\n"
            "    'commune_rows_exact': len(commune) == EXPECTED_COMMUNE_ROWS,\n"
            "    'aggregate_rows_exact': len(aggregate) == EXPECTED_AGGREGATE_ROWS,\n"
            "    'nls_pairs_exact': len(nls[['election_id','scenario_id']].drop_duplicates()) == EXPECTED_NLS_PAIRS,\n"
            "    'commune_keys_unique': not commune[['election_id','scenario_id','unit_id']].duplicated().any(),\n"
            "    'aggregate_keys_unique': not aggregate[['election_id','scenario_id','estimand']].duplicated().any(),\n"
            "    'selection_unique_and_complete': len(selection) == EXPECTED_KRT_PAIRS and not selection[['election_id','scenario_id']].duplicated().any(),\n"
            "    'uncertainty_complete': commune[uncertainty].notna().all().all(),\n"
            "    'probabilities_in_bounds': commune[['b1_mean','b2_mean']].ge(0).all().all() and commune[['b1_mean','b2_mean']].le(1).all().all(),\n"
            "    'contrasts_in_bounds': aggregate.loc[aggregate['estimand'].eq('b_1_minus_b_2'),'mean'].between(-1,1).all(),\n"
            "    'no_mcmc_fail': aggregate['mcmc_status'].isin(['pass','caveat']).all(),\n"
            "    'h0a_h1_exact_invariance': invariance.get('exact') is True,\n"
            "    'ready_scope_exact': validation.get('ready_scope') == 'H0A-H1-H2-H3',\n"
            "}\n"
            "assert all(checks.values()), {key: value for key, value in checks.items() if not value}\n"
            "display(pd.DataFrame([{'check': key, 'status': 'pass' if value else 'fail'} for key, value in checks.items()]))"
        ),
        _markdown("### 3. Resumer sans confondre MCMC et identification"),
        _code(
            "mcmc_summary = diagnostics.groupby(['scenario_id','mcmc_status']).size().rename('n_runs').reset_index()\n"
            "identification_summary = diagnostics.groupby(['scenario_id','identification_status']).size().rename('n_runs').reset_index()\n"
            "display(mcmc_summary)\n"
            "display(identification_summary)"
        ),
        _markdown(
            "## Takeaways\n\n"
            "- Les cles publiques et les effectifs correspondent au perimetre configure.\n"
            "- Les huit champs d'incertitude communale sont complets.\n"
            "- Aucun fail MCMC canonique n'entre dans la release.\n"
            "- L'identification ecologique reste une reserve scientifique distincte.\n"
            "- H0A/H1 sont exactement invariants par rapport a la v1.0.2."
        ),
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _validate_structure(notebook)
    _execute_cells(notebook, release_root)
    _validate_structure(notebook)
    output_path.write_text(json.dumps(notebook, ensure_ascii=False, indent=1), encoding="utf-8")
    return {
        "notebook": output_path.relative_to(release_root).as_posix(),
        "executed": True,
        "execution_backend": "validated_nbformat4_json_sequential_python_exec",
        "cells": len(notebook["cells"]),
        "checks": 13,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and execute the compact v1.1 data-quality notebook.")
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_and_execute_notebook(args.release_root, args.config, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
