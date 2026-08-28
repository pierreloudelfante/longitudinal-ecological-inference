#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(cmdstanr)
  library(jsonlite)
  library(posterior)
})

args <- commandArgs(trailingOnly = TRUE)
runner_file_arg <- grep("^--file=", commandArgs(trailingOnly = FALSE), value = TRUE)
runner_script <- if (length(runner_file_arg)) {
  normalizePath(sub("^--file=", "", runner_file_arg[[1]]), mustWork = TRUE, winslash = "/")
} else {
  NA_character_
}
if (length(args) < 4L) {
  stop(
    paste(
      "usage: run_krt_replication.R MODEL_READY_CSV OUTPUT_DIR",
      "STAN_FILE CMDSTAN_PATH [SEED] [WARMUP] [DRAWS] [CHAINS]"
    )
  )
}

input_csv <- normalizePath(args[[1]], mustWork = TRUE, winslash = "/")
output_dir <- normalizePath(args[[2]], mustWork = FALSE, winslash = "/")
stan_file <- normalizePath(args[[3]], mustWork = TRUE, winslash = "/")
cmdstan_path_arg <- normalizePath(args[[4]], mustWork = TRUE, winslash = "/")
seed <- if (length(args) >= 5L) as.integer(args[[5]]) else 20260802L
iter_warmup <- if (length(args) >= 6L) as.integer(args[[6]]) else 1000L
iter_sampling <- if (length(args) >= 7L) as.integer(args[[7]]) else 1000L
chains <- if (length(args) >= 8L) as.integer(args[[8]]) else 4L
king_lambda <- 0.5
adapt_delta <- 0.99
max_treedepth <- 14L

dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)
chains_dir <- file.path(output_dir, "chains")
dir.create(chains_dir, recursive = TRUE, showWarnings = FALSE)
set_cmdstan_path(cmdstan_path_arg)

frame <- read.csv(
  input_csv,
  stringsAsFactors = FALSE,
  check.names = FALSE,
  fileEncoding = "UTF-8-BOM",
  colClasses = c(unit_id = "character")
)

required <- c(
  "unit_id", "panel_id", "election_id", "scenario_id", "sample_rank", "N_g"
)
missing_required <- setdiff(required, names(frame))
if (length(missing_required)) {
  stop("missing required columns: ", paste(missing_required, collapse = ", "))
}
x_columns <- grep("^X__", names(frame), value = TRUE)
n_columns <- grep("^N__", names(frame), value = TRUE)
y_columns <- grep("^Y__", names(frame), value = TRUE)
if (length(x_columns) != 2L) {
  stop("expected exactly two X__ columns, found ", length(x_columns))
}
if (length(n_columns) != 2L) {
  stop("expected exactly two N__ columns, found ", length(n_columns))
}
if (length(y_columns) != 2L) {
  stop("expected exactly two Y__ columns, found ", length(y_columns))
}
if (!identical(sub("^X__", "", x_columns), sub("^N__", "", n_columns))) {
  stop("X__ and N__ partitions have different names or ordering")
}
x_column <- x_columns[[1]]
n1_column <- n_columns[[1]]
n2_column <- n_columns[[2]]
y_column <- y_columns[[1]]

if (nrow(frame) != 2000L) stop("R KRT production requires exactly 2,000 communes")
if (anyDuplicated(frame$unit_id)) stop("duplicate unit_id in R KRT input")
if (length(unique(frame$panel_id)) != 1L) stop("multiple panel_id values")
if (length(unique(frame$election_id)) != 1L) stop("multiple election_id values")
if (length(unique(frame$scenario_id)) != 1L) stop("multiple scenario_id values")

integer_columns <- c("N_g", n_columns, y_columns)
for (column in integer_columns) {
  values <- frame[[column]]
  if (any(!is.finite(values)) || any(values < 0) || any(abs(values - round(values)) > 1e-8)) {
    stop("invalid non-negative integer counts in ", column)
  }
}
if (any(frame$N_g <= 0)) stop("N_g must be strictly positive")
if (any(rowSums(frame[n_columns]) != frame$N_g)) {
  stop("social counts do not close to N_g")
}
if (any(frame[[y_columns[[1]]]] + frame[[y_columns[[2]]]] != frame$N_g)) {
  stop("vote counts do not close to N_g")
}
if (any(abs(rowSums(frame[x_columns]) - 1) > 1e-12)) {
  stop("social proportions do not close to one")
}
if (any(abs(as.matrix(frame[x_columns]) - as.matrix(frame[n_columns]) / frame$N_g) > 1e-12)) {
  stop("X__ proportions are inconsistent with integer social counts")
}

stan_data <- list(
  P = nrow(frame),
  x = as.numeric(frame[[x_column]]),
  N = as.integer(frame$N_g),
  Y = as.integer(frame[[y_column]]),
  N1_weight = as.numeric(frame[[n1_column]]),
  N2_weight = as.numeric(frame[[n2_column]]),
  king_lambda = king_lambda
)

model <- cmdstan_model(stan_file, force_recompile = FALSE, quiet = FALSE)
started_at <- format(Sys.time(), tz = "UTC", usetz = TRUE)
started_clock <- proc.time()[["elapsed"]]
fit <- model$sample(
  data = stan_data,
  seed = seed,
  chains = chains,
  parallel_chains = 1L,
  iter_warmup = iter_warmup,
  iter_sampling = iter_sampling,
  refresh = 100L,
  adapt_delta = adapt_delta,
  max_treedepth = max_treedepth,
  save_warmup = FALSE,
  output_dir = chains_dir
)
elapsed_seconds <- proc.time()[["elapsed"]] - started_clock
finished_at <- format(Sys.time(), tz = "UTC", usetz = TRUE)

summarize_matrix <- function(draw_matrix, parameter, frame) {
  expected <- paste0(parameter, "[", seq_len(nrow(frame)), "]")
  if (!all(expected %in% colnames(draw_matrix))) {
    stop("missing posterior columns for ", parameter)
  }
  values <- draw_matrix[, expected, drop = FALSE]
  quantiles <- apply(values, 2L, quantile, probs = c(0.025, 0.5, 0.975), names = FALSE)
  data.frame(
    unit_id = frame$unit_id,
    sample_rank = frame$sample_rank,
    parameter = parameter,
    mean = colMeans(values),
    sd = apply(values, 2L, sd),
    q025 = quantiles[1L, ],
    q50 = quantiles[2L, ],
    q975 = quantiles[3L, ],
    stringsAsFactors = FALSE
  )
}

b1_draws <- as.matrix(fit$draws(variables = "b_1", format = "draws_matrix"))
b1_summary <- summarize_matrix(b1_draws, "b_1", frame)
rm(b1_draws)
invisible(gc())
b2_draws <- as.matrix(fit$draws(variables = "b_2", format = "draws_matrix"))
b2_summary <- summarize_matrix(b2_draws, "b_2", frame)
rm(b2_draws)
invisible(gc())

commune <- rbind(b1_summary, b2_summary)
commune$panel_id <- frame$panel_id[[1]]
commune$election_id <- frame$election_id[[1]]
commune$scenario_id <- frame$scenario_id[[1]]
commune$model_key <- "krt_beta_binomial_stan_r_exact"
commune <- commune[, c(
  "panel_id", "election_id", "scenario_id", "model_key", "unit_id",
  "sample_rank", "parameter", "mean", "sd", "q025", "q50", "q975"
)]
write.csv(commune, file.path(output_dir, "commune_latent_summaries_r.csv"), row.names = FALSE)

aggregate_variables <- c("beta1_aggregate", "beta2_aggregate", "contrast_aggregate")
aggregate_draws <- as.matrix(fit$draws(variables = aggregate_variables, format = "draws_matrix"))
aggregate <- do.call(rbind, lapply(aggregate_variables, function(variable) {
  values <- aggregate_draws[, variable]
  data.frame(
    panel_id = frame$panel_id[[1]],
    election_id = frame$election_id[[1]],
    scenario_id = frame$scenario_id[[1]],
    model_key = "krt_beta_binomial_stan_r_exact",
    estimand = variable,
    mean = mean(values),
    sd = sd(values),
    q025 = unname(quantile(values, 0.025)),
    q50 = unname(quantile(values, 0.5)),
    q975 = unname(quantile(values, 0.975)),
    n_posterior_draws = length(values),
    stringsAsFactors = FALSE
  )
}))
write.csv(aggregate, file.path(output_dir, "aggregate_summaries_r.csv"), row.names = FALSE)

parameter_summary <- fit$summary(
  variables = c("c_1", "d_1", "c_2", "d_2", "b_1", "b_2")
)
write.csv(parameter_summary, file.path(output_dir, "parameter_diagnostics_r.csv"), row.names = FALSE)
diagnostic_summary <- fit$diagnostic_summary()
write.csv(diagnostic_summary, file.path(output_dir, "sampler_diagnostics_r.csv"), row.names = FALSE)

manifest <- list(
  schema_version = "longitudinal_r_krt_replication_v1",
  status = "success",
  panel_id = frame$panel_id[[1]],
  election_id = frame$election_id[[1]],
  scenario_id = frame$scenario_id[[1]],
  x_columns = x_columns,
  n_columns = n_columns,
  y_columns = y_columns,
  x_column = x_column,
  n1_column = n1_column,
  n2_column = n2_column,
  y_column = y_column,
  n_communes = nrow(frame),
  model = "exact_reimplementation_of_pyei_ei_beta_binom_model",
  r_version = R.version.string,
  cmdstanr_version = as.character(packageVersion("cmdstanr")),
  cmdstan_version = cmdstan_version(),
  seed = seed,
  chains = chains,
  warmup = iter_warmup,
  draws_per_chain = iter_sampling,
  target_accept = adapt_delta,
  max_treedepth = max_treedepth,
  king_lambda = king_lambda,
  parallel_chains = 1L,
  started_at_utc = started_at,
  finished_at_utc = finished_at,
  elapsed_seconds = unname(elapsed_seconds),
  input_csv = input_csv,
  input_sha256 = digest::digest(file = input_csv, algo = "sha256", serialize = FALSE),
  runner_script = runner_script,
  runner_script_sha256 = if (!is.na(runner_script)) {
    digest::digest(file = runner_script, algo = "sha256", serialize = FALSE)
  } else {
    NA_character_
  },
  stan_file = stan_file,
  stan_sha256 = digest::digest(file = stan_file, algo = "sha256", serialize = FALSE),
  chain_csv = fit$output_files()
)
write_json(
  manifest,
  file.path(output_dir, "manifest_r.json"),
  auto_unbox = TRUE,
  pretty = TRUE,
  digits = NA
)

cat(toJSON(manifest, auto_unbox = TRUE, pretty = TRUE, digits = NA), "\n")
