"""Canonical death and exposure rows, including data unavailable for fitting."""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
import re

from .ages import Age


class Status(StrEnum):
    OBSERVED = "registration_observation"
    ESTIMATED = "historical_model_estimate"
    PROJECTED = "official_projection"
    SIMULATED = "simulation"
    FORECAST = "aevum_forecast"


class Quality(StrEnum):
    COMPLETE = "complete_registration"
    INCOMPLETE = "incomplete_registration"
    UNKNOWN = "unknown_registration_coverage"
    MODELED = "modeled"
    SIMULATED = "synthetic"
    FORECAST = "forecast"


class Availability(StrEnum):
    REPORTED = "reported"
    MISSING = "missing"
    SUPPRESSED = "suppressed"


class Unit(StrEnum):
    PERSON_YEARS = "person_years"
    MIDYEAR_POPULATION = "midyear_headcount_approximation"


class Sex(StrEnum):
    FEMALE = "female"
    MALE = "male"
    BOTH = "both"
    UNKNOWN = "unknown"


def _identifier(value: str) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", value) is not None


@dataclass(frozen=True, slots=True)
class Release:
    source: str
    vintage: str
    available_year: int | None
    last_historical_year: int | None
    raw_sha256: str

    def __post_init__(self) -> None:
        if not _identifier(self.source) or not _identifier(self.vintage):
            raise ValueError("invalid release identity")
        if self.available_year is not None and not _year(self.available_year):
            raise ValueError("invalid release year")
        if self.last_historical_year is not None and not _year(self.last_historical_year):
            raise ValueError("invalid historical boundary")
        if re.fullmatch(r"[0-9a-f]{64}", self.raw_sha256) is None:
            raise ValueError("release requires a lowercase SHA-256 digest")


def _year(value: int) -> bool:
    return type(value) is int and 1800 <= value <= 2300


@dataclass(frozen=True, slots=True)
class Cell:
    territory: str
    geography: str
    region: str
    year: int
    sex: Sex
    age: Age | None
    coverage: str

    def __post_init__(self) -> None:
        if not all(map(_identifier, (self.territory, self.geography, self.region, self.coverage))):
            raise ValueError("invalid territory, geography, region or coverage identity")
        if not _year(self.year) or not isinstance(self.sex, Sex):
            raise ValueError("invalid calendar year or published sex")
        if self.age is not None and not isinstance(self.age, Age):
            raise ValueError("invalid age interval")


@dataclass(frozen=True, slots=True)
class Deaths:
    cell: Cell
    release: Release
    status: Status
    quality: Quality
    availability: Availability
    count: float | None
    cause: str = "all"

    def __post_init__(self) -> None:
        allowed = {
            Status.OBSERVED: {Quality.COMPLETE, Quality.INCOMPLETE, Quality.UNKNOWN},
            Status.ESTIMATED: {Quality.MODELED},
            Status.PROJECTED: {Quality.MODELED},
            Status.SIMULATED: {Quality.SIMULATED},
            Status.FORECAST: {Quality.FORECAST},
        }
        if not isinstance(self.status, Status) or self.quality not in allowed[self.status]:
            raise ValueError("provenance status and quality are incompatible")
        cutoff = self.release.last_historical_year
        if cutoff is not None and self.status in {Status.OBSERVED, Status.ESTIMATED, Status.PROJECTED}:
            if (self.cell.year > cutoff) != (self.status == Status.PROJECTED):
                raise ValueError("year contradicts the release's historical/projection boundary")
        if not isinstance(self.availability, Availability) or not _identifier(self.cause):
            raise ValueError("invalid reporting status or cause identity")
        if self.availability == Availability.REPORTED:
            if self.count is None or not isfinite(self.count) or self.count < 0:
                raise ValueError("reported death counts must be nonnegative and finite")
            if self.status == Status.OBSERVED and self.count != int(self.count):
                raise ValueError("vital-registration deaths require integer counts")
        elif self.count is not None:
            raise ValueError("missing or suppressed deaths require a null count")


@dataclass(frozen=True, slots=True)
class Exposure:
    cell: Cell
    release: Release
    unit: Unit
    amount: float

    def __post_init__(self) -> None:
        if not isinstance(self.unit, Unit):
            raise ValueError("unsupported exposure unit")
        if not isfinite(self.amount) or self.amount < 0:
            raise ValueError("exposure must be finite and nonnegative")
        if self.cell.age is None or self.cell.sex == Sex.UNKNOWN:
            raise ValueError("exposure requires known age and sex")


@dataclass(frozen=True, slots=True)
class Observation:
    deaths: Deaths
    exposure: Exposure | None

    def __post_init__(self) -> None:
        if self.exposure is not None:
            if self.exposure.cell != self.deaths.cell:
                raise ValueError("death and exposure geography, period, age, sex or coverage differ")
            if self.exposure.release != self.deaths.release:
                raise ValueError("death and exposure releases differ")
            if self.exposure.amount == 0 and (self.deaths.count or 0) > 0:
                raise ValueError("positive deaths with zero exposure")

    def exclusion(self, *, permit_approximate: bool = False) -> str | None:
        if self.deaths.availability != Availability.REPORTED:
            return self.deaths.availability.value
        if self.deaths.cell.age is None or self.deaths.cell.sex == Sex.UNKNOWN:
            return "unknown_age_or_sex"
        if self.exposure is None:
            return "no_compatible_exposure"
        if self.exposure.amount == 0:
            return "zero_exposure"
        if self.exposure.unit != Unit.PERSON_YEARS and not permit_approximate:
            return "midyear_approximation_disallowed"
        return None

    def rate(self, *, permit_approximate: bool = False) -> float:
        reason = self.exclusion(permit_approximate=permit_approximate)
        if reason:
            raise ValueError(reason)
        assert self.deaths.count is not None and self.exposure is not None
        value = self.deaths.count / self.exposure.amount
        if not isfinite(value):
            raise ValueError("central rate overflow")
        return value


def join_counts(
    counts: Iterable[Deaths], exposures: Iterable[Exposure]
) -> Iterable[Observation]:
    index: dict[tuple[Cell, Release], Exposure] = {}
    for exposure in exposures:
        key = exposure.cell, exposure.release
        if key in index:
            raise ValueError("duplicate exposure key")
        index[key] = exposure
    seen = set()
    for count in counts:
        key = count.cell, count.release, count.cause
        if key in seen:
            raise ValueError("duplicate count key")
        seen.add(key)
        yield Observation(count, index.get((count.cell, count.release)))


def eligible_outcome(row: Observation, *, data_status: Status) -> bool:
    if data_status not in {Status.OBSERVED, Status.ESTIMATED, Status.SIMULATED}:
        raise ValueError("projection and forecast series are ineligible historical outcomes")
    return (
        row.deaths.status == data_status
        and row.deaths.cause == "all"
        and row.exclusion() is None
    )
