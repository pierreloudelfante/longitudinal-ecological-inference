from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq
from reproducibility.replication_scope import get_scope


ROOT = Path(__file__).resolve().parents[1]
TABLE_DIR = ROOT / "work" / "longitudinal_2000_release_professeur_candidate" / "02_TABLES_PRINCIPALES"
OUTPUT_DIR = ROOT / "work" / "density_all_pairs" / "data"

SOURCES = {
    "krt_python": TABLE_DIR / "longitudinal_krt_commune.parquet",
    "r_eipack": TABLE_DIR / "longitudinal_r_ei_commune.parquet",
}

COLUMNS = [
    "election_id",
    "scenario_id",
    "unit_id",
    "b1_mean",
    "b2_mean",
    "b1_weight",
    "b2_weight",
    "N_g",
]


def finite(value: object) -> bool:
    return value is not None and math.isfinite(float(value))


def export_one(method: str, source: Path) -> dict[str, object]:
    table = pq.read_table(source, columns=COLUMNS)
    method_column = pa.array([method] * table.num_rows, type=pa.string())
    table = table.append_column("method", method_column)
    output = OUTPUT_DIR / f"density_inputs_{method}.csv"
    pacsv.write_csv(table, output)

    values = {name: table[name].to_pylist() for name in ["election_id", "scenario_id", "b1_mean", "b2_mean"]}
    counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    for election_id, scenario_id, b1, b2 in zip(
        values["election_id"],
        values["scenario_id"],
        values["b1_mean"],
        values["b2_mean"],
        strict=True,
    ):
        record = counts[(str(election_id), str(scenario_id))]
        record[0] += 1
        record[1] += int(finite(b1))
        record[2] += int(finite(b2))

    if set(counts) != get_scope().pairs or any(row[0] != 2000 for row in counts.values()):
        raise AssertionError(f"{method}: density inputs must contain exactly 2000 communes for every scoped pair")

    return {
        "method": method,
        "source": source.name,
        "output": output.name,
        "rows": table.num_rows,
        "pairs": len(counts),
        "coverage": [
            {
                "method": method,
                "election_id": election_id,
                "scenario_id": scenario_id,
                "rows": values_[0],
                "finite_b1": values_[1],
                "finite_b2": values_[2],
                "finite_both_lower_bound": min(values_[1], values_[2]),
            }
            for (election_id, scenario_id), values_ in sorted(counts.items())
        ],
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = [export_one(method, source) for method, source in SOURCES.items()]
    coverage = [row for result in results for row in result.pop("coverage")]
    coverage_path = OUTPUT_DIR / "beta_coverage_by_pair.csv"
    with coverage_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(coverage[0]))
        writer.writeheader()
        writer.writerows(coverage)
    manifest = {
        "schema_version": "density_pair_inputs_v1",
        "status": "complete",
        "methods": results,
        "coverage_rows": len(coverage),
        "expected_pairs_per_method": get_scope().pair_count,
        "replication_scope": get_scope().as_dict(),
        "columns": COLUMNS + ["method"],
    }
    (OUTPUT_DIR / "density_inputs_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
