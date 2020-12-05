"""Dense model inputs built exclusively from a declared historical Arrow panel."""

from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from .ages import Age, abridged, validate_grid
from .panel import Status
from .wpp import HISTORICAL_END, VINTAGE, connection, frame

Float = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class Population:
    country: str
    sex: str
    region: str


@dataclass(frozen=True, slots=True)
class Cube:
    groups: tuple[Population, ...]
    years: tuple[int, ...]
    ages: tuple[Age, ...]
    deaths: Float
    exposure: Float
    status: Status
    vintage: str

    def __post_init__(self) -> None:
        validate_grid(self.ages)
        if self.status not in {Status.ESTIMATED, Status.OBSERVED, Status.SIMULATED}:
            raise ValueError("model inputs require a historical or synthetic source")
        if not self.groups or len(set(self.groups)) != len(self.groups):
            raise ValueError("empty or duplicate population support")
        if not self.years or self.years != tuple(range(self.years[0], self.years[-1] + 1)):
            raise ValueError("annual model inputs require a contiguous calendar")
        shape = len(self.groups), len(self.years), len(self.ages)
        if self.deaths.shape != shape or self.exposure.shape != shape:
            raise ValueError("count and exposure shapes contradict the cube dimensions")
        if not np.isfinite(self.deaths).all() or not np.isfinite(self.exposure).all():
            raise ValueError("nonfinite count or exposure")
        if np.any(self.deaths < 0) or np.any(self.exposure <= 0):
            raise ValueError("negative deaths or nonpositive exposure")
        if not np.isfinite(self.deaths / self.exposure).all():
            raise ValueError("invalid central rate")
        self.deaths.setflags(write=False)
        self.exposure.setflags(write=False)

    @property
    def rates(self) -> Float:
        return self.deaths / self.exposure

    def training(self, origin: int, groups: tuple[Population, ...] | None = None) -> "Cube":
        if origin not in self.years:
            raise ValueError("origin outside the source history")
        keep = self.groups if groups is None else groups
        positions = [self.groups.index(group) for group in keep]
        end = self.years.index(origin) + 1
        return replace(
            self, groups=keep, years=self.years[:end],
            deaths=self.deaths[positions, :end, :], exposure=self.exposure[positions, :end, :],
        )


def load_wpp(path: Path) -> Cube:
    regions, first, last = frame()
    years = tuple(range(first, last + 1))
    groups = tuple(
        Population(country, sex, regions[country])
        for country in sorted(regions) for sex in ("female", "male")
    )
    ages = abridged(90)
    with connection() as con:
        validity = con.execute("""
            SELECT count(*), count(DISTINCT (country,sex,year,age_start)),
                   count(*) FILTER (WHERE
                       status IS DISTINCT FROM 'historical_model_estimate'
                       OR vintage IS DISTINCT FROM ?
                       OR quality IS DISTINCT FROM 'modeled'
                       OR source IS DISTINCT FROM 'UN_WPP'
                       OR exposure_unit IS DISTINCT FROM 'person_years'
                       OR cause IS DISTINCT FROM 'all'
                       OR availability IS DISTINCT FROM 'reported'
                       OR year IS NULL OR year > ?
                       OR exposure IS NULL OR NOT isfinite(exposure) OR exposure < 0
                       OR (exposure = 0 AND deaths <> 0)
                       OR exclusion IS DISTINCT FROM CASE WHEN exposure = 0 THEN 'zero_rounded_exposure' END
                       OR deaths IS NULL OR NOT isfinite(deaths) OR deaths < 0
                       OR age_start IS NULL OR age_start NOT BETWEEN 0 AND 100
                       OR age_end IS DISTINCT FROM CASE WHEN age_start < 100 THEN age_start + 1 END)
            FROM read_parquet(?)
        """, [VINTAGE, HISTORICAL_END, str(path)]).fetchone()
        cells = len(groups) * len(years) * 101
        if validity != (cells, cells, 0):
            raise ValueError("WPP panel contains invalid provenance, units or support")
        arrow = con.execute("""
            WITH grouped AS (
                SELECT country, sex, region, year,
                    CASE WHEN age_start < 5 THEN least(age_start, 1)
                         ELSE least((age_start // 5) * 5, 90) END AS age,
                    deaths, exposure
                FROM read_parquet(?)
            )
            SELECT country, sex, region, year, age, sum(deaths) AS deaths, sum(exposure) AS exposure
            FROM grouped GROUP BY ALL ORDER BY country, sex, year, age
        """, [str(path)]).fetch_arrow_table()
    keys = zip(*(arrow[name].to_pylist() for name in ("country", "sex", "region", "year", "age")), strict=True)
    expected = (
        (group.country, group.sex, group.region, year, age.start)
        for group in groups for year in years for age in ages
    )
    if any(a != b for a, b in zip(keys, expected, strict=True)):
        raise ValueError("observed WPP support does not match the frozen frame")
    shape = len(groups), len(years), len(ages)
    return Cube(
        groups, years, ages,
        arrow["deaths"].to_numpy().reshape(shape), arrow["exposure"].to_numpy().reshape(shape),
        Status.ESTIMATED, VINTAGE,
    )
