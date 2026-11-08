"""Competing-risk composition and conditional mortality scenarios."""

from collections.abc import Mapping, Sequence
from math import fsum, isclose, isfinite

import numpy as np

from .ages import Age
from .lifetable import LifeRow, life_table

TAXONOMY = "icd10-chapter-v1"
GROUPS = ("infectious", "neoplasms", "circulatory", "respiratory", "external", "special", "other", "unknown", "residual")


def composition(
    all_cause: float, by_cause: Mapping[str, float],
) -> dict[str, float]:
    if not isfinite(all_cause) or all_cause < 0 or set(by_cause) - set(GROUPS[:-1]):
        raise ValueError("invalid all-cause value or cause taxonomy")
    if any(not isfinite(value) or value < 0 for value in by_cause.values()):
        raise ValueError("cause quantities must be nonnegative and finite")
    residual = all_cause - fsum(by_cause.values())
    if residual < 0 and not isclose(residual, 0, abs_tol=1e-10 * all_cause):
        raise ValueError("cause sum exceeds the reported total")
    return {group: by_cause.get(group, 0.0) for group in GROUPS[:-1]} | {"residual": max(residual, 0.0)}


def forecast_shares(
    local_counts: np.ndarray, reference_counts: np.ndarray, prior_strength: float = 40.0,
) -> np.ndarray:
    """Posterior mean conditional on a supplied training-only reference profile."""
    if local_counts.shape != reference_counts.shape or local_counts.shape[-1] != len(GROUPS):
        raise ValueError("count arrays must share the declared taxonomy")
    if (
        not np.isfinite(local_counts).all() or not np.isfinite(reference_counts).all()
        or np.any(local_counts < 0) or np.any(reference_counts < 0)
        or not isfinite(prior_strength) or prior_strength <= 0
    ):
        raise ValueError("invalid counts or shrinkage strength")
    if np.any(reference_counts.sum(axis=-1) <= 0):
        raise ValueError("no same-age reference support")
    prior = reference_counts / reference_counts.sum(axis=-1, keepdims=True)
    posterior = local_counts + prior_strength * prior
    return posterior / posterior.sum(axis=-1, keepdims=True)


def reconcile_forecast(all_rates: np.ndarray, shares: np.ndarray) -> np.ndarray:
    if shares.shape != all_rates.shape + (len(GROUPS),):
        raise ValueError("cause shares must be supplied for every all-cause cell")
    if (
        not np.isfinite(all_rates).all() or np.any(all_rates < 0)
        or not np.isfinite(shares).all() or np.any(shares < 0)
        or not np.allclose(shares.sum(axis=-1), 1, atol=1e-12, rtol=0)
    ):
        raise ValueError("invalid cause composition or all-cause central rates")
    return all_rates[..., None] * shares


def scenario(
    ages: Sequence[Age], hazards: np.ndarray, multipliers: Mapping[str, float],
) -> tuple[LifeRow, ...]:
    """Apply conditional changes while holding the other cause hazards fixed."""
    if hazards.shape != (len(ages), len(GROUPS)) or not np.isfinite(hazards).all() or np.any(hazards < 0):
        raise ValueError("invalid age-by-cause central rate matrix")
    if set(multipliers) - set(GROUPS[:-2]):
        raise ValueError("residual and unknown causes are fixed in scenarios")
    scale = np.array([multipliers.get(group, 1.0) for group in GROUPS])
    if not np.isfinite(scale).all() or np.any((scale < 0) | (scale > 5)):
        raise ValueError("cause multipliers must lie between zero and five")
    return life_table(ages, hazards @ scale)
