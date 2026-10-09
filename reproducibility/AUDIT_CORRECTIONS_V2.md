# Réplication longitudinale — note technique v2, documentation v2.1

## Verdict et portée

Les sources brutes sont fournies séparément de l'archive de code. Leurs noms, tailles, empreintes et emplacements attendus figurent dans le contrat de réplication. La procédure v2 corrige l'enchaînement des étapes de préparation, d'estimation et de restitution.

La procédure couvre les étapes allant des données brutes externes aux fichiers de résultats attendus. **L'exécution intégrale depuis les sources reste à valider** : les tests disponibles ne comprennent pas la reconstruction depuis les 31 archives ni l'exécution de l'ensemble des ajustements Windows/R/MCMC.

Le correctif ne transforme pas les modèles ayant des diagnostics défavorables en modèles validés. Il ne modifie aucun prior, estimateur, seuil statistique, règle de regroupement électoral ou règle de construction des marges.

## Archives de référence

| Archive | Taille | SHA-256 |
|---|---:|---|
| `longitudinal_2000_reproduction_complete.zip` | 30 049 531 octets | `56cb398adb49efee97df57157b2e3ab46efcdc36fa3ac9df4236be2a849d96db` |
| `longitudinal_2000_results.zip` | 143 246 075 octets | `a5c0978e822e2276c7607764cfa74dd6ece8f135f2af1d290a8a880202cd5b79` |

La décompression et le CRC des deux archives ont été vérifiés. Le paquet de réplication original contient 1 191 fichiers ; l'archive de résultats en contient 610. La livraison technique est distincte et reste hors du périmètre des modifications.

## Blocages constatés et corrections

| Dans le paquet original | Correction limitée à la réplication |
|---|---|
| Contrôle de 27 sources, alors que `data_io.py` et les covariables utilisent quatre archives supplémentaires. | Contrat de 31 sources, noms de téléchargement acceptés, tailles et SHA-256 vérifiés. Aucun téléchargement des données imposé. |
| `python -m code_longitudinal.build_longitudinal_panel` ne fait rien : le module expose une fonction, sans exécution `__main__`. | Appel effectif de `build_longitudinal_panel()`. |
| Préparation globale visant le mauvais chemin par défaut du panel et contrôle de 240 partitions incompatible avec l'ensemble des scénarios. | `prepare_model_ready(..., sample_size=2000, panel_path=PANEL_PATH)` explicite pour les 292 couples sur le panel ; audit national 270 admissibles + 22 différés conservé. |
| Référence du panel écrite par Arrow 25.0.0, mais verrou fourni contenant Arrow 24.0.0 : exiger le même SHA binaire aurait bloqué une reconstruction aux données identiques. | Validation de toutes les lignes/colonnes et de l'ordre contre le CSV maître historique, puis propagation du vrai SHA du panel reconstruit aux contrôles d'exécution. Le fichier de référence ne sert jamais d'entrée d'estimation. |
| Relance des KRT au moyen des configurations générales, qui ne restituent pas tous les réglages individuels historiques. | Plan explicite des 240 appels : graines, draws, warmup, chaînes, cœurs, acceptation cible, profondeur et moteur. Six H0A/H1 renforcés restent à 2 000 + 2 000 ; les autres à 1 000 + 1 000. |
| Consolidation des 240 KRT avant construction des tables canoniques H0A/H1 qu'elle attend. | Reconstruction du socle intermédiaire de 52 KRT et 270 NLS avant consolidation complète, sans s'arrêter à ce sous-ensemble. |
| Certaines fonctions renvoient un dictionnaire signalant des échecs, mais le processus peut sortir avec le code zéro. | Contrôles explicites des nombres attendus et des statuts ; propagation des erreurs au lanceur et arrêt du lot incomplet. |
| Consolidation RxC imposant exactement 17 diagnostics `pass` et 5 `fail`, comme l'exécution historique. | L'adaptateur vérifie la présence des 22 diagnostics, sans imposer leur répartition historique ni changer les seuils de calcul. Les valeurs réellement obtenues sont conservées. |
| Ancien constructeur de restitution dépendant de deux lanceurs et deux documents absents du ZIP autonome. | Les deux anciens lanceurs ne sont plus indispensables à la restitution des 610 fichiers. Les deux documents historiques sont fournis comme ressources de contexte au constructeur, sans reprise d'estimations. |
| Construction de l'atlas sans commande de génération des 480 densités sous-jacentes. | Export des données de densité, exécution effective du générateur R, contrôle du lot et construction de l'atlas. |
| PDF restauré depuis une copie historique plutôt que reconstruit. | Impression du HTML nouvellement généré via Edge/Chrome ; essai réel d'impression prévu dans le preflight. Le PDF historique du ZIP demeure inchangé. |
| Anciennes attestations visuelles inscrites en dur par un finaliseur. | Les nouvelles sorties QA ne déclarent pas d'inspection visuelle non effectuée. |
| Commande `capture` remplaçant les références juste avant `verify`. | Contrat de référence figé ; contrôle des fichiers et tables attendus sans régénérer la référence à partir des candidats. |
| Présentation PowerPoint imposée pour obtenir le ZIP de résultats. | Le parcours vise exactement les 610 fichiers du ZIP de résultats courant ; les supports de présentation historiques restent conservés, sans devenir une dépendance inutile. |

## Fichiers et tables de résultats attendus

Les huit tables principales sont enregistrées dans le contrat avec leurs colonnes et nombres de lignes :

| Table | Lignes attendues |
|---|---:|
| `longitudinal_contrasts_krt_r_nls.parquet` | 720 |
| `longitudinal_krt_aggregate.parquet` | 720 |
| `longitudinal_krt_commune.parquet` | 480 000 |
| `longitudinal_nls.parquet` | 2 370 |
| `longitudinal_nls_covariate_coefficients.parquet` | 6 720 |
| `longitudinal_nls_covariates.parquet` | 2 880 |
| `longitudinal_r_ei_aggregate.parquet` | 720 |
| `longitudinal_r_ei_commune.parquet` | 480 000 |

Le contrôle examine également les clés élection × hypothèse, l'unicité des observations communales, la couverture de 2 000 communes par couple, les spécifications covariées et la présence des incertitudes. Les valeurs non finies de R conservent leur statut et leur documentation, sans imputation ni suppression.

Ces dimensions proviennent du manifeste du ZIP actuel. **Elles ne sont pas des résultats recalculés pendant cet audit.**

## Traçabilité des 240 réglages KRT

Le fichier `contract_v2/krt_replay_240.json` associe chaque couple à son identifiant de run de référence. 123 manifestes individuels exacts ont été retrouvés dans les archives de continuation déjà fournies. Pour 117 autres runs, les paramètres candidats ont été reconstruits à partir des configurations et vérifiés contre le suffixe SHA-256 de l'identifiant du run. Les 240 charges utiles de hachage sont incluses et revérifiées par la commande `plan`.

Ce contrôle permet de détecter une graine, un nombre de tirages ou un paramètre de relance incohérent. Il ne reconstitue pas à lui seul l'environnement matériel historique ni ne garantit des tirages identiques bit pour bit. Les paramètres absents des anciens manifestes sont distingués des paramètres explicitement enregistrés ; le défaut NumPyro du King99 historique est documenté dans le code fourni.

Les fichiers de référence d'estimation restent externes et intacts. Le CSV de référence du panel sert exclusivement à comparer le résultat de la reconstruction ; les estimations prennent le panel et les matrices nouvellement calculés depuis les données.

## Modifications des fichiers d'origine

Sur les 1 191 fichiers du ZIP de réplication original, **5 sont modifiés** :

1. `REPRODUIRE_TOUT.ps1` — lanceur unique corrigé.
2. `COMMENCER_ICI.md` — procédure de démarrage et limites.
3. `DONNEES_BRUTES/LISEZ_MOI.txt` — contrat des 31 archives.
4. `reproducibility/README.md` — documentation de la couche de réplication.
5. `reproducibility/reproduce.ps1` — délégation au lanceur unique.

**Les 1 186 autres fichiers doivent conserver exactement le même SHA-256.** Aucun fichier original n'est supprimé. Le code dans `code_longitudinal/`, les scripts statistiques R, les configurations scientifiques, les verrous existants et les PDF/PPTX d'origine sont conservés.

Les nouveaux fichiers sont confinés à la couche `reproducibility/` : orchestrateur, contrat, contrôles et tests. L'adaptation des constantes de provenance du panel, de l'assertion de répartition des diagnostics et des copies de restitution est faite dans cette couche à l'exécution. Elle ne réécrit pas les modules statistiques d'origine.

Un relevé complet des empreintes avant/après accompagne le correctif. Les caches créés par les tests dans l'environnement de travail ne sont pas livrés.

## Tests réalisés et limites

Les journaux se trouvent sous `reproducibility/tests_executed/`.

- **31 tests de contrat et d'orchestration** : couverture du plan, rejet d'une graine ou d'une empreinte modifiée, détection d'un couple dupliqué, résolution des données avec chemins contenant des espaces, contrôle des erreurs, distribution des 240 appels avec leurs réglages, séquence des 17 étapes, arrêt sur échec et reprise. Les moteurs coûteux sont remplacés localement par des substituts dans les tests de distribution ; aucune estimation n'est présentée comme issue de ces substituts.
- **11 tests NLS d'origine**, sur données synthétiques : probabilités, marges, moindres carrés, départs multiples, erreurs-types sandwich et agrégation. Ils ne remplacent pas les 292 + 960 estimations du projet.
- Le CSV maître de référence a été comparé aux 2 000 lignes de panel livrées dans le ZIP actuel : mêmes 21 colonnes et mêmes valeurs à la tolérance documentée, avec identifiants et ordre exacts.
- Contrôle des réglages historiques de **240/240 KRT**, compilation du code et vérification des **1 186 fichiers originaux préservés**.
- Contrôles du ZIP final : CRC, extraction fraîche, démarrage de `plan` et `integrity` depuis un dossier avec espaces. Le rapport externe de livraison donne leurs résultats effectivement obtenus.

**Validations restant à effectuer** : reconstruction du panel depuis les 31 archives brutes, estimation intégrale des KRT et R, lot longitudinal de NLS, 960 sensibilités, génération des 480 graphiques et rapport depuis ces nouveaux calculs, installation propre sous Windows du verrou Python, invocation réelle de PowerShell/R/Edge. L'environnement d'audit est Linux/Python 3.13, et non le Windows/Python 3.12.10/R 4.6.0 du contrat fourni.

État de validation : **enchaînement corrigé, périmètre contrôlé et tests techniques documentés ; exécution scientifique intégrale restant à effectuer sur les données et l'environnement prévus**. Un résultat MCMC ne doit pas être jugé par le SHA-256 d'un fichier d'export ; les écarts de valeurs et les diagnostics doivent être examinés après réestimation.

## Révision documentaire v2.1

La v2.1 reformule le guide de démarrage, le README de réplication et la présente note technique. Elle conserve tous les chemins, scripts, configurations, données de référence, rapports historiques et journaux de tests de la v2. Le relevé `contract_v2/CHANGEMENTS_FICHIERS.csv` actualise uniquement les empreintes des documents révisés. Cette révision documentaire ne constitue pas une validation supplémentaire des estimations.
