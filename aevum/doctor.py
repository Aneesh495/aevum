"""Report local execution limits and supported numerical devices."""

from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

import torch

from .acquire import ROOT, trusted_sources


def _probe(command: list[str]) -> str | None:
    try:
        return subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL, timeout=3).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def report() -> dict:
    root = ROOT
    data = root / "data/raw"
    sources = {
        key: {"vintage": value["vintage"], "available_files": sum((data / key / p).is_file() for p in value["files"]),
              "expected_files": len(value["files"])}
        for key, value in trusted_sources().items()
    }
    mps = torch.backends.mps.is_available()
    cuda = torch.cuda.is_available()
    driver = _probe(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"]) if cuda else None
    darwin_gpu = _probe(["system_profiler", "SPDisplaysDataType", "-detailLevel", "mini"]) if mps else None
    return {
        "os": platform.platform(), "machine": platform.machine(), "python": sys.version,
        "cpu_logical": os.cpu_count(), "cpu_model": _probe(["sysctl", "-n", "machdep.cpu.brand_string"]) or platform.processor(),
        "memory_bytes": _probe(["sysctl", "-n", "hw.memsize"]),
        "torch_mps": mps, "torch_cuda": cuda, "gpu_driver": driver, "apple_display": darwin_gpu,
        "compute_policy": "CPU training float32; native, evaluation and uncertainty arithmetic float64",
        "free_bytes": shutil.disk_usage(root).free, "workspace_writable": os.access(root, os.W_OK),
        "versions": {package: version(package) for package in ("torch", "numpy", "duckdb", "scipy", "pyarrow")},
        "rustc": _probe(["rustc", "--version"]), "node": _probe(["node", "--version"]), "sources": sources,
    }


if __name__ == "__main__":
    print(json.dumps(report(), indent=2, sort_keys=True))
