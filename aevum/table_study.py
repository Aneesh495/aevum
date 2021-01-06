"""Published life-table reproduction, analytic stress, and age sensitivity."""

import argparse
import csv
from dataclasses import asdict
import json
from math import isfinite
from pathlib import Path
import random
from tempfile import NamedTemporaryFile

from .acquire import get_source
from .ages import abridged, complete
from .lifetable import life_table
from .study import protocol
from .wpp import PREFIX, SUFFIX, connection, frame


def reference(raw: Path, output: Path) -> dict:
    countries, _, _ = frame()
    years = protocol()["reference_years"]
    columns = ("country", "sex", "year", "age", "mx", "ax", "qx", "lx", "dx", "Lx", "Tx", "ex")
    tolerances = {"qx": 6e-6, "lx": 0.03, "dx": 0.03, "Lx": 0.05, "Tx": 1.5, "ex": 0.004}
    output.mkdir(parents=True, exist_ok=False)
    complete_rows = 0
    eligible = 0
    worst = {field: 0.0 for field in tolerances}
    mismatches = []
    exclusions = []
    duplicated_lx = 0
    with (output / "published.csv").open("w") as published, (output / "comparison.jsonl").open("w") as checked, connection() as con:
        writer = csv.writer(published)
        writer.writerow(columns)
        for sex in ("Female", "Male"):
            source = get_source(raw, "wpp", PREFIX + f"Life_Table_Complete_Medium_{sex}_1950-2023.csv.gz")
            records = con.execute("""
                SELECT ISO3_code, lower(Sex), Time::INT, AgeGrpStart::INT,
                    mx::DOUBLE, ax::DOUBLE, qx::DOUBLE, lx::DOUBLE, dx::DOUBLE,
                    Lx::DOUBLE, Tx::DOUBLE, ex::DOUBLE
                FROM read_csv(?, all_varchar=true, delim=',', quote='"', escape='"', sample_size=5000)
                WHERE ISO3_code IN (SELECT unnest(?::VARCHAR[]))
                    AND Time::INT IN (SELECT unnest(?::INTEGER[])) AND Variant = 'Medium'
                ORDER BY ISO3_code, Time::INT, AgeGrpStart::INT
            """, [str(source), sorted(countries), years]).fetchall()
            writer.writerows(records)
            complete_rows += len(records)
            for i in range(0, len(records), 101):
                selection = records[i:i + 101]
                key = tuple(selection[0][:3])
                if len(selection) != 101 or any(tuple(row[:4]) != (*key, age) for age, row in enumerate(selection)):
                    raise ValueError("published table has inconsistent grouping or age support")
                rates = [row[4] for row in selection]
                ax = [row[5] for row in selection[:-1]]
                if any(m is None or not isfinite(m) for m in rates) or rates[-1] <= 0:
                    mismatches.append({"key": key, "reason": "missing or unusable published rate"})
                    continue
                duplicated_lx += sum(row[7] == row[9] for row in selection)
                inconsistent_cap = [
                    row[3] for row in selection[:-1]
                    if row[4] == 1 and abs(row[6] - 1 / (2 - row[5])) > tolerances["qx"]
                ]
                if inconsistent_cap:
                    exclusions.append({"key": key, "reason": "capped_mx_inconsistent_with_published_qx",
                                       "ages": inconsistent_cap})
                    continue
                expected = life_table(complete(100), rates, method="custom", ax=ax)
                # e(x) at ages with negligible survival is sensitive to rounding.
                # This comparison scores e(x) only where published l(x) >= 1.
                differences = {field: 0.0 for field in tolerances}
                for age_index, (got, published_row) in enumerate(zip(expected, selection)):
                    values = (got.q, got.l, got.d, got.L, got.T, got.e)
                    next_total = selection[age_index + 1][10] if age_index < 100 else 0
                    targets = (*published_row[6:9], published_row[10] - next_total, *published_row[10:])
                    for field, value, target in zip(tolerances, values, targets):
                        if field == "ex" and published_row[7] < 1:
                            continue
                        differences[field] = max(differences[field], abs(value - target))
                eligible += 1
                for field in tolerances:
                    worst[field] = max(worst[field], differences[field])
                fail = {field: delta for field, delta in differences.items() if delta > tolerances[field]}
                if fail:
                    mismatches.append({"key": key, "errors": fail})
                checked.write(json.dumps({"key": key, "max_abs_error": differences, "e0": expected[0].e,
                                          "source_e0": selection[0][-1], "passed": not fail}) + "\n")
    summary = {"published_rows": complete_rows, "compared_tables": eligible, "failed": len(mismatches),
               "failures": mismatches, "exclusions": exclusions,
               "published_Lx_equal_to_lx_rows": duplicated_lx,
               "max_abs_error": worst, "tolerance": tolerances,
               "vintage": "WPP2024-original", "reference_years": years,
               "comparison": "v2: reconstruct from published mx and ax; score implied Lx from Tx differences"}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def stress(output: Path, n: int, seed: int = 9008) -> None:
    if not 1 <= n <= 20_000:
        raise ValueError("stress work outside supported range")
    output.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    with output.open("x") as handle:
        for i in range(n):
            ages = complete(100) if i % 20 == 0 else abridged(90)
            rates = [0.0 if rng.random() < 0.05 else 10 ** rng.uniform(-6, 0.2) for _ in ages[:-1]]
            rates.append(10 ** rng.uniform(-2, 0.3))
            rows = life_table(ages, rates)
            handle.write(json.dumps({"table": i, "seed": seed, "method": "force",
                                     "rows": [asdict(row) for row in rows]}, allow_nan=False) + "\n")


def schedule_tables(panel: Path, output: Path) -> dict:
    with connection() as con:
        groups = con.execute("""
            SELECT country, sex, year, list(deaths / nullif(exposure, 0) ORDER BY age_start) AS rates,
                   list(deaths ORDER BY age_start) AS deaths, list(exposure ORDER BY age_start) AS exposure
            FROM read_parquet(?) GROUP BY country, sex, year ORDER BY country, sex, year
        """, [str(panel)]).fetchall()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"complete": 0, "excluded_complete": 0, "abridged": 0}
    stage = None
    try:
        with NamedTemporaryFile(dir=output.parent, delete=False, mode="w") as handle:
            stage = Path(handle.name)
            writer = csv.writer(handle)
            writer.writerow(("country", "sex", "year", "e0_complete", "e0_abridged_90", "e0_hmd_infant",
                             "e0_unweighted_bands", "complete_exclusion"))
            ages = abridged(90)
            for country, sex, year, rates, deaths, exposure in groups:
                if len(rates) != 101:
                    raise ValueError("incomplete WPP period support")
                if None in rates or rates[-1] <= 0:
                    complete_e0 = None
                    report["excluded_complete"] += 1
                else:
                    complete_e0 = life_table(complete(100), rates)[0].e
                    report["complete"] += 1
                aggregate = []
                unweighted = []
                for age in ages:
                    interval = slice(age.start, age.end)
                    aggregate.append(sum(deaths[interval]) / sum(exposure[interval]))
                    finite = [rate for rate in rates[interval] if rate is not None]
                    unweighted.append(sum(finite) / len(finite))
                central = life_table(ages, aggregate)[0].e
                hmd = life_table(ages, aggregate, method="hmd_infant", sex=sex)[0].e
                equal = life_table(ages, unweighted)[0].e
                writer.writerow((country, sex, year, complete_e0, central, hmd, equal,
                                 "" if complete_e0 is not None else "rounded_zero_exposure_or_open_rate"))
                report["abridged"] += 1
        stage.replace(output)
    finally:
        if stage is not None:
            stage.unlink(missing_ok=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="action", required=True)
    tables = subs.add_parser("tables")
    tables.add_argument("--panel", type=Path, default=Path("data/wpp.parquet"))
    tables.add_argument("--out", type=Path, required=True)
    reference_cli = subs.add_parser("reference")
    reference_cli.add_argument("--raw", type=Path, default=Path("data/raw"))
    reference_cli.add_argument("--out", type=Path, required=True)
    stress_cli = subs.add_parser("stress")
    stress_cli.add_argument("--out", type=Path, required=True)
    stress_cli.add_argument("--tables", type=int, default=10_000)
    args = parser.parse_args()
    if args.action == "reference":
        summary = reference(args.raw, args.out)
        print(json.dumps({k: v for k, v in summary.items() if k != "failures"}, allow_nan=False))
        raise SystemExit(int(summary["failed"] > 0 or summary["compared_tables"] < 100))
    if args.action == "stress":
        stress(args.out, args.tables)
    else:
        print(json.dumps(schedule_tables(args.panel, args.out), allow_nan=False))
