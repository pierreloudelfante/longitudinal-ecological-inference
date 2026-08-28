#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(coda)
  library(jsonlite)
  library(nimble)
  library(posterior)
})

args <- commandArgs(trailingOnly = TRUE)
runner_file_arg <- grep("^--file=", commandArgs(trailingOnly = FALSE), value = TRUE)
runner_script <- if (length(runner_file_arg)) {
  normalizePath(sub("^--file=", "", runner_file_arg[[1]]), mustWork = TRUE, winslash = "/")
} else {
  NA_character_
}
if (length(args) < 2L) {
  stop(
    paste(
      "usage: run_krt_replication_nimble.R MODEL_READY_CSV OUTPUT_DIR",
      "[SEED] [WARMUP] [DRAWS] [CHAINS] [MAX_ROWS]"
    )
  )
}

input_csv <- normalizePath(args[[1]], mustWork = TRUE, winslash = "/")
output_dir <- normalizePath(args[[2]], mustWork = FALSE, winslash = "/")
seed <- if (length(args) >= 3L) as.integer(args[[3]]) else 20260802L
iter_warmup <- if (length(args) >= 4L) as.integer(args[[4]]) else 1000L
iter_sampling <- if (length(args) >= 5L) as.integer(args[[5]]) else 1000L
chains <- if (length(args) >= 6L) as.integer(args[[6]]) else 4L
max_rows <- if (length(args) >= 7L) as.integer(args[[7]]) else 2000L
king_lambda <- 0.5

dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)
frame <- read.csv(
  input_csv,
  stringsAsFactors = FALSE,
  check.names = FALSE,
  fileEncoding = "UTF-8-BOM",
  colClasses = c(unit_id = "character")
)
if (max_rows < nrow(frame)) frame <- frame[seq_len(max_rows), , drop = FALSE]

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
if (length(x_columns) != 2L) stop("expected exactly two X__ columns")
if (length(n_columns) != 2L) stop("expected exactly two N__ columns")
if (length(y_columns) != 2L) stop("expected exactly two Y__ columns")
if (!identical(sub("^X__", "", x_columns), sub("^N__", "", n_columns))) {
  stop("X__ and N__ partitions have different names or ordering")
}
x_column <- x_columns[[1]]
n1_column <- n_columns[[1]]
n2_column <- n_columns[[2]]
y_column <- y_columns[[1]]

if (nrow(frame) != max_rows) stop("unexpected row count after MAX_ROWS selection")
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

P <- nrow(frame)
x <- as.numeric(frame[[x_column]])
N <- as.integer(frame$N_g)
Y <- as.integer(frame[[y_column]])
observed_fraction <- Y / N

king_code <- nimbleCode({
  c_1 ~ dexp(rate = king_lambda)
  d_1 ~ dexp(rate = king_lambda)
  c_2 ~ dexp(rate = king_lambda)
  d_2 ~ dexp(rate = king_lambda)
  for (i in 1:P) {
    b_1[i] ~ dbeta(c_1, d_1)
    b_2[i] ~ dbeta(c_2, d_2)
    theta[i] <- x[i] * b_1[i] + (1 - x[i]) * b_2[i]
    Y[i] ~ dbin(prob = theta[i], size = N[i])
  }
})

make_inits <- function(chain_index = 1L) {
  set.seed(seed + chain_index - 1L)
  baseline <- pmin(0.98, pmax(0.02, observed_fraction))
  list(
    c_1 = exp(rnorm(1L, log(2), 0.15)),
    d_1 = exp(rnorm(1L, log(2), 0.15)),
    c_2 = exp(rnorm(1L, log(2), 0.15)),
    d_2 = exp(rnorm(1L, log(2), 0.15)),
    b_1 = pmin(0.995, pmax(0.005, baseline + rnorm(P, 0, 0.01))),
    b_2 = pmin(0.995, pmax(0.005, baseline + rnorm(P, 0, 0.01)))
  )
}
inits <- lapply(seq_len(chains), make_inits)

Rmodel <- nimbleModel(
  king_code,
  constants = list(P = P, x = x, N = N, king_lambda = king_lambda),
  data = list(Y = Y),
  inits = inits[[1]],
  check = TRUE,
  calculate = TRUE
)
if (!is.finite(Rmodel$calculate())) stop("non-finite initial model log probability")

configuration <- configureMCMC(
  Rmodel,
  nodes = NULL,
  monitors = c("c_1", "d_1", "c_2", "d_2", "b_1", "b_2"),
  enableWAIC = FALSE,
  print = FALSE
)
for (node in c("c_1", "d_1", "c_2", "d_2")) {
  configuration$addSampler(
    target = node,
    type = "slice",
    control = list(adaptive = TRUE)
  )
}
for (i in seq_len(P)) {
  configuration$addSampler(
    target = c(sprintf("b_1[%d]", i), sprintf("b_2[%d]", i)),
    type = "RW_block",
    control = list(
      adaptive = TRUE,
      adaptInterval = 100L,
      scale = 0.1,
      propCov = diag(c(0.05, 0.05)^2)
    )
  )
}

Rmcmc <- buildMCMC(configuration)
compile_started <- proc.time()[["elapsed"]]
Cmodel <- compileNimble(Rmodel, showCompilerOutput = FALSE)
Cmcmc <- compileNimble(Rmcmc, project = Rmodel, showCompilerOutput = FALSE)
compile_seconds <- proc.time()[["elapsed"]] - compile_started

started_at <- format(Sys.time(), tz = "UTC", usetz = TRUE)
sample_started <- proc.time()[["elapsed"]]
samples <- runMCMC(
  Cmcmc,
  niter = iter_warmup + iter_sampling,
  nburnin = iter_warmup,
  thin = 1L,
  nchains = chains,
  inits = inits,
  setSeed = seed + seq_len(chains) - 1L,
  progressBar = TRUE,
  samples = TRUE,
  samplesAsCodaMCMC = FALSE,
  summary = FALSE,
  WAIC = FALSE
)
sample_seconds <- proc.time()[["elapsed"]] - sample_started
finished_at <- format(Sys.time(), tz = "UTC", usetz = TRUE)
if (chains == 1L) samples <- list(samples)
if (length(samples) != chains) stop("unexpected number of returned chains")

expected_columns <- c(
  "c_1", "d_1", "c_2", "d_2",
  paste0("b_1[", seq_len(P), "]"),
  paste0("b_2[", seq_len(P), "]")
)
for (chain in samples) {
  if (nrow(chain) != iter_sampling) stop("unexpected retained draw count")
  if (!all(expected_columns %in% colnames(chain))) stop("missing monitored parameters")
}

combined <- do.call(rbind, samples)
summarize_block <- function(parameter) {
  columns <- paste0(parameter, "[", seq_len(P), "]")
  values <- combined[, columns, drop = FALSE]
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
commune <- rbind(summarize_block("b_1"), summarize_block("b_2"))
commune$panel_id <- frame$panel_id[[1]]
commune$election_id <- frame$election_id[[1]]
commune$scenario_id <- frame$scenario_id[[1]]
commune$model_key <- "krt_beta_binomial_nimble_r_exact"
commune <- commune[, c(
  "panel_id", "election_id", "scenario_id", "model_key", "unit_id",
  "sample_rank", "parameter", "mean", "sd", "q025", "q50", "q975"
)]
write.csv(commune, file.path(output_dir, "commune_latent_summaries_r.csv"), row.names = FALSE)

n1 <- as.numeric(frame[[n1_column]])
n2 <- as.numeric(frame[[n2_column]])
b1_columns <- paste0("b_1[", seq_len(P), "]")
b2_columns <- paste0("b_2[", seq_len(P), "]")
beta1_aggregate <- as.numeric(combined[, b1_columns, drop = FALSE] %*% n1 / sum(n1))
beta2_aggregate <- as.numeric(combined[, b2_columns, drop = FALSE] %*% n2 / sum(n2))
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
    model_key = "krt_beta_binomial_nimble_r_exact",
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

draw_array <- array(
  NA_real_,
  dim = c(iter_sampling, chains, length(expected_columns)),
  dimnames = list(NULL, NULL, expected_columns)
)
for (chain_index in seq_len(chains)) {
  draw_array[, chain_index, ] <- samples[[chain_index]][, expected_columns, drop = FALSE]
}
diagnostics <- posterior::summarise_draws(
  posterior::as_draws_array(draw_array),
  rhat = posterior::rhat,
  ess_bulk = posterior::ess_bulk,
  ess_tail = posterior::ess_tail
)
write.csv(diagnostics, file.path(output_dir, "parameter_diagnostics_r.csv"), row.names = FALSE)

manifest <- list(
  schema_version = "longitudinal_r_krt_replication_nimble_v1",
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
  n_communes = P,
  production_panel = identical(P, 2000L),
  model = "exact_reimplementation_of_pyei_ei_beta_binom_model",
  sampler = "nimble_compiled_slice_hyperparameters_and_adaptive_RW_block_by_commune",
  r_version = R.version.string,
  nimble_version = as.character(packageVersion("nimble")),
  seed = seed,
  chains = chains,
  warmup = iter_warmup,
  draws_per_chain = iter_sampling,
  king_lambda = king_lambda,
  compile_seconds = unname(compile_seconds),
  sample_seconds = unname(sample_seconds),
  started_at_utc = started_at,
  finished_at_utc = finished_at,
  input_csv = input_csv,
  input_sha256 = digest::digest(file = input_csv, algo = "sha256", serialize = FALSE),
  runner_script = runner_script,
  runner_script_sha256 = if (!is.na(runner_script)) {
    digest::digest(file = runner_script, algo = "sha256", serialize = FALSE)
  } else {
    NA_character_
  },
  max_rhat = max(diagnostics$rhat, na.rm = TRUE),
  min_ess_bulk = min(diagnostics$ess_bulk, na.rm = TRUE),
  min_ess_tail = min(diagnostics$ess_tail, na.rm = TRUE)
)
write_json(
  manifest,
  file.path(output_dir, "manifest_r.json"),
  auto_unbox = TRUE,
  pretty = TRUE,
  digits = NA
)
cat(toJSON(manifest, auto_unbox = TRUE, pretty = TRUE, digits = NA), "\n")
