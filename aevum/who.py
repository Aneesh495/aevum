"""Stage a separate WHO ICD-10 national-registration cause panel."""

import argparse
import csv
from io import TextIOWrapper
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import pyarrow as pa

from .acquire import get_source, trusted_sources
from .causes import GROUPS, TAXONOMY
from .wpp import connection

MEMBER_LIMIT = 160_000_000
FIRST_YEAR = 2008
LAST_YEAR = 2022
AGE_LABELS = ("all", "0", "1", "2", "3", "4", *map(str, range(5, 100, 5)), "unknown")


def _member(archive: ZipFile):
    members = archive.infolist()
    if len(members) != 1 or members[0].is_dir() or members[0].file_size > MEMBER_LIMIT:
        raise ValueError("unexpected WHO archive shape or uncompressed size")
    return archive.open(members[0])


def _unpack(path: Path, dest: Path) -> None:
    with ZipFile(path) as archive, _member(archive) as stream, dest.open("xb") as handle:
        received = 0
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            received += len(chunk)
            if received > MEMBER_LIMIT:
                raise ValueError("WHO archive exceeds decompression limit")
            handle.write(chunk)


def country_names(raw: Path) -> pa.Table:
    source = get_source(raw, "who", "mort_country_codes.zip")
    with ZipFile(source) as archive, TextIOWrapper(_member(archive), encoding="cp1252") as handle:
        rows = list(csv.DictReader(handle))
    return pa.table({"country": [r["country"] for r in rows], "name": [r["name"] for r in rows]})


def stage(raw: Path, output: Path) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    archives = [f"morticd10_part{i}.zip" for i in range(3, 7)]
    population = get_source(raw, "who", "mort_pop.zip")
    age_map = pa.table({"idx": [f"Deaths{i}" for i in range(1, 27)], "age": AGE_LABELS})
    with TemporaryDirectory(dir=output.parent) as folder, connection() as con:
        temp = Path(folder)
        files = []
        for name in archives:
            local = temp / (name + ".csv")
            _unpack(get_source(raw, "who", name), local)
            files.append(str(local))
        _unpack(population, temp / "pop.csv")
        con.register("country_names", country_names(raw))
        con.register("age_map", age_map)
        con.execute("""
            CREATE TABLE codes AS
            SELECT Country AS country, Year::INT AS year,
                   CASE Sex WHEN '1' THEN 'male' WHEN '2' THEN 'female' ELSE 'unknown' END AS sex,
                   Cause AS code, COLUMNS('^Deaths[0-9]+$')::BIGINT
            FROM read_csv(?, delim=',', quote='"', escape='"', all_varchar=true)
            WHERE Admin1 IS NULL AND SubDiv IS NULL AND List = '104' AND Frmat = '00'
              AND Year::INT BETWEEN ? AND ?
        """, [files, FIRST_YEAR, LAST_YEAR])
        con.execute("""
            CREATE TABLE wide AS
            SELECT country, year, sex, code, age, n
            FROM (FROM codes UNPIVOT INCLUDE NULLS
                  (n FOR idx IN (COLUMNS('^Deaths[0-9]+$')))) AS u
            JOIN age_map USING(idx)
        """)
        con.execute("""
            CREATE TABLE ambiguous AS
            SELECT DISTINCT country, year, sex
            FROM (SELECT country, year, sex, code, count(*) AS n FROM codes GROUP BY ALL)
            WHERE n > 1
        """)
        if con.execute("SELECT count(*) FROM wide WHERE n < 0").fetchone()[0]:
            raise ValueError("negative registration counts")
        con.execute("""
            CREATE TABLE by_age AS WITH classified AS (
                SELECT w.*, CASE
                    WHEN code = 'AAA' THEN 'total'
                    WHEN NOT regexp_full_match(code, '[A-Z][0-9][0-9][0-9]?') THEN 'unsupported'
                    WHEN code[1] IN ('A','B') THEN 'infectious'
                    WHEN code BETWEEN 'C00' AND 'D489' THEN 'neoplasms'
                    WHEN code[1] = 'I' THEN 'circulatory'
                    WHEN code[1] = 'J' THEN 'respiratory'
                    WHEN code[1] IN ('V','W','X','Y') THEN 'external'
                    WHEN code[1] = 'U' THEN 'special'
                    WHEN code[1] = 'R' THEN 'unknown'
                    ELSE 'other'
                END AS cause
                FROM wide AS w ANTI JOIN ambiguous USING(country, year, sex)
            )
            SELECT country, year, sex, age,
                max(n) FILTER (WHERE cause = 'total') AS deaths,
                sum(n) FILTER (WHERE cause NOT IN ('total','unsupported')) AS coded,
                sum(n) FILTER (WHERE cause = 'unsupported') AS unsupported,
                coalesce(sum(n) FILTER (WHERE cause = 'infectious'), 0)::BIGINT AS infectious,
                coalesce(sum(n) FILTER (WHERE cause = 'neoplasms'), 0)::BIGINT AS neoplasms,
                coalesce(sum(n) FILTER (WHERE cause = 'circulatory'), 0)::BIGINT AS circulatory,
                coalesce(sum(n) FILTER (WHERE cause = 'respiratory'), 0)::BIGINT AS respiratory,
                coalesce(sum(n) FILTER (WHERE cause = 'external'), 0)::BIGINT AS external,
                coalesce(sum(n) FILTER (WHERE cause = 'special'), 0)::BIGINT AS special,
                coalesce(sum(n) FILTER (WHERE cause = 'other'), 0)::BIGINT AS other,
                coalesce(sum(n) FILTER (WHERE cause = 'unknown'), 0)::BIGINT AS unknown
            FROM classified GROUP BY country, year, sex, age
        """)
        con.execute("""
            CREATE TABLE pop AS WITH populations AS (
                SELECT Country AS country, Year::INT AS year,
                       CASE Sex WHEN '1' THEN 'male' WHEN '2' THEN 'female' END AS sex,
                       COLUMNS('^Pop[0-9]+$')::BIGINT
                FROM read_csv(?, delim=',', quote='"', escape='"', all_varchar=true)
                WHERE Admin1 IS NULL AND SubDiv IS NULL AND Frmat = '00'
            )
            SELECT country, year, sex, age, max(n) AS exposure
            FROM (FROM populations UNPIVOT INCLUDE NULLS
                  (n FOR idx IN (COLUMNS('^Pop[0-9]+$')))) AS p
            JOIN age_map AS a ON replace(p.idx, 'Pop', 'Deaths') = a.idx
            GROUP BY country, year, sex, age HAVING count(*) = 1
        """, [str(temp / "pop.csv")])
        vintage = trusted_sources()["who"]["vintage"]
        con.execute("""
            CREATE TABLE result AS
            SELECT a.country, c.name, a.year, a.sex, a.age,
                   a.deaths, CASE WHEN a.deaths >= coalesce(a.coded, 0)
                                  THEN (a.deaths - coalesce(a.coded, 0))::BIGINT END AS residual,
                   a.* EXCLUDE (country, year, sex, age, deaths, coded),
                   p.exposure, 'midyear_headcount_approximation' AS exposure_unit,
                   'registration_observation' AS status, 'unknown_registration_coverage' AS quality,
                   'national_tabulation' AS geography, '104' AS list, '00' AS age_format,
                   'WHO_MDB' AS source, ? AS vintage, ? AS taxonomy,
                   CASE WHEN a.deaths IS NULL THEN 'missing_all_cause_count'
                        WHEN a.coded > a.deaths THEN 'cause_count_exceeds_total'
                        WHEN a.sex = 'unknown' OR a.age = 'unknown' THEN 'unknown_sex_or_age'
                        ELSE NULL END AS exclusion
            FROM by_age AS a
            LEFT JOIN country_names AS c USING (country)
            LEFT JOIN pop AS p USING (country, year, sex, age)
        """, [vintage, TAXONOMY])
        summary = con.execute("""
            WITH slices AS (
                SELECT country, year, count(*) AS sexes
                FROM result WHERE age = 'all' AND sex IN ('male','female') AND exclusion IS NULL
                    AND deaths > 0 AND (residual + unknown)::DOUBLE / deaths <= 0.10
                GROUP BY country, year
            ), countries AS (
                SELECT country, count(*) AS years FROM slices WHERE sexes = 2 GROUP BY country
            )
            SELECT count(*) FILTER (WHERE years = ?), count(*) FROM countries
        """, [LAST_YEAR - FIRST_YEAR + 1]).fetchone()
        rows = con.execute("SELECT count(*) FROM result").fetchone()[0]
        invalid = con.execute("SELECT count(*) FROM result WHERE exclusion = 'cause_count_exceeds_total'").fetchone()[0]
        ambiguities = con.execute("SELECT count(*) FROM ambiguous").fetchone()[0]
        dest = temp / "who.parquet"
        con.sql("SELECT * FROM result ORDER BY country, year, sex, age").write_parquet(str(dest), compression="zstd")
        dest.replace(output)
    return {
        "rows": rows, "eligible_countries_all_15_years": summary[0], "eligible_countries_any_year": summary[1],
        "cause_count_excess_rows": invalid, "ambiguous_country_year_sexes": ambiguities,
        "first_year": FIRST_YEAR, "last_year": LAST_YEAR, "vintage": vintage, "taxonomy": TAXONOMY,
        "country_screen": "both sexes, national detailed 104 format 00, all-age unknown plus residual <=10%",
        "registration_completeness": "unverified",
        "cause_columns": GROUPS,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=Path("data/raw"))
    parser.add_argument("--out", type=Path, default=Path("data/who.parquet"))
    args = parser.parse_args()
    print(json.dumps(stage(args.raw, args.out), sort_keys=True))
