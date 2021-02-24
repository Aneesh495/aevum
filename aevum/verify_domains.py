"""Independent reference, cause composition, and synthetic checks."""

from collections import defaultdict
import csv
import json
from math import fsum, isfinite
from pathlib import Path

from .verify import close, force_life_years, grid_widths, require


def published_tables(folder: Path) -> dict:
    records = defaultdict(list)
    with (folder / "published.csv").open() as handle:
        for row in csv.DictReader(handle):
            records[row["country"], row["sex"], int(row["year"])].append(row)
    require(len(records) == 252, "published reference support differs from frozen years and frame")
    exclusions = []
    validated = 0
    limits = {"qx": 6e-6, "lx": 0.03, "dx": 0.03, "Lx": 0.05, "Tx": 1.5, "ex": 0.004}
    for key, rows in records.items():
        require([int(row["age"]) for row in rows] == list(range(101)), "invalid published age schedule")
        data = [{name: float(row[name]) for name in ("mx", "ax", "qx", "lx", "dx", "Lx", "Tx", "ex")}
                for row in rows]
        for row in data:
            require(all(isfinite(x) and x >= 0 for x in row.values()), "nonfinite published input")
        capped = []
        for i, row in enumerate(data[:-1]):
            if row["mx"] == 1 and abs(row["qx"] - 1 / (2 - row["ax"])) > limits["qx"]:
                capped.append(i)
        if capped:
            exclusions.append(key)
            continue
        alive = 100_000.0
        values = []
        for i, row in enumerate(data):
            m = row["mx"]
            ax = row["ax"]
            if i < 100:
                require(0 <= ax <= 1, "impossible published ax")
                years = alive / (1 + (1 - ax) * m)
                deaths = years * m
                q = m / (1 + (1 - ax) * m)
            else:
                require(m > 0, "unsupported published open tail")
                years, deaths, q = alive / m, alive, 1.0
            values.append((q, alive, deaths, years))
            alive -= deaths
        for i, (row, (q, l, d, lived)) in enumerate(zip(data, values)):
            remain = fsum(value[3] for value in values[i:])
            implied_L = row["Tx"] - (data[i + 1]["Tx"] if i < 100 else 0)
            for field, observed, reconstructed in (
                ("qx", row["qx"], q), ("lx", row["lx"], l), ("dx", row["dx"], d),
                ("Lx", implied_L, lived), ("Tx", row["Tx"], remain),
            ):
                close(observed, reconstructed, field, absolute=limits[field], relative=0)
            if row["lx"] >= 1:
                close(row["ex"], remain / l, "reference expectancy", absolute=limits["ex"], relative=0)
        validated += 1
    require(validated >= 100, "insufficient eligible published references")
    return {"validated": validated, "capped_exclusions": [list(key) for key in exclusions]}


def check_causes(panel: Path, folder: Path) -> dict:
    import duckdb

    taxonomy = ("infectious", "neoplasms", "circulatory", "respiratory", "external",
                "special", "other", "unknown", "residual")
    with duckdb.connect(config={"threads": 2, "memory_limit": "1GB"}) as con:
        sums = " + ".join(f'"{column}"' for column in taxonomy)
        rows, corrupt = con.execute(f"""
            SELECT count(*), count(*) FILTER (
                WHERE deaths IS NULL OR deaths <> ({sums})
                OR least({', '.join(f'"{x}"' for x in taxonomy)}) < 0
                OR exposure_unit IS DISTINCT FROM 'midyear_headcount_approximation'
                OR status IS DISTINCT FROM 'registration_observation'
                OR taxonomy IS DISTINCT FROM 'icd10-chapter-v1'
            ) FROM read_parquet(?) WHERE exclusion IS NULL
        """, [str(panel)]).fetchone()
        require(rows > 1000 and not corrupt, "eligible WHO cells have inconsistent units or cause sums")
    with (folder / "quality.csv").open() as handle:
        eligible = {row["who_code"] for row in csv.DictReader(handle) if row["eligible"] == "True"}
    require(len(eligible) >= 15, "too few WHO causes cohorts passed the quality screen")
    data = defaultdict(dict)
    with (folder / "share_forecast.csv").open() as handle:
        for row in csv.DictReader(handle):
            key = row["country"], row["sex"], int(row["year"])
            require(row["cause"] in taxonomy and row["cause"] not in data[key], "invalid cause forecast partition")
            data[key][row["cause"]] = row
    expected = {(code, sex, year) for code in eligible for sex in ("female", "male") for year in range(2019, 2023)}
    require(set(data) == expected, "cause forecast study omits eligible country/year/sex strata")
    for group in data.values():
        require(set(group) == set(taxonomy), "incomplete forecast cause composition")
        total = int(group["other"]["all_deaths"])
        close(fsum(float(row["forecast_share"]) for row in group.values()), 1, "forecast cause shares", absolute=1e-10)
        close(fsum(float(row["conditional_deaths"]) for row in group.values()), total, "coherent forecast counts")
    with (folder / "conditional_scenarios.csv").open() as handle:
        scenarios = list(csv.DictReader(handle))
    require(bool(scenarios), "no eligible registered cause scenarios")
    for row in scenarios:
        require(float(row["conditional_e0"]) >= float(row["baseline_e0"]), "lower cause rate reduced expectancy")
        close(float(row["conditional_e0"]) - float(row["baseline_e0"]), float(row["e0_delta"]), "scenario change")
        close(float(row["residual"]), 0, "decomposition residual", absolute=1e-8)
    return {"reconciled_rows": rows, "screened_countries": len(eligible), "conditional_comparisons": len(data),
            "scenarios": len(scenarios)}


def check_recovery(path: Path) -> int:
    seen = set()
    with path.open() as handle:
        for line in handle:
            record = json.loads(line)
            seed = record["seed"]
            require(30100 <= seed < 30300 and seed not in seen, "unexpected synthetic seed")
            require(record["regime"] == ("shock_and_cohort" if seed % 2 else "stable_drift"), "synthetic regime mismatch")
            widths = grid_widths(record["age_grid"])
            require(set(record["models"]) == {"lee_carter", "count_trend"}, "missing synthetic fitted comparison")
            truth = [fsum(force_life_years(widths, age)[1]) for age in record["true_rates"]]
            require(len(truth) == 4, "invalid synthetic population count")
            for model in record["models"].values():
                forecasts = [fsum(force_life_years(widths, age)[1]) for age in model["predicted_rates"]]
                require(len(forecasts) == len(truth), "missing synthetic forecast strata")
                close(model["mean_absolute_e0_error"], fsum(abs(y - p) for y, p in zip(truth, forecasts)) / len(truth),
                      "synthetic mean absolute error")
                intervals = list(zip(model["lower_80"], model["upper_80"], truth, strict=True))
                require(all(0 < low <= high for low, high, _ in intervals), "invalid synthetic interval")
                close(model["coverage_80"], sum(lo <= y <= hi for lo, hi, y in intervals) / len(truth),
                      "synthetic coverage")
            seen.add(seed)
    require(len(seen) == 200, "incomplete known-truth campaign")
    return len(seen)
