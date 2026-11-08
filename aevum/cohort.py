"""Age/calendar diagonals of period surfaces, with explicit truncation."""

from collections.abc import Iterable
from dataclasses import dataclass

from .ages import Age
from .lifetable import LifeRow, life_table
from .panel import Observation, Release, Sex, Status


@dataclass(frozen=True, slots=True)
class CohortStep:
    age: Age
    year: int
    rate: float | None
    status: Status | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class CohortTrace:
    birth_year: int
    steps: tuple[CohortStep, ...]

    def table(self) -> tuple[LifeRow, ...]:
        if self.steps[-1].age.end is not None or any(step.rate is None for step in self.steps):
            raise ValueError("cohort expectancy requires an unbroken diagonal and a supported tail")
        return life_table(
            [step.age for step in self.steps],
            [step.rate for step in self.steps if step.rate is not None],
        )


def diagonal(
    rows: Iterable[Observation],
    *,
    territory: str,
    geography: str,
    coverage: str,
    sex: Sex,
    release: Release,
    birth_year: int,
    terminal_age: int,
    allow_forecast: bool = False,
) -> CohortTrace:
    if not 1800 <= birth_year <= 2300 or not 1 <= terminal_age <= 150:
        raise ValueError("birth year or terminal age outside supported domain")
    cells = {}
    for row in rows:
        death = row.deaths
        cell = death.cell
        if (cell.territory, cell.geography, cell.coverage, cell.sex, death.release, death.cause) != (
            territory, geography, coverage, sex, release, "all",
        ):
            continue
        age = cell.age
        if age is None or age.width not in (1, None):
            continue
        if age.start > terminal_age or cell.year - age.start != birth_year:
            continue
        if age in cells:
            raise ValueError("ambiguous cohort cell")
        cells[age] = row
    trace = []
    for start in range(terminal_age + 1):
        age = Age(start, start + 1 if start < terminal_age else None)
        row = cells.get(age)
        year = birth_year + start
        if row is None:
            trace.append(CohortStep(age, year, None, None, "missing_diagonal_cell"))
            continue
        status = row.deaths.status
        reason = row.exclusion()
        if status == Status.PROJECTED or (status == Status.FORECAST and not allow_forecast):
            reason = "projection_or_forecast_excluded"
        trace.append(CohortStep(age, year, None if reason else row.rate(), status, reason))
    return CohortTrace(birth_year, tuple(trace))
