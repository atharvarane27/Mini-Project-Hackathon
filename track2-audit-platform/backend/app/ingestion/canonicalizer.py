"""Canonical economic transfers, provenance links, and journal integrity."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from threading import Lock
from uuid import NAMESPACE_URL, uuid5

from app.schemas.common import deterministic_fingerprint


class SourceRevisionConflict(ValueError):
    pass


class UnbalancedJournalError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AcceptedSourceTransfer:
    source_record_id: str
    source_system: str
    external_id: str
    revision: int
    transaction_reference: str
    sender_account_id: str
    receiver_account_id: str
    amount_minor: int
    currency: str
    occurred_at: datetime
    transaction_type: str = "TRANSFER"
    correction_of_reference: str | None = None

    def __post_init__(self) -> None:
        required = (
            self.source_record_id, self.source_system, self.external_id,
            self.transaction_reference, self.sender_account_id,
            self.receiver_account_id, self.currency, self.transaction_type,
        )
        if not all(value.strip() for value in required):
            raise ValueError("accepted transfer fields must not be empty")
        if self.revision <= 0 or self.amount_minor <= 0:
            raise ValueError("revision and amount_minor must be positive")
        if isinstance(self.amount_minor, bool) or not isinstance(self.amount_minor, int):
            raise TypeError("amount_minor must be an integer")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        object.__setattr__(self, "currency", self.currency.strip().upper())
        object.__setattr__(self, "occurred_at", self.occurred_at.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class CanonicalTransfer:
    transaction_id: str
    transaction_reference: str
    sender_account_id: str
    receiver_account_id: str
    amount_minor: int
    currency: str
    occurred_at: datetime
    transaction_type: str
    source_record_ids: tuple[str, ...]
    fingerprint: str
    reversal_of_transaction_id: str | None = None
    review_required: bool = False
    status: str = "POSTED"

    def as_dict(self) -> dict[str, object]:
        return {
            "transaction_id": self.transaction_id,
            "transaction_reference": self.transaction_reference,
            "sender_account_id": self.sender_account_id,
            "receiver_account_id": self.receiver_account_id,
            "amount_minor": self.amount_minor,
            "currency": self.currency,
            "occurred_at": self.occurred_at.isoformat(),
            "transaction_type": self.transaction_type,
            "source_record_ids": list(self.source_record_ids),
            "fingerprint": self.fingerprint,
            "reversal_of_transaction_id": self.reversal_of_transaction_id,
            "review_required": self.review_required,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class JournalPosting:
    posting_id: str
    journal_id: str
    transaction_id: str
    source_record_ids: tuple[str, ...]
    account_id: str
    debit_minor: int
    credit_minor: int
    currency: str


@dataclass(frozen=True, slots=True)
class CanonicalizationResult:
    transaction: CanonicalTransfer
    journal: tuple[JournalPosting, ...]
    replayed: bool


def validate_balanced_journal(postings: Iterable[JournalPosting]) -> None:
    items = tuple(postings)
    if not items:
        raise UnbalancedJournalError("journal must contain postings")
    if len({item.journal_id for item in items}) != 1:
        raise UnbalancedJournalError("postings must share one journal ID")
    if len({item.currency for item in items}) != 1:
        raise UnbalancedJournalError("journal currencies must match")
    if any(
        item.debit_minor < 0
        or item.credit_minor < 0
        or (item.debit_minor == 0) == (item.credit_minor == 0)
        for item in items
    ):
        raise UnbalancedJournalError("each posting must have one positive side")
    if sum(item.debit_minor for item in items) != sum(
        item.credit_minor for item in items
    ):
        raise UnbalancedJournalError("journal debit and credit totals differ")


def _payload(source: AcceptedSourceTransfer) -> dict[str, object]:
    return {
        "reference": source.transaction_reference.strip().casefold(),
        "sender": source.sender_account_id.strip(),
        "receiver": source.receiver_account_id.strip(),
        "amount_minor": source.amount_minor,
        "currency": source.currency,
        "occurred_at": source.occurred_at,
        "transaction_type": source.transaction_type.strip().upper(),
        "correction_of_reference": source.correction_of_reference,
    }


def _economic_payload(source: AcceptedSourceTransfer) -> dict[str, object]:
    payload = _payload(source)
    payload.pop("reference")
    return payload


class InMemoryCanonicalRepository:
    """Atomic reference adapter for the future P02 database transaction."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._transactions: dict[str, CanonicalTransfer] = {}
        self._transaction_ids_by_fingerprint: dict[str, str] = {}
        self._transaction_ids_by_reference: dict[str, str] = {}
        self._source_identity: dict[tuple[str, str, int], tuple[str, str]] = {}
        self._journals: dict[str, tuple[JournalPosting, ...]] = {}
        self._economic_fingerprints: dict[str, set[str]] = {}

    def canonicalize(self, source: AcceptedSourceTransfer) -> CanonicalizationResult:
        source_key = (source.source_system, source.external_id, source.revision)
        payload_hash = deterministic_fingerprint("source-transfer", _payload(source))
        fingerprint = deterministic_fingerprint("canonical-transfer", _payload(source))
        economic = deterministic_fingerprint("economic-transfer", _economic_payload(source))
        with self._lock:
            existing_source = self._source_identity.get(source_key)
            if existing_source is not None:
                saved_hash, transaction_id = existing_source
                if saved_hash != payload_hash:
                    raise SourceRevisionConflict(
                        "source identity was reused with a changed payload"
                    )
                transaction = self._transactions[transaction_id]
                if source.source_record_id not in transaction.source_record_ids:
                    transaction = replace(
                        transaction,
                        source_record_ids=tuple(
                            sorted((*transaction.source_record_ids, source.source_record_id))
                        ),
                    )
                    self._transactions[transaction_id] = transaction
                    self._journals[transaction_id] = tuple(
                        replace(posting, source_record_ids=transaction.source_record_ids)
                        for posting in self._journals[transaction_id]
                    )
                return CanonicalizationResult(
                    transaction, self._journals[transaction_id], replayed=True
                )

            existing_id = self._transaction_ids_by_fingerprint.get(fingerprint)
            if existing_id is not None:
                current = self._transactions[existing_id]
                linked = replace(
                    current,
                    source_record_ids=tuple(
                        sorted({*current.source_record_ids, source.source_record_id})
                    ),
                )
                journal = tuple(
                    replace(
                        posting,
                        source_record_ids=linked.source_record_ids,
                    )
                    for posting in self._journals[existing_id]
                )
                self._transactions[existing_id] = linked
                self._journals[existing_id] = journal
                self._source_identity[source_key] = (payload_hash, existing_id)
                return CanonicalizationResult(linked, journal, replayed=True)

            reversal_of: str | None = None
            sender, receiver = source.sender_account_id, source.receiver_account_id
            amount, currency = source.amount_minor, source.currency
            if source.correction_of_reference is not None:
                reversal_of = self._transaction_ids_by_reference.get(
                    source.correction_of_reference.strip().casefold()
                )
                if reversal_of is None:
                    raise ValueError("correction references an unknown transaction")
                original = self._transactions[reversal_of]
                sender, receiver = original.receiver_account_id, original.sender_account_id
                amount, currency = original.amount_minor, original.currency

            transaction_id = str(uuid5(NAMESPACE_URL, f"transaction:{fingerprint}"))
            related = self._economic_fingerprints.get(economic, set())
            ambiguous = bool(related)
            for related_id in related:
                self._transactions[related_id] = replace(
                    self._transactions[related_id], review_required=True
                )
            transaction = CanonicalTransfer(
                transaction_id=transaction_id,
                transaction_reference=source.transaction_reference.strip(),
                sender_account_id=sender,
                receiver_account_id=receiver,
                amount_minor=amount,
                currency=currency,
                occurred_at=source.occurred_at,
                transaction_type=source.transaction_type.strip().upper(),
                source_record_ids=(source.source_record_id,),
                fingerprint=fingerprint,
                reversal_of_transaction_id=reversal_of,
                review_required=ambiguous,
            )
            journal_id = str(uuid5(NAMESPACE_URL, f"journal:{transaction_id}"))
            journal = (
                JournalPosting(
                    str(uuid5(NAMESPACE_URL, f"posting:{journal_id}:debit")),
                    journal_id, transaction_id, transaction.source_record_ids,
                    sender, amount, 0, currency,
                ),
                JournalPosting(
                    str(uuid5(NAMESPACE_URL, f"posting:{journal_id}:credit")),
                    journal_id, transaction_id, transaction.source_record_ids,
                    receiver, 0, amount, currency,
                ),
            )
            validate_balanced_journal(journal)
            self._transactions[transaction_id] = transaction
            self._journals[transaction_id] = journal
            self._transaction_ids_by_fingerprint[fingerprint] = transaction_id
            self._transaction_ids_by_reference[
                source.transaction_reference.strip().casefold()
            ] = transaction_id
            self._source_identity[source_key] = (payload_hash, transaction_id)
            self._economic_fingerprints.setdefault(economic, set()).add(transaction_id)
            return CanonicalizationResult(transaction, journal, replayed=False)

    def list_transactions(
        self,
        *,
        account_id: str | None = None,
        reference: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[CanonicalTransfer, ...]:
        if offset < 0 or not 1 <= limit <= 500:
            raise ValueError("invalid transaction page")
        with self._lock:
            values = sorted(
                self._transactions.values(),
                key=lambda item: (item.occurred_at, item.transaction_id),
            )
            if account_id is not None:
                values = [
                    item for item in values
                    if account_id in {item.sender_account_id, item.receiver_account_id}
                ]
            if reference is not None:
                normalized = reference.strip().casefold()
                values = [
                    item for item in values
                    if item.transaction_reference.casefold() == normalized
                ]
            return tuple(values[offset : offset + limit])

    def downstream_snapshot(self) -> tuple[CanonicalTransfer, ...]:
        with self._lock:
            return tuple(
                sorted(
                    self._transactions.values(),
                    key=lambda item: (item.occurred_at, item.transaction_id),
                )
            )

    def journal_for(self, transaction_id: str) -> tuple[JournalPosting, ...]:
        with self._lock:
            return self._journals[transaction_id]
