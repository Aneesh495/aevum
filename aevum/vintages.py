"""Compare aligned historical releases and run an as-of-2022 forecast."""

import argparse
import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import numpy as np

from .acquire import digest, get_source
from .baselines import FAMILIES, predict
from .cube import load_wpp
from .study import json_atomic
from .uncertainty import expectancy
from .wpp import connection, stage_pair

OLDER = "WPP2022-original"
CUTOFF = 2021
AVAILABLE = 2022
TARGET = 2023


def _extract(archive: ZipFile, filename: str, output: Path) -> None:
    member = archive.getinfo("CSV_FILES/" + filename)
    if member.is_dir() or member.file_size > 750_000_000:
        raise ValueError("unexpected WPP2022 archive member")
    amount = 0
    with archive.open(member) as handle, output.open("xb") as destination:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            amount += len(block)
            if amount > member.file_size:
                raise ValueError("WPP2022 member exceeded its declared size")
            destination.write(block)


def compare(raw: Path, panel: Path, output: Path) -> dict:
    archive = get_source(raw, "wpp2022", "WPP2022-CSV-data.zip")
    output.mkdir(parents=True, exist_ok=False)
    old_panel = output / "wpp2022.parquet"
    with TemporaryDirectory(dir=output) as tmp, ZipFile(archive) as zipped:
        paths = []
        for table in ("DeathsBySingleAgeSex", "PopulationExposureBySingleAgeSex"):
            filename = f"WPP2022_{table}_Medium_1950-2021.csv"
            dest = Path(tmp) / filename
            _extract(zipped, filename, dest)
            paths.append(dest)
        stage_pair(*paths, old_panel, 1970, CUTOFF, OLDER, *map(digest, paths))
    with connection() as con:
        mismatch = con.execute("""
            WITH a AS (SELECT DISTINCT country, location_id FROM read_parquet(?)),
                 b AS (SELECT DISTINCT country, location_id FROM read_parquet(?))
            SELECT country, a.location_id, b.location_id
            FROM a FULL JOIN b USING (country)
            WHERE a.location_id IS DISTINCT FROM b.location_id
        """, [str(old_panel), str(panel)]).fetchall()
    if mismatch:
        raise ValueError(f"territory identity changed between releases: {mismatch}")
    previous = load_wpp(old_panel, vintage=OLDER)
    latest = load_wpp(panel)
    aligned = latest.training(CUTOFF)
    if previous.groups != aligned.groups or previous.years != aligned.years or previous.ages != aligned.ages:
        raise ValueError("calendar, geography, age or sex support changed")
    before, after = (expectancy(cube.ages, cube.rates) for cube in (previous, aligned))
    changes = after - before
    with (output / "revisions.csv").open("x") as handle:
        writer = csv.writer(handle)
        writer.writerow(("country", "sex", "year", "wpp2022_e0", "wpp2024_e0", "change_years"))
        for i, group in enumerate(previous.groups):
            for j, year in enumerate(previous.years):
                writer.writerow((group.country, group.sex, year, before[i, j], after[i, j], changes[i, j]))
    endpoint = expectancy(latest.ages, latest.rates[:, latest.years.index(TARGET)])
    forecasts = {}
    with (output / "as-of-2022.csv").open("x") as handle:
        writer = csv.writer(handle)
        writer.writerow(("family", "country", "sex", "availability_year", "last_input_event_year", "target_year",
                         "prediction_input_vintage_2022", "prediction_input_vintage_2024", "target_e0_2024"))
        for family in FAMILIES:
            earlier, hindsight = [
                expectancy(cube.ages, np.exp(predict(family, cube, cube.groups, TARGET - CUTOFF).log_rates[:, -1]))
                for cube in (previous, aligned)
            ]
            forecasts[family] = {"mae_2022_vintage": float(np.abs(earlier - endpoint).mean()),
                                 "mae_2024_hindsight": float(np.abs(hindsight - endpoint).mean())}
            for i, group in enumerate(previous.groups):
                writer.writerow((family, group.country, group.sex, AVAILABLE, CUTOFF, TARGET,
                                 earlier[i], hindsight[i], endpoint[i]))
    summary = {
        "matched_country_sexes": len(previous.groups), "historical_years": len(previous.years),
        "historical_comparisons": int(changes.size), "median_absolute_revision_years": float(np.median(np.abs(changes))),
        "max_absolute_revision_years": float(np.max(np.abs(changes))), "availability_year": AVAILABLE,
        "last_input_event_year": CUTOFF, "target_year": TARGET, "scores": forecasts,
        "target_provenance": "historical_model_estimate", "target_vintage": latest.vintage,
        "interpretation": "one historical availability comparison; the 2023 target remains a later modeled estimate",
    }
    json_atomic(output / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=Path("data/raw"))
    parser.add_argument("--panel", type=Path, default=Path("data/wpp.parquet"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(compare(args.raw, args.panel, args.out), allow_nan=False))
