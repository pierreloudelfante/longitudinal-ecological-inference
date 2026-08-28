from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
from scipy.optimize import OptimizeResult, least_squares
from scipy.special import softmax


@dataclass(frozen=True)
class NLSData:
    x: np.ndarray
    t: np.ndarray
    n: np.ndarray
    z: np.ndarray


def design_from_covariates(z: np.ndarray, n_units: int | None = None) -> np.ndarray:
    z = np.asarray(z, dtype=float)
    if z.ndim == 1:
        z = z[:, None]
    if z.ndim != 2:
        raise ValueError("z must be a vector or matrix")
    rows = z.shape[0] if n_units is None else n_units
    if z.shape[0] != rows:
        raise ValueError("z and x must have the same number of units")
    return np.column_stack([np.ones(rows, dtype=float), z])


def unpack_params(params: np.ndarray, n_groups: int, n_outcomes: int, n_regressors: int) -> np.ndarray:
    return np.asarray(params, dtype=float).reshape(n_groups, n_outcomes - 1, n_regressors)


def probabilities(
    params: np.ndarray,
    x: np.ndarray,
    z: np.ndarray,
    n_outcomes: int,
) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(x, dtype=float)
    design = design_from_covariates(z, x.shape[0])
    coefficients = unpack_params(params, x.shape[1], n_outcomes, design.shape[1])
    eta = np.einsum("ip,rcp->irc", design, coefficients)
    eta_full = np.concatenate([eta, np.zeros((x.shape[0], x.shape[1], 1))], axis=2)
    pi = softmax(eta_full, axis=2)
    fitted = np.einsum("ir,irc->ic", x, pi)
    return pi, fitted


def residuals(params: np.ndarray, x: np.ndarray, t: np.ndarray, z: np.ndarray) -> np.ndarray:
    _, fitted = probabilities(params, x, z, t.shape[1])
    return (t[:, :-1] - fitted[:, :-1]).ravel()


def objective_sse(params: np.ndarray, x: np.ndarray, t: np.ndarray, z: np.ndarray) -> float:
    residual = residuals(params, x, t, z)
    return float(residual @ residual)


def _clip_normalize(beta: np.ndarray, eps: float = 1e-5) -> np.ndarray:
    beta = np.clip(beta, eps, None)
    return beta / beta.sum(axis=1, keepdims=True)


def pooled_start(x: np.ndarray, t: np.ndarray, n_regressors: int) -> np.ndarray:
    beta = np.column_stack([np.linalg.lstsq(x, t[:, c], rcond=None)[0] for c in range(t.shape[1])])
    beta = _clip_normalize(beta)
    coefficients = np.zeros((x.shape[1], t.shape[1] - 1, n_regressors), dtype=float)
    coefficients[:, :, 0] = np.log(beta[:, :-1] / beta[:, -1:])
    return coefficients.ravel()


def strata_start(x: np.ndarray, t: np.ndarray, z: np.ndarray, n_strata: int) -> np.ndarray:
    z = np.asarray(z, dtype=float)
    if z.ndim == 1:
        z = z[:, None]
    n_regressors = z.shape[1] + 1
    if z.shape[1] == 0:
        return pooled_start(x, t, n_regressors)
    edges = np.unique(np.quantile(z[:, 0], np.linspace(0, 1, n_strata + 1)))
    if len(edges) <= 2:
        return pooled_start(x, t, n_regressors)
    z_means: list[np.ndarray] = []
    beta_by_stratum: list[np.ndarray] = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (z[:, 0] >= lo) & (z[:, 0] <= hi if hi == edges[-1] else z[:, 0] < hi)
        if int(mask.sum()) <= x.shape[1]:
            continue
        z_means.append(z[mask].mean(axis=0))
        beta = np.column_stack([np.linalg.lstsq(x[mask], t[mask, c], rcond=None)[0] for c in range(t.shape[1])])
        beta_by_stratum.append(_clip_normalize(beta))
    if len(beta_by_stratum) < 2:
        return pooled_start(x, t, n_regressors)
    design = design_from_covariates(np.vstack(z_means))
    beta_stack = np.stack(beta_by_stratum)
    coefficients = np.zeros((x.shape[1], t.shape[1] - 1, n_regressors), dtype=float)
    for r in range(x.shape[1]):
        for c in range(t.shape[1] - 1):
            logits = np.log(beta_stack[:, r, c] / beta_stack[:, r, -1])
            coefficients[r, c, :] = np.linalg.lstsq(design, logits, rcond=None)[0]
    return coefficients.ravel()


def fit_nls(
    data: NLSData,
    *,
    n_starts: int = 20,
    start_scale: float = 0.5,
    n_start_strata: int = 5,
    max_nfev: int = 5000,
    tolerance: float = 1e-9,
    random_seed: int = 20260802,
) -> tuple[OptimizeResult, list[dict[str, object]]]:
    if n_starts < 2:
        raise ValueError("n_starts must be at least two")
    n_regressors = data.z.shape[1] + 1
    n_parameters = data.x.shape[1] * (data.t.shape[1] - 1) * n_regressors
    rng = np.random.default_rng(random_seed)
    starts = [strata_start(data.x, data.t, data.z, n_start_strata), np.zeros(n_parameters)]
    starts.extend(rng.normal(0.0, start_scale, n_parameters) for _ in range(n_starts - 2))
    fits: list[OptimizeResult] = []
    for start in starts:
        fits.append(
            least_squares(
                residuals,
                x0=start,
                args=(data.x, data.t, data.z),
                method="trf",
                loss="linear",
                max_nfev=max_nfev,
                xtol=tolerance,
                ftol=tolerance,
                gtol=tolerance,
            )
        )
    finite = [fit for fit in fits if np.isfinite(fit.cost)]
    if not finite:
        raise RuntimeError("no finite NLS fit")
    best = min(finite, key=lambda fit: float(fit.cost))
    _, best_prediction = probabilities(best.x, data.x, data.z, data.t.shape[1])
    summaries: list[dict[str, object]] = []
    for idx, fit in enumerate(fits):
        _, prediction = probabilities(fit.x, data.x, data.z, data.t.shape[1])
        summaries.append(
            {
                "start_index": idx,
                "start_type": "strata_or_pooled_ols_logit" if idx == 0 else "zero" if idx == 1 else "random",
                "success": bool(fit.success),
                "status": int(fit.status),
                "message": str(fit.message),
                "nfev": int(fit.nfev),
                "cost": float(fit.cost),
                "optimality": float(fit.optimality),
                "coefficients_json": json.dumps(fit.x.tolist()),
                "max_abs_coefficient_difference_from_best": float(np.max(np.abs(fit.x - best.x))),
                "max_abs_prediction_difference_from_best": float(np.max(np.abs(prediction - best_prediction))),
            }
        )
    return best, summaries


def jacobian_per_unit(params: np.ndarray, x_i: np.ndarray, z_i: np.ndarray, n_outcomes: int) -> np.ndarray:
    z_i = np.asarray(z_i, dtype=float).reshape(1, -1)
    design_i = design_from_covariates(z_i, 1)[0]
    pi, _ = probabilities(params, x_i[None, :], z_i, n_outcomes)
    n_groups = x_i.size
    n_regressors = design_i.size
    jac = np.zeros((n_outcomes - 1, n_groups * (n_outcomes - 1) * n_regressors))
    for c in range(n_outcomes - 1):
        for r in range(n_groups):
            for k in range(n_outcomes - 1):
                common = x_i[r] * pi[0, r, c] * ((1.0 if c == k else 0.0) - pi[0, r, k])
                base = (r * (n_outcomes - 1) + k) * n_regressors
                jac[c, base : base + n_regressors] = common * design_i
    return jac


def sandwich_standard_errors(params: np.ndarray, data: NLSData) -> tuple[np.ndarray, dict[str, object]]:
    _, fitted = probabilities(params, data.x, data.z, data.t.shape[1])
    residual = data.t[:, :-1] - fitted[:, :-1]
    n_params = params.size
    bread = np.zeros((n_params, n_params))
    meat = np.zeros((n_params, n_params))
    for i in range(data.x.shape[0]):
        jac_i = jacobian_per_unit(params, data.x[i], data.z[i], data.t.shape[1])
        score_i = -2.0 * jac_i.T @ residual[i]
        meat += np.outer(score_i, score_i)
        bread += 2.0 * jac_i.T @ jac_i
    meat_inv = np.linalg.pinv(meat)
    info = bread.T @ meat_inv @ bread
    covariance = np.linalg.pinv(info)
    diag = np.diag(covariance)
    se = np.sqrt(np.where(diag >= 0, diag, np.nan))
    singular = np.linalg.svd(bread, compute_uv=False)
    return se, {
        "sandwich_rank_meat": int(np.linalg.matrix_rank(meat)),
        "sandwich_rank_info": int(np.linalg.matrix_rank(info)),
        "sandwich_condition_meat": float(np.linalg.cond(meat)),
        "sandwich_condition_info": float(np.linalg.cond(info)),
        "bread_rank": int(np.linalg.matrix_rank(bread)),
        "bread_condition": float(np.linalg.cond(bread)),
        "bread_singular_values_json": json.dumps(singular.tolist()),
    }


def aggregate_probabilities(x: np.ndarray, n: np.ndarray, pi: np.ndarray) -> np.ndarray:
    numerator = (n[:, None, None] * x[:, :, None] * pi).sum(axis=0)
    denominator = (n[:, None] * x).sum(axis=0)[:, None]
    return np.divide(numerator, denominator, out=np.full_like(numerator, np.nan), where=denominator > 0)
