"""Export the reviewed thesis only with the evidence it describes."""

import argparse
import re
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory

from aevum.acquire import ROOT
from aevum.publication import RESEARCH, matches, verify_publication
from aevum.verify import read_json, require, source_manifest, verify_manifest


def build(base: Path, output: Path) -> None:
    publication = read_json(RESEARCH / "PUBLICATION.json")
    commit = publication["executable_commit"]
    require(matches(publication, base, commit), "no reviewed thesis for this campaign; use aevum.results for new runs")
    verify_manifest(base)
    require(read_json(base / "SOURCE_INPUTS.json") == source_manifest(commit), "thesis source manifest mismatch")
    verify_publication(publication, base)
    docs_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as temporary:
        stage = Path(temporary) / "report"
        stage.mkdir()
        for relative in sorted(publication["files"]):
            source = RESEARCH / relative
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.suffix == ".md":
                def link(match):
                    path = (source.parent / match[1]).resolve().relative_to(ROOT)
                    revision = docs_commit if path.parts[0] == "docs" else commit
                    return f"](https://github.com/Aneesh495/aevum/blob/{revision}/{path.as_posix()})"

                target.write_text(re.sub(r"\]\((\.\./[^)]+)\)", link, source.read_text()))
            else:
                shutil.copyfile(source, target)
        shutil.copyfile(RESEARCH / "PUBLICATION.json", stage / "PUBLICATION.json")
        output.mkdir()
        try:
            stage.replace(output)
        except OSError:
            shutil.rmtree(output)
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        build(args.candidate, args.output)
    except (KeyError, OSError, ValueError) as exc:
        parser.exit(1, f"Thesis export failed: {exc}\n")


if __name__ == "__main__":
    main()
