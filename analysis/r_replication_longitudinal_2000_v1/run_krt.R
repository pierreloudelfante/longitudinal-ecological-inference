source(file.path(dirname(normalizePath(sub("^--file=", "", grep("^--file=", commandArgs(), value = TRUE)[[1]]), winslash = "/")), "common.R"))

options <- parse_options()
if (!(options$scenario %in% c("H0A", "H1"))) stop("KRT longitudinal v1 is restricted to H0A and H1.")

engine <- if (requireNamespace("cmdstanr", quietly = TRUE) && nzchar(cmdstanr::cmdstan_version(error_on_NA = FALSE))) {
  "cmdstanr"
} else if (requireNamespace("rstan", quietly = TRUE)) {
  "rstan"
} else {
  "unavailable"
}

preflight <- list(
  checked_at_utc = utc_now(),
  status = if (engine == "unavailable") "blocked" else "pass",
  engine = engine,
  required_model = "exact PyEI king99 beta-binomial hierarchy",
  panel_id = PANEL_ID,
  sample_size = PRIMARY_N,
  chains = 4L,
  warmup = 1000L,
  draws = 1000L,
  target_accept = 0.99,
  max_treedepth = 14L,
  king_lambda = 0.5,
  random_seed = RANDOM_SEED,
  blocker = if (engine == "unavailable") {
    "Neither cmdstanr+CmdStan nor rstan is installed. R ei is intentionally not substituted because it is not the PyEI king99 KRT model."
  } else ""
)
write_json_file(preflight, file.path(RESULTS_DIR, "krt_preflight.json"))
if (engine == "unavailable") {
  message(preflight$blocker)
  quit(status = 3L)
}

panel <- read_panel_primary()
dat <- read_model_ready(options$election, options$scenario, panel)
x_name <- grep("^X__", names(dat), value = TRUE)[[1]]
y_name <- grep("^Y__", names(dat), value = TRUE)[[1]]
n_names <- grep("^N__", names(dat), value = TRUE)
x <- as.numeric(dat[[x_name]])
y <- as.integer(dat[[y_name]])
n <- as.integer(dat$N_g)
stan_data <- list(I = nrow(dat), N_g = n, Y = y, X = x, king_lambda = 0.5)
pair_key <- paste(options$election, options$scenario, sep = "__")
output_dir <- file.path(RESULTS_DIR, "krt", pair_key)
dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

started <- proc.time()[["elapsed"]]
if (engine == "cmdstanr") {
  model <- cmdstanr::cmdstan_model(file.path(R_REPLICATION_DIR, "krt_king99.stan"))
  fit <- model$sample(
    data = stan_data,
    seed = RANDOM_SEED,
    chains = 4L,
    parallel_chains = min(4L, options$cores),
    iter_warmup = 1000L,
    iter_sampling = 1000L,
    adapt_delta = 0.99,
    max_treedepth = 14L,
    refresh = 100L
  )
  draws <- fit$draws(variables = c("b_1", "b_2", "c_1", "d_1", "c_2", "d_2"), format = "matrix")
  diagnostic_summary <- fit$summary(variables = c("c_1", "d_1", "c_2", "d_2", "b_1", "b_2"))
} else {
  model <- rstan::stan_model(file = file.path(R_REPLICATION_DIR, "krt_king99.stan"))
  fit <- rstan::sampling(
    model,
    data = stan_data,
    seed = RANDOM_SEED,
    chains = 4L,
    cores = min(4L, options$cores),
    iter = 2000L,
    warmup = 1000L,
    control = list(adapt_delta = 0.99, max_treedepth = 14L),
    refresh = 100L
  )
  draws <- as.matrix(fit, pars = c("b_1", "b_2", "c_1", "d_1", "c_2", "d_2"))
  diagnostic_summary <- as.data.frame(summary(fit, pars = c("c_1", "d_1", "c_2", "d_2", "b_1", "b_2"))$summary)
  diagnostic_summary$variable <- rownames(diagnostic_summary)
}
elapsed <- proc.time()[["elapsed"]] - started

b1_columns <- grep("^b_1\\[", colnames(draws))
b2_columns <- grep("^b_2\\[", colnames(draws))
if (length(b1_columns) != PRIMARY_N || length(b2_columns) != PRIMARY_N) stop("KRT latent draw dimensions do not equal 2,000 communes.")
b1 <- draws[, b1_columns, drop = FALSE]
b2 <- draws[, b2_columns, drop = FALSE]
summarize_columns <- function(matrix_value) {
  cbind(
    mean = colMeans(matrix_value),
    sd = apply(matrix_value, 2L, sd),
    t(apply(matrix_value, 2L, quantile, probs = c(0.025, 0.5, 0.975), names = FALSE, type = 8))
  )
}
b1_summary <- summarize_columns(b1)
b2_summary <- summarize_columns(b2)
commune <- data.frame(
  unit_id = dat$unit_id,
  panel_id = PANEL_ID,
  election_id = options$election,
  scenario_id = options$scenario,
  b1_mean = b1_summary[, 1],
  b1_sd = b1_summary[, 2],
  b1_q025 = b1_summary[, 3],
  b1_q50 = b1_summary[, 4],
  b1_q975 = b1_summary[, 5],
  b2_mean = b2_summary[, 1],
  b2_sd = b2_summary[, 2],
  b2_q025 = b2_summary[, 3],
  b2_q50 = b2_summary[, 4],
  b2_q975 = b2_summary[, 5],
  stringsAsFactors = FALSE
)

weights_1 <- as.numeric(dat[[n_names[[1]]]])
weights_2 <- as.numeric(dat[[n_names[[2]]]])
b1_aggregate <- as.numeric(b1 %*% weights_1 / sum(weights_1))
b2_aggregate <- as.numeric(b2 %*% weights_2 / sum(weights_2))
contrast <- b1_aggregate - b2_aggregate
summarize_draw <- function(draw, estimand) {
  q <- quantile(draw, c(0.025, 0.5, 0.975), names = FALSE, type = 8)
  data.frame(estimand = estimand, mean = mean(draw), sd = sd(draw), q025 = q[[1]], q50 = q[[2]], q975 = q[[3]])
}
aggregate <- rbind(
  summarize_draw(b1_aggregate, "b_1"),
  summarize_draw(b2_aggregate, "b_2"),
  summarize_draw(contrast, "b_1_minus_b_2")
)
aggregate$panel_id <- PANEL_ID
aggregate$election_id <- options$election
aggregate$scenario_id <- options$scenario
aggregate$engine <- engine

write.csv(commune, file.path(output_dir, "r_krt_commune.csv"), row.names = FALSE, fileEncoding = "UTF-8")
write.csv(aggregate, file.path(output_dir, "r_krt_aggregate.csv"), row.names = FALSE, fileEncoding = "UTF-8")
write.csv(diagnostic_summary, file.path(output_dir, "r_krt_diagnostics.csv"), row.names = FALSE, fileEncoding = "UTF-8")
if (options$save_fit) saveRDS(fit, file.path(output_dir, "fit.rds"), compress = "xz")
write_json_file(
  c(
    preflight,
    list(
      status = "success",
      completed_at_utc = utc_now(),
      election_id = options$election,
      scenario_id = options$scenario,
      input_path = relative_path(attr(dat, "source_path")),
      input_sha256 = sha256_file(attr(dat, "source_path")),
      exact_panel_order_match = TRUE,
      elapsed_seconds = elapsed,
      output_dir = relative_path(output_dir)
    )
  ),
  file.path(output_dir, "manifest.json")
)
message(sprintf("Completed matched R KRT %s with %s in %.1fs", pair_key, engine, elapsed))
