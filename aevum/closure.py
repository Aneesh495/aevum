"""Explicit, exposure-weighted old-age sensitivity schedules."""

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from .ages import Age, complete
from .lifetable import life_table


@dataclass(frozen=True, slots=True)
class TailFit:
    intercept: float
    slope: float
    from_age: int
    terminal: int
    plateau: float
    loss: float

    def rates(self, ages: np.ndarray) -> np.ndarray:
        odds = np.exp(self.intercept + self.slope * (ages - self.from_age))
        return self.plateau * odds / (1 + odds)


def fit_tail(
    deaths: np.ndarray, exposure: np.ndarray, *, from_age: int = 80,
    train_until: int = 95, terminal: int = 110, plateau: float = 1.0,
) -> TailFit:
    if deaths.shape != exposure.shape or deaths.ndim != 1 or len(deaths) < train_until:
        raise ValueError("old-age inputs need paired complete single-year cells")
    if not 65 <= from_age < train_until - 4 < terminal <= 125 or not 0.25 <= plateau <= 3:
        raise ValueError("unsupported tail fitting window or plateau")
    d = deaths[from_age:train_until]
    e = exposure[from_age:train_until]
    mask = (e > 0) & np.isfinite(e) & np.isfinite(d)
    if np.any(d < 0) or np.any(e < 0) or np.any((e == 0) & (d > 0)) or mask.sum() < 8:
        raise ValueError("insufficient compatible old-age counts")
    d, e = d[mask], e[mask]
    if d.sum() < 10:
        raise ValueError("fewer than ten deaths in the tail calibration window")
    age = np.arange(train_until - from_age)[mask]
    normalization = d.sum()

    def objective(theta):
        log_odds = theta[0] + theta[1] * age
        log_fraction = -np.logaddexp(0, -log_odds)
        log_mean = np.log(e * plateau) + log_fraction
        forecast = np.exp(log_mean)
        gradient = (forecast - d) * (1 - np.exp(log_fraction))
        return (forecast - d * log_mean).sum() / normalization, np.array([gradient.sum(), gradient @ age]) / normalization

    result = minimize(objective, np.array([-2.0, 0.1]), jac=True, method="L-BFGS-B",
                      bounds=[(-12, 5), (0, 0.5)], options={"maxiter": 100, "ftol": 1e-12})
    if not result.success:
        raise ArithmeticError(f"old-age extrapolation failed: {result.message}")
    return TailFit(*map(float, result.x), from_age, terminal, plateau, float(result.fun))


def compare_closures(deaths: np.ndarray, exposure: np.ndarray) -> dict:
    if len(deaths) != 101 or len(exposure) != 101 or not np.isfinite(deaths).all() or not np.isfinite(exposure).all():
        raise ValueError("expected one WPP complete schedule ending at 100+")
    if np.any(deaths < 0) or np.any(exposure < 0) or np.any((exposure == 0) & (deaths > 0)):
        raise ValueError("negative or incompatible demographic input")
    below_90 = deaths[:90] / exposure[:90]
    main = np.append(below_90, deaths[90:].sum() / exposure[90:].sum())
    reference = life_table(complete(90), main)
    alternative = fit_tail(deaths, exposure)
    extended = np.concatenate((below_90, alternative.rates(np.arange(90, alternative.terminal + 1))))
    extended_table = life_table(complete(alternative.terminal), extended)
    return {
        "from_age": alternative.from_age, "terminal_age": alternative.terminal, "plateau": alternative.plateau,
        "slope": alternative.slope, "e0_90plus": reference[0].e, "e0_extrapolated": extended_table[0].e,
        "e90_90plus": reference[90].e, "e90_extrapolated": extended_table[90].e,
    }
