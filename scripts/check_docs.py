"""Check local Markdown references, public style, and rendered diagram syntax."""

from pathlib import Path
import re
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
links = re.compile(r"\[[^\]]+\]\(([^\s)]+)\)")
failures = []
for path in [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]:
    body = path.read_text()
    if "\N{EM DASH}" in body:
        failures.append(f"{path.relative_to(ROOT)} contains a forbidden punctuation character")
    for url in links.findall(body):
        local = url.split("#")[0]
        if local and "://" not in local and not (path.parent / local).is_file():
            failures.append(f"{path.relative_to(ROOT)} has a broken link to {url}")
for source in (ROOT / "docs/diagrams").glob("*.dot"):
    target = source.with_suffix(".svg")
    if not target.is_file():
        failures.append(f"missing rendered export for {source.name}")
        continue
    if ElementTree.parse(target).getroot().tag != "{http://www.w3.org/2000/svg}svg":
        failures.append(f"{target.name} is not an SVG")
if failures:
    raise SystemExit("\n".join(failures))
