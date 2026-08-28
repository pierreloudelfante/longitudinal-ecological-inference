# Tests automatisés

## Rôle de chaque fichier

| Fichier | Vérifications principales |
|---|---|
| `conftest.py` | rend le paquet importable et place les caches Matplotlib/Numba dans le projet |
| `test_panel.py` | balance, tailles 3 000/2 000, reproductibilité, emboîtement et présence sur 26 scrutins |
| `test_partitions.py` | arrondi par plus forts restes, identifiants corses et fermeture exacte des partitions |
| `test_nls.py` | softmax, bornes, référence, SSE, optimisation multi-départs, sandwich et agrégation |
| `test_outputs.py` | registre, schémas, latents, intersection King/KRT, reprise, garde-fous et β consolidés |
| `test_illustrated_report.py` | moyenne des β communaux, huit scénarios canoniques et rejet d'une fausse intersection King/KRT |

## Couverture fonctionnelle

La suite couvre :

- reproductibilité, balance et emboîtement des panels ;
- stabilité des identifiants et présence sur 26 scrutins ;
- partitions sociales et politiques, fermeture et valeurs négatives ;
- registre politique et disponibilité FN/RN ;
- extraction des bêta, bornes et intersection King/KRT ;
- softmax, référence, objectif, récupération synthétique et stabilité NLS ;
- rang, conditionnement et erreurs standards sandwich ;
- schémas, clés, reprise et immutabilité des sorties.

Commande normale après installation des dépendances de développement :

```powershell
python -m pytest -q -p no:cacheprovider tests
```

`-p no:cacheprovider` évite de créer un cache pytest dans le projet. Les tests utilisent les petits artefacts déjà livrés et ne relancent pas les ajustements MCMC coûteux.

Le détail du rôle des modules testés se trouve dans
`../docs/SCRIPT_GUIDE.md`.
