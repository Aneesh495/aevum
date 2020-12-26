"""Known-truth demographic panels with explicit observation defects."""

from dataclasses import dataclass

import numpy as np

from .ages import abridged
from .causes import GROUPS
from .cube import Cube, Float, Population
from .panel import Status


@dataclass(frozen=True)
class Synthetic:
    panel: Cube
    rates: Float
    true_exposure: Float
    cause_counts: np.ndarray
    missing: np.ndarray
    suppressed: np.ndarray
    shift_year: int
    shock_year: int


def generate(
    seed: int, *, countries: int = 4, years: int = 38, defects: bool = False,
    misspecified: bool = False,
) -> Synthetic:
    if not 2 <= countries <= 70 or not 15 <= years <= 80:
        raise ValueError("synthetic work exceeds supported dimensions")
    rng = np.random.default_rng(seed)
    ages = abridged(90)
    age = np.array([a.start + (a.width or 0) / 2 for a in ages])[None, None, :]
    time = np.arange(years)[None, :, None]
    groups = tuple(
        Population(f"SIM{i:02d}", sex, f"region{i % 3}")
        for i in range(countries) for sex in ("female", "male")
    )
    shape = len(groups), years, len(ages)
    scale = rng.uniform(9, 15, (countries, 1, 1)).repeat(2, axis=0)
    exposure = np.exp(scale - age / 35 + time * 0.01) * rng.lognormal(0, 0.06, shape)
    sex_level = np.tile([0, 0.28], countries)[:, None, None]
    random_level = rng.normal(0, 0.23, (countries, 1, 1)).repeat(2, axis=0)
    age_rate = 0.00013 + 0.025 * np.exp(-age / 1.4) + 0.0009 * np.exp((age - 35) / 10)
    rate = age_rate * np.exp(sex_level + random_level - time * (0.012 + 0.013 * np.exp(-age / 50)))
    shock, coding = years - 7, years - 10
    if misspecified:
        rate = rate * np.exp((time >= shock) * (0.16 + 0.32 * (age > 65)))
        rate = rate * np.exp(0.15 * np.sin((time - age) / 9))
    deaths = rng.poisson(exposure * rate)
    shares = np.broadcast_to(
        np.array([0.04, 0.22, 0.28, 0.12, 0.08, 0.0, 0.22, 0.03, 0.01]),
        shape + (len(GROUPS),),
    ).copy()
    if defects:
        shares[:, coding:, :, 7] += 0.02
        shares[:, coding:, :, 6] -= 0.02
    cause_counts = rng.multinomial(deaths, shares)
    missing = np.zeros(shape, dtype=bool)
    suppressed = np.zeros(shape, dtype=bool)
    if defects:
        missing = rng.random(shape) < 0.025
        suppressed = (deaths < 5) & ~missing
    # The dense panel contains complete simulated counts. Defect masks belong to the
    # reporting layer and are used to test exclusion and missingness policies.
    panel = Cube(
        groups, tuple(range(1980, 1980 + years)), ages, deaths.astype(float), exposure,
        Status.SIMULATED, f"simulation-{seed}",
    )
    return Synthetic(panel, rate, exposure, cause_counts, missing, suppressed, 1980 + coding, 1980 + shock)
