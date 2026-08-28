from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .paths import ROOT
from .release_scope import load_release_scope


CONFIG = ROOT / "config" / "releases" / "v1.5_retained6.json"
CANDIDATE = ROOT / "work" / "longitudinal_2000_v1.5_H0A_H1_H0B_H0C_H2_H3_candidate"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def build(candidate: Path = CANDIDATE, config: Path = CONFIG) -> dict[str, object]:
    scope = load_release_scope(config)
    validation = json.loads((candidate / "VALIDATION_RETAINED6.json").read_text(encoding="utf-8"))
    scientific = "validée" if validation["scientific_ready"] else "candidate avec réserves MCMC documentées"
    scenarios = ", ".join(scope.krt_scenarios)

    _write(
        candidate / "README.md",
        f"""# Release longitudinale — périmètre retenu

Statut : **{scientific}**. Périmètre : `{scope.ready_scope}`. Le mot `ready` ne couvre jamais d'autres hypothèses.

Cette livraison contient 26 scrutins, un panel fixe de 2 000 communes et six scénarios : {scenarios}. Les mêmes `unit_id` et le même hash de panel sont utilisés partout.

## Lecture rapide

1. `01_entrees/` décrit le panel et les 156 matrices transmises aux modèles.
2. `01_resultats_python/` contient les trois tables publiques Python : KRT communal, KRT agrégé et NLS.
3. `03_resultats_r_eipack/` contient les estimations R `ei`/`eiPack` sans NIMBLE.
4. `04_comparaison_python_r/` compare deux modèles King non identiques ; ce n'est pas une réplication bit-à-bit.
5. `04_figures_essentielles/` contient les trajectoires, comparaisons et diagnostics graphiques.
6. `02_syntheses/` et `03_panel_et_audit/` donnent les décisions, diagnostics et lignages.
7. `05_methodologie_et_code/` explique les modèles et la reproduction.

Les anciens scénarios H4/H5/H6/H7 déjà tentés restent hors du périmètre public et ne sont pas mélangés à ces tables.
""",
    )
    _write(
        candidate / "01_entrees" / "README.md",
        """# Entrées des modèles

`MODEL_READY_INDEX.csv` est l'inventaire des 156 matrices (`26 élections × 6 scénarios`). Chaque ligne donne le chemin d'exécution, le chemin prévu dans l'archive technique, le nombre de communes et le SHA-256.

Le ZIP professeur fournit l'index et le panel. Le ZIP technique ajoute les 156 fichiers Parquet `model_ready`, un seul format étant conservé pour éviter les doublons CSV/Parquet.
""",
    )
    _write(
        candidate / "01_resultats_python" / "README.md",
        """# Sorties Python

- `longitudinal_krt_commune.parquet` : une ligne par `election_id × scenario_id × unit_id`, soit 312 000 lignes, avec les huit champs d'incertitude de β1/β2.
- `longitudinal_krt_aggregate.parquet` : β1, β2 et β1−β2 pour chacun des 156 couples, soit 468 lignes.
- `longitudinal_nls.parquet` : NLS ponctuel correspondant au même périmètre, sans pseudo-intervalle postérieur.

Les statuts MCMC et d'identification écologique sont deux diagnostics distincts. Un fit informatique `success` peut conserver un statut MCMC `fail` et reste alors explicitement non validé scientifiquement.
""",
    )
    _write(
        candidate / "03_resultats_r_eipack" / "README.md",
        """# Sorties R `ei` / `eiPack`

La phase R utilise `ei` 1.3-3, qui dépend de `eiPack` 0.2-2. NIMBLE n'est pas utilisé. Les objets complets `.rds` ne sont pas conservés : seules les synthèses communales, agrégées, l'audit des runs et le manifeste sont livrés.

Le modèle R est l'EI classique de King à normale bivariée tronquée. Le modèle Python est un KRT beta-binomial. Ils répondent à la même question 2×2 mais ne sont pas mathématiquement identiques.
""",
    )
    _write(
        candidate / "04_comparaison_python_r" / "README.md",
        """# Comparaison Python–R

Les écarts, corrélations et recouvrements d'intervalles sont des diagnostics de robustesse entre deux modèles King non identiques. Ils ne doivent pas être interprétés comme une vérification bit-à-bit ni comme un effet causal du logiciel.
""",
    )
    _write(
        candidate / "04_figures_essentielles" / "README.md",
        """# Figures essentielles

Les trajectoires législatives et présidentielles sont toujours séparées. Les figures KRT–NLS n'attribuent aucun intervalle artificiel au NLS. La figure H2/H3 compare descriptivement deux β1 issus de modèles dont les compléments diffèrent.
""",
    )
    _write(
        candidate / "05_methodologie_et_code" / "README.md",
        """# Méthodologie et code minimal

La configuration de release est la source unique du périmètre, des effectifs et des réglages. Le bundle technique conserve seulement les scripts appelés par la chaîne finale, les tests associés et les fichiers de configuration nécessaires.

Les données sources brutes restent dans le dépôt parent ; la reproduction à partir des matrices `model_ready` est autonome dans le ZIP technique.
""",
    )
    _write(
        candidate / "PIPELINE_MAP.md",
        """# Carte de la pipeline

```text
sources électorales + sociales
          |
          v
harmonisation géographique et politique
          |
          v
panel fixe 2 000 + 156 matrices model_ready
          |
          +--> Python KRT beta-binomial --> tables communales/agrégées + diagnostics
          |
          +--> Python NLS ---------------> estimations ponctuelles
          |
          +--> R ei/eiPack --------------> tables communales/agrégées
                                           |
                                           v
                              comparaison Python–R
                                           |
                                           v
                          figures + rapport + ZIP vérifiés
```
""",
    )
    _write(
        candidate / "05_methodologie_et_code" / "MODEL_CARDS.md",
        """# Fiches modèles

## Python KRT beta-binomial

- Données : marges 2×2 au niveau communal.
- Panel : 2 000 communes fixes.
- Paramétrisation : `king99_beta_binomial_independent_beta_random_effects_v1`.
- Priors : β communaux beta, hyperparamètres exponentiels avec `king_lambda=0.5`.
- Calibration : quatre chaînes, 1 000 chauffe, 1 000 tirages, `target_accept=0.99`, profondeur 14.
- Sorties : β1/β2 communaux et agrégés, quantiles, diagnostics MCMC et identification séparés.

## Python NLS

- Estimateur ponctuel de Rosen pour les 2×2.
- Solveur TRF, 20 départs, tolérance `1e-9`, 5 000 évaluations maximum.
- Aucun pseudo-intervalle postérieur.

## R `ei` / `eiPack`

- Package principal : `ei` 1.3-3 ; dépendance : `eiPack` 0.2-2.
- Modèle : EI classique de King à normale bivariée tronquée.
- Simulation native : 99 tirages d'importance par commune.
- NIMBLE : non utilisé.
- Comparabilité : robustesse inter-modèles, pas identité mathématique avec Python KRT.
""",
    )
    _write(
        candidate / "05_methodologie_et_code" / "REPRODUCTION.md",
        """# Reproduction en trois niveaux

## Niveau 1 — lire les résultats

Ouvrir les Parquet avec Python/pandas, R/arrow ou DuckDB. Aucun dépôt parent n'est nécessaire.

## Niveau 2 — reproduire depuis `model_ready`

Utiliser le ZIP technique, créer les environnements Python et R décrits dans `DEPENDENCIES.md`, puis exécuter la chaîne finale. Les 156 matrices et le panel sont inclus.

## Niveau 3 — reconstruire depuis les sources brutes

Le dépôt parent et les archives électorales/sociales sont requis. Ils ne sont pas dupliqués dans la livraison. Les hashes, membres d'archives et décisions d'harmonisation sont documentés dans l'audit.
""",
    )
    _write(
        candidate / "05_methodologie_et_code" / "DEPENDENCIES.md",
        """# Dépendances

Python 3.12 : pandas, numpy, scipy, pyarrow, matplotlib, PyMC, ArviZ, PyEI, psutil.

R 4.6 : `ei` 1.3-3, `eiPack` 0.2-2 et leurs dépendances déclarées. NIMBLE n'est ni nécessaire ni utilisé.

Le système doit disposer d'environ 16 Go de RAM pour reproduire les KRT séquentiellement. Les NetCDF et objets RDS bruts ne font pas partie de la livraison.
""",
    )

    lineage = pd.DataFrame(
        [
            {"stage": "panel", "input": "sources harmonisées", "output": "panel_primaire_2000.csv", "grain": "unit_id", "public": True},
            {"stage": "model_ready", "input": "panel + marges sociales/politiques", "output": "156 Parquet techniques", "grain": "unit_id × election_id × scenario_id", "public": False},
            {"stage": "python_krt", "input": "model_ready", "output": "longitudinal_krt_commune.parquet", "grain": "unit_id × election_id × scenario_id", "public": True},
            {"stage": "python_krt", "input": "model_ready", "output": "longitudinal_krt_aggregate.parquet", "grain": "election_id × scenario_id × estimand", "public": True},
            {"stage": "python_nls", "input": "model_ready", "output": "longitudinal_nls.parquet", "grain": "cellule/estimand × election_id × scenario_id", "public": True},
            {"stage": "r_ei", "input": "model_ready", "output": "longitudinal_king_ei_r_commune_retained6.parquet", "grain": "unit_id × election_id × scenario_id", "public": True},
            {"stage": "r_ei", "input": "model_ready", "output": "longitudinal_king_ei_r_aggregate_retained6.parquet", "grain": "election_id × scenario_id × estimand", "public": True},
            {"stage": "comparison", "input": "agrégats Python + R", "output": "king_python_r_retained6_aggregate_comparison.parquet", "grain": "election_id × scenario_id × estimand", "public": True},
        ]
    )
    lineage.to_csv(candidate / "DATA_LINEAGE.csv", index=False, encoding="utf-8-sig")

    result = {
        "status": "complete",
        "release_id": scope.release_id,
        "scientific_status": scientific,
        "markdown_files": len(list(candidate.rglob("*.md"))),
        "lineage_rows": len(lineage),
    }
    return result


def main() -> None:
    print(json.dumps(build(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
