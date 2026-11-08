"""Generate report figures from an existing research campaign."""

import argparse
from pathlib import Path
import shutil

from aevum.results import summarize


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    base = args.candidate
    args.output.mkdir(parents=True, exist_ok=False)
    summarize(
        base / "study", args.output / "figures", life_tables=base / "life-tables.csv",
        recovery=base / "recovery.jsonl", reference=base / "reference/summary.json",
        browser=base / "browser/browser.json",
    )
    source = Path(__file__).resolve().parents[1] / "docs/research/THESIS.md"
    shutil.copy2(source, args.output / "THESIS.md")


if __name__ == "__main__":
    main()
