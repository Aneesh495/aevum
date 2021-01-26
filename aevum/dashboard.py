"""Local, bounded JSON service for the Aevum research dashboard."""

import argparse
from dataclasses import asdict
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from math import isfinite
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit

import numpy as np

from .acquire import ROOT, digest
from .ages import Age
from .causes import GROUPS, scenario
from .cube import Population, load_wpp
from .decomposition import finite_change
from .learned import load, predict
from .lifetable import life_table
from .uncertainty import Calibration, LEVELS, expectancy, interval
from .wpp import connection

LABELS = {
    "infectious": "Infectious", "neoplasms": "Neoplasms", "circulatory": "Circulatory",
    "respiratory": "Respiratory", "external": "External", "special": "Special codes",
    "other": "Other classified", "unknown": "Ill-defined", "residual": "Unreconciled",
}


def _one(query: dict[str, list[str]], key: str, default: str | None = None) -> str:
    values = query.get(key, [] if default is None else [default])
    if len(values) != 1 or not values[0] or len(values[0]) > 80:
        raise ValueError(f"invalid {key} parameter")
    return values[0]


def _sex(value: str) -> str:
    if value not in {"female", "male"}:
        raise ValueError("select female or male series")
    return value


class Laboratory:
    def __init__(self, panel: Path, causes: Path | None, checkpoint: Path | None):
        self.panel = panel
        self.panel_sha = digest(panel)
        self.cube = load_wpp(panel)
        self.causes = causes if causes and causes.is_file() else None
        self.forecast = None
        with connection() as con:
            self.countries = dict(con.execute(
                "SELECT DISTINCT country, name FROM read_parquet(?) ORDER BY name", [str(panel)]
            ).fetchall())
            self.cause_countries = {} if self.causes is None else dict(con.execute("""
                SELECT DISTINCT country, name FROM read_parquet(?)
                WHERE name IS NOT NULL AND age = 'all' AND exclusion IS NULL
                ORDER BY name
            """, [str(self.causes)]).fetchall())
        if checkpoint:
            model = load(checkpoint, self.panel_sha)
            origin = model.support.origin
            training = self.cube.training(origin, model.support.groups)
            if model.support.ages != tuple(age.start for age in training.ages):
                raise ValueError("forecast checkpoint age grid mismatch")
            years = tuple(range(origin + 1, origin + 21))
            log_rates = predict(model, training.groups, years)
            fitted = predict(model, training.groups, training.years)
            calibrator = Calibration.from_fit(fitted, training.deaths, training.exposure)
            paths = calibrator.paths(log_rates, draws=64, seed=731)
            e = expectancy(training.ages, paths)
            self.forecast = {
                "years": years, "origin": origin, "model": model.spec.family, "seed": model.spec.seed,
                "points": expectancy(training.ages, np.exp(log_rates)).tolist(),
                "bounds": {str(level): tuple(edge.tolist() for edge in interval(e, level)) for level in LEVELS},
                "groups": training.groups, "checkpoint_sha256": digest(checkpoint),
            }

    def catalogue(self) -> dict:
        return {
            "countries": [{"code": code, "name": name} for code, name in self.countries.items()],
            "years": self.cube.years, "vintage": self.cube.vintage,
            "panel_sha256": self.panel_sha,
            "cause_countries": [{"code": code, "name": name} for code, name in self.cause_countries.items()],
            "forecast": None if not self.forecast else {
                key: self.forecast[key] for key in ("model", "seed", "origin", "checkpoint_sha256")
            },
        }

    def _group(self, country: str, sex: str) -> tuple[int, Population]:
        for i, group in enumerate(self.cube.groups):
            if group.country == country and group.sex == _sex(sex):
                return i, group
        raise ValueError("population is outside the WPP study frame")

    @lru_cache(maxsize=128)
    def comparison(self, left: str, right: str, sex: str, year: int) -> dict:
        i, group = self._group(left, sex)
        j, peer = self._group(right, sex)
        if year not in self.cube.years:
            raise ValueError("year is outside the historical panel")
        year_pos = self.cube.years.index(year)
        rates = self.cube.rates
        records = []
        for position, target in ((i, group), (j, peer)):
            grid = rates[position]
            point = life_table(self.cube.ages, grid[year_pos])
            e0 = expectancy(self.cube.ages, grid)
            future = None
            if self.forecast and target in self.forecast["groups"]:
                f = self.forecast
                index = f["groups"].index(target)
                future = {
                    "years": f["years"], "point": f["points"][index],
                    "bounds": {level: (lower[index], upper[index]) for level, (lower, upper) in f["bounds"].items()},
                    "origin": f["origin"], "model": f["model"], "seed": f["seed"],
                }
            records.append({
                "country": target.country, "name": self.countries[target.country], "region": target.region,
                "year": year, "sex": sex, "e0": point[0].e, "table": [asdict(row) for row in point],
                "e0_history": e0.tolist(), "forecast": future,
                "exposure": self.cube.exposure[position, year_pos].tolist(),
                "deaths": self.cube.deaths[position, year_pos].tolist(),
            })
        return {
            "status": "historical_model_estimate", "quality": "modeled", "vintage": self.cube.vintage,
            "panel_sha256": self.panel_sha, "source": "UN World Population Prospects",
            "year": year, "years": self.cube.years, "ages": [asdict(age) | {"label": age.label} for age in self.cube.ages],
            "lexis": rates[i].tolist(), "series": records, "unit": "deaths_per_person_year",
        }

    @lru_cache(maxsize=64)
    def cohort(self, country: str, sex: str, birth: int) -> dict:
        self._group(country, sex)
        if not 1870 <= birth <= self.cube.years[-1]:
            raise ValueError("birth year outside the supported study window")
        with connection() as con:
            raw = con.execute("""
                SELECT year, age_start, deaths / nullif(exposure, 0) AS rate
                FROM read_parquet(?) WHERE country = ? AND sex = ? AND year - age_start = ?
                    AND age_end = age_start + 1
                ORDER BY age_start
            """, [str(self.panel), country, sex, birth]).fetchall()
        return {"birth": birth, "status": "period_surface_diagonal", "vintage": self.cube.vintage,
                "points": [{"year": year, "age": age, "rate": rate} for year, age, rate in raw],
                "truncated": True, "e0": None}

    @lru_cache(maxsize=96)
    def composition(self, country: str, sex: str, year: int, cause: str, factor: float, permit: bool) -> dict:
        if self.causes is None or country not in self.cause_countries:
            raise ValueError("WHO panel is unavailable for this selection")
        _sex(sex)
        if cause not in GROUPS[:-2] or not isfinite(factor) or not 0 <= factor <= 5 or not 2008 <= year <= 2022:
            raise ValueError("cause scenario outside supported bounds")
        columns = ", ".join(f'"{group}"' for group in GROUPS)
        with connection() as con:
            selected = con.execute(f"""
                SELECT age, deaths, exposure, exclusion, {columns}
                FROM read_parquet(?) WHERE country = ? AND sex = ? AND year = ?
            """, [str(self.causes), country, sex, year]).fetchall()
        rows = {row[0]: row[1:] for row in selected}
        total = rows.get("all")
        if total is None or total[2] is not None or not total[0]:
            return {"available": False, "message": "No eligible national registration tabulation for this selection."}
        view = {
            "available": True, "year": year, "sex": sex, "name": self.cause_countries[country],
            "status": "registration_observation", "vintage": "MDB-2026-02-23",
            "quality": "unknown_registration_coverage", "unit": "registered_deaths",
            "groups": [{"id": group, "label": LABELS[group], "count": value}
                       for group, value in zip(GROUPS, total[3:])],
            "all_deaths": total[0], "unknown_age_deaths": rows.get("unknown", (None,))[0],
            "scenario": None, "message": "Enable the matched midyear-headcount approximation to test a scenario.",
        }
        if not permit:
            return view
        starts = (0, 1, 2, 3, 4, *range(5, 100, 5))
        ages = tuple(Age(start, end) for start, end in zip(starts, (*starts[1:], None)))
        age_rows = [rows.get(str(start)) for start in starts]
        if any(row is None or row[2] is not None or row[1] is None or row[1] <= 0 for row in age_rows):
            return view | {"message": "Matched age-specific WHO midyear denominators are incomplete."}
        hazards = np.array([row[3:] for row in age_rows], dtype=float)
        hazards /= np.array([row[1] for row in age_rows])[:, None]
        before = scenario(ages, hazards, {})
        adjusted = hazards.copy()
        adjusted[:, GROUPS.index(cause)] *= factor
        try:
            after = scenario(ages, hazards, {cause: factor})
            decomposition = finite_change(ages, hazards, adjusted)
        except ValueError:
            return view | {"message": "This scenario has no finite, supported open-age tail."}
        return view | {"scenario": {
            "cause": cause, "factor": factor, "baseline_e0": before[0].e, "conditional_e0": after[0].e,
            "by_age": decomposition.contributions.sum(axis=1).tolist(),
            "ages": [age.label for age in ages], "residual_years": decomposition.residual,
            "unit": "deaths_per_midyear_headcount_approximation",
        }, "message": "Conditional calculation. Other cause rates are held fixed. Unknown-age deaths are kept outside the age profile."}


class BoundedServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 12

    def __init__(self, address, handler, laboratory):
        super().__init__(address, handler)
        self.slots = threading.BoundedSemaphore(8)
        self.laboratory = laboratory

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            request.settimeout(8)
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("dist/app.js", "text/javascript; charset=utf-8"),
}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, mime: str):
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, data):
        self._send(code, json.dumps(data, ensure_ascii=False, allow_nan=False).encode(), "application/json")

    def do_GET(self):
        if len(self.path) > 600:
            self._json(414, {"error": "request URI exceeds bound"})
            return
        url = urlsplit(self.path)
        if url.path in STATIC and not url.query:
            name, mime = STATIC[url.path]
            target = ROOT / "web" / name
            if not target.is_file():
                self._json(503, {"error": "dashboard assets need make web"})
                return
            self._send(200, target.read_bytes(), mime)
            return
        try:
            query = parse_qs(url.query, max_num_fields=10, keep_blank_values=True)
            lab = self.server.laboratory
            if url.path == "/api/catalogue":
                value = lab.catalogue()
            elif url.path == "/api/compare":
                value = lab.comparison(_one(query, "left"), _one(query, "right"),
                                       _one(query, "sex"), int(_one(query, "year")))
            elif url.path == "/api/cohort":
                value = lab.cohort(_one(query, "country"), _one(query, "sex"), int(_one(query, "birth")))
            elif url.path == "/api/causes":
                value = lab.composition(_one(query, "country"), _one(query, "sex"), int(_one(query, "year")),
                                        _one(query, "cause", "circulatory"), float(_one(query, "factor", "1")),
                                        _one(query, "approx", "0") == "1")
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "unknown route"})
                return
            self._json(200, value)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        except (ValueError, ArithmeticError) as exc:
            self._json(400, {"error": str(exc)})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=Path("data/wpp.parquet"))
    parser.add_argument("--causes", type=Path, default=Path("data/who.parquet"))
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--port", default=8078, type=int)
    args = parser.parse_args()
    lab = Laboratory(args.panel, args.causes, args.checkpoint)
    with BoundedServer(("127.0.0.1", args.port), Handler, lab) as server:
        print(f"Aevum serving http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
