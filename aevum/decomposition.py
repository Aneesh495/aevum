"""Symmetric finite-change decomposition under piecewise constant force."""

from dataclasses import dataclass
from math import exp, expm1, isfinite
from collections.abc import Sequence

import numpy as np

from .ages import Age
from .lifetable import life_table


@dataclass(frozen=True, slots=True)
class Decomposition:
    before: float
    after: float
    contributions: np.ndarray
    residual: float


def _local_difference(
    width: int | None, start: float, end: float, suffix: float,
) -> float:
    """Secant of conditional life expectancy for one age coordinate."""
    if width is None:
        return -1 / start / end
    if abs(end - start) * width < 1e-6:
        rate = (start + end) / 2
        force = rate * width
        if force < 1e-4:
            derivative = width ** 2 * (-0.5 + force / 3 - force ** 2 / 8)
        else:
            derivative = (expm1(-force) + force * exp(-force)) / rate ** 2
        return derivative - width * exp(-force) * suffix
    start_years = -expm1(-width * start) / start if start > 0 else width
    end_years = -expm1(-width * end) / end if end > 0 else width
    survival_delta = exp(-width * end) - exp(-width * start)
    return (end_years - start_years + survival_delta * suffix) / (end - start)


def finite_change(
    ages: Sequence[Age], before: np.ndarray, after: np.ndarray,
) -> Decomposition:
    """Average forward and reverse age replacement, apportioning within age by cause."""
    if before.ndim != 2 or before.shape != after.shape or before.shape[0] != len(ages):
        raise ValueError("both scenarios require the same age-by-cause shape")
    if not np.isfinite(before).all() or not np.isfinite(after).all() or np.any(before < 0) or np.any(after < 0):
        raise ValueError("decomposition requires finite nonnegative cause hazards")
    if np.any(before > 100) or np.any(after > 100):
        raise ValueError("scenario decomposition rate exceeds numeric support")
    old = before.sum(axis=1)
    new = after.sum(axis=1)
    old_table = life_table(ages, old, radix=1.0)
    new_table = life_table(ages, new, radix=1.0)
    widths = np.array([age.width or 0 for age in ages])
    if min(old[-1], new[-1]) < 1e-8:
        raise ValueError("decomposition requires an identifiable finite open-age tail")
    suffix_old = np.zeros(len(ages))
    suffix_new = np.zeros(len(ages))
    suffix_old[-1], suffix_new[-1] = 1 / old[-1], 1 / new[-1]
    # Recurrence avoids dividing by a survival product that may underflow.
    for suffix, rates in ((suffix_old, old), (suffix_new, new)):
        for i in range(len(ages) - 2, -1, -1):
            n, m = widths[i], rates[i]
            suffix[i] = (-expm1(-n * m) / m if m else n) + exp(-n * m) * suffix[i + 1]
    out = np.empty_like(before, dtype=float)
    for i, age in enumerate(ages):
        after_prefix = new_table[i].l
        before_prefix = old_table[i].l
        if age.width is None:
            forward = reverse = _local_difference(None, old[i], new[i], 0)
        else:
            forward = _local_difference(age.width, old[i], new[i], suffix_old[i + 1])
            reverse = _local_difference(age.width, old[i], new[i], suffix_new[i + 1])
        out[i] = (after[i] - before[i]) * (after_prefix * forward + before_prefix * reverse) / 2
    start, end = old_table[0].e, new_table[0].e
    assert start is not None and end is not None
    residual = (end - start) - float(out.sum())
    if not isfinite(residual) or abs(residual) > 1e-8 * max(1, abs(start), abs(end)):
        raise ArithmeticError("decomposition failed finite-change reconciliation")
    return Decomposition(start, end, out, residual)
