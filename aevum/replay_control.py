"""Exercise a rehashed checkpoint mutation through the real verifier."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

import torch

from .acquire import digest
from .cube import Population
from .study import json_atomic
from .verify import _check_replay, manifest_files, read_json, verify_manifest


def run(study: Path, panel: Path, output: Path) -> None:
    source = study / "rolling.1995.structured.731"
    if not source.is_dir():
        raise ValueError("frozen checkpoint control is missing")
    with TemporaryDirectory(dir=output.parent) as temp:
        clone = Path(temp) / "mutated"
        shutil.copytree(source, clone)
        checkpoint = clone / "checkpoint.pt"
        payload = torch.load(checkpoint, weights_only=True, map_location="cpu")
        payload["model"]["anchor"] += 0.2
        torch.save(payload, checkpoint)
        json_atomic(clone / "MANIFEST.json", manifest_files(clone))
        command = [sys.executable, "-m", "aevum.replay_control", "--check", str(clone), "--panel", str(panel)]
        tested = subprocess.run(command, text=True, capture_output=True, timeout=60)
        json_atomic(output, {"invocation": command, "exit": tested.returncode, "stderr": tested.stderr})
        if tested.returncode != 1 or "frozen model replay" not in tested.stderr:
            raise ValueError("modified checkpoint was not rejected for replay divergence")


def check(folder: Path, panel: Path) -> None:
    verify_manifest(folder)
    result = read_json(folder / "result.json")
    targets = tuple(Population(**record) for record in result["training_groups"])
    _check_replay(result, folder, digest(panel), targets)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        if args.check:
            check(args.directory, args.panel)
        else:
            if args.out is None:
                parser.error("--out is required")
            run(args.directory, args.panel, args.out)
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, f"Verification failed: {exc}\n")
