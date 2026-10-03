"""Download the sample judgments in tests/fixtures/scr/sources.yaml and
extract their text.

    python scripts/fetch_scr_samples.py            # all samples
    python scripts/fetch_scr_samples.py 2024_2_685_692

Needs `pdftotext` (poppler-utils). The PDFs are cached in
tests/fixtures/scr/pdf/, which git ignores; the extracted .txt files are the
fixtures. Prints the size of each judgment's text (after `scr.clean_scr`) with
a rough token count for the cost estimate: characters / 4. The Claude API's
token counter gives exact numbers.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import urllib.request
from pathlib import Path

import yaml

from app.scr import clean_scr

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "scr"


def main(only: list[str]) -> None:
    manifest = yaml.safe_load((FIXTURES / "sources.yaml").read_text())
    pdf_dir = FIXTURES / "pdf"
    pdf_dir.mkdir(exist_ok=True)
    for entry in manifest["judgments"]:
        jid = entry["id"]
        if only and jid not in only:
            continue
        pdf = pdf_dir / f"{jid}.pdf"
        if not pdf.exists():
            url = f"{manifest['source']}/data/pdf/year={entry['year']}/english/{jid}_EN.pdf"
            with urllib.request.urlopen(url, timeout=60) as resp:
                pdf.write_bytes(resp.read())
        txt = FIXTURES / f"{jid}.txt"
        subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(pdf), str(txt)], check=True)
        text = txt.read_text()
        body = clean_scr(text).body
        sha = hashlib.sha256(pdf.read_bytes()).hexdigest()[:12]
        pages = text.count("\f")
        print(f"{jid}: {pages} pages, judgment {len(body.split())} words, ~{len(body) // 4} tokens, pdf {sha}")


if __name__ == "__main__":
    main(sys.argv[1:])
