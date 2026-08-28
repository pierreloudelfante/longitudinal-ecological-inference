script_directory <- function() {
  file_arg <- grep("^--file=", commandArgs(), value = TRUE)
  if (!length(file_arg)) {
    return(normalizePath(getwd(), winslash = "/", mustWork = TRUE))
  }
  dirname(normalizePath(sub("^--file=", "", file_arg[[1]]), winslash = "/", mustWork = TRUE))
}

R_REPLICATION_DIR <- script_directory()
PROJECT_ROOT <- normalizePath(
  file.path(R_REPLICATION_DIR, "..", ".."),
  winslash = "/",
  mustWork = TRUE
)
LOCAL_R_LIBRARY <- file.path(PROJECT_ROOT, ".r_lib")
if (dir.exists(LOCAL_R_LIBRARY)) {
  .libPaths(c(LOCAL_R_LIBRARY, .libPaths()))
}

SPEC_VERSION <- "longitudinal_2000_v1"
HARMONIZATION_VERSION <- "stable_unit_geography_v1"
PANEL_ID <- "longitudinal_2000_v1__strict_nested_3000__seed_20260803"
PANEL_CSV <- file.path(PROJECT_ROOT, "panel", "longitudinal_2000_v1.csv")
PANEL_MANIFEST <- file.path(PROJECT_ROOT, "panel", "longitudinal_2000_v1_manifest.json")
RUN_PLAN_CSV <- file.path(
  PROJECT_ROOT,
  "outputs",
  SPEC_VERSION,
  "audit",
  "longitudinal_run_plan.csv"
)
MODEL_READY_DIR <- file.path(PROJECT_ROOT, "outputs", "model_ready")
PYTHON_RUNS_DIR <- file.path(PROJECT_ROOT, "outputs", "runs")
RESULTS_DIR <- file.path(R_REPLICATION_DIR, "results")

PRIMARY_N <- 2000L
MASTER_N <- 3000L
RANDOM_SEED <- 20260802L

dir.create(RESULTS_DIR, recursive = TRUE, showWarnings = FALSE)

require_jsonlite <- function() {
  if (!requireNamespace("jsonlite", quietly = TRUE)) {
    stop("The locally installed jsonlite package is required.")
  }
}

read_json_file <- function(path) {
  require_jsonlite()
  jsonlite::fromJSON(path, simplifyVector = FALSE)
}

write_json_file <- function(value, path) {
  require_jsonlite()
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  jsonlite::write_json(
    value,
    path,
    pretty = TRUE,
    auto_unbox = TRUE,
    null = "null",
    na = "null"
  )
}

sha256_file <- function(path) {
  if (!file.exists(path)) stop("Missing file for SHA-256: ", path)
  if (requireNamespace("digest", quietly = TRUE)) {
    return(digest::digest(file = path, algo = "sha256", serialize = FALSE))
  }
  if (.Platform$OS.type == "windows") {
    lines <- system2("certutil", c("-hashfile", shQuote(path), "SHA256"), stdout = TRUE, stderr = TRUE)
    candidates <- gsub("[^0-9A-Fa-f]", "", lines)
    candidates <- candidates[nchar(candidates) == 64L]
    if (length(candidates)) return(tolower(candidates[[1]]))
  }
  stop("SHA-256 requires the digest package or Windows certutil.")
}

relative_path <- function(path) {
  normalized <- normalizePath(path, winslash = "/", mustWork = FALSE)
  prefix <- paste0(PROJECT_ROOT, "/")
  if (startsWith(normalized, prefix)) substring(normalized, nchar(prefix) + 1L) else normalized
}

read_panel_primary <- function() {
  if (!file.exists(PANEL_CSV)) stop("Missing canonical panel CSV: ", PANEL_CSV)
  panel <- read.csv(
    PANEL_CSV,
    stringsAsFactors = FALSE,
    check.names = FALSE,
    colClasses = c(unit_id = "character", panel_id = "character", sample_id = "character")
  )
  if (nrow(panel) != MASTER_N) stop("Canonical panel must contain exactly 3,000 master rows.")
  if (anyDuplicated(panel$unit_id)) stop("Duplicate unit_id in canonical panel.")
  if (!identical(as.integer(panel$master_draw_order), seq_len(MASTER_N))) {
    stop("master_draw_order is not exactly 1:3000.")
  }
  if (!all(panel$panel_id == PANEL_ID) || !all(panel$sample_id == PANEL_ID)) {
    stop("Unexpected panel_id/sample_id in canonical panel.")
  }
  primary <- panel[as.logical(panel$included_primary_2000), , drop = FALSE]
  primary <- primary[order(primary$master_draw_order), , drop = FALSE]
  if (nrow(primary) != PRIMARY_N) stop("Primary panel must contain exactly 2,000 rows.")
  if (!identical(as.integer(primary$master_draw_order), seq_len(PRIMARY_N))) {
    stop("Primary panel is not the first 2,000 rows of the master draw.")
  }
  primary
}

read_run_plan <- function() {
  if (!file.exists(RUN_PLAN_CSV)) stop("Missing longitudinal run plan: ", RUN_PLAN_CSV)
  read.csv(RUN_PLAN_CSV, stringsAsFactors = FALSE, check.names = FALSE)
}

model_ready_path <- function(election_id, scenario_id) {
  file.path(
    MODEL_READY_DIR,
    paste0(
      election_id,
      "__",
      scenario_id,
      "__",
      PANEL_ID,
      "__n2000.csv"
    )
  )
}

read_model_ready <- function(election_id, scenario_id, panel = read_panel_primary()) {
  path <- model_ready_path(election_id, scenario_id)
  if (!file.exists(path)) stop("Missing model-ready CSV: ", path)
  dat <- read.csv(
    path,
    stringsAsFactors = FALSE,
    check.names = FALSE,
    colClasses = c(unit_id = "character", panel_id = "character", sample_id = "character")
  )
  check <- check_model_ready(dat, panel, election_id, scenario_id)
  attr(dat, "input_check") <- check
  attr(dat, "source_path") <- path
  dat
}

check_model_ready <- function(dat, panel, election_id, scenario_id, tolerance = 1e-12) {
  if (nrow(dat) != PRIMARY_N) stop("Model-ready input is not exactly 2,000 rows: ", election_id, "/", scenario_id)
  if (anyDuplicated(dat$unit_id)) stop("Duplicate unit_id: ", election_id, "/", scenario_id)
  if (!identical(as.character(dat$unit_id), as.character(panel$unit_id))) {
    stop("unit_id values or ordering differ from the primary panel: ", election_id, "/", scenario_id)
  }
  if (!all(dat$panel_id == PANEL_ID) || !all(dat$sample_id == PANEL_ID)) {
    stop("panel_id/sample_id mismatch: ", election_id, "/", scenario_id)
  }
  if (!all(dat$election_id == election_id) || !all(dat$scenario_id == scenario_id)) {
    stop("Election/scenario metadata mismatch: ", election_id, "/", scenario_id)
  }
  if (!identical(as.integer(dat$sample_rank), seq_len(PRIMARY_N))) {
    stop("sample_rank is not exactly 1:2000: ", election_id, "/", scenario_id)
  }
  if (!identical(as.integer(dat$master_draw_order), seq_len(PRIMARY_N))) {
    stop("master_draw_order is not exactly 1:2000: ", election_id, "/", scenario_id)
  }

  n_total <- as.numeric(dat$N_g)
  n_columns <- grep("^N__", names(dat), value = TRUE)
  x_columns <- grep("^X__", names(dat), value = TRUE)
  y_columns <- grep("^Y__", names(dat), value = TRUE)
  if (!length(n_columns) || length(n_columns) != length(x_columns) || !length(y_columns)) {
    stop("Incomplete N__/X__/Y__ model-ready columns: ", election_id, "/", scenario_id)
  }
  n_matrix <- as.matrix(data.frame(lapply(dat[n_columns], as.numeric), check.names = FALSE))
  x_matrix <- as.matrix(data.frame(lapply(dat[x_columns], as.numeric), check.names = FALSE))
  y_matrix <- as.matrix(data.frame(lapply(dat[y_columns], as.numeric), check.names = FALSE))
  if (any(!is.finite(n_total)) || any(n_total <= 0) || any(abs(n_total - round(n_total)) > tolerance)) {
    stop("Invalid N_g counts: ", election_id, "/", scenario_id)
  }
  if (any(!is.finite(n_matrix)) || any(n_matrix < 0) || any(abs(n_matrix - round(n_matrix)) > tolerance)) {
    stop("Invalid social counts: ", election_id, "/", scenario_id)
  }
  if (any(!is.finite(y_matrix)) || any(y_matrix < 0) || any(abs(y_matrix - round(y_matrix)) > tolerance)) {
    stop("Invalid political counts: ", election_id, "/", scenario_id)
  }
  social_gap <- max(abs(rowSums(n_matrix) - n_total))
  political_gap <- max(abs(rowSums(y_matrix) - n_total))
  share_gap <- max(abs(rowSums(x_matrix) - 1))
  share_count_gap <- max(abs(x_matrix - n_matrix / n_total))
  if (social_gap != 0) stop("Social counts do not close exactly: ", election_id, "/", scenario_id)
  if (political_gap != 0) stop("Political counts do not close exactly: ", election_id, "/", scenario_id)
  if (share_gap > tolerance || share_count_gap > tolerance) {
    stop("Social fractions do not round-trip to social counts: ", election_id, "/", scenario_id)
  }

  list(
    election_id = election_id,
    scenario_id = scenario_id,
    rows = nrow(dat),
    unique_unit_ids = length(unique(dat$unit_id)),
    exact_panel_order_match = TRUE,
    social_count_closure_max_abs = social_gap,
    political_count_closure_max_abs = political_gap,
    social_share_closure_max_abs = share_gap,
    social_share_count_roundtrip_max_abs = share_count_gap,
    N_total = sum(n_total)
  )
}

parse_options <- function(args = commandArgs(trailingOnly = TRUE)) {
  result <- list(
    election = "leg_1962_r1",
    scenario = "H0A",
    all = FALSE,
    starts = 20L,
    cores = 1L,
    force = FALSE,
    save_fit = FALSE
  )
  for (arg in args) {
    if (arg == "--all") result$all <- TRUE
    else if (arg == "--force") result$force <- TRUE
    else if (arg == "--save-fit") result$save_fit <- TRUE
    else if (startsWith(arg, "--election=")) result$election <- sub("^--election=", "", arg)
    else if (startsWith(arg, "--scenario=")) result$scenario <- sub("^--scenario=", "", arg)
    else if (startsWith(arg, "--starts=")) result$starts <- as.integer(sub("^--starts=", "", arg))
    else if (startsWith(arg, "--cores=")) result$cores <- as.integer(sub("^--cores=", "", arg))
    else stop("Unknown command-line argument: ", arg)
  }
  result
}

utc_now <- function() format(Sys.time(), "%Y-%m-%dT%H:%M:%OSZ", tz = "UTC")

latest_python_run <- function(election_id, scenario_id, model_prefix) {
  candidates <- list()
  manifests <- list.files(PYTHON_RUNS_DIR, pattern = "manifest\\.json$", recursive = TRUE, full.names = TRUE)
  for (manifest_path in manifests) {
    manifest <- tryCatch(read_json_file(manifest_path), error = function(e) NULL)
    if (is.null(manifest) || !identical(manifest$status, "success")) next
    parameters <- manifest$parameters
    if (is.null(parameters)) next
    if (!identical(parameters$election_id, election_id) || !identical(parameters$scenario_id, scenario_id)) next
    if (!identical(parameters$panel_id, PANEL_ID)) next
    if (!startsWith(parameters$model_key, model_prefix)) next
    run_dir <- dirname(manifest_path)
    if (!file.exists(file.path(run_dir, "longitudinal_estimates.csv"))) next
    candidates[[length(candidates) + 1L]] <- list(
      run_dir = run_dir,
      run_id = manifest$run_id,
      finished_at_utc = if (is.null(manifest$finished_at_utc)) "" else manifest$finished_at_utc,
      manifest = manifest
    )
  }
  if (!length(candidates)) return(NULL)
  candidates[[which.max(vapply(candidates, function(x) x$finished_at_utc, character(1)))]]
}
