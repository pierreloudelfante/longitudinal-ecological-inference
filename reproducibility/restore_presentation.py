from __future__ import annotations

"""Restore the QA-approved presentation from its hash-locked source artifact.

The deck is a frozen presentation source, not an analytical input.  All numbers
and figures referenced by it are rebuilt from the Parquet tables before this
step.  Keeping the approved binary source avoids Office renderer drift while
the accompanying brief and source notes preserve semantic traceability.
"""

import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reproducibility" / "presentation" / "PRESENTATION_RESULTATS_240.source.pptx"
OUTPUT_DIR = ROOT / "work" / "longitudinal_2000_v1_full_240_professeur_candidate" / "04_PRESENTATION"
OUTPUT = OUTPUT_DIR / "PRESENTATION_RESULTATS_240.pptx"
SOURCE_MANIFEST = ROOT / "reproducibility" / "presentation" / "PRESENTATION_SOURCE_MANIFEST.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    if sha256(SOURCE) != manifest["source_sha256"]:
        raise RuntimeError("presentation source hash mismatch")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".pptx.tmp")
    shutil.copy2(SOURCE, temporary)
    temporary.replace(OUTPUT)
    observed = sha256(OUTPUT)
    if observed != manifest["source_sha256"]:
        raise RuntimeError("restored presentation hash mismatch")
    print(json.dumps({"status": "complete", "path": str(OUTPUT), "sha256": observed}, indent=2))


if __name__ == "__main__":
    main()
