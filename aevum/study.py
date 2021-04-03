"""Run source-identified rolling-origin and transfer experiments."""

import argparse
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from math import isfinite
import shutil
import os
from pathlib import Path
import platform
import re
import subprocess
from tempfile import NamedTemporaryFile
import time

import numpy as np

from . import baselines, learned
from .acquire import ROOT, digest
from .cube import Cube, Population, load_wpp
from .uncertainty import Calibration, LEVELS, expectancy, interval, interval_score, weighted_interval_score


@dataclass(frozen=True)
class Task:
    mode: str
    origin: int
    family: str
    seed: int | None = None
    holdout: str = ""
    ablation: str = ""

    @property
    def identity(self) -> str:
        return ".".join(str(part) for part in (
            self.mode, self.origin, self.family, self.seed, self.holdout, self.ablation
        ) if part is not None and part != "")


def protocol() -> dict:
    return json.loads((ROOT / "config/experiment-v1.json").read_text())


PROFILES = ("baselines", "diagnostic", "full")


def plan(cube: Cube, profile: str) -> Iterator[Task]:
    if profile not in PROFILES:
        raise ValueError("unrecognized experiment profile")
    cfg = protocol()
    if profile != "full":
        yield from (Task("rolling", 2019, family) for family in baselines.FAMILIES)
        if profile == "diagnostic":
            yield Task("rolling", 2019, "structured", cfg["seeds"][0])
            yield Task("rolling", 2019, "state_space", cfg["seeds"][0])
        return
    for origin in cfg["origins"]:
        yield from (Task("rolling", origin, family) for family in baselines.FAMILIES)
        for family in ("structured", "state_space"):
            yield from (Task("rolling", origin, family, seed) for seed in cfg["seeds"])
    for mode, labels in (
        ("region", sorted({group.region for group in cube.groups})),
        ("country", cfg["transfer_countries"]),
    ):
        for label in labels:
            for family in baselines.FAMILIES:
                yield Task(mode, cfg["transfer_origin"], family, holdout=label)
            for family in ("structured", "state_space"):
                yield Task(mode, cfg["transfer_origin"], family, cfg["seeds"][0], holdout=label)
    for origin in cfg["ablation_origins"] + [2022]:
        ablations = ("shock",) if origin == 2022 else (
            "age_basis", "hierarchy", "dynamics", "likelihood", "calibration"
        )
        for ablation in ablations:
            for seed in cfg["seeds"]:
                yield Task("ablation", origin, "structured", seed, ablation=ablation)


def json_atomic(path: Path, value) -> None:
    stage = None
    try:
        with NamedTemporaryFile(dir=path.parent, delete=False, mode="w") as handle:
            stage = Path(handle.name)
            json.dump(value, handle, allow_nan=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        stage.replace(path)
    finally:
        if stage is not None:
            stage.unlink(missing_ok=True)


def _targets(cube: Cube, task: Task) -> tuple[tuple[Population, ...], tuple[Population, ...]]:
    if task.mode not in {"region", "country"}:
        return cube.groups, cube.groups
    targets = tuple(group for group in cube.groups if getattr(group, task.mode) == task.holdout)
    training = tuple(group for group in cube.groups if group not in targets)
    if not targets or not training:
        raise ValueError("empty holdout or training population")
    return training, targets


def _calibration(train: Cube, targets: tuple[Population, ...], fitted: np.ndarray, enabled: bool) -> Calibration:
    fitted_cal = Calibration.from_fit(fitted, train.deaths, train.exposure)
    innovations, counts = [], []
    for target in targets:
        if target in train.groups:
            i = train.groups.index(target)
            innovations.append(fitted_cal.innovations[i])
            counts.append(fitted_cal.endpoint_count_sd[i])
        else:
            peers = [i for i, group in enumerate(train.groups) if group.sex == target.sex]
            innovations.append(fitted_cal.innovations[peers].mean(axis=0))
            counts.append(np.median(fitted_cal.endpoint_count_sd[peers], axis=0))
    innovations = np.stack(innovations)
    return Calibration(
        innovations if enabled else np.zeros_like(innovations), np.stack(counts), fitted_cal.endpoint_exposure_sd,
    )


def _score(
    cube: Cube, task: Task, targets: tuple[Population, ...], horizons: tuple[int, ...],
    forecast: np.ndarray, draws: np.ndarray, support: tuple[str, ...],
) -> list[dict]:
    dataset_positions = [cube.groups.index(group) for group in targets]
    years = [cube.years.index(task.origin + h) for h in horizons]
    requested = [h - 1 for h in horizons]
    truth = cube.rates[np.ix_(dataset_positions, years)]
    predicted = np.exp(forecast[:, requested])
    true_e0 = expectancy(cube.ages, truth)
    forecast_e0 = expectancy(cube.ages, predicted)
    sampled_e0 = expectancy(cube.ages, draws[:, :, requested])
    weighted = weighted_interval_score(sampled_e0, true_e0)
    low_high = {level: interval(sampled_e0, level) for level in LEVELS}
    exposures = cube.exposure[np.ix_(dataset_positions, years)].sum(axis=-1)
    log_rmse = np.sqrt(np.mean((np.log(np.maximum(truth, 1e-12)) - np.log(predicted)) ** 2, axis=-1))
    rows = []
    for i, group in enumerate(targets):
        for j, h in enumerate(horizons):
            actual = float(true_e0[i, j])
            endpoint = task.origin + h
            bounds = []
            for level, (low, high) in low_high.items():
                lower, upper = float(low[i, j]), float(high[i, j])
                score = interval_score(np.array(lower), np.array(upper), np.array(actual), level)
                bounds.append({"level": level, "low": lower, "high": upper, "covered": lower <= actual <= upper,
                               "width": upper - lower, "score": float(score)})
            rows.append({
                **asdict(group), "origin": task.origin, "horizon": h, "year": endpoint,
                "support": support[i], "status": cube.status.value, "vintage": cube.vintage,
                "unit": "deaths_per_person_year", "actual_e0": actual, "point_e0": float(forecast_e0[i, j]),
                "actual_rates": truth[i, j].tolist(), "predicted_rates": predicted[i, j].tolist(),
                "exposure_person_years": float(exposures[i, j]),
                "sparse": bool(exposures[i, j] < 3_000_000), "shock": endpoint in (2020, 2021),
                "wis": float(weighted[i, j]), "log_rmse": float(log_rmse[i, j]),
                "e0_draws": sampled_e0[:, i, j].tolist(), "intervals": bounds,
            })
    return rows


def execute(cube: Cube, task: Task, directory: Path, data_id: str, profile: str) -> dict:
    cfg = protocol()
    groups, targets = _targets(cube, task)
    train = cube.training(task.origin, groups)
    horizons = tuple(h for h in cfg["horizons"] if task.origin + h <= cube.years[-1])
    horizon = max(horizons)
    training_meta = {}
    checkpoint = None
    if task.family in baselines.FAMILIES:
        baseline = baselines.predict(task.family, train, targets, horizon)
        forecasts, support = baseline.log_rates, baseline.support
        fitted = baseline.fitted_log_rates if targets == groups else baselines.predict(
            task.family, train, groups, horizon
        ).fitted_log_rates
        training_meta["fits"] = baseline.diagnostics
    else:
        changes = {}
        if task.ablation in {"age_basis", "hierarchy", "shock", "dynamics"}:
            changes[task.ablation] = False
        if task.ablation == "likelihood":
            changes["likelihood"] = "negative_binomial"
        spec = learned.TrainingSpec(task.family, task.seed, steps=cfg["steps"] if profile == "full" else 28, **changes)
        checkpoint = "checkpoint.pt"
        if task.ablation == "calibration":
            base = directory.parent / Task("rolling", task.origin, task.family, task.seed).identity
            shutil.copyfile(base / checkpoint, directory / checkpoint)
            training_meta["reused_fit"] = base.name
        else:
            training_meta["training"] = learned.fit(train, spec, directory / checkpoint, data_id)
        model = learned.load(directory / checkpoint, data_id)
        years = tuple(range(task.origin + 1, task.origin + 1 + horizon))
        forecasts = learned.predict(model, targets, years)
        fitted = learned.predict(model, groups, train.years)
        support = tuple(model.support_status(group) for group in targets)
        with learned.torch.random.fork_rng():
            learned.torch.manual_seed(spec.seed)
            untrained = learned.MortalityModel(spec, model.support)
            untrained_forecast = learned.predict(untrained, targets, years)
        selected = [h - 1 for h in horizons]
        target_groups = [cube.groups.index(group) for group in targets]
        target_years = [cube.years.index(task.origin + h) for h in horizons]
        actual = expectancy(cube.ages, cube.rates[np.ix_(target_groups, target_years)])
        training_meta["held_out_mae_untrained"] = float(np.mean(np.abs(
            actual - expectancy(cube.ages, np.exp(untrained_forecast[:, selected]))
        )))
        training_meta["held_out_mae_trained"] = float(np.mean(np.abs(
            actual - expectancy(cube.ages, np.exp(forecasts[:, selected]))
        )))
    if not np.isfinite(forecasts).all() or np.max(np.abs(forecasts)) > 30:
        raise ArithmeticError("nonfinite or out-of-domain model forecast")
    calibration = _calibration(train, targets, fitted, enabled=task.ablation != "calibration")
    paths = calibration.paths(forecasts, draws=cfg["draws"] if profile == "full" else 20,
                              seed=task.origin * 11 + (task.seed or 0))
    outcomes = _score(cube, task, targets, horizons, forecasts, paths, support)
    return {
        "task": asdict(task), "checkpoint": checkpoint, "training": training_meta,
        "training_groups": [asdict(group) for group in groups], "training_years": list(train.years),
        "horizons": horizons, "outcomes": outcomes,
        "age_grid": [[age.start, age.end] for age in cube.ages],
    }


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def run(panel: Path, directory: Path, profile: str, resume: bool = False) -> dict:
    if profile not in PROFILES:
        raise ValueError("unrecognized experiment profile")
    panel = panel.resolve()
    data_id = digest(panel)
    cube = load_wpp(panel)
    tasks = tuple(plan(cube, profile))
    metadata = {
        "profile": profile, "panel_sha256": data_id, "commit": _git("rev-parse", "HEAD"),
        "protocol_sha256": digest(ROOT / "config/experiment-v1.json"),
        "tasks": [task.identity for task in tasks],
        "clean_checkout": not bool(_git("status", "--porcelain")),
    }
    if resume:
        stored = json.loads((directory / "STUDY.json").read_text())
        if metadata != stored:
            raise ValueError("study source or data identity changed; create a new run")
    else:
        directory.mkdir(parents=True, exist_ok=False)
        json_atomic(directory / "STUDY.json", metadata)
        json_atomic(directory / "ENVIRONMENT.json", {
            "platform": platform.platform(), "python": platform.python_version(),
            "numpy": np.__version__, "torch": str(learned.torch.__version__),
            "utc_start": datetime.now(timezone.utc).isoformat(),
        })
    failures = []
    complete = 0
    for task in tasks:
        folder = directory / task.identity
        result_file = folder / "result.json"
        if resume and result_file.is_file():
            complete += 1
            continue
        folder.mkdir(exist_ok=True)
        start = time.monotonic()
        command_log = directory / "COMMANDS.jsonl"
        entry = {"task": task.identity, "command": "aevum.study.execute", "requested": 1}
        try:
            result = execute(cube, task, folder, data_id, profile)
            json_atomic(result_file, result)
        except (ArithmeticError, OSError, RuntimeError, ValueError) as exc:
            failure = {"task": task.identity, "type": type(exc).__name__, "detail": str(exc)}
            json_atomic(folder / "failure.json", failure)
            failures.append(failure)
            entry.update(exit=1, completed=0, detail=str(exc))
        else:
            complete += 1
            entry.update(exit=0, completed=1)
        elapsed = time.monotonic() - start
        if not isfinite(elapsed):
            raise RuntimeError("elapsed time failed measurement")
        entry["seconds"] = elapsed
        with command_log.open("a") as handle:
            handle.write(json.dumps(entry, allow_nan=False) + "\n")
        print(json.dumps(entry, allow_nan=False), flush=True)
    summary = {"requested": len(tasks), "completed": complete, "failures": failures, "profile": profile}
    json_atomic(directory / "SUMMARY.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=Path("data/wpp.parquet"))
    parser.add_argument("--profile", choices=PROFILES, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,96}", args.out.name):
        parser.error("invalid run identifier")
    summary = run(args.panel, args.out, args.profile, args.resume)
    print(json.dumps(summary, allow_nan=False))
    raise SystemExit(int(bool(summary["failures"])))
