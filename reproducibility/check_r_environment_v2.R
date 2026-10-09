args <- commandArgs(trailingOnly=TRUE)
if(length(args) != 1L) stop('Usage: Rscript check_r_environment_v2.R <racine>')
root <- normalizePath(args[1], winslash='/', mustWork=TRUE)
lib <- file.path(root, '.cache', 'R', 'library')
.libPaths(c(lib, .Library), include.site=FALSE)
if(as.character(getRversion()) != '4.6.0') stop('Le verrou fourni demande R 4.6.0')
if(.Platform$OS.type != 'windows') stop('La bibliotheque binaire fournie vise Windows x86_64')
if(R.version$platform != 'x86_64-w64-mingw32' || .Machine$sizeof.pointer != 8L) {
  stop(paste('Plateforme R differente: observee', R.version$platform, 'attendue x86_64-w64-mingw32 64 bits'))
}
if(!requireNamespace('jsonlite', quietly=TRUE)) stop('jsonlite absent de la bibliotheque fournie')
lock <- jsonlite::fromJSON(file.path(root, 'reproducibility', 'r-packages.lock.json'))
critical <- jsonlite::fromJSON(file.path(root, 'reproducibility', 'contract_v2', 'critical_r_versions.json'))
# Paquets effectivement utilisés par l'estimation King EI et le moteur graphique.
needed <- lock$critical_packages
if(!setequal(needed, names(critical$versions))) stop('Contrat des versions R critiques incomplet')
for(p in needed) {
  if(!requireNamespace(p, quietly=TRUE)) stop(paste('Paquet R absent:',p))
  expected <- unname(critical$versions[[p]])
  if(length(expected) != 1L || is.na(expected) || !nzchar(expected)) {
    stop(paste('Version critique absente du verrou pour', p))
  }
  observed <- as.character(utils::packageVersion(p))
  # packageVersion normalise les tirets CRAN en points (1.3-3 -> 1.3.3).
  # Comparer les deux formes normalisees pour ne pas rejeter le paquet exact.
  normalize_version <- function(x) gsub('-', '.', x, fixed=TRUE)
  if(normalize_version(observed) != normalize_version(expected)) {
    stop(paste('Version R differente pour', p, 'observee', observed, 'attendue', expected))
  }
}
# Charger dès le preflight chaque paquet binaire réellement livré. Cela détecte
# Smart App Control/WDAC avant les longues estimations, au lieu de découvrir un
# DLL bloqué plusieurs heures plus tard.
library_root <- file.path(root, '.cache', 'R', 'library')
package_dirs <- list.dirs(library_root, recursive=FALSE, full.names=TRUE)
native_packages <- sort(vapply(
  Filter(function(path) {
    length(list.files(file.path(path, 'libs'), pattern='\\.dll$', recursive=TRUE)) > 0L
  }, package_dirs),
  basename,
  character(1L),
  USE.NAMES=FALSE
))
if(length(native_packages) != 22L) {
  stop(paste('Nombre inattendu de paquets R natifs:', length(native_packages), 'attendu 22'))
}
for(p in native_packages) {
  failure <- tryCatch({
    loadNamespace(p)
    NULL
  }, error=function(e) e)
  if(inherits(failure, 'error')) {
    stop(paste(
      'Paquet R natif impossible a charger pendant le preflight:', p, '-',
      conditionMessage(failure),
      'Si Windows mentionne Application Control, Smart App Control ou WDAC, transmettre ce message et ne pas lancer les estimations.'
    ))
  }
}
cat('R, ei/eiPack et 22 paquets R natifs: controle des versions et chargement reussi\n')
