"""Download the judgment PDFs in tests/fixtures/sci/sources.yaml from the
Supreme Court's website and extract their text.

    python scripts/fetch_sci_samples.py            # all samples
    python scripts/fetch_sci_samples.py judis_3650

Needs `pdftotext` (poppler-utils). The PDFs are cached in
tests/fixtures/sci/pdf/, which git ignores; the extracted .txt files are the
fixtures. Downloads run one at a time with a pause between them, to be gentle
on the court's servers. Prints the size of each judgment's text (after
`sci.clean_sci`) with a rough token count: characters / 4.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import yaml

from app.sci import clean_sci

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "sci"
PAUSE = 5  # seconds between downloads


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
            with urllib.request.urlopen(entry["url"], timeout=120) as resp:
                data = resp.read()
            if b"%PDF" not in data[:1024]:  # JUDIS files have a few bytes before the header
                # The site answers a bad link with an HTML page, not an error status.
                raise SystemExit(f"{jid}: {entry['url']} did not return a PDF")
            pdf.write_bytes(data)
            time.sleep(PAUSE)
        txt = FIXTURES / f"{jid}.txt"
        subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(pdf), str(txt)], check=True)
        text = txt.read_text()
        body = clean_sci(text).body
        sha = hashlib.sha256(pdf.read_bytes()).hexdigest()[:12]
        pages = text.count("\f")
        print(f"{jid}: {pages} pages, judgment {len(body.split())} words, ~{len(body) // 4} tokens, pdf {sha}")


if __name__ == "__main__":
    main(sys.argv[1:])
