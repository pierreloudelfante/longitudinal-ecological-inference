source(file.path(dirname(normalizePath(sub("^--file=", "", grep("^--file=", commandArgs(), value = TRUE)[[1]]), winslash = "/")), "common.R"))

options <- parse_options()
pair_key <- paste(options$election, options$scenario, sep = "__")
r_dir <- file.path(RESULTS_DIR, "nls", pair_key)
r_estimates_path <- file.path(r_dir, "r_nls_estimates.csv")
r_diagnostics_path <- file.path(r_dir, "r_nls_diagnostics.csv")
if (!file.exists(r_estimates_path)) stop("Run the paired R NLS first: ", r_estimates_path)

python <- latest_python_run(options$election, options$scenario, "rosen_nls")
if (is.null(python)) stop("No successful matched Python NLS run found.")
python_estimates_path <- file.path(python$run_dir, "longitudinal_estimates.csv")
python_diagnostics_path <- file.path(python$run_dir, "model_diagnostics.csv")

r_estimates <- read.csv(r_estimates_path, stringsAsFactors = FALSE, check.names = FALSE)
python_estimates <- read.csv(python_estimates_path, stringsAsFactors = FALSE, check.names = FALSE)
comparison <- merge(
  r_estimates[, c("election_id", "scenario_id", "social_group", "vote_category", "estimate")],
  python_estimates[, c("election_id", "scenario_id", "social_group", "vote_category", "estimate")],
  by = c("election_id", "scenario_id", "social_group", "vote_category"),
  suffixes = c("_r", "_python"),
  all = TRUE
)
if (nrow(comparison) != nrow(r_estimates) || any(!complete.cases(comparison))) {
  stop("R/Python estimand keys do not match exactly.")
}
comparison$difference_r_minus_python <- comparison$estimate_r - comparison$estimate_python
comparison$absolute_difference <- abs(comparison$difference_r_minus_python)

r_diag <- read.csv(r_diagnostics_path, stringsAsFactors = FALSE, check.names = FALSE)
python_diag <- read.csv(python_diagnostics_path, stringsAsFactors = FALSE, check.names = FALSE)
summary <- data.frame(
  election_id = options$election,
  scenario_id = options$scenario,
  panel_id = PANEL_ID,
  n_communes_r = unique(r_estimates$n_communes_used),
  n_communes_python = unique(python_estimates$n_communes_used),
  python_run_id = python$run_id,
  python_engine = "SciPy least_squares TRF",
  r_engine = "R stats::optim BFGS",
  python_objective_sse = python_diag$objective_sse_unweighted[[1]],
  r_objective_sse = r_diag$objective_sse_unweighted[[1]],
  objective_sse_difference = r_diag$objective_sse_unweighted[[1]] - python_diag$objective_sse_unweighted[[1]],
  max_abs_estimate_difference = max(comparison$absolute_difference),
  mean_abs_estimate_difference = mean(comparison$absolute_difference),
  exact_estimand_key_match = TRUE,
  exact_panel_n_match = identical(unique(r_estimates$n_communes_used), unique(python_estimates$n_communes_used)),
  stringsAsFactors = FALSE
)

output_dir <- file.path(RESULTS_DIR, "comparison")
dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)
write.csv(comparison, file.path(output_dir, paste0("nls_cells__", pair_key, ".csv")), row.names = FALSE, fileEncoding = "UTF-8")
write.csv(summary, file.path(output_dir, paste0("nls_summary__", pair_key, ".csv")), row.names = FALSE, fileEncoding = "UTF-8")
write_json_file(
  list(
    generated_at_utc = utc_now(),
    comparison_type = "matched mathematical specification with independent optimizer implementations",
    panel_id = PANEL_ID,
    input_sha256 = read_json_file(file.path(r_dir, "manifest.json"))$input_sha256,
    python_run_id = python$run_id,
    summary = as.list(summary[1, ])
  ),
  file.path(output_dir, paste0("nls_manifest__", pair_key, ".json"))
)
print(summary)
