from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


CHUNK_SIZE = 90 * 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def split_archive(source: Path) -> dict[str, object]:
    source = source.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    output_dir = source.parent / f"{source.name}.parts"
    if output_dir.exists():
        raise FileExistsError(output_dir)
    output_dir.mkdir()
    parts: list[dict[str, object]] = []
    with source.open("rb") as stream:
        sequence = 1
        while True:
            payload = stream.read(CHUNK_SIZE)
            if not payload:
                break
            part = output_dir / f"{source.name}.part{sequence:03d}"
            with part.open("xb") as target:
                target.write(payload)
            parts.append(
                {
                    "sequence": sequence,
                    "file_name": part.name,
                    "size_bytes": part.stat().st_size,
                    "sha256": sha256(part),
                }
            )
            sequence += 1
    combined = hashlib.sha256()
    combined_size = 0
    for item in parts:
        part = output_dir / str(item["file_name"])
        with part.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                combined.update(block)
                combined_size += len(block)
    source_hash = sha256(source)
    if combined_size != source.stat().st_size or combined.hexdigest() != source_hash:
        raise AssertionError("split parts do not reconstruct the exact source bytes")
    manifest = {
        "schema_version": "exact_binary_split_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_file_name": source.name,
        "source_size_bytes": source.stat().st_size,
        "source_sha256": source_hash,
        "chunk_size_bytes": CHUNK_SIZE,
        "parts_count": len(parts),
        "parts": parts,
        "verification": "exact_concatenation_sha256_match",
    }
    (output_dir / "PARTS_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "REASSEMBLE_WINDOWS.ps1").write_text(
        f'''$ErrorActionPreference = "Stop"
$folder = $PSScriptRoot
$output = Join-Path $folder "{source.name}"
if (Test-Path -LiteralPath $output) {{ throw "Le ZIP reconstruit existe deja: $output" }}
$parts = Get-ChildItem -LiteralPath $folder -Filter "{source.name}.part*" | Sort-Object Name
if ($parts.Count -ne {len(parts)}) {{ throw "Nombre de fragments incorrect: $($parts.Count), attendu {len(parts)}" }}
$target = [System.IO.File]::Open($output, [System.IO.FileMode]::CreateNew)
try {{
    foreach ($part in $parts) {{
        $inputStream = [System.IO.File]::OpenRead($part.FullName)
        try {{ $inputStream.CopyTo($target) }} finally {{ $inputStream.Dispose() }}
    }}
}} finally {{ $target.Dispose() }}
$observed = (Get-FileHash -Algorithm SHA256 -LiteralPath $output).Hash.ToLowerInvariant()
$expected = "{source_hash}"
if ($observed -ne $expected) {{ throw "SHA-256 incorrect: $observed" }}
Write-Host "ZIP reconstruit et verifie: $output"
Write-Host "SHA-256: $observed"
''',
        encoding="utf-8-sig",
    )
    (output_dir / "README_REASSEMBLAGE.txt").write_text(
        f"Télécharger les {len(parts)} fragments, PARTS_MANIFEST.json et REASSEMBLE_WINDOWS.ps1 dans le même dossier.\n\n"
        "Dans PowerShell :\n"
        "  powershell -ExecutionPolicy Bypass -File .\\REASSEMBLE_WINDOWS.ps1\n\n"
        f"Le fichier obtenu doit s'appeler {source.name}\n"
        f"SHA-256 attendu : {source_hash}\n"
        "La concaténation restitue exactement les octets du ZIP original ; il ne s'agit pas d'une recompression.\n",
        encoding="utf-8",
    )
    return {"output_dir": str(output_dir), **manifest}


def main() -> None:
    parser = argparse.ArgumentParser(description="Split a verified archive into exact sub-100 MiB parts.")
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    print(json.dumps(split_archive(args.source), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
