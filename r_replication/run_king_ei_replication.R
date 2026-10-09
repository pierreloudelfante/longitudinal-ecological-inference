#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(ei)
  library(jsonlite)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 2L) {
  stop("usage: run_king_ei_replication.R MODEL_READY_CSV OUTPUT_DIR [SEED]")
}

input_csv <- normalizePath(args[[1]], mustWork = TRUE, winslash = "/")
output_dir <- normalizePath(args[[2]], mustWork = FALSE, winslash = "/")
seed <- if (length(args) >= 3L) as.integer(args[[3]]) else 20260802L
dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

frame <- read.csv(
  input_csv,
  stringsAsFactors = FALSE,
  check.names = FALSE,
  colClasses = c(unit_id = "character")
)
# Some model-ready CSV files are UTF-8 with a BOM.  This Windows R runtime
# cannot translate that first name under its current locale, so strip the
# three UTF-8 BOM bytes without any character-set conversion.
strip_utf8_bom <- function(value) {
  bytes <- charToRaw(value)
  if (length(bytes) >= 3L && identical(as.integer(bytes[1:3]), c(239L, 187L, 191L))) {
    return(rawToChar(bytes[-(1:3)]))
  }
  value
}
names(frame) <- vapply(names(frame), strip_utf8_bom, character(1L), USE.NAMES = FALSE)

# H4 is the only 2x2 specification whose two social groups have substantive
# names in the model-ready files.  Normalize those names locally so the same
# King EI implementation can validate and estimate every 2x2 specification.
# Keep the source names for the audit manifest below.
social_share_column <- "X__target_group"
social_target_column <- "N__target_group"
social_complement_column <- "N__complement_group"
scenario_values <- unique(frame$scenario_id)
if (
  length(scenario_values) == 1L &&
  identical(scenario_values[[1]], "H4") &&
  !all(c("X__target_group", "N__target_group", "N__complement_group") %in% names(frame))
) {
  h4_required <- c("X__agri_indp", "N__agri_indp", "N__salaries")
  h4_missing <- setdiff(h4_required, names(frame))
  if (length(h4_missing)) {
    stop("missing required H4 columns: ", paste(h4_missing, collapse = ", "))
  }
  frame$X__target_group <- frame$X__agri_indp
  frame$N__target_group <- frame$N__agri_indp
  frame$N__complement_group <- frame$N__salaries
  social_share_column <- "X__agri_indp"
  social_target_column <- "N__agri_indp"
  social_complement_column <- "N__salaries"
}
required <- c(
  "unit_id", "panel_id", "election_id", "scenario_id", "sample_rank", "N_g",
  "X__target_group", "N__target_group", "N__complement_group"
)
missing_required <- setdiff(required, names(frame))
if (length(missing_required)) {
  stop("missing required columns: ", paste(missing_required, collapse = ", "))
}
y_columns <- grep("^Y__", names(frame), value = TRUE)
if (length(y_columns) != 2L) stop("expected exactly two Y__ columns")
y_column <- y_columns[[1]]

if (nrow(frame) != 2000L) stop("R King EI production requires exactly 2,000 communes")
if (anyDuplicated(frame$unit_id)) stop("duplicate unit_id in R King EI input")
if (length(unique(frame$panel_id)) != 1L) stop("multiple panel_id values")
if (length(unique(frame$election_id)) != 1L) stop("multiple election_id values")
if (length(unique(frame$scenario_id)) != 1L) stop("multiple scenario_id values")
integer_columns <- c("N_g", "N__target_group", "N__complement_group", y_columns)
for (column in integer_columns) {
  values <- frame[[column]]
  if (any(!is.finite(values)) || any(values < 0) || any(abs(values - round(values)) > 1e-8)) {
    stop("invalid non-negative integer counts in ", column)
  }
}
if (any(frame$N_g <= 0)) stop("N_g must be strictly positive")
if (any(frame$N__target_group + frame$N__complement_group != frame$N_g)) {
  stop("social counts do not close to N_g")
}
if (any(frame[[y_columns[[1]]]] + frame[[y_columns[[2]]]] != frame$N_g)) {
  stop("vote counts do not close to N_g")
}
if (any(abs(frame$X__target_group - frame$N__target_group / frame$N_g) > 1e-12)) {
  stop("X__target_group is inconsistent with integer social counts")
}

work <- data.frame(
  unit_id = frame$unit_id,
  t = as.numeric(frame[[y_column]]) / as.numeric(frame$N_g),
  x = as.numeric(frame$X__target_group),
  n = as.integer(frame$N_g),
  stringsAsFactors = FALSE
)

set.seed(seed)
started_at <- format(Sys.time(), tz = "UTC", usetz = TRUE)
started_clock <- proc.time()[["elapsed"]]
fit <- ei::ei(
  t ~ x,
  total = "n",
  id = "unit_id",
  data = work,
  erho = 0.5,
  esigma = 0.5,
  ebeta = 0.5,
  simulate = TRUE
)
elapsed_seconds <- proc.time()[["elapsed"]] - started_clock
finished_at <- format(Sys.time(), tz = "UTC", usetz = TRUE)

b1_draws <- as.matrix(fit$betabs)
b2_draws <- as.matrix(fit$betaws)
if (nrow(b1_draws) != nrow(frame) || nrow(b2_draws) != nrow(frame)) {
  stop("unexpected precinct dimension in ei posterior draws")
}
if (ncol(b1_draws) != 99L || ncol(b2_draws) != 99L) {
  stop("unexpected native ei importance draw count")
}

summarize_draws <- function(draws, parameter) {
  summarize_one <- function(values) {
    if (all(is.na(values))) return(c(NA_real_, NA_real_, NA_real_, NA_real_, NA_real_))
    c(
      mean(values, na.rm = TRUE),
      sd(values, na.rm = TRUE),
      unname(quantile(values, 0.025, na.rm = TRUE)),
      unname(quantile(values, 0.5, na.rm = TRUE)),
      unname(quantile(values, 0.975, na.rm = TRUE))
    )
  }
  summaries <- t(apply(draws, 1L, summarize_one))
  data.frame(
    unit_id = frame$unit_id,
    sample_rank = frame$sample_rank,
    parameter = parameter,
    mean = summaries[, 1L],
    sd = summaries[, 2L],
    q025 = summaries[, 3L],
    q50 = summaries[, 4L],
    q975 = summaries[, 5L],
    stringsAsFactors = FALSE
  )
}

commune <- rbind(summarize_draws(b1_draws, "b_1"), summarize_draws(b2_draws, "b_2"))
commune$panel_id <- frame$panel_id[[1]]
commune$election_id <- frame$election_id[[1]]
commune$scenario_id <- frame$scenario_id[[1]]
commune$model_key <- "king_ei_1997_r"
commune <- commune[, c(
  "panel_id", "election_id", "scenario_id", "model_key", "unit_id",
  "sample_rank", "parameter", "mean", "sd", "q025", "q50", "q975"
)]
write.csv(commune, file.path(output_dir, "commune_latent_summaries_r.csv"), row.names = FALSE)

weighted_draws <- function(draws, weights) {
  weighted <- sweep(draws, 1L, weights, `*`)
  weighted[is.na(weighted) & weights == 0] <- 0
  if (anyNA(weighted)) stop("positive-weight ei posterior draw is missing")
  colSums(weighted) / sum(weights)
}
n1 <- as.numeric(frame$N__target_group)
n2 <- as.numeric(frame$N__complement_group)
beta1_aggregate <- weighted_draws(b1_draws, n1)
beta2_aggregate <- weighted_draws(b2_draws, n2)
aggregate_draws <- cbind(
  beta1_aggregate = beta1_aggregate,
  beta2_aggregate = beta2_aggregate,
  contrast_aggregate = beta1_aggregate - beta2_aggregate
)
aggregate <- do.call(rbind, lapply(colnames(aggregate_draws), function(variable) {
  values <- aggregate_draws[, variable]
  data.frame(
    panel_id = frame$panel_id[[1]],
    election_id = frame$election_id[[1]],
    scenario_id = frame$scenario_id[[1]],
    model_key = "king_ei_1997_r",
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
manifest <- list(
  schema_version = "longitudinal_r_king_ei_replication_v1",
  status = "success",
  panel_id = frame$panel_id[[1]],
  election_id = frame$election_id[[1]],
  scenario_id = frame$scenario_id[[1]],
  y_column = y_column,
  social_share_column = social_share_column,
  social_target_column = social_target_column,
  social_complement_column = social_complement_column,
  n_communes = nrow(frame),
  model = "King_1997_truncated_bivariate_normal_EI",
  comparison_target = "PyEI_king99_beta_binomial",
  mathematical_identity_with_python_model = FALSE,
  raw_fit_retained = FALSE,
  raw_fit_retention_reason = "parsimonious release: validated commune and aggregate summaries are retained",
  r_version = R.version.string,
  ei_version = as.character(packageVersion("ei")),
  eiPack_version = as.character(packageVersion("eiPack")),
  seed = seed,
  native_importance_draws = ncol(b1_draws),
  erho = 0.5,
  esigma = 0.5,
  ebeta = 0.5,
  resampling_batches = fit$resamp,
  hessian_condition_number = kappa(fit$hessianC),
  started_at_utc = started_at,
  finished_at_utc = finished_at,
  elapsed_seconds = unname(elapsed_seconds),
  input_csv = input_csv,
  input_sha256 = digest::digest(file = input_csv, algo = "sha256", serialize = FALSE)
)
write_json(
  manifest,
  file.path(output_dir, "manifest_r.json"),
  auto_unbox = TRUE,
  pretty = TRUE,
  digits = NA
)
cat(toJSON(manifest, auto_unbox = TRUE, pretty = TRUE, digits = NA), "\n")
