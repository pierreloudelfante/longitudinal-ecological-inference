suppressPackageStartupMessages({
  library(jsonlite)
})

args <- commandArgs(trailingOnly = TRUE)
root <- if (length(args) >= 1L) args[[1]] else getwd()
root <- normalizePath(root, mustWork = TRUE, winslash = "/")
output_dir <- if (length(args) >= 2L) {
  args[[2]]
} else {
  file.path(root, "outputs", "longitudinal_2000_v1", "r_replication", "density_cross_validation_r")
}
scenario_ids <- if (length(args) >= 3L) {
  strsplit(args[[3]], ",", fixed = TRUE)[[1]]
} else {
  c("H0A", "H1", "H0B", "H0C", "H2", "H3", "H4", "H5", "H6", "H7")
}

output_dir <- normalizePath(output_dir, mustWork = FALSE, winslash = "/")
dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

years <- c(1962L, 1986L, 2022L)
election_ids <- setNames(paste0("leg_", years, "_r1"), years)
run_root <- file.path(root, "outputs", "longitudinal_2000_v1", "r_replication", "king_ei_runs")
grid_axis_joint <- seq(0, 1, length.out = 121L)
grid_axis_marginal <- seq(0, 1, length.out = 401L)
grid_axis_joint_all_years <- seq(0, 1, length.out = 61L)
grid_axis_marginal_all_years <- seq(0, 1, length.out = 201L)
year_colors <- c(`1962` = "#2F5DA8", `1986` = "#C99700", `2022` = "#C03A7A")
year_lty <- c(`1962` = 1L, `1986` = 2L, `2022` = 3L)

strip_utf8_bom <- function(value) {
  bytes <- charToRaw(value)
  if (length(bytes) >= 3L && identical(as.integer(bytes[1:3]), c(239L, 187L, 191L))) {
    return(rawToChar(bytes[-(1:3)]))
  }
  value
}

read_csv_portable <- function(path) {
  frame <- read.csv(path, stringsAsFactors = FALSE, check.names = FALSE)
  names(frame) <- vapply(names(frame), strip_utf8_bom, character(1L), USE.NAMES = FALSE)
  frame
}

effective_sample_size <- function(weights) {
  total <- sum(weights)
  squared <- sum(weights^2)
  if (!is.finite(total) || !is.finite(squared) || total <= 0 || squared <= 0) {
    stop("weights must have positive finite totals")
  }
  total^2 / squared
}

period_balanced_weights <- function(frame, weight_column = NULL) {
  balanced <- numeric(nrow(frame))
  for (year in years) {
    selected <- frame$year == year
    raw <- if (is.null(weight_column)) rep(1, sum(selected)) else frame[[weight_column]][selected]
    if (sum(raw) <= 0) stop("zero period weight denominator for ", year)
    balanced[selected] <- raw / sum(raw)
  }
  balanced
}

regularized_covariance <- function(values, weights) {
  normalized <- weights / sum(weights)
  center <- colSums(values * normalized)
  centered <- sweep(values, 2L, center, "-")
  covariance <- crossprod(centered * sqrt(normalized))
  covariance <- (covariance + t(covariance)) / 2
  decomposition <- eigen(covariance, symmetric = TRUE)
  ceiling <- max(max(decomposition$values), 1e-8)
  eigenvalues <- pmax(decomposition$values, max(ceiling * 1e-6, 1e-10))
  decomposition$vectors %*% diag(eigenvalues, nrow = 2L) %*% t(decomposition$vectors)
}

common_bandwidth_matrix <- function(frame, weight_column = NULL) {
  values <- as.matrix(frame[, c("b1_mean", "b2_mean")])
  pooled_weights <- period_balanced_weights(frame, weight_column)
  covariance <- regularized_covariance(values, pooled_weights)
  period_effective_n <- vapply(years, function(year) {
    selected <- frame$year == year
    weights <- if (is.null(weight_column)) rep(1, sum(selected)) else frame[[weight_column]][selected]
    effective_sample_size(weights)
  }, numeric(1L))
  reference_n <- median(period_effective_n)
  scott_factor <- reference_n^(-1 / 6)
  list(matrix = covariance * scott_factor^2, reference_n = reference_n)
}

common_bandwidth_1d <- function(frame, value_column, weight_column) {
  values <- frame[[value_column]]
  pooled_weights <- period_balanced_weights(frame, weight_column)
  center <- sum(values * pooled_weights) / sum(pooled_weights)
  variance <- sum(pooled_weights * (values - center)^2) / sum(pooled_weights)
  variance <- max(variance, 1e-10)
  period_effective_n <- vapply(years, function(year) {
    effective_sample_size(frame[[weight_column]][frame$year == year])
  }, numeric(1L))
  reference_n <- median(period_effective_n)
  scott_factor <- reference_n^(-1 / 5)
  list(sd = sqrt(variance) * scott_factor, reference_n = reference_n)
}

fixed_kde_2d <- function(values, axis, bandwidth_matrix, weights = NULL, chunk_size = 256L) {
  samples <- as.matrix(values)
  if (is.null(weights)) weights <- rep(1, nrow(samples))
  if (nrow(samples) == 0L || any(!is.finite(samples)) || any(!is.finite(weights)) ||
      any(weights < 0) || sum(weights) <= 0) {
    stop("invalid samples or weights for the two-dimensional KDE")
  }
  inverse <- solve(bandwidth_matrix)
  determinant <- det(bandwidth_matrix)
  if (!is.finite(determinant) || determinant <= 0) stop("bandwidth matrix is not positive definite")
  queries <- as.matrix(expand.grid(b1 = axis, b2 = axis))
  sample_quadratic <- rowSums((samples %*% inverse) * samples)
  result <- numeric(nrow(queries))
  normalizer <- 2 * pi * sqrt(determinant) * sum(weights)
  starts <- seq.int(1L, nrow(queries), by = chunk_size)
  for (start in starts) {
    stop_index <- min(start + chunk_size - 1L, nrow(queries))
    index <- start:stop_index
    query <- queries[index, , drop = FALSE]
    query_times_inverse <- query %*% inverse
    query_quadratic <- rowSums(query_times_inverse * query)
    distance_squared <- outer(query_quadratic, sample_quadratic, "+") -
      2 * (query_times_inverse %*% t(samples))
    distance_squared <- pmax(distance_squared, 0)
    result[index] <- as.vector(exp(-0.5 * distance_squared) %*% weights) / normalizer
  }
  matrix(result, nrow = length(axis), ncol = length(axis), byrow = FALSE)
}

fixed_kde_1d <- function(values, axis, bandwidth_sd, weights) {
  if (!is.finite(bandwidth_sd) || bandwidth_sd <= 0 || any(!is.finite(values)) ||
      any(!is.finite(weights)) || any(weights < 0) || sum(weights) <= 0) {
    stop("invalid samples, weights, or bandwidth for the one-dimensional KDE")
  }
  standardized <- outer(axis, values, "-") / bandwidth_sd
  kernels <- exp(-0.5 * standardized^2) / sqrt(2 * pi)
  as.vector(kernels %*% weights) / (bandwidth_sd * sum(weights))
}

hdr_levels <- function(density, masses = c(0.50, 0.80, 0.95)) {
  ordered <- sort(as.vector(density), decreasing = TRUE)
  cumulative <- cumsum(ordered) / sum(ordered)
  vapply(masses, function(mass) ordered[which(cumulative >= mass)[1]], numeric(1L))
}

load_scenario_data <- function(scenario_id) {
  frames <- list()
  missing <- character()
  for (year in years) {
    election_id <- election_ids[[as.character(year)]]
    run_dir <- file.path(run_root, paste0(election_id, "__", scenario_id))
    commune_path <- file.path(run_dir, "commune_latent_summaries_r.csv")
    manifest_path <- file.path(run_dir, "manifest_r.json")
    if (!file.exists(commune_path) || !file.exists(manifest_path)) {
      missing <- c(missing, election_id)
      next
    }
    manifest <- fromJSON(manifest_path, simplifyVector = TRUE)
    if (!identical(as.character(manifest$status), "success")) {
      missing <- c(missing, election_id)
      next
    }
    commune <- read_csv_portable(commune_path)
    b1 <- commune[commune$parameter == "b_1", c("unit_id", "sample_rank", "mean")]
    b2 <- commune[commune$parameter == "b_2", c("unit_id", "sample_rank", "mean")]
    names(b1)[names(b1) == "mean"] <- "b1_mean"
    names(b2)[names(b2) == "mean"] <- "b2_mean"
    latent <- merge(b1, b2, by = c("unit_id", "sample_rank"), all = FALSE, sort = FALSE)
    input_path <- as.character(manifest$input_csv)
    if (!file.exists(input_path)) stop("missing model-ready input: ", input_path)
    source <- read_csv_portable(input_path)
    weights <- source[, c("unit_id", "N_g", "N__target_group", "N__complement_group")]
    frame <- merge(latent, weights, by = "unit_id", all = FALSE, sort = FALSE)
    frame$scenario_id <- scenario_id
    frame$election_id <- election_id
    frame$year <- year
    frame$b1_weight <- frame$N__target_group
    frame$b2_weight <- frame$N__complement_group
    frame$N_total <- frame$N_g
    frame <- frame[
      is.finite(frame$b1_mean) & is.finite(frame$b2_mean) &
        frame$b1_mean >= 0 & frame$b1_mean <= 1 &
        frame$b2_mean >= 0 & frame$b2_mean <= 1 & frame$N_total > 0,
    ]
    if (nrow(frame) < 100L) stop("too few finite R commune estimates for ", election_id, "/", scenario_id)
    frames[[as.character(year)]] <- frame
  }
  if (length(missing)) return(list(data = NULL, missing = missing))
  list(data = do.call(rbind, frames), missing = character())
}

load_all_scenario_data <- function(scenario_id) {
  directories <- list.dirs(run_root, recursive = FALSE, full.names = TRUE)
  directories <- directories[endsWith(basename(directories), paste0("__", scenario_id))]
  frames <- list()
  for (run_dir in sort(directories)) {
    commune_path <- file.path(run_dir, "commune_latent_summaries_r.csv")
    manifest_path <- file.path(run_dir, "manifest_r.json")
    if (!file.exists(commune_path) || !file.exists(manifest_path)) next
    manifest <- fromJSON(manifest_path, simplifyVector = TRUE)
    if (!identical(as.character(manifest$status), "success")) next
    commune <- read_csv_portable(commune_path)
    b1 <- commune[commune$parameter == "b_1", c("unit_id", "sample_rank", "mean")]
    b2 <- commune[commune$parameter == "b_2", c("unit_id", "sample_rank", "mean")]
    names(b1)[names(b1) == "mean"] <- "b1_mean"
    names(b2)[names(b2) == "mean"] <- "b2_mean"
    latent <- merge(b1, b2, by = c("unit_id", "sample_rank"), all = FALSE, sort = FALSE)
    input_path <- as.character(manifest$input_csv)
    if (!file.exists(input_path)) stop("missing model-ready input: ", input_path)
    source <- read_csv_portable(input_path)
    weights <- source[, c(
      "unit_id", "N_g", "N__target_group", "N__complement_group",
      "election_id", "election_type", "year", "round"
    )]
    frame <- merge(latent, weights, by = "unit_id", all = FALSE, sort = FALSE)
    frame$scenario_id <- scenario_id
    frame$b1_weight <- frame$N__target_group
    frame$b2_weight <- frame$N__complement_group
    frame$N_total <- frame$N_g
    frame <- frame[
      is.finite(frame$b1_mean) & is.finite(frame$b2_mean) &
        frame$b1_mean >= 0 & frame$b1_mean <= 1 &
        frame$b2_mean >= 0 & frame$b2_mean <= 1 & frame$N_total > 0,
    ]
    if (nrow(frame) < 100L) next
    frames[[as.character(manifest$election_id)]] <- frame
  }
  if (!length(frames)) return(NULL)
  result <- do.call(rbind, frames)
  result[order(result$election_type, result$year, result$round, result$election_id, result$sample_rank), ]
}

period_balanced_weights_by <- function(frame, period_values, period_column, weight_column = NULL) {
  balanced <- numeric(nrow(frame))
  for (period_value in period_values) {
    selected <- frame[[period_column]] == period_value
    raw <- if (is.null(weight_column)) rep(1, sum(selected)) else frame[[weight_column]][selected]
    if (sum(raw) <= 0) stop("zero period weight denominator for ", period_value)
    balanced[selected] <- raw / sum(raw)
  }
  balanced
}

common_bandwidth_matrix_by <- function(frame, period_values, period_column, weight_column = NULL) {
  values <- as.matrix(frame[, c("b1_mean", "b2_mean")])
  pooled_weights <- period_balanced_weights_by(frame, period_values, period_column, weight_column)
  covariance <- regularized_covariance(values, pooled_weights)
  period_effective_n <- vapply(period_values, function(period_value) {
    selected <- frame[[period_column]] == period_value
    weights <- if (is.null(weight_column)) rep(1, sum(selected)) else frame[[weight_column]][selected]
    effective_sample_size(weights)
  }, numeric(1L))
  reference_n <- median(period_effective_n)
  scott_factor <- reference_n^(-1 / 6)
  list(matrix = covariance * scott_factor^2, reference_n = reference_n)
}

common_bandwidth_1d_by <- function(frame, period_values, period_column, value_column, weight_column) {
  values <- frame[[value_column]]
  pooled_weights <- period_balanced_weights_by(frame, period_values, period_column, weight_column)
  center <- sum(values * pooled_weights) / sum(pooled_weights)
  variance <- sum(pooled_weights * (values - center)^2) / sum(pooled_weights)
  variance <- max(variance, 1e-10)
  period_effective_n <- vapply(period_values, function(period_value) {
    effective_sample_size(frame[[weight_column]][frame[[period_column]] == period_value])
  }, numeric(1L))
  reference_n <- median(period_effective_n)
  scott_factor <- reference_n^(-1 / 5)
  list(sd = sqrt(variance) * scott_factor, reference_n = reference_n)
}

joint_grid_frame_period <- function(scenario_id, election_id, year, variant, axis, density) {
  coordinates <- expand.grid(x = axis, y = axis)
  data.frame(
    method = "r_eipack",
    scenario_id = scenario_id,
    election_id = election_id,
    year = year,
    density_type = "joint_2d",
    variant = variant,
    x = coordinates$x,
    y = coordinates$y,
    density = as.vector(density),
    stringsAsFactors = FALSE
  )
}

marginal_grid_frame_period <- function(
  scenario_id, election_id, year, value_column, weight_column, axis, density
) {
  data.frame(
    method = "r_eipack",
    scenario_id = scenario_id,
    election_id = election_id,
    year = year,
    density_type = "marginal_1d",
    variant = paste0("all_years_", value_column, "_", weight_column),
    x = axis,
    y = NA_real_,
    density = density,
    stringsAsFactors = FALSE
  )
}

joint_grid_frame <- function(scenario_id, year, variant, axis, density) {
  coordinates <- expand.grid(x = axis, y = axis)
  data.frame(
    method = "r_eipack",
    scenario_id = scenario_id,
    election_id = election_ids[[as.character(year)]],
    year = year,
    density_type = "joint_2d",
    variant = variant,
    x = coordinates$x,
    y = coordinates$y,
    density = as.vector(density),
    stringsAsFactors = FALSE
  )
}

marginal_grid_frame <- function(scenario_id, year, value_column, weight_column, axis, density) {
  data.frame(
    method = "r_eipack",
    scenario_id = scenario_id,
    election_id = election_ids[[as.character(year)]],
    year = year,
    density_type = "marginal_1d",
    variant = paste0(value_column, "_", weight_column),
    x = axis,
    y = NA_real_,
    density = density,
    stringsAsFactors = FALSE
  )
}

draw_joint_plot <- function(path, device, scenario_id, frame, axis, surfaces, title) {
  if (device == "png") {
    png(path, width = 2250, height = 800, res = 150)
  } else {
    svg(path, width = 15, height = 5.35, pointsize = 11)
  }
  on.exit(dev.off(), add = TRUE)
  old <- par(no.readonly = TRUE)
  on.exit(par(old), add = TRUE)
  par(mfrow = c(1, 3), mar = c(4.2, 4.2, 4.0, 1.0), oma = c(1.0, 1.0, 3.0, 1.0))
  palette <- hcl.colors(72L, palette = "Blues 3", rev = TRUE)
  z_limit <- range(unlist(surfaces), finite = TRUE)
  for (year in years) {
    z <- surfaces[[as.character(year)]]
    image(axis, axis, z, col = palette, zlim = z_limit, xlim = c(0, 1), ylim = c(0, 1),
          xlab = expression(beta[1]), ylab = expression(beta[2]), main = as.character(year), useRaster = TRUE)
    levels <- sort(unique(hdr_levels(z)))
    contour(axis, axis, z, levels = levels, add = TRUE, drawlabels = FALSE,
            col = c("#FFFFFF", "#6B7280", "#111827")[seq_along(levels)], lwd = c(1.0, 1.3, 1.6)[seq_along(levels)])
    points(frame$b1_mean[frame$year == year], frame$b2_mean[frame$year == year],
           pch = 16, cex = 0.16, col = adjustcolor("#111827", alpha.f = 0.22))
    box(col = "#374151")
  }
  mtext(paste0(scenario_id, " - ", title), outer = TRUE, side = 3, line = 1.1, cex = 1.25, font = 2)
  mtext("Panel fixe de 2 000 communes; meme matrice de lissage pour les trois annees", outer = TRUE,
        side = 3, line = -0.4, cex = 0.85, col = "#4B5563")
}

draw_marginal_plot <- function(path, device, scenario_id, axis, marginal_surfaces) {
  if (device == "png") {
    png(path, width = 1800, height = 850, res = 150)
  } else {
    svg(path, width = 12, height = 5.7, pointsize = 11)
  }
  on.exit(dev.off(), add = TRUE)
  old <- par(no.readonly = TRUE)
  on.exit(par(old), add = TRUE)
  par(mfrow = c(1, 2), mar = c(4.2, 4.4, 4.0, 1.0), oma = c(1.0, 1.0, 3.0, 1.0))
  for (value_column in c("b1_mean", "b2_mean")) {
    surfaces <- marginal_surfaces[[value_column]]
    y_limit <- c(0, max(unlist(surfaces), finite = TRUE) * 1.05)
    plot(axis, surfaces[["1962"]], type = "n", xlim = c(0, 1), ylim = y_limit,
         xlab = if (value_column == "b1_mean") expression(beta[1]) else expression(beta[2]),
         ylab = "Densite", main = if (value_column == "b1_mean") "Groupe cible" else "Groupe complementaire")
    grid(col = "#E5E7EB", lty = 1)
    for (year in years) {
      lines(axis, surfaces[[as.character(year)]], col = year_colors[[as.character(year)]],
            lty = year_lty[[as.character(year)]], lwd = 2.3)
    }
    box(col = "#374151")
    legend("topright", legend = as.character(years), col = year_colors, lty = year_lty,
           lwd = 2.3, bty = "n", cex = 0.85)
  }
  mtext(paste0(scenario_id, " - densites marginales R-eiPack"), outer = TRUE, side = 3,
        line = 1.1, cex = 1.25, font = 2)
  mtext("Ponderation par la population du groupe; bande passante commune entre annees", outer = TRUE,
        side = 3, line = -0.4, cex = 0.85, col = "#4B5563")
}

draw_joint_all_periods <- function(
  path, device, scenario_id, election_type, frame, events, axis, surfaces, title
) {
  count <- nrow(events)
  columns <- if (count >= 13L) 5L else 4L
  rows <- ceiling(count / columns)
  if (device == "png") {
    png(path, width = 420 * columns, height = 390 * rows + 180, res = 120)
  } else {
    svg(path, width = 3.5 * columns, height = 3.25 * rows + 1.5, pointsize = 9)
  }
  on.exit(dev.off(), add = TRUE)
  old <- par(no.readonly = TRUE)
  on.exit(par(old), add = TRUE)
  par(mfrow = c(rows, columns), mar = c(3.0, 3.1, 2.5, 0.7), oma = c(1.0, 1.0, 3.2, 1.0))
  palette <- hcl.colors(64L, palette = "Blues 3", rev = TRUE)
  z_limit <- range(unlist(surfaces), finite = TRUE)
  for (row_index in seq_len(count)) {
    election_id <- events$election_id[[row_index]]
    year <- events$year[[row_index]]
    z <- surfaces[[election_id]]
    image(axis, axis, z, col = palette, zlim = z_limit, xlim = c(0, 1), ylim = c(0, 1),
          xlab = expression(beta[1]), ylab = expression(beta[2]), main = as.character(year),
          useRaster = TRUE, cex.axis = 0.75, cex.lab = 0.85)
    levels <- sort(unique(hdr_levels(z)))
    contour(axis, axis, z, levels = levels, add = TRUE, drawlabels = FALSE,
            col = c("#FFFFFF", "#6B7280", "#111827")[seq_along(levels)],
            lwd = c(0.8, 1.0, 1.2)[seq_along(levels)])
    selected <- frame$election_id == election_id
    points(frame$b1_mean[selected], frame$b2_mean[selected], pch = 16, cex = 0.10,
           col = adjustcolor("#111827", alpha.f = 0.17))
    box(col = "#374151")
  }
  if (count < rows * columns) {
    for (unused in seq_len(rows * columns - count)) plot.new()
  }
  type_label <- if (election_type == "legislative") "legislatives" else "presidentielles"
  mtext(paste0(scenario_id, " - ", title, " - toutes les ", type_label), outer = TRUE,
        side = 3, line = 1.2, cex = 1.25, font = 2)
  mtext("Panel fixe de 2 000 communes; meme matrice de lissage dans chaque serie electorale",
        outer = TRUE, side = 3, line = -0.3, cex = 0.85, col = "#4B5563")
}

draw_marginal_all_periods <- function(
  path, device, scenario_id, election_type, events, axis, marginal_surfaces
) {
  if (device == "png") {
    png(path, width = 1900, height = 1050, res = 150)
  } else {
    svg(path, width = 12.7, height = 7.0, pointsize = 10)
  }
  on.exit(dev.off(), add = TRUE)
  old <- par(no.readonly = TRUE)
  on.exit(par(old), add = TRUE)
  par(mfrow = c(1, 2), mar = c(4.3, 5.2, 3.7, 1.1), oma = c(1.0, 1.0, 3.1, 1.0))
  period_positions <- seq_len(nrow(events))
  period_labels <- as.character(events$year)
  palette <- hcl.colors(72L, palette = "Blues 3", rev = TRUE)
  for (value_column in c("b1_mean", "b2_mean")) {
    surfaces <- marginal_surfaces[[value_column]]
    density_matrix <- do.call(cbind, lapply(events$election_id, function(value) surfaces[[value]]))
    image(axis, period_positions, density_matrix, col = palette, axes = FALSE,
          xlab = if (value_column == "b1_mean") expression(beta[1]) else expression(beta[2]),
          ylab = "Annee du scrutin",
          main = if (value_column == "b1_mean") "Groupe cible" else "Groupe complementaire",
          useRaster = TRUE)
    axis(1)
    axis(2, at = period_positions, labels = period_labels, las = 1, cex.axis = 0.78)
    box(col = "#374151")
  }
  type_label <- if (election_type == "legislative") "legislatives" else "presidentielles"
  mtext(paste0(scenario_id, " - densites marginales R-eiPack - toutes les ", type_label),
        outer = TRUE, side = 3, line = 1.1, cex = 1.25, font = 2)
  mtext("Intensite = densite; ponderation par la population du groupe; bande passante commune dans la serie",
        outer = TRUE, side = 3, line = -0.4, cex = 0.82, col = "#4B5563")
}

all_inputs <- list()
all_grids <- list()
all_metadata <- list()
completed <- character()
skipped <- list()
all_years_completed <- character()
all_years_skipped <- list()

for (scenario_id in scenario_ids) {
  full_frame <- load_all_scenario_data(scenario_id)
  if (is.null(full_frame)) {
    all_years_skipped[[scenario_id]] <- "no successful R run available"
  } else {
    scenario_dir <- file.path(output_dir, scenario_id)
    dir.create(scenario_dir, recursive = TRUE, showWarnings = FALSE)
    all_inputs[[scenario_id]] <- full_frame
    for (election_type in sort(unique(full_frame$election_type))) {
      type_frame <- full_frame[full_frame$election_type == election_type, ]
      events <- unique(type_frame[, c("election_id", "year", "round")])
      events <- events[order(events$year, events$round, events$election_id), ]
      period_values <- as.character(events$election_id)
      if (!length(period_values)) next

      for (weight_column in list(NULL, "N_total")) {
        bandwidth <- common_bandwidth_matrix_by(
          type_frame, period_values, "election_id", weight_column
        )
        surfaces <- list()
        variant_base <- if (is.null(weight_column)) "equal_communes" else "N_total_weighted"
        variant <- paste0("all_years_", election_type, "_", variant_base)
        for (row_index in seq_len(nrow(events))) {
          election_id <- as.character(events$election_id[[row_index]])
          year <- as.integer(events$year[[row_index]])
          selected <- type_frame$election_id == election_id
          weights <- if (is.null(weight_column)) NULL else type_frame[[weight_column]][selected]
          density <- fixed_kde_2d(
            type_frame[selected, c("b1_mean", "b2_mean")],
            grid_axis_joint_all_years,
            bandwidth$matrix,
            weights = weights
          )
          surfaces[[election_id]] <- density
          key <- paste(scenario_id, "all_years_joint", election_id, variant_base, sep = "__")
          all_grids[[key]] <- joint_grid_frame_period(
            scenario_id, election_id, year, variant, grid_axis_joint_all_years, density
          )
        }
        type_slug <- if (election_type == "legislative") "legislatives" else "presidentielles"
        file_stem <- paste0(
          "joint_beta_", scenario_id, "_", type_slug, "_all_years_", variant_base, "_R"
        )
        title <- if (is.null(weight_column)) {
          "densite jointe, poids egal entre communes"
        } else {
          "densite jointe ponderee par N total"
        }
        draw_joint_all_periods(
          file.path(scenario_dir, paste0(file_stem, ".png")), "png", scenario_id,
          election_type, type_frame, events, grid_axis_joint_all_years, surfaces, title
        )
        draw_joint_all_periods(
          file.path(scenario_dir, paste0(file_stem, ".svg")), "svg", scenario_id,
          election_type, type_frame, events, grid_axis_joint_all_years, surfaces, title
        )
        all_metadata[[paste(scenario_id, "all_years_joint", election_type, variant_base, sep = "__")]] <- data.frame(
          method = "r_eipack",
          scenario_id = scenario_id,
          figure_type = paste0("joint_2d_all_years_", election_type),
          weight_basis = variant,
          bandwidth_h11 = bandwidth$matrix[1, 1],
          bandwidth_h12 = bandwidth$matrix[1, 2],
          bandwidth_h22 = bandwidth$matrix[2, 2],
          bandwidth_sd = NA_real_,
          reference_effective_n = bandwidth$reference_n,
          n_communes_1962 = NA_integer_,
          n_communes_1986 = NA_integer_,
          n_communes_2022 = NA_integer_,
          grid_mass_1962 = NA_real_,
          grid_mass_1986 = NA_real_,
          grid_mass_2022 = NA_real_,
          stringsAsFactors = FALSE
        )
      }

      marginal_surfaces_all <- list()
      for (specification in list(c("b1_mean", "b1_weight"), c("b2_mean", "b2_weight"))) {
        value_column <- specification[[1]]
        weight_column <- specification[[2]]
        bandwidth <- common_bandwidth_1d_by(
          type_frame, period_values, "election_id", value_column, weight_column
        )
        surfaces <- list()
        for (row_index in seq_len(nrow(events))) {
          election_id <- as.character(events$election_id[[row_index]])
          year <- as.integer(events$year[[row_index]])
          selected <- type_frame$election_id == election_id
          density <- fixed_kde_1d(
            type_frame[[value_column]][selected],
            grid_axis_marginal_all_years,
            bandwidth$sd,
            type_frame[[weight_column]][selected]
          )
          surfaces[[election_id]] <- density
          key <- paste(scenario_id, "all_years_marginal", election_id, value_column, sep = "__")
          all_grids[[key]] <- marginal_grid_frame_period(
            scenario_id, election_id, year, value_column, weight_column,
            grid_axis_marginal_all_years, density
          )
        }
        marginal_surfaces_all[[value_column]] <- surfaces
        all_metadata[[paste(scenario_id, "all_years_marginal", election_type, value_column, sep = "__")]] <- data.frame(
          method = "r_eipack",
          scenario_id = scenario_id,
          figure_type = paste0("marginal_1d_all_years_", election_type, "_", value_column),
          weight_basis = paste0("all_years_", weight_column),
          bandwidth_h11 = NA_real_,
          bandwidth_h12 = NA_real_,
          bandwidth_h22 = NA_real_,
          bandwidth_sd = bandwidth$sd,
          reference_effective_n = bandwidth$reference_n,
          n_communes_1962 = NA_integer_,
          n_communes_1986 = NA_integer_,
          n_communes_2022 = NA_integer_,
          grid_mass_1962 = NA_real_,
          grid_mass_1986 = NA_real_,
          grid_mass_2022 = NA_real_,
          stringsAsFactors = FALSE
        )
      }
      type_slug <- if (election_type == "legislative") "legislatives" else "presidentielles"
      marginal_stem <- paste0(
        "marginal_beta_", scenario_id, "_", type_slug, "_all_years_group_weighted_R"
      )
      draw_marginal_all_periods(
        file.path(scenario_dir, paste0(marginal_stem, ".png")), "png", scenario_id,
        election_type, events, grid_axis_marginal_all_years, marginal_surfaces_all
      )
      draw_marginal_all_periods(
        file.path(scenario_dir, paste0(marginal_stem, ".svg")), "svg", scenario_id,
        election_type, events, grid_axis_marginal_all_years, marginal_surfaces_all
      )
    }
    all_years_completed <- c(all_years_completed, scenario_id)
  }

  loaded <- load_scenario_data(scenario_id)
  if (is.null(loaded$data)) {
    skipped[[scenario_id]] <- loaded$missing
    next
  }
  frame <- loaded$data
  scenario_dir <- file.path(output_dir, scenario_id)
  dir.create(scenario_dir, recursive = TRUE, showWarnings = FALSE)

  for (weight_column in list(NULL, "N_total")) {
    bandwidth <- common_bandwidth_matrix(frame, weight_column)
    surfaces <- list()
    variant <- if (is.null(weight_column)) "equal_communes" else "N_total_weighted"
    period_mass <- numeric(length(years))
    names(period_mass) <- years
    for (year in years) {
      selected <- frame$year == year
      weights <- if (is.null(weight_column)) NULL else frame[[weight_column]][selected]
      density <- fixed_kde_2d(
        frame[selected, c("b1_mean", "b2_mean")],
        grid_axis_joint,
        bandwidth$matrix,
        weights = weights
      )
      surfaces[[as.character(year)]] <- density
      step <- grid_axis_joint[[2]] - grid_axis_joint[[1]]
      period_mass[[as.character(year)]] <- sum(density) * step^2
      key <- paste(scenario_id, "joint", variant, year, sep = "__")
      all_grids[[key]] <- joint_grid_frame(scenario_id, year, variant, grid_axis_joint, density)
    }
    file_stem <- paste0("joint_beta_", scenario_id, "_common_bandwidth_", variant, "_R")
    title <- if (is.null(weight_column)) "densite jointe, poids egal entre communes" else "densite jointe ponderee par N total"
    draw_joint_plot(file.path(scenario_dir, paste0(file_stem, ".png")), "png", scenario_id, frame, grid_axis_joint, surfaces, title)
    draw_joint_plot(file.path(scenario_dir, paste0(file_stem, ".svg")), "svg", scenario_id, frame, grid_axis_joint, surfaces, title)
    all_metadata[[paste(scenario_id, "joint", variant, sep = "__")]] <- data.frame(
      method = "r_eipack",
      scenario_id = scenario_id,
      figure_type = "joint_2d",
      weight_basis = variant,
      bandwidth_h11 = bandwidth$matrix[1, 1],
      bandwidth_h12 = bandwidth$matrix[1, 2],
      bandwidth_h22 = bandwidth$matrix[2, 2],
      bandwidth_sd = NA_real_,
      reference_effective_n = bandwidth$reference_n,
      n_communes_1962 = sum(frame$year == 1962),
      n_communes_1986 = sum(frame$year == 1986),
      n_communes_2022 = sum(frame$year == 2022),
      grid_mass_1962 = period_mass[["1962"]],
      grid_mass_1986 = period_mass[["1986"]],
      grid_mass_2022 = period_mass[["2022"]],
      stringsAsFactors = FALSE
    )
  }

  marginal_surfaces <- list()
  for (specification in list(c("b1_mean", "b1_weight"), c("b2_mean", "b2_weight"))) {
    value_column <- specification[[1]]
    weight_column <- specification[[2]]
    bandwidth <- common_bandwidth_1d(frame, value_column, weight_column)
    surfaces <- list()
    period_mass <- numeric(length(years))
    names(period_mass) <- years
    for (year in years) {
      selected <- frame$year == year
      density <- fixed_kde_1d(
        frame[[value_column]][selected],
        grid_axis_marginal,
        bandwidth$sd,
        frame[[weight_column]][selected]
      )
      surfaces[[as.character(year)]] <- density
      step <- grid_axis_marginal[[2]] - grid_axis_marginal[[1]]
      period_mass[[as.character(year)]] <- sum(density) * step
      key <- paste(scenario_id, "marginal", value_column, year, sep = "__")
      all_grids[[key]] <- marginal_grid_frame(
        scenario_id, year, value_column, weight_column, grid_axis_marginal, density
      )
    }
    marginal_surfaces[[value_column]] <- surfaces
    all_metadata[[paste(scenario_id, "marginal", value_column, sep = "__")]] <- data.frame(
      method = "r_eipack",
      scenario_id = scenario_id,
      figure_type = paste0("marginal_1d_", value_column),
      weight_basis = weight_column,
      bandwidth_h11 = NA_real_,
      bandwidth_h12 = NA_real_,
      bandwidth_h22 = NA_real_,
      bandwidth_sd = bandwidth$sd,
      reference_effective_n = bandwidth$reference_n,
      n_communes_1962 = sum(frame$year == 1962),
      n_communes_1986 = sum(frame$year == 1986),
      n_communes_2022 = sum(frame$year == 2022),
      grid_mass_1962 = period_mass[["1962"]],
      grid_mass_1986 = period_mass[["1986"]],
      grid_mass_2022 = period_mass[["2022"]],
      stringsAsFactors = FALSE
    )
  }
  marginal_stem <- paste0("marginal_beta_", scenario_id, "_group_population_weighted_R")
  draw_marginal_plot(file.path(scenario_dir, paste0(marginal_stem, ".png")), "png", scenario_id, grid_axis_marginal, marginal_surfaces)
  draw_marginal_plot(file.path(scenario_dir, paste0(marginal_stem, ".svg")), "svg", scenario_id, grid_axis_marginal, marginal_surfaces)
  completed <- c(completed, scenario_id)
}

input_frame <- if (length(all_inputs)) do.call(rbind, all_inputs) else data.frame()
grid_frame <- if (length(all_grids)) do.call(rbind, all_grids) else data.frame()
metadata_frame <- if (length(all_metadata)) do.call(rbind, all_metadata) else data.frame()
write.csv(input_frame, file.path(output_dir, "density_inputs_r.csv"), row.names = FALSE)
write.csv(grid_frame, file.path(output_dir, "density_grid_r.csv"), row.names = FALSE)
write.csv(metadata_frame, file.path(output_dir, "density_bandwidths_r.csv"), row.names = FALSE)

manifest <- list(
  schema_version = "longitudinal_r_density_cross_validation_v1",
  status = if (setequal(all_years_completed, scenario_ids)) "complete" else "partial",
  generated_at_utc = format(Sys.time(), tz = "UTC", usetz = TRUE),
  model = "King_1997_truncated_bivariate_normal_EI_R_ei_depending_on_eiPack",
  mathematical_identity_with_python_krt = FALSE,
  professor_reference_years = years,
  scenarios_requested = scenario_ids,
  scenarios_completed = all_years_completed,
  scenarios_completed_professor_three_years = completed,
  scenarios_skipped_all_years = all_years_skipped,
  scenarios_skipped_missing_anchor_runs = skipped,
  professor_joint_grid_size = length(grid_axis_joint),
  professor_marginal_grid_size = length(grid_axis_marginal),
  all_years_joint_grid_size = length(grid_axis_joint_all_years),
  all_years_marginal_grid_size = length(grid_axis_marginal_all_years),
  shared_bandwidth_within_election_series = TRUE,
  input_rows = nrow(input_frame),
  density_grid_rows = nrow(grid_frame),
  bandwidth_rows = nrow(metadata_frame),
  output_dir = output_dir
)
write_json(manifest, file.path(output_dir, "density_cross_validation_r_manifest.json"),
           auto_unbox = TRUE, pretty = TRUE, digits = NA)
cat(toJSON(manifest, auto_unbox = TRUE, pretty = TRUE, digits = NA), "\n")
