"""Run and independently verify a source-bound research evidence bundle."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import resource
import shutil
import subprocess
import sys
import time

from .acquire import ROOT, digest, trusted_sources
from .study import _git, json_atomic
from .verify import read_json, require, source_manifest, verify_manifest, manifest_files

UNRESOLVED = {
    "G13": "Focused results and thesis require final scientific review.",
    "G15": "Full release and all project acceptance requirements must be independently audited.",
}


def _run(root: Path, name: str, command: list[str], *, timeout: int, extra_env: dict | None = None) -> dict:
    start = time.monotonic()
    recorded = {"step": name, "argv": command, "requested": 1, "cwd": str(ROOT)}
    with (root / "logs" / (name + ".log")).open("x") as handle:
        try:
            process = subprocess.run(
                command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT,
                timeout=timeout, env=os.environ | {
                    "OPENBLAS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "OMP_NUM_THREADS": "2",
                } | (extra_env or {}),
            )
            status = process.returncode
        except subprocess.TimeoutExpired:
            status = 124
        except OSError as exc:
            handle.write(str(exc) + "\n")
            status = 126
    peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    if sys.platform != "darwin":
        peak *= 1024
    recorded.update(exit=status, completed=int(status == 0), seconds=time.monotonic() - start,
                    children_high_water_bytes=peak, log=f"logs/{name}.log")
    with (root / "COMMANDS.jsonl").open("a") as handle:
        handle.write(json.dumps(recorded, allow_nan=False) + "\n")
    print(json.dumps(recorded, allow_nan=False), flush=True)
    return recorded


def _python(*args: str | Path) -> list[str]:
    return [sys.executable, "-m", *(str(a) for a in args)]


def execute(output: Path, raw: Path, profile: str) -> dict:
    if profile not in {"full", "diagnostic"}:
        raise ValueError("unknown acceptance profile")
    if profile == "full" and _git("status", "--porcelain"):
        raise ValueError("full research execution requires a clean checkout")
    output = output.resolve()
    raw = raw.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "logs").mkdir()
    commit = _git("rev-parse", "HEAD")
    json_atomic(output / "SOURCE_INPUTS.json", source_manifest(commit))
    json_atomic(output / "DATASETS.json", {"declared": trusted_sources(), "input_root": str(raw)})
    json_atomic(output / "ENVIRONMENT.json", {
        "profile": profile, "os": platform.platform(), "python": platform.python_version(),
        "architecture": platform.machine(), "cpu_logical": os.cpu_count(),
        "disk_free_bytes": shutil.disk_usage(output).free, "utc_start": datetime.now(timezone.utc).isoformat(),
        "sys_executable_sha256": digest(Path(sys.executable)),
    })
    commands = []
    steps = [
        ("build", ["make", "build"], 240),
        ("tests", ["make", "test"], 240),
        ("demo", _python("aevum.demo", output / "demo", "--controls", output / "NEGATIVE_CONTROLS.json"), 120),
        ("stress", _python("aevum.table_study", "stress", "--out", output / "stress.jsonl",
                            "--tables", "10000" if profile == "full" else "200"), 180),
        ("stress-verification", _python("aevum.verify", "stress", output / "stress.jsonl",
                                         "--count", "10000" if profile == "full" else "200"), 180),
    ]
    if profile == "full":
        panel = output / "wpp.parquet"
        who = output / "who.parquet"
        steps.extend([
            ("wpp", _python("aevum.wpp", "--raw", raw, "--out", panel), 240),
            ("who", _python("aevum.who", "--raw", raw, "--out", who), 240),
            ("reference", _python("aevum.table_study", "reference", "--raw", raw, "--out", output / "reference"), 240),
            ("age-sensitivity", _python("aevum.table_study", "tables", "--panel", panel,
                                        "--out", output / "life-tables.csv"), 180),
            ("cause-study", _python("aevum.cause_study", "--panel", who, "--raw", raw, "--out", output / "cause"), 180),
            ("synthetic-recovery", _python("aevum.recovery", "--out", output / "recovery.jsonl"), 240),
            ("backtest", _python("aevum.study", "--profile", "full", "--panel", panel, "--out", output / "study"), 2400),
            ("backtest-verification", _python("aevum.verify", "study", output / "study", "--panel", panel,
                                              "--expected-commit", commit), 480),
            ("vintage", _python("aevum.vintages", "--raw", raw, "--panel", panel, "--out", output / "vintages"), 360),
            ("serve-fit", _python("aevum.forecast", "fit", "--panel", panel,
                                   "--checkpoint", output / "serving.pt"), 180),
            ("web-build", ["make", "web"], 180),
            ("browser", ["scripts/browser-bench.sh", str(output / "serving.pt"), str(output / "browser")], 180),
            ("replay-control", _python("aevum.replay_control", output / "study", "--panel", panel,
                                       "--out", output / "REPLAY_CONTROL.json"), 120),
        ])
    for name, command, limit in steps:
        env = {"AEVUM_PANEL": str(output / "wpp.parquet"), "AEVUM_CAUSES": str(output / "who.parquet")} if name == "browser" else None
        commands.append(_run(output, name, command, timeout=limit, extra_env=env))
    passed = {item["step"] for item in commands if item["exit"] == 0}
    gates = {f"G{i:02d}": {"status": "unverified"} for i in range(1, 16)}

    def step_gate(gate: str, names: set[str]):
        gate_status = "passed" if names <= passed else "failed"
        gates[gate] = {"status": gate_status, "steps": sorted(names)}

    if profile == "full":
        for gate, names in {
            "G01": {"wpp", "who", "cause-study"}, "G02": {"stress", "stress-verification", "tests"}, "G03": {"reference"},
            "G04": {"tests"}, "G05": {"tests", "backtest-verification"},
            "G07": {"backtest", "backtest-verification"}, "G08": {"backtest-verification"},
            "G09": {"demo", "cause-study"}, "G10": {"cause-study", "tests"},
            "G11": {"synthetic-recovery"}, "G12": {"browser"}, "G14": {"demo", "replay-control"},
        }.items():
            step_gate(gate, names)
        if "backtest" in passed:
            probes = [read_json(path)["training"] for path in (output / "study").glob("*/result.json")]
            learned = [x for x in probes if "held_out_mae_trained" in x and "reused_fit" not in x]
            wins = sum(x["held_out_mae_trained"] < x["held_out_mae_untrained"] for x in learned)
            gates["G06"] = {"status": "passed" if len(learned) == wins == 129 else "failed",
                            "held_out_improvements": wins, "learned_fits": len(learned)}
        for gate, detail in UNRESOLVED.items():
            gates[gate] = {"status": "unverified", "detail": detail}
    result = {"profile": profile, "commit": commit, "gates": gates,
              "required_steps": [name for name, *_ in steps],
              "successful_steps": len(passed), "failed_steps": [item["step"] for item in commands if item["exit"] != 0],
              "full_pass": False}
    json_atomic(output / "ACCEPTANCE.json", result)
    json_atomic(output / "MANIFEST.json", manifest_files(output))
    return result


def verify_candidate(directory: Path, expected_commit: str) -> dict:
    from .verify import verify_demo, verify_stress, verify_study
    from .verify_domains import check_causes, check_recovery, published_tables

    verify_manifest(directory)
    require(read_json(directory / "SOURCE_INPUTS.json") == source_manifest(expected_commit), "candidate source mismatch")
    result = read_json(directory / "ACCEPTANCE.json")
    require(result["commit"] == source_manifest(expected_commit)["commit"], "candidate commit mismatch")
    profile = result["profile"]
    require(profile in {"full", "diagnostic"}, "unsupported evidence profile")
    raw_commands = (directory / "COMMANDS.jsonl").read_text().splitlines()
    commands = [json.loads(row) for row in raw_commands]
    names = [item["step"] for item in commands]
    require(names == result["required_steps"] and len(set(names)) == len(names), "command evidence incomplete")
    require(all(item["exit"] == 0 and item["completed"] == 1 and item["requested"] == 1 for item in commands),
            "at least one research command failed or was incomplete")
    require("demo" in names and "stress-verification" in names and "tests" in names, "missing required diagnostic execution")
    demo = verify_demo(directory / "demo", expected_commit)
    tables = 10_000 if profile == "full" else 200
    verify_stress(directory / "stress.jsonl", count=tables)
    controls = read_json(directory / "NEGATIVE_CONTROLS.json")
    require({x["case"] for x in controls} == {"projection", "unit", "survival", "cause", "missing", "corrupt", "source"}
            and all(x["exit"] == 1 and x["passed"] is True and x["stderr"] for x in controls),
            "semantic controls missing or unexpected exit")
    info = {"profile": profile, "demo": demo, "verified_stress_tables": tables}
    if profile == "full":
        require({"reference", "cause-study", "backtest", "backtest-verification", "replay-control", "synthetic-recovery"} <= set(names),
                "missing required research execution")
        info["study"] = verify_study(directory / "study", directory / "wpp.parquet", expected_commit)
        info["known_truth_panels"] = check_recovery(directory / "recovery.jsonl")
        info["reference"] = published_tables(directory / "reference")
        info["cause_study"] = check_causes(directory / "who.parquet", directory / "cause")
        browser = read_json(directory / "browser/browser.json")
        samples = sorted(browser["cached_samples"])
        require(len(samples) == 40 and all(0 < x < 5000 for x in samples) and not browser["errors"],
                "browser samples invalid")
        require(samples[37] < 500 and browser["p95_ms"] == samples[37], "browser p95 latency claim failed")
        info["browser_p95_ms"] = samples[37]
        replay = read_json(directory / "REPLAY_CONTROL.json")
        require(replay["exit"] == 1 and "frozen model replay" in replay["stderr"], "failed replay negative control missing")
    info["full_acceptance"] = False
    return info


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "verify"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--raw", type=Path, default=Path("data/raw"))
    parser.add_argument("--profile", choices=("diagnostic", "full"), default="diagnostic")
    parser.add_argument("--expected-commit")
    parser.add_argument("--candidate", action="store_true", help="verify completed evidence without certifying all research gates")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,96}", args.out.name):
        parser.error("invalid evidence identity")
    if args.action == "run":
        result = execute(args.out, args.raw, args.profile)
        print(json.dumps(result, sort_keys=True))
        raise SystemExit(int(bool(result["failed_steps"]) or args.profile == "full" and not result["full_pass"]))
    if not args.expected_commit:
        parser.error("--expected-commit is required for verification")
    try:
        result = verify_candidate(args.out, args.expected_commit)
    except (ArithmeticError, OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(1, f"Verification failed: {exc}\n")
    print(json.dumps(result, sort_keys=True))
    if result["profile"] == "full" and not args.candidate:
        parser.exit(1, "Evidence checked, but mandatory full research gates remain open.\n")
