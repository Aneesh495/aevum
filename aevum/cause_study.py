"""Screen WHO cause-composition cohorts and quantify conditional forecast error."""

import argparse
import csv
import json
from math import log, sinh
from pathlib import Path
import re
from statistics import mean, median
import subprocess
import unicodedata

import numpy as np

from .acquire import get_source
from .ages import Age
from .causes import GROUPS, forecast_shares, reconcile_forecast
from .decomposition import finite_change
from .lifetable import life_table
from .study import json_atomic
from .who import FIRST_YEAR, LAST_YEAR
from .wpp import connection

GEOGRAPHIC_EXCLUSIONS = ("Cyprus", "Georgia", "Republic of Moldova", "Russian Federation", "Serbia", "Singapore", "Mauritius")
ALIASES = {"Czech Republic": "Czechia", "Republic of Korea": "Republic of Korea",
           "United States": "United States of America", "The former Yugoslav Republic of Macedonia": "North Macedonia",
           "Moldova, Republic of": "Republic of Moldova", "Turkey": "Türkiye"}
AGE_STARTS = (0, 1, 2, 3, 4, *range(5, 100, 5))
AGES = tuple(Age(start, end) for start, end in zip(AGE_STARTS, (*AGE_STARTS[1:], None)))


def _clean(name: str) -> str:
    return " ".join(unicodedata.normalize("NFC", name).split())


def _annex(raw: Path, filename: str, heading: str) -> str:
    path = get_source(raw, "quality", filename)
    body = subprocess.check_output(["pdftotext", "-layout", str(path), "-"], text=True, timeout=30)
    if len(body) > 2_000_000:
        raise ValueError("quality annex outside size contract")
    _, match, relevant = body.rpartition(heading)
    if not match:
        raise ValueError("quality annex heading was not found")
    return relevant


def quality_screen(raw: Path) -> tuple[dict[str, tuple[int, int]], set[str]]:
    completion = _annex(raw, "ghe2023_lifetable_methods.pdf", "Annex B: Estimated completeness*")
    usable = _annex(raw, "ghe2023_cod_methods.pdf", "Annex Table D            Methods used for estimation")
    registry = {}
    for line in completion.splitlines():
        if re.match(r"^\s{2,}\S", line):
            for name, year, percent in re.findall(r"([^0-9]+?)\s{2,}(20[0-2]\d)\s+(\d{1,3})(?=\s|$)", line):
                if 0 <= int(percent) <= 100:
                    registry[_clean(name)] = int(year), int(percent)
    supported = {
        _clean(re.split(r"\s{2,}", line)[0])
        for line in usable.splitlines()
        if line.rstrip().endswith("Useable VR") and len(re.split(r"\s{2,}", line)) >= 4
    }
    if len(registry) < 80 or len(supported) < 35:
        raise ValueError("unexpected WHO quality annex parsing coverage")
    return registry, supported


def _csv(path: Path, rows: list[dict]):
    with path.open("x") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _smooth_year_exposure(previous: np.ndarray, midyear: np.ndarray, next_year: np.ndarray) -> np.ndarray:
    growth = 0.25 * np.log(next_year / previous)
    ratio = np.ones_like(growth)
    np.divide(np.sinh(growth), growth, out=ratio, where=growth != 0)
    return midyear * ratio


def analyze(panel: Path, raw: Path, out: Path) -> dict:
    registry, supported = quality_screen(raw)
    out.mkdir(parents=True, exist_ok=False)
    columns = ", ".join(f'"{group}"' for group in GROUPS)
    with connection() as con:
        rows = con.execute(f"""
            SELECT country, name, year, sex, age, deaths, exposure, {columns}
            FROM read_parquet(?) WHERE exclusion IS NULL AND name IS NOT NULL
              AND sex IN ('female','male') AND deaths IS NOT NULL
            ORDER BY country, year, sex, age
        """, [str(panel)]).fetchall()
    data = {(country, year, sex, age): (deaths, exposure, np.array(groups, dtype=float))
            for country, _, year, sex, age, deaths, exposure, *groups in rows}
    names = {row[0]: row[1] for row in rows}
    eligible = []
    assessments = []
    for code, name in sorted(names.items()):
        lookup = _clean(ALIASES.get(name, name))
        coverage_year, coverage = registry.get(lookup, (None, None))
        complete = all(
            (record := data.get((code, year, sex, "all"))) is not None and record[0] > 0
            and (record[2][-1] + record[2][-2]) / record[0] <= 0.10
            for year in range(FIRST_YEAR, LAST_YEAR + 1) for sex in ("female", "male")
        )
        good = complete and coverage is not None and coverage >= 95 and lookup in supported and lookup not in GEOGRAPHIC_EXCLUSIONS
        assessments.append({"who_code": code, "name": name, "complete_15y_screen": complete,
                            "completeness_benchmark_year": coverage_year, "benchmark_completeness_pct": coverage,
                            "who_usable_age5plus": lookup in supported, "eligible": good})
        if good:
            eligible.append(code)
    if not eligible:
        raise ValueError("cause study has no eligible countries")
    _csv(out / "quality.csv", assessments)
    results = []
    sensitivity = []
    counterfactuals = []
    for code in eligible:
        for sex in ("female", "male"):
            keys = [(code, year, sex, "all") for year in range(2014, 2019)]
            local = np.sum([data[key][2] for key in keys], axis=0)
            reference = np.sum(
                [data[(peer, year, sex, "all")][2] for peer in eligible if peer != code for year in range(2014, 2019)],
                axis=0,
            )
            shares = forecast_shares(local, reference, prior_strength=40)
            for year in (2019, 2020, 2021, 2022):
                total, _, causes = data[(code, year, sex, "all")]
                if causes.sum() != total:
                    raise ValueError("registered cause counts do not sum to all deaths")
                expected = reconcile_forecast(np.array(total, dtype=float), shares)
                for i, group in enumerate(GROUPS):
                    results.append({"country": code, "sex": sex, "year": year, "cause": group,
                                    "deaths": int(causes[i]), "all_deaths": total,
                                    "observed_share": causes[i] / total, "forecast_share": shares[i],
                                    "conditional_deaths": expected[i]})
            for year in range(2009, 2022):
                records = [[data.get((code, year + offset, sex, str(age))) for age in AGE_STARTS]
                           for offset in (-1, 0, 1)]
                if any(record is None or record[1] is None or record[1] <= 0 for table in records for record in table):
                    continue
                deaths = np.array([record[0] for record in records[1]])
                if deaths[-1] <= 0:
                    continue
                previous, current, subsequent = (np.array([record[1] for record in group]) for group in records)
                midpoint = life_table(AGES, deaths / current)[0].e
                smooth_exposure = _smooth_year_exposure(previous, current, subsequent)
                smooth = life_table(AGES, deaths / smooth_exposure)[0].e
                sensitivity.append({"country": code, "sex": sex, "year": year, "e0_midyear": midpoint,
                                    "e0_smooth_exposure": smooth, "e0_delta": smooth - midpoint,
                                    "max_abs_log_correction": float(np.max(np.abs(np.log(smooth_exposure / current))))})
                if year == 2019:
                    hazard = np.stack([record[2] for record in records[1]]) / current[:, None]
                    adjusted = hazard.copy()
                    adjusted[:, GROUPS.index("circulatory")] *= 0.5
                    change = finite_change(AGES, hazard, adjusted)
                    counterfactuals.append({"country": code, "sex": sex, "year": year,
                                            "baseline_e0": change.before, "conditional_e0": change.after,
                                            "e0_delta": change.after - change.before, "residual": change.residual})
    _csv(out / "share_forecast.csv", results)
    if sensitivity:
        _csv(out / "denominator_sensitivity.csv", sensitivity)
    if counterfactuals:
        _csv(out / "conditional_scenarios.csv", counterfactuals)
    summary = {"eligible_countries": len(eligible), "first_year": FIRST_YEAR, "last_year": LAST_YEAR,
               "vintage": "MDB-2026-02-23", "eligibility": "both published sexes, 15-year comparable ICD10 format, "
               "unknown plus residual <= 10%, WHO adult completeness benchmark >= 95% and usable VR age 5+",
               "annual_completeness_claim": "not identified from latest benchmark",
               "conditional_composition_cells": len(results), "midyear_sensitivity_tables": len(sensitivity),
               "scenarios": len(counterfactuals), "largest_decomposition_residual":
               max((abs(x["residual"]) for x in counterfactuals), default=None)}
    if sensitivity:
        summary["median_abs_midyear_effect_years"] = median(abs(x["e0_delta"]) for x in sensitivity)
        summary["max_abs_midyear_effect_years"] = max(abs(x["e0_delta"]) for x in sensitivity)
    summary["mae_share_by_year"] = {str(year): mean(
        abs(x["observed_share"] - x["forecast_share"]) for x in results if x["year"] == year
    ) for year in (2019, 2020, 2021, 2022)}
    json_atomic(out / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=Path("data/who.parquet"))
    parser.add_argument("--raw", type=Path, default=Path("data/raw"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(analyze(args.panel, args.raw, args.out), allow_nan=False))
