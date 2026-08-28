# Périmètre de production retenu le 26 août 2026

Le calcul Python est désormais limité à six scénarios longitudinaux sur le panel fixe de 2 000 communes :

- H0A et H1, déjà terminés ;
- H0B et H0C, à terminer ;
- H2 et H3, à terminer après H0B/H0C.

Aucun nouveau calcul Python H4, H5, H6 ou H7 ne doit être lancé. Les résultats déjà calculés pour ces scénarios sont conservés comme historique technique, mais restent hors du périmètre canonique de la prochaine livraison.

Après les 156 couples Python (`6 scénarios × 26 élections`), la réplication R porte sur les mêmes 156 entrées avec le package `ei` 1.3-3, qui dépend de `eiPack` 0.2-2. NIMBLE n'est pas utilisé. Cette réplication implémente le modèle EI classique de King (normale bivariée tronquée) et n'est pas mathématiquement identique au KRT beta-binomial PyMC ; la comparaison est donc une robustesse inter-implémentation, pas une égalité bit-à-bit du modèle.

La consigne « finir H0B/H0C et H2/H3 puis arrêter » est appliquée aux fits Python initiaux. Les anciennes files de relances renforcées sont désactivées : un diagnostic MCMC `fail` reste visible et empêche une qualification scientifique `ready=true`, mais ne déclenche plus automatiquement un second calcul long dans ce périmètre raccourci.

Les sorties canoniques finales doivent séparer clairement :

1. les entrées `model_ready` et le panel ;
2. les résultats Python KRT ;
3. les résultats R `ei`/`eiPack` ;
4. la comparaison Python–R ;
5. les figures et tableaux de restitution ;
6. le code minimal de reproduction.
