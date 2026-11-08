"""Synthetic recovery and failure under an unannounced structural shock."""

import argparse
import json
from pathlib import Path

import numpy as np

from .baselines import predict
from .simulate import generate
from .study import protocol
from .uncertainty import Calibration, expectancy, interval, weighted_interval_score


def recover(seed: int, misspecified: bool) -> dict:
    truth = generate(seed, countries=2, years=35, defects=True, misspecified=misspecified)
    cube = truth.panel
    origin = truth.shock_year - 1
    train = cube.training(origin)
    h = 5
    end = cube.years.index(origin + h)
    actual = expectancy(cube.ages, truth.rates[:, end])
    effects = {}
    for family in ("lee_carter", "count_trend"):
        outcome = predict(family, train, train.groups, h)
        point_rates = np.exp(outcome.log_rates[:, -1])
        point = expectancy(cube.ages, point_rates)
        sampler = Calibration.from_fit(outcome.fitted_log_rates, train.deaths, train.exposure)
        draws = sampler.paths(outcome.log_rates, draws=48, seed=seed)
        sample_e0 = expectancy(cube.ages, draws[:, :, -1])
        low, high = interval(sample_e0, 0.8)
        effects[family] = {
            "mean_absolute_e0_error": float(np.mean(np.abs(point - actual))),
            "mean_e0_bias": float(np.mean(point - actual)),
            "log_rate_rmse": float(np.sqrt(np.mean((np.log(point_rates) - np.log(truth.rates[:, end])) ** 2))),
            "coverage_80": float(np.mean((low <= actual) & (actual <= high))),
            "width_80": float(np.mean(high - low)),
            "wis": float(np.mean(weighted_interval_score(sample_e0, actual))),
            "target_e0": actual.tolist(),
            "predicted_e0": point.tolist(),
            "lower_80": low.tolist(), "upper_80": high.tolist(),
            "predicted_rates": point_rates.tolist(),
        }
    return {
        "seed": seed, "regime": "shock_and_cohort" if misspecified else "stable_drift",
        "origin": origin, "endpoint": origin + h, "shock_year": truth.shock_year, "coding_shift": truth.shift_year,
        "true_rates": truth.rates[:, end].tolist(), "exposure": cube.exposure[:, end].tolist(),
        "missing_cells": int(truth.missing.sum()), "suppressed_cells": int(truth.suppressed.sum()),
        "training_treatment": "complete simulated counts; reporting defects measured separately",
        "age_grid": [[age.start, age.end] for age in cube.ages], "models": effects,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cases", type=int, default=protocol()["synthetic_cases"])
    args = parser.parse_args()
    if not 2 <= args.cases <= 500:
        parser.error("case count must be between 2 and 500")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as handle:
        for i in range(args.cases):
            handle.write(json.dumps(recover(30100 + i, i % 2 == 1), allow_nan=False) + "\n")
