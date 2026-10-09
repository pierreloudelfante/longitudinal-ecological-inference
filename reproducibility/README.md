# Réplication longitudinale — documentation finale portable

Le point d'entrée est `../REPRODUIRE_TOUT.ps1`. La marche à suivre figure dans `../COMMENCER_ICI.md` : données requises, environnement, lancement, contrôles préalables, résultats et reprise.

`replication_complete.py` enchaîne les fonctions statistiques du projet. `contract_v2/` décrit les 31 sources externes, les paramètres des 240 appels KRT et les 610 fichiers de résultats attendus. Le panel et les matrices d'estimation sont reconstruits à partir des données sources.

`generated/`, les scripts historiques `repro.py` et `build_bundle.py`, les PDF et les supports de présentation conservent leur contenu et leur emplacement. Pour cette procédure, utiliser le lanceur racine ; `reproduce.ps1` lui délègue l'exécution. La commande historique `capture` ne fait pas partie du parcours : elle redéfinit les références, qui doivent rester fixes pendant la vérification.

Le PDF est généré depuis le HTML de l'exécution par Edge ou Chrome. Les présentations PPTX sont des supports distincts ; elles ne font pas partie des 610 fichiers attendus de l'archive de résultats. Les nouvelles sorties sont enregistrées séparément des livraisons de référence.

## Contrôles techniques

```powershell
python -m reproducibility.replication_complete plan
python -m reproducibility.replication_complete integrity
python -m unittest discover -s reproducibility/tests_v2 -v
python -m pytest -q tests/test_nls.py
```

Les deux premières commandes exigent seulement Python. Les tests d'orchestration utilisent certains imports scientifiques et remplacent temporairement les moteurs de calcul intensifs par des substituts. Ils vérifient les appels, les contrôles de fichiers sauvegardés, les limites de temps, l'arrêt des arbres de processus et la reprise explicite ; ils ne constituent pas des réestimations. Les tests NLS utilisent des données synthétiques.

La commande racine exécute ensuite les 17 étapes historiques, fabrique l'archive candidate et lance automatiquement la certification contre `longitudinal_2000_results.zip`. Elle échoue si les 610 chemins, la structure des tables, les statuts, les diagnostics ou les tolérances numériques ne sont pas respectés. Une comparaison seule peut être relancée ainsi :

```powershell
python -m reproducibility.replication_complete certify `
  --reference-results .\longitudinal_2000_results.zip `
  --candidate-results .\deliverables\longitudinal_2000_results_recalcules.zip
```

Les seuils préenregistrés et leur justification figurent dans `CERTIFICATION_SCIENTIFIQUE_V2_2.md` (nom conservé pour compatibilité) et `contract_v2/certification_policy_v1.json`. La portée des validations antérieures est décrite dans `AUDIT_CORRECTIONS_V2.md`. Le seul guide opératoire courant est `../COMMENCER_ICI.md`; le reçu du binaire R remplacé pour la portabilité Windows est `contract_v2/R_CLI_3_6_6_CRAN_RECEIPT.json`.

Les tests de code, le lanceur, l'installation Python dans un environnement neuf, la génération PDF Chrome/Edge et un rejeu exact de la comparaison contre l'archive de référence ont été exécutés. L'exécution intégrale à partir des 31 archives brutes reste la seule preuve finale des 610 sorties ; elle est certifiée par `deliverables/longitudinal_2000_results_recalcules.certification.json`.
