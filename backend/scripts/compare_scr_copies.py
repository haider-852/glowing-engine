"""Compare official Digital SCR PDFs with the mirror's copies used as fixtures.

    python scripts/compare_scr_copies.py 1950_1_594_605=~/Downloads/romesh.pdf 2024_2_685_692=...

scr.sci.gov.in shows a report's PDF only after a search that needs a CAPTCHA,
so the official copies are downloaded by hand. Each id is a sample in
tests/fixtures/scr/sources.yaml; the mirror's PDF is fetched (and cached in
tests/fixtures/scr/pdf/) if needed. For each pair it prints whether the files
are identical, their page counts, and how much of the extracted text matches.
Needs `pdftotext` and `pdfinfo` (poppler-utils).
"""

from __future__ import annotations

import difflib
import hashlib
import re
import subprocess
import sys
from pathlib import Path

from fetch_scr_samples import FIXTURES, download


def pages(pdf: Path) -> int:
    info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, check=True).stdout
    return int(re.search(r"^Pages:\s+(\d+)", info, re.M).group(1))


def text(pdf: Path) -> list[str]:
    out = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
    return [" ".join(line.split()) for line in out.splitlines() if line.strip()]


def compare(jid: str, official: Path) -> str:
    mirror = download(jid)
    a, b = mirror.read_bytes(), official.read_bytes()
    if a == b:
        return f"{jid}: identical files ({hashlib.sha256(a).hexdigest()[:12]})"
    ratio = difflib.SequenceMatcher(None, text(mirror), text(official), autojunk=False).ratio()
    return (
        f"{jid}: files differ; pages {pages(mirror)} (mirror) / {pages(official)} (official); "
        f"text lines matching {ratio:.1%}"
    )


if __name__ == "__main__":
    if not sys.argv[1:]:
        raise SystemExit(__doc__)
    for arg in sys.argv[1:]:
        jid, _, path = arg.partition("=")
        print(compare(jid, Path(path).expanduser()))
    print(f"(mirror copies in {FIXTURES / 'pdf'})")
