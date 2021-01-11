"""Independently verify signed-off inputs and recompute demographic evidence."""

import argparse
from collections import Counter
from collections.abc import Sequence
import json
from math import exp, expm1, floor, fsum, isclose, isfinite, log
from pathlib import Path
import subprocess

from .acquire import ROOT, digest

VINTAGE = "WPP2024-original"
LAST_HISTORICAL = 2023
HORIZONS = (1, 5, 10, 20)
LEVELS = (0.50, 0.80, 0.95)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def close(a: float, b: float, label: str, *, absolute: float = 2e-8, relative: float = 3e-9) -> None:
    require(
        type(a) in (float, int) and type(b) in (float, int) and isfinite(a) and isfinite(b)
        and isclose(a, b, abs_tol=absolute, rel_tol=relative),
        f"{label} mismatch: {a!r} != {b!r}",
    )


def read_json(path: Path, max_bytes: int = 25_000_000):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= max_bytes, f"missing or oversized {path.name}")
    return json.loads(path.read_text())


def source_manifest(commit: str) -> dict:
    resolved = subprocess.check_output(["git", "rev-parse", "--verify", commit + "^{commit}"], cwd=ROOT, text=True).strip()
    rows = subprocess.check_output(["git", "ls-tree", "-r", "-z", resolved], cwd=ROOT).split(b"\0")
    files = {}
    for row in rows:
        if not row:
            continue
        metadata, path = row.split(b"\t", 1)
        mode, kind, blob = metadata.decode().split()
        require(kind == "blob", f"unsupported source input {path!r}")
        files[path.decode()] = {"mode": mode, "git_blob": blob}
    return {"commit": resolved, "files": files}


def manifest_files(directory: Path, *, max_files: int = 4096) -> dict:
    files = {}
    for path in sorted(directory.rglob("*")):
        if path == directory / "MANIFEST.json":
            continue
        require(not path.is_symlink(), "evidence contains a symbolic link")
        if path.is_file():
            require(len(files) < max_files and path.stat().st_size < 650_000_000, "bundle exceeds limits")
            files[path.relative_to(directory).as_posix()] = {"sha256": digest(path), "bytes": path.stat().st_size}
    return files


def verify_manifest(directory: Path) -> None:
    declared = read_json(directory / "MANIFEST.json")
    require(declared == manifest_files(directory), "bundle file membership or SHA-256 mismatch")


def grid_widths(grid: Sequence[Sequence[int | None]]) -> list[int | None]:
    require(1 <= len(grid) <= 151, "invalid age-grid length")
    previous = grid[0][0]
    widths = []
    for i, (start, end) in enumerate(grid):
        require(type(start) is int and start == previous and 0 <= start <= 150, "noncontiguous age grid")
        require((end is None and i == len(grid) - 1)
                or (type(end) is int and start < end <= 150 and i < len(grid) - 1), "invalid age width or tail")
        widths.append(None if end is None else end - start)
        previous = end
    return widths


def force_life_years(widths: Sequence[int | None], rates: Sequence[float], radix: float = 1.0):
    require(len(widths) == len(rates), "rate shape differs from age grid")
    require(all(type(r) in (float, int) and isfinite(r) and r >= 0 for r in rates) and rates[-1] > 0,
            "invalid central rate or open-age tail")
    terms = [float(m * width) for m, width in zip(rates[:-1], widths[:-1])]
    l = [radix * exp(-fsum(terms[:i])) for i in range(len(rates))]
    years = [alive * (-expm1(-m * width) / m if m else width)
             for width, m, alive in zip(widths[:-1], rates[:-1], l[:-1])]
    years.append(l[-1] / rates[-1])
    return l, years


def verify_table(rows: list[dict]) -> None:
    widths = grid_widths([(row["age"]["start"], row["age"]["end"]) for row in rows])
    rates = [row["rate"] for row in rows]
    l, years = force_life_years(widths, rates, radix=100_000)
    for i, (row, width, rate) in enumerate(zip(rows, widths, rates)):
        q = 1.0 if width is None else -expm1(-rate * width)
        require(0 <= row["q"] <= 1 and row["l"] >= 0 and row["d"] >= 0, "impossible survival or deaths")
        close(row["l"], l[i], "survivorship")
        close(row["q"], q, "death probability")
        close(row["d"], q * l[i], "death accounting")
        close(row["L"], years[i], "person-years lived")
        remaining = fsum(years[i:])
        close(row["T"], remaining, "remaining person-years")
        if l[i] > 1e-300:
            close(row["e"], remaining / l[i], "remaining expectancy")


def verify_stress(path: Path, *, count: int = 10_000) -> None:
    require(path.is_file() and not path.is_symlink() and path.stat().st_size < 500_000_000, "invalid stress output")
    seen = 0
    with path.open() as handle:
        for line in handle:
            seen += 1
            require(len(line) <= 100_000 and seen <= count, "unexpected stress work")
            record = json.loads(line)
            require(record["table"] == seen - 1 and record["seed"] == 9008 and record["method"] == "force",
                    "invalid stress identity")
            verify_table(record["rows"])
    require(seen == count, f"incomplete stress work: {seen} of {count}")


def _quantile(sorted_samples: list[float], probability: float) -> float:
    x = probability * (len(sorted_samples) - 1)
    low = floor(x)
    high = min(low + 1, len(sorted_samples) - 1)
    return sorted_samples[low] + (x - low) * (sorted_samples[high] - sorted_samples[low])


def verify_scoring(row: dict, widths: list[int | None], expected_rates, expected_exposure: float, draw_count: int) -> None:
    require(row["status"] == "historical_model_estimate" and row["vintage"] == VINTAGE
            and row["year"] <= LAST_HISTORICAL, "projection or unknown vintage used as outcome")
    require(row["unit"] == "deaths_per_person_year", "forecast denominator unit mismatch")
    require(len(row["actual_rates"]) == len(expected_rates), "outcome age support mismatch")
    for actual, expected in zip(row["actual_rates"], expected_rates):
        close(actual, float(expected), "observed rate against trusted panel", absolute=1e-11)
    close(row["exposure_person_years"], expected_exposure, "historical exposure")
    point = fsum(force_life_years(widths, row["predicted_rates"])[1])
    actual = fsum(force_life_years(widths, row["actual_rates"])[1])
    close(row["point_e0"], point, "point e0")
    close(row["actual_e0"], actual, "actual e0")
    lr = fsum((log(max(m, 1e-12)) - log(p)) ** 2 for m, p in zip(row["actual_rates"], row["predicted_rates"]))
    close(row["log_rmse"], (lr / len(widths)) ** 0.5, "rate log RMSE")
    samples = sorted(row["e0_draws"])
    require(len(samples) == draw_count and all(isfinite(x) and x > 0 for x in samples), "invalid prediction draws")
    wis = 0.5 * abs(_quantile(samples, 0.5) - actual)
    require(len(row["intervals"]) == 3, "missing interval levels")
    for level, estimate in zip(LEVELS, row["intervals"]):
        alpha = (1 - level) / 2
        lower, upper = _quantile(samples, alpha), _quantile(samples, 1 - alpha)
        interval_score = upper - lower + max(0, lower - actual, actual - upper) / alpha
        close(estimate["level"], level, "interval nominal level")
        close(estimate["low"], lower, "lower prediction interval")
        close(estimate["high"], upper, "upper prediction interval")
        close(estimate["width"], upper - lower, "interval width")
        close(estimate["score"], interval_score, "interval score")
        require(estimate["covered"] is (lower <= actual <= upper), "interval coverage mismatch")
        wis += alpha * interval_score
    close(row["wis"], wis / 3.5, "weighted interval score")


def _check_replay(result: dict, folder: Path, data_id: str, targets) -> None:
    import numpy as np
    from .learned import load, predict, torch

    checkpoint = folder / "checkpoint.pt"
    require(result["checkpoint"] == checkpoint.name and checkpoint.is_file(), "missing required checkpoint")
    model = load(checkpoint, data_id)
    require(model.support.origin == result["task"]["origin"] and model.spec.seed == result["task"]["seed"],
            "checkpoint origin or seed mismatch")
    require(model.spec.family == result["task"]["family"], "checkpoint family mismatch")
    training = [tuple(record[key] for key in ("country", "sex", "region")) for record in result["training_groups"]]
    require(training == [(g.country, g.sex, g.region) for g in model.support.groups], "checkpoint training geography mismatch")
    require(tuple(model.support.ages) == tuple(row[0] for row in result["age_grid"]), "checkpoint age support mismatch")
    raw = torch.load(checkpoint, map_location="cpu", weights_only=True)
    delta = sum(
        (raw["model"][name] - tensor).double().square().sum().item()
        for name, tensor in raw["initial_parameters"].items()
    ) ** 0.5
    require(delta > 0 and raw["training_diagnostics"]["max_gradient"] > 0, "empty or unchanged optimization")
    close(raw["training_diagnostics"]["parameter_l2_change"], delta, "checkpoint parameter change", absolute=1e-5, relative=1e-6)
    years = tuple(model.support.origin + h for h in result["horizons"])
    probes = (0, len(targets) // 2, len(targets) - 1)
    predictions = np.exp(predict(model, tuple(targets[i] for i in probes), years))
    by_id = {(row["country"], row["sex"], row["year"]): row for row in result["outcomes"]}
    for i, group in enumerate(targets[pos] for pos in probes):
        for j, year in enumerate(years):
            recorded = by_id[(group.country, group.sex, year)]["predicted_rates"]
            for expected, saved in zip(predictions[i, j], recorded):
                close(saved, float(expected), "frozen model replay", absolute=2e-7, relative=2e-6)


def verify_study(directory: Path, panel: Path, expected_commit: str) -> dict:
    from .cube import load_wpp

    # Model replay uses only the frozen inference entry point. Scoring below is independent.
    source = source_manifest(expected_commit)
    cube = load_wpp(panel)
    data_id = digest(panel)
    metadata = read_json(directory / "STUDY.json")
    require(metadata["commit"] == source["commit"] and metadata["clean_checkout"] is True, "study source mismatch or dirty checkout")
    require(metadata["panel_sha256"] == data_id, "study uses different panel bytes")
    require(metadata["protocol_sha256"] == digest(ROOT / "config/experiment-v1.json"), "study protocol mismatch")
    require(metadata["profile"] == "full", "diagnostic studies cannot satisfy full acceptance")
    cfg = read_json(ROOT / "config/experiment-v1.json")
    baseline_families = ("lee_carter", "count_trend", "apc", "coherent")
    learned_families = ("structured", "state_space")
    expected_tasks = {
        f"rolling.{origin}.{family}" for origin in cfg["origins"] for family in baseline_families
    } | {
        f"rolling.{origin}.{family}.{seed}" for origin in cfg["origins"] for family in learned_families for seed in cfg["seeds"]
    }
    for mode, labels in (("region", sorted({g.region for g in cube.groups})), ("country", cfg["transfer_countries"])):
        for label in labels:
            expected_tasks |= {f"{mode}.{cfg['transfer_origin']}.{f}.{label}" for f in baseline_families}
            expected_tasks |= {f"{mode}.{cfg['transfer_origin']}.{f}.{cfg['seeds'][0]}.{label}" for f in learned_families}
    for origin in cfg["ablation_origins"] + [2022]:
        variants = ("shock",) if origin == 2022 else ("age_basis", "hierarchy", "dynamics", "likelihood", "calibration")
        expected_tasks |= {f"ablation.{origin}.structured.{seed}.{v}" for v in variants for seed in cfg["seeds"]}
    require(len(metadata["tasks"]) == len(expected_tasks) and set(metadata["tasks"]) == expected_tasks, "study matrix mismatch")
    logged = (directory / "COMMANDS.jsonl").read_text().splitlines()
    successful = set()
    for line in logged:
        rec = json.loads(line)
        require(rec["task"] in expected_tasks and rec["requested"] == 1 and rec["seconds"] >= 0,
                "unsupported command log entry")
        if rec["exit"] == 0 and rec["completed"] == 1:
            successful.add(rec["task"])
    require(successful == expected_tasks, "study command log has missing completed runs")

    rates = cube.rates
    grid = [[age.start, age.end] for age in cube.ages]
    widths = grid_widths(grid)
    results = Counter()
    replays = 0
    for task_id in sorted(expected_tasks):
        folder = directory / task_id
        result = read_json(folder / "result.json")
        task = result["task"]
        identity = ".".join(str(x) for x in (
            task["mode"], task["origin"], task["family"], task["seed"], task["holdout"], task["ablation"],
        ) if x is not None and x != "")
        require(identity == task_id and result["age_grid"] == grid, "result task or age support mismatch")
        origin = task["origin"]
        horizons = tuple(h for h in HORIZONS if origin + h <= LAST_HISTORICAL)
        require(tuple(result["horizons"]) == horizons, "incorrect historical follow-up")
        training = set(range(len(cube.groups)))
        targets = training
        if task["mode"] in {"region", "country"}:
            targets = {i for i, group in enumerate(cube.groups) if getattr(group, task["mode"]) == task["holdout"]}
            training = training - targets
        groups = {(g["country"], g["sex"], g["region"]) for g in result["training_groups"]}
        expected_training = {(cube.groups[i].country, cube.groups[i].sex, cube.groups[i].region) for i in training}
        require(groups == expected_training and result["training_years"] == list(range(cube.years[0], origin + 1)),
                "chronology or geography split contamination")
        cells = {
            (cube.groups[i].country, cube.groups[i].sex, origin + h): (i, cube.years.index(origin + h))
            for i in targets for h in horizons
        }
        for outcome in result["outcomes"]:
            cell = outcome["country"], outcome["sex"], outcome["year"]
            require(cell in cells and outcome["origin"] == origin and outcome["horizon"] == cell[2] - origin,
                    "duplicate or ineligible forecast outcome")
            i, j = cells.pop(cell)
            require(outcome["region"] == cube.groups[i].region, "outcome geography mismatch")
            verify_scoring(outcome, widths, rates[i, j], float(cube.exposure[i, j].sum()), cfg["draws"])
            results["evaluated_strata"] += 1
        require(not cells, "missing eligible historical outcomes")
        if task["family"] in learned_families:
            _check_replay(result, folder, data_id, tuple(cube.groups[i] for i in sorted(targets)))
            replays += 1
        results["completed_comparisons"] += 1
        results["distinct_fits"] += int(task["ablation"] != "calibration")
        if task["mode"] == "rolling":
            results["rolling_fits"] += 1
    return dict(results) | {"checkpoint_replays": replays}


def verify_demo(directory: Path, expected_commit: str) -> dict:
    verify_manifest(directory)
    require(read_json(directory / "SOURCE_INPUTS.json") == source_manifest(expected_commit), "demo source identity mismatch")
    artifact = read_json(directory / "comparison.json")
    require(artifact["status"] == "simulation" and artifact["unit"] == "deaths_per_person_year",
            "invalid demo provenance or forecast unit")
    rows = artifact["life_table"]
    verify_table(rows)
    require(len(artifact["panel"]) == len(rows), "missing raw demonstration observations")
    for row, observation in zip(rows, artifact["panel"]):
        require(observation["status"] == "simulation", "projection or wrong provenance in demo observation")
        require(observation["exposure_unit"] == "person_years" and observation["exposure"] > 0,
                "death/exposure denominator unit mismatch")
        close(row["rate"], observation["deaths"] / observation["exposure"], "death/exposure rate")
        require(all(isfinite(rate) and rate >= 0 for rate in observation["cause_rates"]), "invalid cause hazard")
        close(fsum(observation["cause_rates"]), row["rate"], "cause hazards fail reconciliation", absolute=1e-12)
    close(artifact["e0"], rows[0]["e"], "reported life expectancy")
    return {"life_tables": 1, "age_rows": len(rows), "e0": rows[0]["e"], "profile": "synthetic_demo"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    stress = sub.add_parser("stress")
    stress.add_argument("file", type=Path)
    stress.add_argument("--count", type=int, default=10_000)
    for mode in ("study", "demo"):
        item = sub.add_parser(mode)
        item.add_argument("directory", type=Path)
        item.add_argument("--expected-commit", required=True)
        if mode == "study":
            item.add_argument("--panel", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "stress":
            verify_stress(args.file, count=args.count)
            summary = {"verified_tables": args.count}
        elif args.action == "study":
            summary = verify_study(args.directory, args.panel, args.expected_commit)
        else:
            summary = verify_demo(args.directory, args.expected_commit)
        print(json.dumps(summary, sort_keys=True))
    except (ArithmeticError, KeyError, OSError, TypeError, ValueError) as exc:
        parser.exit(1, f"Verification failed: {exc}\n")
