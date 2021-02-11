"""Join historical age/calendar cells to sampled future rate paths."""

from dataclasses import dataclass
from math import isfinite

import numpy as np

from .ages import Age, validate_grid
from .uncertainty import expectancy, interval, LEVELS


@dataclass(frozen=True, slots=True)
class CohortEstimate:
    birth_year: int
    attained_age: int
    terminal_age: int
    age_year_status: tuple[tuple[int, int, str], ...]
    point_years: float | None
    remaining_years: tuple[tuple[float, float, float], ...]
    status: str


def project(
    *,
    birth_year: int,
    attained_age: int,
    historical: dict[tuple[int, int], float],
    forecast_years: tuple[int, ...],
    bands: tuple[Age, ...],
    forecasts: np.ndarray,
    point: np.ndarray,
) -> CohortEstimate:
    """Interpret each future model band as piecewise constant within the band."""
    validate_grid(bands)
    terminal = bands[-1].start
    if type(birth_year) is not int or not 1800 <= birth_year <= 2300 or not 0 <= attained_age < terminal:
        raise ValueError("invalid cohort birth or attained age")
    if not forecast_years or forecast_years != tuple(range(forecast_years[0], forecast_years[-1] + 1)):
        raise ValueError("future model years must be contiguous")
    if (
        forecasts.ndim != 3 or not 1 <= len(forecasts) <= 512
        or point.shape != (len(forecast_years), len(bands)) or forecasts.shape[1:] != point.shape
        or not np.isfinite(forecasts).all() or np.any(forecasts <= 0)
        or not np.isfinite(point).all() or np.any(point <= 0)
    ):
        raise ValueError("invalid positive forecast paths")
    origin = forecast_years[0] - 1
    trace, center, samples = [], [], []
    for age in range(attained_age, terminal + 1):
        year = birth_year + age
        if year <= origin:
            rate = historical.get((age, year))
            # A single-age observation cannot supply a grouped open tail.
            if rate is None or age == terminal:
                trace.append((age, year, "historical_cell_or_tail_unavailable"))
                continue
            if not isfinite(rate) or rate < 0:
                raise ValueError("invalid historical age rate")
            center.append(rate)
            samples.append(np.full(len(forecasts), rate))
            trace.append((age, year, "historical_single_age"))
        elif year in forecast_years:
            j = year - forecast_years[0]
            k = next(i for i, band in enumerate(bands) if band.start <= age and (band.end is None or age < band.end))
            center.append(point[j, k])
            samples.append(forecasts[:, j, k])
            trace.append((age, year, "aevum_forecast_piecewise_age"))
        else:
            trace.append((age, year, "beyond_forecast_horizon"))
    if len(center) != len(trace):
        return CohortEstimate(birth_year, attained_age, terminal, tuple(trace), None, (), "truncated")
    ages = tuple(Age(i, i + 1 if i < terminal else None) for i in range(attained_age, terminal + 1))
    sample_years = expectancy(ages, np.stack(samples, axis=1))
    point_years = float(expectancy(ages, np.array(center)))
    limits = tuple((level, *map(float, interval(sample_years, level))) for level in LEVELS)
    return CohortEstimate(birth_year, attained_age, terminal, tuple(trace), point_years, limits,
                          "conditional_remaining_lifetime_piecewise_forecast")
