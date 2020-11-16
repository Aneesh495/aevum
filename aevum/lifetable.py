"""Python ownership and input contracts for the native life-table kernel."""

from collections.abc import Sequence
from ctypes import CDLL, POINTER, c_double, c_int, c_size_t, c_uint16
from dataclasses import dataclass
from functools import cache
from math import isfinite, isnan
import os
from pathlib import Path
import sys
from typing import Literal

from .ages import Age, validate_grid

Sex = Literal["female", "male"]
Method = Literal["force", "hmd_infant", "custom"]


@dataclass(frozen=True, slots=True)
class LifeRow:
    age: Age
    rate: float
    q: float
    l: float
    d: float
    L: float
    T: float
    e: float | None
    ax: float


@cache
def _kernel():
    suffix = {"darwin": ".dylib", "win32": ".dll"}.get(sys.platform, ".so")
    prefix = "" if sys.platform == "win32" else "lib"
    default = Path(__file__).resolve().parents[1] / "native" / "target" / "release"
    library = os.environ.get("AEVUM_NATIVE", str(default / f"{prefix}aevum_demography{suffix}"))
    try:
        calculate = CDLL(library).aevum_table
    except OSError as exc:
        raise RuntimeError("native life-table library unavailable; run make build") from exc
    calculate.argtypes = [
        c_size_t, POINTER(c_uint16), POINTER(c_double), POINTER(c_double),
        c_double, POINTER(c_double),
    ]
    calculate.restype = c_int
    return calculate


def infant_ax(rate: float, sex: Sex) -> float:
    """Apply the HMD v6 Table 3 central-rate formula for the published sex."""
    if not isfinite(rate) or rate < 0:
        raise ValueError("invalid infant rate")
    if sex == "male":
        if rate < 0.023:
            return 0.14929 - 1.99545 * rate
        return 0.02832 + 3.26021 * rate if rate < 0.08307 else 0.29915
    if sex == "female":
        if rate < 0.01724:
            return 0.14903 - 2.05527 * rate
        return 0.04667 + 3.88089 * rate if rate < 0.06891 else 0.31411
    raise ValueError("the HMD v6 infant formula requires a published female or male series")


def life_table(
    ages: Sequence[Age],
    rates: Sequence[float],
    *,
    method: Method = "force",
    sex: Sex | None = None,
    ax: Sequence[float] | None = None,
    radix: float = 100_000.0,
) -> tuple[LifeRow, ...]:
    grid = tuple(ages)
    validate_grid(grid)
    n = len(grid)
    if n != len(rates):
        raise ValueError("each age interval requires exactly one central rate")
    if method == "force" and ax is None:
        assumptions = [-1.0] * n
    elif method == "hmd_infant" and ax is None:
        if grid[0] != Age(0, 1) or sex is None:
            raise ValueError("hmd_infant requires a separate infant interval and sex")
        assumptions = [infant_ax(rates[0], sex), *[-1.0] * (n - 1)]
    elif method == "custom" and ax is not None and len(ax) == n - 1:
        if any(not isfinite(value) or not 0 <= value <= age.width for value, age in zip(ax, grid[:-1])):
            raise ValueError("custom a(x) values must lie within their closed age intervals")
        assumptions = [*ax, 0.0]
    else:
        raise ValueError("incompatible life-table method and a(x) arguments")
    widths = (c_uint16 * n)(*(age.width or 0 for age in grid))
    rate_buffer = (c_double * n)(*rates)
    assumptions_buffer = (c_double * n)(*assumptions)
    output = (c_double * (7 * n))()
    code = _kernel()(n, widths, rate_buffer, assumptions_buffer, radix, output)
    if code:
        detail = {
            1: "invalid age-grid shape",
            2: "nonfinite or out-of-bounds input",
            3: "the open-age rate must have a finite positive inverse",
            4: "the selected a(x) implies an impossible probability",
            5: "person-years or expectancy overflowed",
        }
        raise ValueError(detail.get(code, "native life-table failure"))

    rows = []
    for i, (age, rate) in enumerate(zip(grid, rates)):
        q, l, d, lived, remaining, e, assumption = output[i * 7:(i + 1) * 7]
        rows.append(LifeRow(age, float(rate), q, l, d, lived, remaining, None if isnan(e) else e, assumption))
    return tuple(rows)
