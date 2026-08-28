from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .utils import file_sha256, write_json


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def render_report_pdf(
    *,
    release_root: Path,
    chrome_path: Path,
    html_path: Path | None = None,
    pdf_path: Path | None = None,
) -> dict[str, Any]:
    release_root = release_root.resolve()
    chrome_path = chrome_path.resolve()
    html_path = (
        html_path.resolve()
        if html_path is not None
        else release_root / "RAPPORT_TECHNIQUE_v1.1.html"
    )
    pdf_path = (
        pdf_path.resolve()
        if pdf_path is not None
        else release_root / "RAPPORT_TECHNIQUE_v1.1.pdf"
    )
    if not chrome_path.is_file():
        raise FileNotFoundError(chrome_path)
    if not html_path.is_file():
        raise FileNotFoundError(html_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    cache_root = release_root / ".pdf_render_cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="chrome-profile-", dir=cache_root) as profile:
        command = [
            str(chrome_path),
            "--headless=new",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-background-networking",
            "--no-first-run",
            "--no-default-browser-check",
            "--no-pdf-header-footer",
            "--run-all-compositor-stages-before-draw",
            "--virtual-time-budget=10000",
            f"--user-data-dir={profile}",
            f"--print-to-pdf={pdf_path}",
            html_path.as_uri(),
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    try:
        cache_root.rmdir()
    except OSError:
        pass
    if completed.returncode != 0:
        raise RuntimeError(f"Chrome PDF rendering failed with exit code {completed.returncode}")
    if not pdf_path.is_file() or pdf_path.stat().st_size < 10_000:
        raise AssertionError("Chrome did not create a non-empty report PDF")
    version = subprocess.run(
        [str(chrome_path), "--version"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    ).stdout.strip()
    receipt = {
        "pdf_generation_schema_version": "v1",
        "status": "generated_pending_visual_qa",
        "source_html": html_path.relative_to(release_root).as_posix(),
        "source_html_sha256": file_sha256(html_path),
        "output_pdf": pdf_path.relative_to(release_root).as_posix(),
        "output_pdf_sha256": file_sha256(pdf_path),
        "output_pdf_bytes": pdf_path.stat().st_size,
        "renderer": "chrome_headless_print_to_pdf",
        "renderer_version": version,
        "created_at_utc": _utc_now(),
    }
    receipt_path = release_root / "05_methodologie_et_code" / "REPORT_PDF_GENERATION.json"
    write_json(receipt_path, receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the validated v1.1 HTML report to PDF with Chrome.")
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--chrome", type=Path, required=True)
    parser.add_argument("--html", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = render_report_pdf(
        release_root=args.release_root,
        chrome_path=args.chrome,
        html_path=args.html,
        pdf_path=args.output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
