from __future__ import annotations

import json
from pathlib import Path

import nbformat as nbf


HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"


def main() -> None:
    highlights = json.loads((RESULTS / "comparison_highlights.json").read_text(encoding="utf-8"))
    notebook = nbf.v4.new_notebook()
    notebook["metadata"]["kernelspec"] = {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    }
    notebook["metadata"]["language_info"] = {"name": "python", "version": "3.12"}
    notebook["cells"] = [
        nbf.v4.new_markdown_cell(
            "## tl;dr\n\n"
            f"Les six fits R ont utilisé exactement les mêmes lignes effectives que les runs Python épinglés. "
            f"L’écart absolu médian entre moteurs est de **{highlights['median_absolute_difference_pp']:.2f} points** "
            f"et le maximum de **{highlights['max_absolute_difference_pp']:.2f} points**. "
            "Les résultats restent exploratoires : les runs Python disponibles n’ont qu’une chaîne et 20 draws, "
            "et R `ei` fournit 99 simulations d’importance sans R-hat multi-chaînes."
        ),
        nbf.v4.new_markdown_cell(
            "## Context & Methods\n\n"
            "### Key Assumptions\n\n"
            "- Panel nominal fixe de 3 000 communes (`panel_3000_seed_20260802`).\n"
            "- H0A et H1, sur les législatives 1962, 1986 et 2022.\n"
            "- Filtre de tomographie PyEI appliqué une seule fois avant les deux moteurs.\n"
            "- Même ordre communal et même graine numérique 20260802.\n"
            "- Famille King à normale tronquée, avec moteurs et priors non strictement identiques."
        ),
        nbf.v4.new_code_cell(
            "from pathlib import Path\n"
            "import json\n"
            "import pandas as pd\n"
            "from IPython.display import display\n\n"
            "HERE = Path.cwd()\n"
            "if not (HERE / 'results').exists():\n"
            "    HERE = HERE / 'analysis' / 'king_r_python_comparison'\n"
            "RESULTS = HERE / 'results'\n"
            "manifest = pd.read_csv(RESULTS / 'comparison_manifest.csv')\n"
            "input_audit = pd.read_csv(RESULTS / 'input_audit.csv')\n"
            "comparison = pd.read_csv(RESULTS / 'comparison_summary.csv')\n"
            "diagnostics = pd.read_csv(RESULTS / 'diagnostic_comparison.csv')\n"
            "highlights = json.loads((RESULTS / 'comparison_highlights.json').read_text(encoding='utf-8'))"
        ),
        nbf.v4.new_markdown_cell("## Data\n\nLes six entrées communes et leur audit de parité."),
        nbf.v4.new_code_cell(
            "display(input_audit[['comparison_key','nominal_rows','prepared_rows','excluded_during_preparation','effective_rows','excluded_degenerate_rows',"
            "'duplicate_unit_ids','python_unit_order_match','max_group_count_roundtrip_error','max_vote_count_roundtrip_error']])\n"
            "assert input_audit['python_unit_order_match'].all()\n"
            "assert (input_audit['duplicate_unit_ids'] == 0).all()"
        ),
        nbf.v4.new_markdown_cell("## Results\n\nComparaison des estimations agrégées β1 et β2."),
        nbf.v4.new_code_cell(
            "cols = ['fit_group_label','effective_n_python','estimate_python','lower_python','upper_python',"
            "'estimate_r','lower_r','upper_r','difference_r_minus_python','absolute_difference_pp','interval_overlap_ratio']\n"
            "display(comparison[cols].round(4))"
        ),
        nbf.v4.new_code_cell(
            "summary = comparison.groupby(['scenario_id','estimand']).agg(\n"
            "    median_abs_diff_pp=('absolute_difference_pp','median'),\n"
            "    max_abs_diff_pp=('absolute_difference_pp','max'),\n"
            "    mean_overlap=('interval_overlap_ratio','mean'),\n"
            ").reset_index()\n"
            "display(summary.round(3))"
        ),
        nbf.v4.new_markdown_cell("### Diagnostics\n\nLes diagnostics ne sont pas directement homologues entre NUTS/PyMC et l’importance sampling de R `ei`."),
        nbf.v4.new_code_cell(
            "diag_cols = ['comparison_key','engine','fit_status','diagnostic_status','diagnostic_reason','effective_n','elapsed_seconds',"
            "'draws','chains','mcmc_divergences','mcmc_min_ess_bulk','importance_simulations','hessian_positive_definite',"
            "'max_accounting_reconstruction_error']\n"
            "display(diagnostics.reindex(columns=diag_cols).round(5))"
        ),
        nbf.v4.new_markdown_cell(
            "## Takeaways\n\n"
            "1. La parité des inputs est vérifiée par effectif, ordre des identifiants, fermeture comptable et SHA-256.\n"
            "2. Les écarts observés ne peuvent donc pas être attribués à un changement de composition des communes.\n"
            "3. Ils peuvent en revanche provenir des priors, de l’optimisation/simulation et du faible budget de tirages du run Python existant.\n"
            "4. Une conclusion substantielle demanderait un rerun Python multi-chaînes et, idéalement, une implémentation R du même modèle KRT `king99` bêta-binomial."
        ),
    ]
    path = HERE / "king_r_python_comparison.ipynb"
    nbf.write(notebook, path)
    print(path)


if __name__ == "__main__":
    main()
