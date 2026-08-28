from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .release_scope import load_release_scope
from .utils import file_sha256


def verify_handoff(root: Path) -> dict[str, object]:
    root = root.resolve()
    manifest_path = root / "HANDOFF_MANIFEST_SHA256.csv"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    rows = list(csv.DictReader(manifest_path.open(encoding="utf-8-sig", newline="")))
    if not rows:
        raise AssertionError("handoff hash manifest is empty")
    for row in rows:
        relative = str(row["delivery_path"])
        path = root / relative
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise AssertionError(f"unsafe handoff path: {relative}")
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.stat().st_size != int(row["bytes"]):
            raise AssertionError(f"handoff size mismatch: {relative}")
        if file_sha256(path) != row["sha256"]:
            raise AssertionError(f"handoff hash mismatch: {relative}")

    scope = load_release_scope(root / "config" / "releases" / "v1.1.json")
    panel = root / "panel" / "longitudinal_2000_v1.parquet"
    if file_sha256(panel) != scope.panel_sha256:
        raise AssertionError("fixed panel hash differs from v1.1 release configuration")
    model_ready = list((root / "outputs" / "model_ready").glob("*__n2000.parquet"))
    if len(model_ready) != 52:
        raise AssertionError(f"handoff contains {len(model_ready)} model-ready Parquet files; expected 52")
    for path in model_ready:
        sidecar = path.with_name(path.stem + "__manifest.json")
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        if payload.get("output_sha256") != file_sha256(path):
            raise AssertionError(f"model-ready sidecar hash mismatch: {path.name}")
    base = root / "work" / "longitudinal_2000_v1.0.2_H0A_H1_validated"
    if not (base / "01_resultats_python" / "longitudinal_krt_commune.parquet").is_file():
        raise AssertionError("validated v1.0.2 scientific base is missing")
    state = json.loads((root / "HANDOFF_STATE.json").read_text(encoding="utf-8"))
    return {
        "status": "pass",
        "files_verified": len(rows),
        "panel_sha256": scope.panel_sha256,
        "model_ready_pairs": len(model_ready),
        "handoff_ready_for_continuation": bool(state["handoff_ready_for_continuation"]),
        "scientific_release_ready": bool(state["scientific_release_ready"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the portable v1.1 continuation bundle.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps(verify_handoff(args.root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
