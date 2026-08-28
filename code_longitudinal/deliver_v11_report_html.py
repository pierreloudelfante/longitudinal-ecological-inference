from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .build_v11_report_artifact import build_report_artifact
from .paths import ROOT
from .utils import file_sha256, write_json


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _last_json_object(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        candidate = line.strip()
        if not candidate.startswith("{"):
            continue
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("portable report builder did not emit a JSON receipt")


def deliver_report_html(
    *,
    release_root: Path,
    config_path: Path,
    plugin_root: Path,
    artifact_path: Path | None = None,
    html_path: Path | None = None,
) -> dict[str, Any]:
    release_root = release_root.resolve()
    plugin_root = plugin_root.resolve()
    artifact_path = (
        artifact_path.resolve()
        if artifact_path is not None
        else release_root / "05_methodologie_et_code" / "report_artifact.json"
    )
    html_path = (
        html_path.resolve()
        if html_path is not None
        else release_root / "RAPPORT_TECHNIQUE_v1.1.html"
    )
    package_path = plugin_root / "package.json"
    if not package_path.is_file():
        raise FileNotFoundError(package_path)
    package = json.loads(package_path.read_text(encoding="utf-8"))
    artifact_result = build_report_artifact(release_root, config_path, artifact_path)
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        raise FileNotFoundError("npm executable not found")
    command = [
        npm,
        "run",
        "report:deliver",
        "--",
        "--input",
        str(artifact_path),
        "--output",
        str(html_path),
    ]
    completed = subprocess.run(
        command,
        cwd=plugin_root,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    delivery = _last_json_object(completed.stdout)
    if completed.returncode != 0 or not delivery.get("ok"):
        raise RuntimeError(
            "portable report delivery failed: "
            + json.dumps(delivery, ensure_ascii=False, sort_keys=True)
        )
    stages = delivery.get("stages", {})
    verification = str(stages.get("verification", "unknown"))
    if verification not in {"passed", "structural_only"}:
        raise AssertionError(f"unexpected report verification stage: {verification}")
    if not html_path.is_file() or html_path.stat().st_size == 0:
        raise AssertionError("portable report HTML was not created")
    browser_warning = delivery.get("browserWarning")
    receipt = {
        "report_delivery_schema_version": "v1",
        "status": "pass" if verification == "passed" else "pass_with_structural_qa",
        "artifact": {
            key: value for key, value in artifact_result.items() if key != "artifact_path"
        },
        "builder": {
            "package_name": package.get("name"),
            "package_version": package.get("version"),
            "validation": stages.get("validation"),
            "package": stages.get("package"),
            "verification": verification,
            "counts": delivery.get("counts", {}),
            "browser_warning": browser_warning,
            "source_dialog": delivery.get("sourceDialog"),
            "source_interaction": delivery.get("sourceInteraction"),
        },
        "artifact_path": artifact_path.relative_to(release_root).as_posix(),
        "artifact_sha256": file_sha256(artifact_path),
        "html_path": html_path.relative_to(release_root).as_posix(),
        "html_sha256": file_sha256(html_path),
        "external_builder_required_for_regeneration": True,
        "created_at_utc": _utc_now(),
    }
    receipt_path = release_root / "05_methodologie_et_code" / "report_delivery_receipt.json"
    write_json(receipt_path, receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and verify the portable v1.1 HTML report.")
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--plugin-root", type=Path, required=True)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = deliver_report_html(
        release_root=args.release_root,
        config_path=args.config,
        plugin_root=args.plugin_root,
        artifact_path=args.artifact,
        html_path=args.output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
