"""Validated demographic age grids."""

from dataclasses import dataclass


@dataclass(frozen=True, order=True, slots=True)
class Age:
    start: int
    end: int | None

    def __post_init__(self) -> None:
        if type(self.start) is not int or not 0 <= self.start <= 150:
            raise ValueError("age start must be an integer in [0, 150]")
        if self.end is not None and (
            type(self.end) is not int or not self.start < self.end <= 150
        ):
            raise ValueError("closed intervals require a larger integer upper boundary")

    @property
    def width(self) -> int | None:
        return None if self.end is None else self.end - self.start

    @property
    def label(self) -> str:
        if self.end is None:
            return f"{self.start}+"
        return str(self.start) if self.width == 1 else f"{self.start}–{self.end - 1}"


def validate_grid(ages: tuple[Age, ...], *, open_tail: bool = True) -> None:
    if not 1 <= len(ages) <= 151:
        raise ValueError("expected between one and 151 age intervals")
    if (ages[-1].end is None) != open_tail:
        raise ValueError("unexpected terminal interval")
    if any(left.end != right.start for left, right in zip(ages, ages[1:])):
        raise ValueError("age grid must be ordered, contiguous, and nonoverlapping")


def complete(terminal: int) -> tuple[Age, ...]:
    if type(terminal) is not int or not 1 <= terminal <= 150:
        raise ValueError("terminal age must be an integer in [1, 150]")
    return tuple(Age(age, age + 1) for age in range(terminal)) + (Age(terminal, None),)


def abridged(terminal: int = 100) -> tuple[Age, ...]:
    if type(terminal) is not int or not 5 <= terminal <= 150 or terminal % 5:
        raise ValueError("terminal age must be a multiple of five in [5, 150]")
    return (Age(0, 1), Age(1, 5)) + tuple(
        Age(age, age + 5) for age in range(5, terminal, 5)
    ) + (Age(terminal, None),)
