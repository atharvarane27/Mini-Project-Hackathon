"""P01 shared contract and identity acceptance tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.core.idempotency import (
    idempotency_payload_hash,
    normalize_idempotency_key,
)
from app.schemas.cases import (
    AuditCaseContract,
    AuditCaseStatus,
    WorkflowTaskContract,
    WorkflowTaskStatus,
)
from app.schemas.common import (
    DataEnvelope,
    OutboxEventContract,
    OutboxStatus,
    deterministic_fingerprint,
)
from app.schemas.detectors import FindingContract, FindingType
from app.schemas.transactions import CanonicalTransaction, JournalLine, SourceRecord


NOW = datetime(2026, 10, 30, 8, 0, tzinfo=UTC)


def transaction_payload() -> dict[str, object]:
    return {
        "transaction_id": "txn-001",
        "source_record_ids": ["source-001"],
        "sender_account_id": "account-a",
        "receiver_account_id": "account-b",
        "amount_minor": 125_050,
        "currency": "INR",
        "occurred_at": "2026-10-30T08:00:00Z",
        "transaction_type": "TRANSFER",
        "status": "POSTED",
    }


def test_source_transaction_and_journal_validate_json_payloads() -> None:
    source = SourceRecord.model_validate_json(
        json.dumps(
            {
                "source_record_id": "source-001",
                "source_system": "branch-ledger",
                "external_id": "EXT-1",
                "revision": 1,
                "received_at": "2026-10-30T08:01:00+00:00",
                "raw_payload": {"amount": "1250.50"},
            }
        )
    )
    transaction = CanonicalTransaction.model_validate_json(
        json.dumps(transaction_payload())
    )
    line = JournalLine(
        journal_line_id="line-1",
        journal_id="journal-1",
        account_id="account-a",
        debit_minor=125_050,
        credit_minor=0,
        currency="INR",
        occurred_at=NOW,
    )
    assert source.received_at.tzinfo is UTC
    assert transaction.amount_minor == 125_050
    assert line.debit_minor == transaction.amount_minor


@pytest.mark.parametrize(
    "change",
    [
        {"transaction_id": None},
        {"amount_minor": 1250.50},
        {"occurred_at": "2026-10-30 08:00:00"},
        {"currency": "inr"},
    ],
)
def test_contract_rejects_missing_id_float_money_and_malformed_time(
    change: dict[str, object],
) -> None:
    payload = {**transaction_payload(), **change}
    with pytest.raises(ValidationError):
        CanonicalTransaction.model_validate_json(json.dumps(payload))


def test_all_detector_families_use_one_finding_contract() -> None:
    examples = (
        (FindingType.RECONCILIATION_MISMATCH, {"Reconciliation_Variance_Minor": 500}),
        (FindingType.CIRCULAR_FLOW, {"Circular_Flow_Detected": True, "Cycle_Length": 3}),
        (FindingType.SPLITTING_PATTERN, {"Splitting_Window_Count": 4}),
    )
    findings = [
        FindingContract(
            finding_id=f"finding-{index}",
            finding_type=finding_type,
            fingerprint=deterministic_fingerprint("finding", {"index": index}),
            transaction_ids=(f"txn-{index}",),
            facts=facts,
            evidence={"source": "fixture"},
            detector_config_version=1,
            algorithm_version="v1",
            created_at=NOW,
        )
        for index, (finding_type, facts) in enumerate(examples)
    ]
    assert {item.finding_type for item in findings} == {item[0] for item in examples}
    with pytest.raises(ValidationError, match="unknown finding fact"):
        FindingContract(
            **{
                **findings[0].model_dump(),
                "facts": {"Unregistered_Fact": True},
            }
        )


def test_case_workflow_outbox_and_envelope_contracts() -> None:
    case = AuditCaseContract(
        case_id="case-1",
        case_code="CASE-001",
        finding_ids=("finding-1",),
        rule_version_id="rule-v1",
        state=AuditCaseStatus.QUEUED,
        priority=80,
        row_version=1,
        created_at=NOW,
    )
    task = WorkflowTaskContract(
        workflow_task_id="task-1",
        case_id=case.case_id,
        task_key="review",
        state=WorkflowTaskStatus.READY,
        row_version=1,
    )
    payload = {"case_id": case.case_id, "row_version": case.row_version}
    outbox = OutboxEventContract(
        event_id="event-1",
        event_type="CASE_QUEUED",
        entity_id=case.case_id,
        entity_version=1,
        payload=payload,
        payload_hash=deterministic_fingerprint("outbox", payload),
        status=OutboxStatus.PENDING,
        attempt_count=0,
        created_at=NOW,
    )
    envelope = DataEnvelope[AuditCaseContract](
        data=case, meta={}, request_id="request-1"
    )
    assert task.case_id == outbox.entity_id == envelope.data.case_id


def test_fingerprint_and_idempotency_are_deterministic_and_float_safe() -> None:
    left = {"b": 2, "a": [1, {"time": NOW}]}
    right = {"a": [1, {"time": NOW}], "b": 2}
    assert deterministic_fingerprint("test", left) == deterministic_fingerprint(
        "test", right
    )
    assert idempotency_payload_hash("ingest", left) == idempotency_payload_hash(
        "ingest", right
    )
    assert normalize_idempotency_key(" import-001 ") == "import-001"
    with pytest.raises(TypeError, match="floating-point"):
        deterministic_fingerprint("test", {"amount": 1.25})
