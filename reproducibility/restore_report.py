from __future__ import annotations

"""Restore the QA-approved secondary PDF export from its hash-locked source.

The portable HTML report remains the canonical, data-derived report and is
rebuilt before this step.  The PDF is frozen because browser/PDF renderers can
change pagination, fonts and binary output even when the HTML is identical.
"""

import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "reproducibility" / "report"
SOURCE = SOURCE_DIR / "RAPPORT_LONGITUDINAL.source.pdf"
SOURCE_MANIFEST = SOURCE_DIR / "REPORT_SOURCE_MANIFEST.json"
OUTPUT_DIR = ROOT / "work" / "longitudinal_2000_release_professeur_candidate" / "01_RAPPORT"
OUTPUT = OUTPUT_DIR / "RAPPORT_LONGITUDINAL.pdf"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    expected = manifest["source_sha256"]
    if sha256(SOURCE) != expected:
        raise RuntimeError("report PDF source hash mismatch")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".pdf.tmp")
    shutil.copy2(SOURCE, temporary)
    temporary.replace(OUTPUT)
    observed = sha256(OUTPUT)
    if observed != expected:
        raise RuntimeError("restored report PDF hash mismatch")
    print(json.dumps({"status": "complete", "path": str(OUTPUT), "sha256": observed}, indent=2))


if __name__ == "__main__":
    main()
