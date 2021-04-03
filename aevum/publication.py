"""Check a reviewed manuscript and its figure receipts against one campaign."""

from pathlib import Path

from .acquire import ROOT, digest
from .verify import read_json, require

RESEARCH = ROOT / "docs/research"


def matches(publication: dict, candidate: Path, commit: str) -> bool:
    return (publication["executable_commit"] == commit
            and publication["manifest_sha256"] == digest(candidate / "MANIFEST.json"))


def verify_publication(publication: dict, candidate: Path, research: Path = RESEARCH) -> None:
    manifest = read_json(candidate / "MANIFEST.json")
    figures = publication["figures"]
    files = publication["files"]
    require(len(figures) == 14 and {key.split("-", 1)[0] for key in figures} == {
        f"{i:02d}" for i in range(1, 15)
    }, "publication must cover all 14 focused studies")
    required = {"README.md", "THESIS.md", "CLAIMS.md", "figures/forecast-wis.svg",
                "figures/interval-width.svg", "figures/strata.csv", "figures/synthetic.csv"}
    for key, figure in figures.items():
        require(key.replace("-", "").isalnum(), "invalid publication figure identifier")
        required.update({f"{key}.md", f"figures/{key}.csv", f"figures/{key}.svg"})
        sources = figure["source_artifacts"]
        require(bool(figure["scope"]) and bool(sources), f"missing source or scope for {key}")
        require(all(isinstance(sha, str) and len(sha) == 64 and manifest.get(path, {}).get("sha256") == sha
                    for path, sha in sources.items()),
                f"figure source receipts do not match the campaign for {key}")
        if "derived_artifact" in figure:
            name = figure["derived_artifact"]
            require(Path(name).name == name, "invalid derived artifact path")
            required.add(f"figures/{name}")
    require(set(files) == required, "publication file list is incomplete or unexpected")
    for path, sha in files.items():
        artifact = research / path
        require(artifact.is_file() and not artifact.is_symlink() and digest(artifact) == sha,
                f"reviewed publication file mismatch: {path}")
