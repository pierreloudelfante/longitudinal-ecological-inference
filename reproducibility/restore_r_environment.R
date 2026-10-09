args <- commandArgs(trailingOnly = TRUE)
lock_path <- if (length(args) >= 1) args[[1]] else "reproducibility/r-packages.lock.json"
library_path <- if (length(args) >= 2) args[[2]] else ".cache/R/library"

if (!requireNamespace("jsonlite", quietly = TRUE)) {
  stop("Le paquet jsonlite est requis pour lire le verrou R.")
}
if (!requireNamespace("remotes", quietly = TRUE)) {
  install.packages("remotes", repos = "https://cloud.r-project.org")
}

lock <- jsonlite::fromJSON(lock_path, simplifyDataFrame = TRUE)
dir.create(library_path, recursive = TRUE, showWarnings = FALSE)
installed <- installed.packages(lib.loc = library_path)

for (index in seq_len(nrow(lock$packages))) {
  package <- lock$packages$package[[index]]
  version <- lock$packages$version[[index]]
  current <- if (package %in% rownames(installed)) installed[package, "Version"] else NA_character_
  if (is.na(current) || current != version) {
    message(sprintf("Installation de %s %s", package, version))
    remotes::install_version(
      package,
      version = version,
      lib = library_path,
      repos = "https://cloud.r-project.org",
      upgrade = "never",
      dependencies = FALSE
    )
  }
}

message("Environnement R restauré. Lancer ensuite le contrôle full.")
