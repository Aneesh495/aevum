"""Summarize raw forecast strata and emit figure data for the research paper."""

import argparse
from collections import defaultdict
import csv
from html import escape
import json
from pathlib import Path
from statistics import mean

import numpy as np

from .study import json_atomic


def _observations(directory: Path):
    for folder in sorted(directory.iterdir()):
        path = folder / "result.json"
        if not path.is_file():
            continue
        result = json.loads(path.read_text())
        task = result["task"]
        for row in result["outcomes"]:
            yield task, row


def _metrics(row: dict) -> dict[str, float]:
    actual, predicted = row["actual_e0"], row["point_e0"]
    values = {"mae_e0": abs(actual - predicted), "bias_e0": predicted - actual,
              "wis_e0": row["wis"], "log_rate_rmse": row["log_rmse"]}
    for part in row["intervals"]:
        level = round(100 * part["level"])
        values[f"coverage_{level}"] = int(part["covered"])
        values[f"width_{level}"] = part["width"]
        values[f"score_{level}"] = part["score"]
    return values


def _paired(data: dict, h: int, best_baseline: str, learned: str, seed: int = 9001) -> dict:
    effects = []
    for country in sorted({key[0] for key in data}):
        base = data.get((country, h, best_baseline))
        alt = data.get((country, h, learned))
        if base and alt:
            effects.append(mean(alt) - mean(base))
    rng = np.random.default_rng(seed)
    bootstrap = np.mean(rng.choice(effects, size=(2000, len(effects))), axis=1)
    return {
        "baseline": best_baseline, "learned": learned, "horizon": h, "countries": len(effects),
        "wis_difference": mean(effects), "country_block_95": np.quantile(bootstrap, [0.025, 0.975]).tolist(),
        "interpretation": "descriptive paired bootstrap after selecting the best methods on this matrix",
    }


def _table_csv(path: Path, records: list[dict]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def _chart(path: Path, scores: list[dict], title: str, metric: str, label: str) -> None:
    models = sorted({item["family"] for item in scores})
    horizons = sorted({item["horizon"] for item in scores})
    colors = ["#213c53", "#ca644a", "#6d8c45", "#507fa6", "#9d668c", "#187765"]
    width, height = 780, 400
    left, right, top, bottom = 73, 585, 55, 342
    limit = max(item[metric] for item in scores) * 1.1
    xp = lambda value: left + (value - horizons[0]) * (right - left) / max(1, horizons[-1] - horizons[0])
    yp = lambda value: bottom - value * (bottom - top) / limit
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img">',
             f'<title>{escape(title)}</title><rect width="100%" height="100%" fill="#fbfaf4"/>',
             f'<text x="35" y="33" font-family="Georgia" font-size="23" fill="#163034">{escape(title)}</text>']
    for value in np.linspace(0, limit, 6):
        y = yp(value)
        parts.append(f'<path d="M{left} {y}H{right}" stroke="#d1dbd4"/>')
        parts.append(f'<text x="{left - 9}" y="{y + 4}" text-anchor="end" font-family="monospace" font-size="12">{value:.2f}</text>')
    for horizon in horizons:
        parts.append(f'<text x="{xp(horizon)}" y="{bottom + 24}" text-anchor="middle" font-family="monospace" font-size="12">{horizon}y</text>')
    for i, model in enumerate(models):
        group = sorted((row for row in scores if row["family"] == model), key=lambda x: x["horizon"])
        color = colors[i]
        points = " ".join(f'{xp(x["horizon"]):.1f},{yp(x[metric]):.1f}' for x in group)
        parts.append(f'<polyline points="{points}" stroke="{color}" fill="none" stroke-width="3"/>')
        for row in group:
            parts.append(f'<circle cx="{xp(row["horizon"]):.1f}" cy="{yp(row[metric]):.1f}" r="3.5" fill="{color}"/>')
        y = 80 + 26 * i
        parts.append(f'<path d="M615 {y - 3}h22" stroke="{color}" stroke-width="3"/>')
        parts.append(f'<text x="647" y="{y}" font-family="sans-serif" font-size="13">{escape(model.replace("_", " "))}</text>')
    parts.append(f'<text x="{left}" y="390" font-family="monospace" font-size="12">{escape(label)}</text></svg>')
    path.write_text("\n".join(parts) + "\n")


def summarize(study: Path, output: Path, *, life_tables: Path, recovery: Path, reference: Path, browser: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    aggregate = defaultdict(list)
    by_country = defaultdict(list)
    fit_diagnostics = []
    for task, row in _observations(study):
        modes = [("all", "all"), ("region", row["region"]), ("sex", row["sex"]),
                 ("shock", "2020-2021" if row["shock"] else "other"),
                 ("exposure", "below-3M" if row["sparse"] else "at-least-3M")]
        if task["ablation"]:
            modes = [("variant", task["ablation"])]
        if task["holdout"]:
            modes = [("holdout", task["holdout"])]
        scores = _metrics(row)
        family = task["family"]
        for category, stratum in modes:
            key = task["mode"], family, row["horizon"], category, stratum
            aggregate[key].append(scores)
            if task["seed"] is not None:
                aggregate[(task["mode"], family, row["horizon"], category, stratum + f"/seed-{task['seed']}")].append(scores)
        if task["mode"] == "rolling":
            by_country[(row["country"], row["horizon"], family)].append(row["wis"])
    records = []
    for key, values in sorted(aggregate.items()):
        mode, family, horizon, category, stratum = key
        records.append({"mode": mode, "family": family, "horizon": horizon, "category": category,
                        "stratum": stratum, "n": len(values),
                        **{metric: mean(row[metric] for row in values) for metric in values[0]}})
    _table_csv(output / "strata.csv", records)
    _table_csv(output / "country_errors.csv", [
        {"country": country, "horizon": horizon, "family": family, "count": len(values), "wis_e0": mean(values)}
        for (country, horizon, family), values in sorted(by_country.items())
    ])
    rolling = [row for row in records if row["mode"] == "rolling" and row["stratum"] == "all"]
    horizons = sorted({row["horizon"] for row in rolling})
    paired = []
    for horizon in horizons:
        candidates = [row for row in rolling if row["horizon"] == horizon]
        baseline = min((x for x in candidates if x["family"] not in {"structured", "state_space"}), key=lambda r: r["wis_e0"])
        learned = min((x for x in candidates if x["family"] in {"structured", "state_space"}), key=lambda r: r["wis_e0"])
        paired.append(_paired(by_country, horizon, baseline["family"], learned["family"]))
    _chart(output / "forecast-wis.svg", rolling, "Forecast error across horizons", "wis_e0",
           "Weighted interval score in period life-expectancy years")
    _chart(output / "interval-width.svg", rolling, "Width of the central 80% interval", "width_80",
           "Mean width in period life-expectancy years")
    for path in sorted(study.glob("*/result.json")):
        result = json.loads(path.read_text())
        training = result["training"]
        if "held_out_mae_trained" in training:
            fit_diagnostics.append({
                "run": path.parent.name, "family": result["task"]["family"],
                "trained": training["held_out_mae_trained"], "untrained": training["held_out_mae_untrained"],
                "training_objective": training.get("training", {}).get("final_objective"),
            })
    _table_csv(output / "trained-comparison.csv", fit_diagnostics)
    ages = []
    with life_tables.open() as handle:
        for row in csv.DictReader(handle):
            main = float(row["e0_abridged_90"])
            ages.append({
                "country": row["country"], "sex": row["sex"], "year": int(row["year"]),
                "weighted_e0": main,
                "infant_delta": float(row["e0_hmd_infant"]) - main,
                "unweighted_delta": float(row["e0_unweighted_bands"]) - main,
                "complete_delta": float(row["e0_complete"]) - main if row["e0_complete"] else None,
            })
    _table_csv(output / "age_assumptions.csv", ages)
    synthetic = defaultdict(list)
    with recovery.open() as handle:
        for line in handle:
            case = json.loads(line)
            for family, outcome in case["models"].items():
                synthetic[(case["regime"], family)].append(outcome)
    synthetic_results = [
        {"regime": regime, "family": family, "n": len(values),
         **{metric: mean(row[metric] for row in values)
            for metric in ("mean_absolute_e0_error", "coverage_80", "width_80", "wis", "log_rate_rmse")}}
        for (regime, family), values in sorted(synthetic.items())
    ]
    _table_csv(output / "synthetic.csv", synthetic_results)
    result = {
        "study": json.loads((study / "STUDY.json").read_text()),
        "counts": json.loads((study / "SUMMARY.json").read_text()),
        "rolling": rolling, "paired": paired,
        "training_wins": sum(item["trained"] < item["untrained"] for item in fit_diagnostics),
        "training_comparisons": len(fit_diagnostics),
        "age_complete": sum(item["complete_delta"] is not None for item in ages),
        "age_abridged": len(ages),
        "unweighted_median_abs_delta": float(np.median([abs(row["unweighted_delta"]) for row in ages])),
        "infant_max_abs_delta": max(abs(item["infant_delta"]) for item in ages),
        "max_abridged_complete_abs_delta": max(abs(item["complete_delta"]) for item in ages if item["complete_delta"] is not None),
        "references": json.loads(reference.read_text()), "browser": json.loads(browser.read_text()),
        "synthetic": synthetic_results,
        "shock": [r for r in records if r["mode"] == "rolling" and r["category"] == "shock" and "/seed-" not in r["stratum"]],
    }
    json_atomic(output / "summary.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("study", "output", "life-tables", "recovery", "reference", "browser"):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    summarize(args.study, args.output, life_tables=args.life_tables, recovery=args.recovery,
              reference=args.reference, browser=args.browser)
