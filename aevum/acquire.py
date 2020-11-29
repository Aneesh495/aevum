"""Immutable source receipts and bounded acquisition."""

import argparse
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
CHUNK_BYTES = 1024 * 1024


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return file_digest(handle, "sha256").hexdigest()


def trusted_sources() -> dict:
    return json.loads((ROOT / "config/sources.json").read_text())


def get_source(root: Path, key: str, filename: str) -> Path:
    source = trusted_sources()[key]
    expected = source["files"][filename]
    path = root / key / filename
    if not path.is_file() or path.stat().st_size > source["max_bytes"] or digest(path) != expected:
        raise ValueError(f"{key}/{filename} missing or different from frozen bytes; run make acquire")
    return path


def _download(url: str, dest: Path, expected: str, limit: int) -> None:
    if not re.fullmatch(r"[a-z0-9._-]+", dest.name, re.IGNORECASE):
        raise ValueError("invalid source filename")
    if dest.exists():
        if dest.stat().st_size <= limit and digest(dest) == expected:
            return
        raise ValueError(f"{dest} differs from the pinned bytes; move it aside to reacquire")
    dest.parent.mkdir(parents=True, exist_ok=True)
    stage = None
    try:
        checksum = sha256()
        received = 0
        with NamedTemporaryFile(dir=dest.parent, prefix=f".{dest.name}.", delete=False) as handle:
            stage = Path(handle.name)
            with urlopen(url, timeout=40) as response:
                if urlparse(response.url).scheme != "https":
                    raise ValueError("source redirected to an insecure protocol")
                for chunk in iter(lambda: response.read(CHUNK_BYTES), b""):
                    received += len(chunk)
                    if received > limit:
                        raise ValueError(f"{dest.name} exceeded its acquisition byte limit")
                    checksum.update(chunk)
                    handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if checksum.hexdigest() != expected:
            raise ValueError(f"SHA-256 mismatch for {dest.name}")
        stage.replace(dest)
    finally:
        if stage is not None:
            stage.unlink(missing_ok=True)


def acquire(root: Path, key: str) -> None:
    source = trusted_sources()[key]
    for filename, expected in source["files"].items():
        path = root / key / filename
        _download(source["base"] + filename, path, expected, source["max_bytes"])
        print(f"{key}/{filename} {expected}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=sorted(trusted_sources()))
    parser.add_argument("--root", default=Path("data/raw"), type=Path)
    options = parser.parse_args()
    acquire(options.root, options.source)
