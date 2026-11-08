"""Dependence-preserving forecast uncertainty and interval scoring."""

from dataclasses import dataclass

import numpy as np

from .ages import Age, validate_grid
from .cube import Float

LEVELS = (0.50, 0.80, 0.95)


def expectancy(ages: tuple[Age, ...], rates: Float) -> Float:
    """Vectorized constant-force e0 recurrence for Monte Carlo arrays."""
    validate_grid(ages)
    if rates.shape[-1] != len(ages) or not np.isfinite(rates).all() or np.any(rates < 0):
        raise ValueError("invalid sampled rate or age-grid shape")
    if np.any(rates[..., -1] <= 0):
        raise ValueError("forecast terminal rate must be positive")
    remaining = 1 / rates[..., -1]
    for i in range(len(ages) - 2, -1, -1):
        width = ages[i].width
        rate = rates[..., i]
        force = width * rate
        lived = np.full_like(rate, width)
        np.divide(-np.expm1(-force), rate, out=lived, where=rate != 0)
        remaining = lived + np.exp(-force) * remaining
    if not np.isfinite(remaining).all():
        raise ValueError("nonfinite sampled expectancy")
    return remaining


def survival(ages: tuple[Age, ...], rates: Float) -> Float:
    validate_grid(ages)
    if rates.shape[-1] != len(ages) or not np.isfinite(rates).all() or np.any(rates < 0):
        raise ValueError("invalid rate for sampled survival")
    width = np.array([age.width for age in ages[:-1]])
    elapsed = np.cumsum(rates[..., :-1] * width, axis=-1)
    return np.concatenate((np.ones_like(rates[..., :1]), np.exp(-elapsed)), axis=-1)


@dataclass(frozen=True, slots=True)
class Calibration:
    innovations: Float
    endpoint_count_sd: Float
    endpoint_exposure_sd: float

    @classmethod
    def from_fit(
        cls, fitted: Float, deaths: Float, exposure: Float,
        *, exposure_cv: float = 0.02,
    ) -> "Calibration":
        if fitted.shape != deaths.shape or exposure.shape != fitted.shape or fitted.ndim != 3:
            raise ValueError("calibration arrays must match by population, year and age")
        if fitted.shape[1] < 12 or not 0 <= exposure_cv <= 0.5:
            raise ValueError("calibration history or denominator sensitivity outside supported limits")
        pseudo = np.log(np.where(deaths > 0, deaths, 0.5) / exposure)
        residual = pseudo - fitted
        innovations = np.diff(residual, axis=1)
        innovations -= innovations.mean(axis=1, keepdims=True)
        # This cap limits single-year register anomalies from defining every future step.
        innovations = np.clip(innovations, -0.65, 0.65)
        innovations -= innovations.mean(axis=1, keepdims=True)
        sampling_sd = 1 / np.sqrt(deaths[:, -3:, :].sum(axis=1) + 1)
        return cls(innovations, np.minimum(sampling_sd, 0.75), exposure_cv)

    def paths(self, log_rate: Float, *, draws: int, seed: int, block: int = 3) -> Float:
        if log_rate.ndim != 3 or not 1 <= draws <= 512 or not 1 <= block <= 12:
            raise ValueError("invalid forecast shape or draw budget")
        groups, steps, ages = log_rate.shape
        if self.innovations.shape[0] != groups or self.innovations.shape[-1] != ages:
            raise ValueError("calibration and target axes differ")
        rng = np.random.default_rng(seed)
        history = self.innovations.shape[1]
        starts = rng.integers(0, history - min(block, history) + 1, size=(draws, (steps + block - 1) // block))
        time = (starts[..., None] + np.arange(block)).reshape(draws, -1)[:, :steps] % history
        # Synchronized calendar blocks preserve cross-age and cross-population dependence.
        residual_steps = self.innovations[:, time, :].transpose(1, 0, 2, 3)
        trajectory = np.cumsum(residual_steps, axis=2)
        count_noise = rng.normal(size=(draws, groups, 1, ages)) * self.endpoint_count_sd[None, :, None, :]
        exposure_noise = rng.normal(size=(draws, groups, 1, 1)) * self.endpoint_exposure_sd
        return np.exp(np.clip(log_rate[None, ...] + trajectory + count_noise - exposure_noise, -25, 8))


def interval(values: Float, level: float) -> tuple[Float, Float]:
    if level not in LEVELS or not np.isfinite(values).all() or len(values) == 0:
        raise ValueError("invalid predictive draw set or nominal level")
    alpha = (1 - level) / 2
    low, high = np.quantile(values, [alpha, 1 - alpha], axis=0)
    return low, high


def interval_score(low: Float, high: Float, truth: Float, level: float) -> Float:
    if not np.isfinite(low).all() or not np.isfinite(high).all() or not np.isfinite(truth).all():
        raise ValueError("interval scores require finite outcomes and bounds")
    if np.any(low > high) or not 0 < level < 1:
        raise ValueError("invalid prediction interval")
    penalty = 2 / (1 - level)
    return high - low + penalty * (np.maximum(low - truth, 0) + np.maximum(truth - high, 0))


def weighted_interval_score(draws: Float, truth: Float) -> Float:
    median = np.median(draws, axis=0)
    value = 0.5 * np.abs(median - truth)
    for level in LEVELS:
        low, high = interval(draws, level)
        value += (1 - level) / 2 * interval_score(low, high, truth, level)
    return value / (len(LEVELS) + 0.5)
