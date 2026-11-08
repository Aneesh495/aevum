"""Build paired, typed WPP death and person-year panels from pinned archives."""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb
import pyarrow as pa

from .acquire import ROOT, get_source, trusted_sources

VINTAGE = "WPP2024-original"
HISTORICAL_END = 2023
PREFIX = "WPP2024_"
SUFFIX = "_Medium_1950-2023.csv.gz"


def frame() -> tuple[dict[str, str], int, int]:
    config = json.loads((ROOT / "config/wpp-cohort.json").read_text())
    regions = {
        country: region for region, countries in config["regions"].items() for country in countries
    }
    if len(regions) != sum(map(len, config["regions"].values())):
        raise ValueError("overlapping region frame")
    return regions, config["first_year"], config["last_year"]


def connection():
    return duckdb.connect(config={"threads": 4, "memory_limit": "2GB"})


def stage_panel(raw: Path, dest: Path) -> dict:
    deaths = get_source(raw, "wpp", PREFIX + "DeathsBySingleAgeSex" + SUFFIX)
    exposures = get_source(raw, "wpp", PREFIX + "PopulationExposureBySingleAgeSex" + SUFFIX)
    checksums = trusted_sources()["wpp"]["files"]
    _, first, last = frame()
    return stage_pair(deaths, exposures, dest, first, last, VINTAGE, checksums[deaths.name], checksums[exposures.name])


def stage_pair(
    deaths: Path, exposures: Path, dest: Path, first: int, last: int, vintage: str,
    death_digest: str, exposure_digest: str,
) -> dict:
    regions, _, _ = frame()
    if not 1950 <= first <= last <= HISTORICAL_END:
        raise ValueError("invalid WPP historical panel window")
    frame_table = pa.table({"iso": list(regions), "region": list(regions.values())})
    dest.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=dest.parent) as tmp, connection() as con:
        con.register("frame", frame_table)
        for name, path, value in (("deaths", deaths, "Death"), ("exposures", exposures, "Pop")):
            con.execute(
                f"""
                CREATE TEMP TABLE {name} AS SELECT
                    LocID::INTEGER AS location_id, Location AS name, ISO3_code AS country,
                    region, "Time"::INTEGER AS year, AgeGrpStart::INTEGER AS age,
                    AgeGrpSpan::INTEGER AS width, {value}Male::DOUBLE * 1000 AS male,
                    {value}Female::DOUBLE * 1000 AS female
                FROM read_csv(?, all_varchar=true, sample_size=5000, delim=',', quote='"', escape='"')
                JOIN frame ON ISO3_code = iso
                WHERE "Time"::INTEGER BETWEEN ? AND ? AND Variant = 'Medium'
                """,
                [str(path), first, last],
            )
            invalid = con.execute(f"""
                SELECT count(*) FROM {name}
                WHERE location_id IS NULL OR name IS NULL OR age IS NULL OR width IS NULL
                   OR NOT ((age BETWEEN 0 AND 99 AND width = 1) OR (age = 100 AND width = -1))
                   OR female IS NULL OR male IS NULL OR NOT isfinite(female) OR NOT isfinite(male)
                   OR least(female, male) < 0
            """).fetchone()[0]
            if invalid:
                raise ValueError(f"{invalid} invalid WPP {name} rows")
        con.execute("""
            CREATE TEMP TABLE paired AS SELECT
                d.country, d.location_id, d.name, d.region, d.year, d.age AS age_start,
                CASE WHEN d.width > 0 THEN d.age + d.width END AS age_end,
                t.sex, t.deaths, t.exposure,
                'historical_model_estimate' AS status, 'modeled' AS quality,
                'person_years' AS exposure_unit, 'all' AS cause,
                'reported' AS availability, 'UN_WPP' AS source, ? AS vintage,
                CASE WHEN t.exposure = 0 THEN 'zero_rounded_exposure' END AS exclusion,
                ? AS death_sha256, ? AS exposure_sha256
            FROM deaths AS d
            JOIN exposures AS e USING (location_id, name, country, region, year, age, width)
            CROSS JOIN LATERAL (
                VALUES ('female', d.female, e.female), ('male', d.male, e.male)
            ) t(sex, deaths, exposure)
            """, [vintage, death_digest, exposure_digest])
        per_source = len(regions) * (last - first + 1) * 101
        for name in ("deaths", "exposures"):
            rows, unique, populations = con.execute(f"""
                SELECT count(*), count(DISTINCT (country,year,age)),
                       count(DISTINCT (country,location_id)) FROM {name}
            """).fetchone()
            if (rows, unique, populations) != (per_source, per_source, len(regions)):
                raise ValueError(f"WPP {name} archive does not match the declared frame")
        matched, rounded, contradictions, minimum_age = con.execute("""
            SELECT count(*), count(*) FILTER (WHERE exposure = 0),
                   count(*) FILTER (WHERE exposure = 0 AND deaths > 0),
                   min(age_start) FILTER (WHERE exposure = 0)
            FROM paired
        """).fetchone()
        if matched != 2 * per_source or contradictions:
            raise ValueError(f"WPP compatibility check failed: {matched} pairs and {contradictions} positive counts with zero exposure")
        staged = Path(tmp) / "panel.parquet"
        con.sql("SELECT * FROM paired ORDER BY country, sex, year, age_start").write_parquet(
            str(staged), compression="zstd"
        )
        staged.replace(dest)
    return {"country_count": len(regions), "first_year": first, "last_year": last,
            "sexes": 2, "age_intervals": 101, "rows": matched, "vintage": vintage,
            "rounded_zero_exposures": rounded, "youngest_zero_exposure_age": minimum_age}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=Path("data/raw"))
    parser.add_argument("--out", type=Path, default=Path("data/wpp.parquet"))
    args = parser.parse_args()
    print(json.dumps(stage_panel(args.raw, args.out), sort_keys=True))
