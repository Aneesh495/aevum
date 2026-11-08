"""Serve bounded batches from a frozen, source-identified checkpoint."""

import argparse
from dataclasses import asdict
from pathlib import Path

import numpy as np

from .acquire import digest
from .cohort_forecast import project
from .cube import load_wpp
from .learned import TrainingSpec, fit, load, predict
from .study import json_atomic, protocol
from .uncertainty import Calibration, LEVELS, expectancy, interval, survival
from .wpp import connection


def train_checkpoint(panel: Path, checkpoint: Path, family: str, seed: int, origin: int) -> dict:
    cube = load_wpp(panel).training(origin)
    return fit(cube, TrainingSpec(family, seed, protocol()["steps"]), checkpoint, digest(panel))


def export(
    panel: Path, checkpoint: Path, output: Path, countries: list[str], horizon: int,
    birth: int | None = None, attained_age: int = 0,
) -> None:
    if not 1 <= horizon <= 20 or not 1 <= len(countries) <= 10 or len(countries) != len(set(countries)):
        raise ValueError("forecast batch requires 1 to 10 distinct countries and a horizon of 1 to 20 years")
    identity = digest(panel)
    model = load(checkpoint, identity)
    cube = load_wpp(panel).training(model.support.origin, model.support.groups)
    groups = tuple(group for group in cube.groups if group.country in countries)
    if {group.country for group in groups} != set(countries):
        raise ValueError("requested countries are outside the checkpoint support")
    first = model.support.origin + 1
    years = tuple(range(first, first + horizon))
    forecast = predict(model, groups, years)
    fit_log_rates = predict(model, cube.groups, cube.years)
    fit_calibration = Calibration.from_fit(fit_log_rates, cube.deaths, cube.exposure)
    indices = [cube.groups.index(group) for group in groups]
    calibrator = Calibration(
        fit_calibration.innovations[indices], fit_calibration.endpoint_count_sd[indices],
        fit_calibration.endpoint_exposure_sd,
    )
    paths = calibrator.paths(forecast, draws=64, seed=731)
    e0 = expectancy(cube.ages, paths)
    rates = np.exp(forecast)
    cohorts = []
    if birth is not None:
        with connection() as con:
            for i, group in enumerate(groups):
                cells = con.execute("""
                    SELECT age_start, year, deaths / nullif(exposure, 0)
                    FROM read_parquet(?) WHERE country = ? AND sex = ?
                        AND age_end = age_start + 1 AND year - age_start = ? AND year <= ?
                """, [str(panel), group.country, group.sex, birth, model.support.origin]).fetchall()
                historical = {(age, year): rate for age, year, rate in cells if rate is not None}
                cohort = project(birth_year=birth, attained_age=attained_age, historical=historical,
                                 forecast_years=years, bands=cube.ages, forecasts=paths[:, i], point=rates[i])
                cohorts.append(asdict(group) | asdict(cohort))
    output.parent.mkdir(parents=True, exist_ok=True)
    json_atomic(output, {
        "status": "aevum_forecast", "source": "UN_WPP_historical_model_estimates",
        "vintage": cube.vintage, "unit": "deaths_per_person_year",
        "panel_sha256": identity, "checkpoint_sha256": digest(checkpoint),
        "model": asdict(model.spec), "origin": model.support.origin, "years": years,
        "age_grid": [asdict(age) for age in cube.ages], "populations": [asdict(g) for g in groups],
        "cohort_projections": cohorts, "central_rates": rates.tolist(), "survival": survival(cube.ages, rates).tolist(),
        "expectancy": expectancy(cube.ages, rates).tolist(),
        "e0_intervals": {str(level): [edge.tolist() for edge in interval(e0, level)] for level in LEVELS},
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("fit", "predict"))
    parser.add_argument("--panel", type=Path, default=Path("data/wpp.parquet"))
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--family", choices=("structured", "state_space"), default="structured")
    parser.add_argument("--seed", type=int, default=731)
    parser.add_argument("--origin", type=int, default=2023)
    parser.add_argument("--out", type=Path, default=Path("evidence/forecast.json"))
    parser.add_argument("--countries", nargs="+", default=["JPN", "USA"])
    parser.add_argument("--horizon", type=int, default=20)
    parser.add_argument("--birth", type=int)
    parser.add_argument("--attained-age", type=int, default=0)
    args = parser.parse_args()
    if args.action == "fit":
        if args.checkpoint.exists():
            parser.error("checkpoint exists; use a new filename")
        train_checkpoint(args.panel, args.checkpoint, args.family, args.seed, args.origin)
    else:
        export(args.panel, args.checkpoint, args.out, args.countries, args.horizon, args.birth, args.attained_age)
