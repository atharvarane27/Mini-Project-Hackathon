"""Validate and summarize the frozen, synthetic Phase 20 demo fixtures."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures"


def row_count(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as source:
        return sum(1 for _ in csv.DictReader(source))


def demo_manifest() -> dict[str, object]:
    expected = json.loads(
        (FIXTURES / "expected_findings.json").read_text(encoding="utf-8")
    )
    if not isinstance(expected, list) or not expected:
        raise ValueError("expected_findings.json must contain frozen findings")
    files = {
        name: row_count(FIXTURES / name)
        for name in (
            "circular_transfers.csv",
            "splitting_transfers.csv",
            "ledger_internal.csv",
            "ledger_counterpart.csv",
            "malformed_records.csv",
        )
    }
    return {
        "schema_version": 1,
        "synthetic_only": True,
        "fixture_rows": files,
        "expected_finding_count": len(expected),
        "expected_finding_types": sorted(
            {str(item["finding_type"]) for item in expected}
        ),
    }


def main() -> None:
    print(json.dumps(demo_manifest(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
