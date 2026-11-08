"""Four forecast baselines with explicit extrapolation, age support, and fallback."""

from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy.linalg import solve
from scipy.optimize import minimize

from .cube import Cube, Float, Population

Family = Literal["lee_carter", "count_trend", "apc", "coherent"]
FAMILIES: tuple[Family, ...] = ("lee_carter", "count_trend", "apc", "coherent")


def proxy_rates(deaths: Float, exposure: Float) -> Float:
    """Only log-rate fits require a finite proxy for an observed zero."""
    return np.log(np.where(deaths == 0, 0.5, deaths) / exposure)


def lee_carter(log_rates: Float) -> tuple[Float, Float, Float, float]:
    alpha = log_rates.mean(axis=0)
    residual = log_rates - alpha
    u, singular, v = np.linalg.svd(residual, full_matrices=False)
    loading = v[0].copy()
    total = float(loading.sum())
    # Signed L2 normalization handles a valid contrast with near-zero signed mass.
    if abs(total) < 1e-8:
        total = float(np.sign(loading[np.argmax(np.abs(loading))]))
    beta = loading / total
    kappa = singular[0] * u[:, 0] * total
    shift = float(kappa.mean())
    alpha = alpha + shift * beta
    kappa -= shift
    power = float(np.sum(singular ** 2))
    explained = float(singular[0] ** 2 / power) if power else 1.0
    return alpha, beta, kappa, explained


def _drift(values: Float) -> Float:
    # A random walk with drift has a mean equal to the average historical increment.
    return (values[-1] - values[0]) / (len(values) - 1)


def _count_trend(deaths: Float, exposure: Float, time: Float) -> tuple[Float, dict]:
    """Age-specific log-linear rate with a log exposure offset and ridge on drift."""
    total = deaths.sum(axis=0)
    weight = float(max(total.sum(), 1))
    initial = np.vstack((np.log((total + 0.5) / exposure.sum(axis=0)), np.zeros(len(total))))

    def objective(flat):
        alpha, beta = flat.reshape(2, -1)
        linear = alpha + time[:, None] * beta
        mean = exposure * np.exp(linear)
        difference = mean - deaths
        penalty = 0.0005 * np.sum(beta ** 2)
        loss = np.sum(mean - deaths * linear) / weight + penalty
        gradient = np.stack((difference.sum(axis=0), time @ difference)) / weight
        gradient[1] += 0.001 * beta
        return loss, gradient.ravel()

    bounds = [(-24.0, 2.0)] * len(total) + [(-4.0, 4.0)] * len(total)
    fit = minimize(
        objective, initial.ravel(), method="L-BFGS-B", jac=True, bounds=bounds,
        options={"maxiter": 250, "ftol": 1e-11},
    )
    coef = fit.x.reshape(2, -1)
    expected = exposure * np.exp(coef[0] + time[:, None] * coef[1])
    dispersion = float(np.sum((deaths - expected) ** 2 / expected) / max(deaths.size - coef.size, 1))
    return coef, {"converged": bool(fit.success), "iterations": int(fit.nit), "pearson_dispersion": dispersion}


def _apc_features(time: Float, age: Float, start: float, stop: float) -> Float:
    cohort = (time[:, None] - age[None, :] - start) / (stop - start)
    knots = np.linspace(0.05, 0.95, 9)
    return np.maximum(cohort[..., None] - knots, 0.0) ** 2


def apc_recenter(age: Float, period: Float, cohort: Float, tilt: float) -> tuple[Float, Float, Float]:
    """Redistribute linear trend when the calendar coordinate equals age plus cohort."""
    return -tilt * age, tilt * period, -tilt * cohort


def _fit_apc(log_rates: Float, ages: Float, years: Float, future: Float) -> tuple[Float, dict]:
    """Fit age fixed effects, period drift and detrended cohort curvature."""
    nt, na = log_rates.shape
    cmin = years[0] - ages[-1]
    cmax = years[-1] - ages[0]
    scale = max(years[-1] - years[0], 1.0)

    def bases(grid):
        time = (grid - years[-1]) / scale
        age = np.broadcast_to(np.eye(na), (len(grid), na, na))
        trend = np.broadcast_to(time[:, None, None], (len(grid), na, 1))
        cohort = _apc_features(grid, ages, cmin, cmax)
        return np.concatenate((age, trend), axis=-1).reshape(-1, na + 1), cohort.reshape(-1, 9)

    fixed, curve = bases(years)
    # The fitted cohort basis has zero mean and zero projection onto the
    # age intercepts and period drift in the calibration window.
    projection = np.linalg.lstsq(fixed, curve, rcond=None)[0]
    orthogonal = curve - fixed @ projection
    design = np.column_stack((fixed, orthogonal))
    ridge = np.diag([1e-8] * (na + 1) + [0.25] * 9)
    coef = solve(design.T @ design + ridge, design.T @ log_rates.ravel(), assume_a="pos")
    fixed_future, curve_future = bases(future)
    # The alternative stops the cohort contribution at the last observed cohort
    # before removing its training-window projection. Fits remain identical.
    cohort_raw = future[:, None] - ages[None, :]
    clipped = np.minimum(cohort_raw, cmax)
    knots = np.linspace(0.05, 0.95, 9)
    frozen = np.maximum((clipped[..., None] - cmin) / (cmax - cmin) - knots, 0.0) ** 2
    frozen = frozen.reshape(-1, 9)
    log_mean = np.column_stack((fixed_future, frozen - fixed_future @ projection)) @ coef
    alternate = np.column_stack((fixed_future, curve_future - fixed_future @ projection)) @ coef
    shifts = apc_recenter(ages[None, :], years[:, None], years[:, None] - ages[None, :], 0.02)
    return log_mean.reshape(-1, na), {
        "linear_null_max": float(np.max(np.abs(sum(shifts)))),
        "alternative_forecast_log_rate_rmse": float(np.sqrt(np.mean((alternate - log_mean) ** 2))),
        "fitted_log_rate_rmse": float(np.sqrt(np.mean((design @ coef - log_rates.ravel()) ** 2))),
        "training_cells": nt * na,
    }


@dataclass(frozen=True)
class BaselineForecast:
    log_rates: Float
    fitted_log_rates: Float
    diagnostics: tuple[dict, ...]
    support: tuple[str, ...]


def _fit_one(
    family: Family, d: Float, e: Float, years: Float, ages: Float, future: Float,
) -> tuple[Float, Float, dict]:
    log_rates = proxy_rates(d, e)
    horizon = future - years[-1]
    if family == "lee_carter":
        alpha, beta, kappa, explained = lee_carter(log_rates)
        fitted = alpha + np.outer(kappa, beta)
        prediction = alpha + np.outer(kappa[-1] + horizon * _drift(kappa), beta)
        return prediction, fitted, {
            "explained_log_rate_variance": explained,
            "beta_sum": float(beta.sum()), "kappa_mean": float(kappa.mean()),
        }
    if family == "count_trend":
        scale = years[-1] - years[0]
        coef, diagnostics = _count_trend(d, e, (years - years[-1]) / scale)
        return (
            coef[0] + np.outer(horizon / scale, coef[1]),
            coef[0] + np.outer((years - years[-1]) / scale, coef[1]),
            diagnostics,
        )
    if family == "apc":
        prediction, diagnostics = _fit_apc(log_rates, ages, years, np.concatenate((years, future)))
        return prediction[len(years):], prediction[:len(years)], diagnostics
    raise ValueError("coherent baseline requires multiple populations")


def _by_sex(groups: tuple[Population, ...], target: Population) -> list[int]:
    peers = [i for i, group in enumerate(groups) if group.sex == target.sex]
    if not peers:
        raise ValueError(f"no training support for sex {target.sex}")
    return peers


def _coherent(log_rates: Float, peers: list[int], index: int | None, horizon: Float):
    log_reference = log_rates[peers].mean(axis=0)
    alpha, beta, kappa, explained = lee_carter(log_reference)
    reference_fit = alpha + np.outer(kappa, beta)
    reference_future = alpha + np.outer(kappa[-1] + horizon * _drift(kappa), beta)
    if index is None:
        return reference_future, reference_fit, {"peer_count": len(peers), "rho": 0.0}
    gap = log_rates[index] - log_reference
    level = gap.mean(axis=0)
    centered = gap - level
    rho = float(np.clip(
        np.sum(centered[1:] * centered[:-1]) / max(np.sum(centered[:-1] ** 2), 1e-12),
        0.0, 0.97,
    ))
    fitted = reference_fit + level
    fitted[1:] += rho * centered[:-1]
    prediction = reference_future + level + rho ** horizon[:, None] * centered[-1]
    return prediction, fitted, {"peer_count": len(peers), "rho": rho, "factor_variance": explained}


def predict(
    family: Family, train: Cube, targets: tuple[Population, ...], horizon: int,
) -> BaselineForecast:
    if family not in FAMILIES or not 1 <= horizon <= 50 or len(train.years) < 12:
        raise ValueError("unsupported baseline, horizon or training window")
    years = np.asarray(train.years, dtype=np.float64)
    future = years[-1] + np.arange(1, horizon + 1)
    ages = np.array([age.start + (age.width or 0) / 2 for age in train.ages])
    forecasts, fits, diagnostics, support = [], [], [], []
    pooled = {}
    log_rates = proxy_rates(train.deaths, train.exposure)
    for target in targets:
        index = train.groups.index(target) if target in train.groups else None
        peers = _by_sex(train.groups, target)
        if family == "coherent":
            forecast, fit, diagnostic = _coherent(log_rates, peers, index, future - years[-1])
        elif index is not None:
            forecast, fit, diagnostic = _fit_one(family, train.deaths[index], train.exposure[index], years, ages, future)
        else:
            if target.sex not in pooled:
                pooled[target.sex] = _fit_one(
                    family, train.deaths[peers].sum(axis=0), train.exposure[peers].sum(axis=0),
                    years, ages, future,
                )
            forecast, fit, diagnostic = pooled[target.sex]
        forecasts.append(forecast)
        fits.append(fit)
        diagnostics.append(diagnostic)
        support.append("training_population" if index is not None else "unseen_country_same_sex_pool")
    return BaselineForecast(np.stack(forecasts), np.stack(fits), tuple(diagnostics), tuple(support))
