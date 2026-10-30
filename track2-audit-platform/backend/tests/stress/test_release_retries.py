"""P20 adversarial retry and frozen-fixture release checks."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from pathlib import Path

from app.ingestion.service import InMemoryIngestionRepository, IngestionService


ROOT = Path(__file__).resolve().parents[3]
HEADER = (
    "external_id,transaction_reference,sender_account_id,receiver_account_id,"
    "amount,currency,occurred_at,revision,direction\n"
)


def csv_fixture(rows: int) -> str:
    return HEADER + "".join(
        f"EXT-{index},REF-{index},A-{index},B-{index},1250.50,INR,"
        "2026-10-30T08:00:00Z,1,DEBIT\n"
        for index in range(rows)
    )


def test_simultaneous_reimports_create_one_source_identity_per_row() -> None:
    content = csv_fixture(250)
    digest = hashlib.sha256(content.encode()).hexdigest()
    repository = InMemoryIngestionRepository()
    service = IngestionService(repository, batch_size=50)

    def import_copy(copy: int) -> str:
        job = service.ingest(
            StringIO(content),
            source_system="release-ledger",
            source_file="release.csv",
            file_hash=digest,
            idempotency_key=f"release-import-{copy:02d}",
        )
        return job.job_id

    with ThreadPoolExecutor(max_workers=12) as executor:
        job_ids = tuple(executor.map(import_copy, range(24)))

    assert len(job_ids) == 24
    accepted = repository.accepted()
    assert len(accepted) == 250
    assert len(
        {
            (
                item.transfer.source_system,
                item.transfer.external_id,
                item.transfer.revision,
            )
            for item in accepted
        }
    ) == 250


def test_frozen_expected_findings_have_unique_evidence() -> None:
    findings = json.loads(
        (ROOT / "fixtures" / "expected_findings.json").read_text(encoding="utf-8")
    )
    evidence = [tuple(item["transaction_ids"]) for item in findings]

    assert len(findings) == 3
    assert len(evidence) == len(set(evidence))
    assert all(item["expected_count"] == 1 for item in findings)
