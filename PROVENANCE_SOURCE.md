# Provenance du kit final

- Projet source : `ARE/part2/longitudinal_2022`
- Branche historique de préparation : `codex/finalisation-professeur-240`
- Révision Git historique de base : `5b243c6b3b63f8cc4102182a65f9e88e714e1370`
- Date du gel final portable : 2026-10-08
- Entrées brutes attendues : **31 archives ZIP** — 26 archives électorales et 5 archives socio-économiques — contrôlées par nom, taille et SHA-256 à partir de `reproducibility/contract_v2/raw_sources_31.json`

Le kit embarque les sources et réglages de la livraison reproductible. L'overlay portable final, distinct de la révision historique de base, est authentifié fichier par fichier dans `reproducibility/contract_v2/CHANGEMENTS_FICHIERS.csv` et décrit dans `reproducibility/contract_v2/V26_PACKAGE_METADATA.json`. Le reçu de changement couvre tous les autres fichiers du paquet et exclut sa propre auto-empreinte par conception. Le kit n'embarque pas les données brutes : le lanceur les recherche récursivement dans le dossier indiqué par `-DossierDonneesBrutes`.

La mention historique de 27 archives était incomplète : elle omettait quatre archives socio-économiques utilisées par la préparation et les modèles avec covariables. Le contrat exécutable final en exige 31 et refuse de commencer si l'une d'elles manque ou si sa taille ou son SHA-256 diffère.
