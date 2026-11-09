"""Derive the focused research figures from the archived campaign."""

import argparse
from collections import defaultdict
import csv
from html import escape
import json
from pathlib import Path
from statistics import mean, median

from aevum.acquire import digest
from aevum.forecast import export
from aevum.results import summarize
from aevum.study import json_atomic
from aevum.verify import read_json, require, verify_manifest


def _csv(path: Path) -> list[dict]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def _records(path: Path):
    with path.open() as handle:
        for line in handle:
            yield json.loads(line)


def _bars(path: Path, title: str, units: str, points: list[tuple[str, float]]) -> None:
    width, left, right = 760, 275, 660
    height = 96 + 27 * len(points)
    values = [value for _, value in points]
    low, high = min(0.0, min(values)), max(0.0, max(values))
    span = high - low or 1.0
    zero = left - low * (right - left) / span
    body = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img">',
        f'<title>{escape(title)}</title><rect width="100%" height="100%" fill="#fbfaf4"/>',
        f'<text x="24" y="32" font-family="Georgia, serif" font-size="22" fill="#163034">{escape(title)}</text>',
        f'<text x="24" y="54" font-family="sans-serif" font-size="13" fill="#48615d">{escape(units)}</text>',
        f'<path d="M{zero:.2f} 67V{height - 14}" stroke="#82958c"/>',
    ]
    for i, (label, value) in enumerate(points):
        end = left + (value - low) * (right - left) / span
        x = min(zero, end)
        y = 74 + i * 27
        color = "#a84b36" if value < 0 else "#187765"
        body.extend([
            f'<text x="24" y="{y + 12}" font-family="sans-serif" font-size="14" fill="#163034">{escape(label)}</text>',
            f'<rect x="{x:.2f}" y="{y}" width="{abs(end - zero):.2f}" height="15" fill="{color}"/>',
            f'<text x="738" y="{y + 12}" text-anchor="end" font-family="monospace" font-size="12" fill="#163034">{value:.5g}</text>',
        ])
    path.write_text("\n".join([*body, "</svg>"]) + "\n")


def render(base: Path, output: Path, run: str) -> dict:
    """Return the figure index. Aggregate WHO results before writing plot data."""
    figures = {}
    manifest = read_json(base / "MANIFEST.json")

    def emit(key, title, units, points, sources, scope):
        require(bool(points), f"{key} has no plotted rows")
        source_receipts = {name: manifest[name]["sha256"] for name in sorted(sources)}
        with (output / f"{key}.csv").open("w", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(["run", "category", "value", "unit"])
            writer.writerows((run, label, value, units) for label, value in points)
        _bars(output / f"{key}.svg", title, units, points)
        figures[key] = {"title": title, "scope": scope, "source_artifacts": source_receipts}

    life = _csv(base / "life-tables.csv")
    norway = {int(row["year"]): row for row in life if row["country"] == "NOR" and row["sex"] == "female"}
    emit("01-exposure", "Norway's change depends on the exposure weights", "Change in period e₀, years",
         [(label, float(norway[1988][col]) - float(norway[1987][col])) for label, col in
          (("Exposure-weighted rates", "e0_abridged_90"), ("Equal weight per single age", "e0_unweighted_bands"))],
         ["life-tables.csv"], "WPP 2024, Norwegian female series, 1987–1988, age bands through 90+. Deterministic contrasts.")

    by_year = defaultdict(list)
    for row in _records(base / "reference/comparison.jsonl"):
        by_year[row["key"][2]].append(row["max_abs_error"]["ex"])
    emit("02-reconstruction", "Published life-table reconstruction error", "Maximum absolute e(x) error, years",
         [(str(year), max(rows)) for year, rows in sorted(by_year.items())],
         ["reference/comparison.jsonl", "reference/summary.json", "reference/published.csv"],
         "Eligible complete WPP 2024 tables, both sexes, ages 0–100+ where published l(x) ≥ 1. Synthetic radix 100,000.")

    emit("03-infant-tail", "Life expectancy sensitivity to age assumptions", "Maximum absolute difference in e₀, years",
         [("HMD infant vs constant force", max(abs(float(r["e0_hmd_infant"]) - float(r["e0_abridged_90"])) for r in life)),
          ("Complete vs abridged", max(abs(float(r["e0_complete"]) - float(r["e0_abridged_90"])) for r in life if r["e0_complete"]))],
         ["life-tables.csv"], "WPP 2024, 42 countries, 1970–2023, both sexes. Deaths per matched person-year. Deterministic maxima.")

    cohort_path = output / "04-cohort-forecast.json"
    export(base / "wpp.parquet", base / "serving.pt", cohort_path, ["JPN", "USA"], 20, birth=1950, attained_age=20)
    cohort = read_json(cohort_path)
    require(cohort["panel_sha256"] == digest(base / "wpp.parquet"), "cohort panel mismatch")
    emit("04-cohort", "Remaining years for the 1950 birth cohort", "Point estimate of remaining years at age 20",
         [(f'{r["country"]} {r["sex"]}', r["point_years"]) for r in cohort["cohort_projections"]],
         ["wpp.parquet", "serving.pt"], "WPP 2024 single-age history through 2023, then forecast age bands through 90+ in 2040. Conditional on survival to age 20.")
    figures["04-cohort"]["derived_artifact"] = cohort_path.name

    synthetic = _csv(output / "synthetic.csv")
    emit("05-counts", "Count and log-rate fits in known-truth panels", "Five-year e₀ MAE, years",
         [(f'{r["regime"].replace("_", " ")} / {r["family"].replace("_", " ")}', float(r["mean_absolute_e0_error"]))
          for r in synthetic], ["recovery.jsonl"],
         "200 synthetic panels, 100 per regime, four populations per panel, ages through 90+. Deaths per person-year.")

    apc = []
    for path in sorted((base / "study").glob("rolling.*.apc/result.json")):
        fit = read_json(path)
        apc.append((str(fit["task"]["origin"]),
                    max(x["alternative_forecast_log_rate_rmse"] for x in fit["training"]["fits"])))
    emit("06-apc", "APC sensitivity to extrapolating the cohort term", "Maximum log-rate RMSE between two continuation rules",
         apc, [f"study/rolling.{origin}.apc/result.json" for origin, _ in apc],
         "WPP 2024 rolling origins, 42 countries, both sexes, 20 age bands. Model contrast across available forecasts.")

    strata = _csv(output / "strata.csv")
    rolling = {(r["family"], int(r["horizon"])): r for r in strata if r["mode"] == "rolling" and r["stratum"] == "all"}
    def scope(paths):
        return [p.relative_to(base).as_posix() for p in sorted(paths)]

    emit("07-coherence", "Coherence helps at short horizons", "Weighted interval score, e₀ years",
         [(f'{family.replace("_", " ")} / {h}y', float(rolling[family, h]["wis_e0"]))
          for h in (1, 20) for family in ("coherent", "count_trend")],
         scope(p for family in ("coherent", "count_trend") for p in (base / "study").glob(f"rolling.*.{family}/result.json")),
         "WPP 2024, 42 countries, both sexes, 20 age bands, deaths per person-year. All eligible rolling origins at each horizon.")

    ablations = [r for r in strata if r["mode"] == "ablation" and r["horizon"] == "1"
                 and r["stratum"] != "shock" and "/" not in r["stratum"]]
    matched = sorted(p for origin in (2003, 2019) for p in (base / "study").glob(f"rolling.{origin}.structured.*/result.json"))
    original = mean(row["wis"] for p in matched for row in read_json(p)["outcomes"] if row["horizon"] == 1)
    emit("08-learned", "Structured forecast ablations", "One-year weighted interval score, e₀ years",
         [("Full structured model", original),
          *((r["stratum"].replace("_", " "), float(r["wis_e0"])) for r in ablations)],
         scope([*matched, *(p for origin in (2003, 2019) for p in (base / "study").glob(f"ablation.{origin}.*/result.json"))]),
         "WPP 2024, 42 countries, both sexes, 20 age bands, deaths per person-year. Matched 2003 and 2019 origins across all seeds.")

    shocks = [r for r in strata if r["mode"] == "rolling" and r["category"] == "shock" and r["horizon"] == "1"
              and r["family"] == "coherent" and "/" not in r["stratum"]]
    emit("09-shocks", "Coherent forecast coverage during the shock", "Observed coverage of nominal 80% intervals, percent",
         [(r["stratum"], 100 * float(r["coverage_80"])) for r in shocks],
         scope((base / "study").glob("rolling.*.coherent/result.json")),
         "WPP 2024, one-year forecasts, both sexes, 42 countries and 20 age bands. Retrospective pandemic targets versus other years.")

    transfer = []
    for mode in ("country", "region"):
        for path in sorted((base / "study").glob(f"{mode}.*/result.json")):
            row = read_json(path)
            train = row["training"]
            if "held_out_mae_trained" in train:
                delta = train["held_out_mae_trained"] - train["held_out_mae_untrained"]
                if delta >= 0:
                    task = row["task"]
                    transfer.append((f'{task["holdout"]} / {task["family"].replace("_", " ")}', delta, path))
    emit("10-transfer", "Transfer fits that regressed from initialization", "Increase in held-out e₀ MAE, years",
         [(name, delta) for name, delta, _ in transfer], scope(path for _, _, path in transfer),
         "WPP 2024, 2013 origin, both sexes, horizons 1/5/10, 20 age bands. Selected nonimproving fits from the full transfer matrix.")

    revision = _csv(base / "vintages/as-of-2022.csv")
    changes = defaultdict(list)
    for row in revision:
        y = float(row["target_e0_2024"])
        changes[row["family"]].append(abs(float(row["prediction_input_vintage_2024"]) - y)
                                      - abs(float(row["prediction_input_vintage_2022"]) - y))
    emit("11-vintage", "Training vintage changes 2023 forecast error", "MAE change with revised input, e₀ years",
         [(family.replace("_", " "), mean(errors)) for family, errors in sorted(changes.items())],
         ["vintages/as-of-2022.csv", "vintages/revisions.csv"],
         "42 countries, both sexes, 2023 target, historical cutoff 2021, age bands through 90+. Only the 2022 inputs were available at origin.")

    errors = defaultdict(list)
    for row in _csv(base / "cause/share_forecast.csv"):
        errors[row["year"]].append(abs(float(row["observed_share"]) - float(row["forecast_share"])))
    emit("12-causes", "Cause-share error rises after 2019", "Mean absolute cause-share error, percentage points",
         [(year, 100 * mean(values)) for year, values in sorted(errors.items())],
         ["cause/share_forecast.csv", "cause/quality.csv"],
         "WHO February 2026 archive, 21 screened countries, both sexes, all ages. Shares conditional on realized all-cause registered deaths.")

    scenario = [float(r["e0_delta"]) for r in _csv(base / "cause/conditional_scenarios.csv")]
    emit("13-scenarios", "Conditional expectancy gain after halving circulatory mortality", "Change in period e₀, years",
         [("Minimum", min(scenario)), ("Median", median(scenario)), ("Maximum", max(scenario))],
         ["cause/conditional_scenarios.csv", "cause/denominator_sensitivity.csv"],
         "WHO February 2026 archive, 22 matched 2019 population-sex slices, 24 age bins. Approximate midyear denominators and fixed competing rates.")

    emit("14-calibration", "Coherent forecast coverage across horizons", "Observed coverage of nominal 80% intervals, percent",
         [(f"{h} year", 100 * float(rolling["coherent", h]["coverage_80"])) for h in (1, 5, 10, 20)],
         scope((base / "study").glob("rolling.*.coherent/result.json")),
         "WPP 2024, 42 countries, both sexes, 20 age bands. Empirical coverage on the eligible retrospective outcomes.")
    return figures


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    base = args.candidate
    verify_manifest(base)
    summarize(base / "study", args.output, life_tables=base / "life-tables.csv", recovery=base / "recovery.jsonl",
              reference=base / "reference/summary.json", browser=base / "browser/browser.json")
    json_atomic(args.output / "figure-index.json", render(base, args.output, base.name))
