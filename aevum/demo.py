"""Build a bounded, explicitly synthetic end-to-end demonstration bundle."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

from .lifetable import life_table
from .simulate import generate
from .study import _git, json_atomic
from .verify import manifest_files, source_manifest


def write_bundle(directory: Path) -> str:
    commit = _git("rev-parse", "HEAD")
    directory.mkdir(parents=True, exist_ok=False)
    synthetic = generate(483, countries=2, years=24)
    cube = synthetic.panel
    deaths, exposure = cube.deaths[0, -1], cube.exposure[0, -1]
    hazards = synthetic.cause_counts[0, -1] / exposure[:, None]
    rows = life_table(cube.ages, deaths / exposure)
    artifact = {
        "status": "simulation", "unit": "deaths_per_person_year",
        "e0": rows[0].e, "life_table": [asdict(row) for row in rows],
        "panel": [
            {"deaths": float(d), "exposure": float(e), "cause_rates": causes.tolist(),
             "exposure_unit": "person_years", "status": "simulation"}
            for d, e, causes in zip(deaths, exposure, hazards)
        ],
    }
    json_atomic(directory / "comparison.json", artifact)
    json_atomic(directory / "SOURCE_INPUTS.json", source_manifest(commit))
    json_atomic(directory / "DATASETS.json", {"kind": "seeded known-truth simulation", "seed": 483, "year": cube.years[-1]})
    json_atomic(directory / "MANIFEST.json", manifest_files(directory))
    return commit


def controls(directory: Path, output: Path, commit: str) -> None:
    outcomes = []
    alterations = {
        "projection": (lambda data: data["panel"][0].update(status="official_projection"), "provenance"),
        "unit": (lambda data: data["panel"][0].update(exposure_unit="midyear_headcount"), "denominator unit"),
        "survival": (lambda data: data["life_table"][1].update(q=1.1), "impossible survival"),
        "cause": (lambda data: data["panel"][0]["cause_rates"].__setitem__(0, 0.4), "cause hazards"),
        "missing": (None, "missing"),
        "corrupt": (None, "SHA-256"),
        "source": (None, "source identity"),
    }
    for key, (edit, expected) in alterations.items():
        with TemporaryDirectory(dir=output.parent) as tmp:
            clone = Path(tmp) / "evidence"
            shutil.copytree(directory, clone)
            path = clone / "comparison.json"
            if edit:
                data = json.loads(path.read_text())
                edit(data)
                json_atomic(path, data)
            elif key == "missing":
                path.unlink()
            elif key == "corrupt":
                path.write_text("{")
            else:
                inputs = json.loads((clone / "SOURCE_INPUTS.json").read_text())
                inputs["commit"] = "0" * 40
                json_atomic(clone / "SOURCE_INPUTS.json", inputs)
            if key != "corrupt":
                json_atomic(clone / "MANIFEST.json", manifest_files(clone))
            cmd = [sys.executable, "-m", "aevum.verify", "demo", str(clone), "--expected-commit", commit]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            outcomes.append({"case": key, "invocation": cmd, "exit": result.returncode,
                             "stderr": result.stderr, "passed": result.returncode == 1 and expected in result.stderr})
    json_atomic(output, outcomes)
    if not all(row["passed"] for row in outcomes):
        raise ValueError("at least one verifier control was not rejected for the required reason")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--controls", type=Path)
    args = parser.parse_args()
    commit = write_bundle(args.directory)
    subprocess.run([sys.executable, "-m", "aevum.verify", "demo", str(args.directory), "--expected-commit", commit], check=True)
    if args.controls is not None:
        controls(args.directory, args.controls, commit)
