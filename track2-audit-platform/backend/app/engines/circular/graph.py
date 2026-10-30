"""Scaffold for backend/app/engines/circular/graph; implementation pending."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping
import csv


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    return None


def _as_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float, str)):
        return Decimal(str(value))
    raise TypeError(f"Unsupported amount value: {value!r}")


@dataclass(frozen=True)
class CircularEdge:
    txn_id: str
    sender: str
    receiver: str
    timestamp: datetime
    amount: Decimal
    currency: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "txn_id": self.txn_id,
            "sender": self.sender,
            "receiver": self.receiver,
            "timestamp": self.timestamp.isoformat(),
            "amount": str(self.amount),
            "currency": self.currency,
            "metadata": dict(self.metadata),
        }


class MultiDiGraph:
    """Directed multigraph for circular transfer detection.

    The graph intentionally stores adjacency lists rather than a workflow DAG and
    keeps parallel edges distinct by transaction ID.
    """

    def __init__(self) -> None:
        self._adjacency: dict[str, list[CircularEdge]] = defaultdict(list)
        self._nodes: set[str] = set()
        self._edges: dict[str, CircularEdge] = {}

    @property
    def adjacency(self) -> dict[str, list[CircularEdge]]:
        return {node: list(edges) for node, edges in self._adjacency.items()}

    @property
    def nodes(self) -> set[str]:
        return set(self._nodes)

    @property
    def edges(self) -> dict[str, CircularEdge]:
        return dict(self._edges)

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    def add_edge(
        self,
        *,
        txn_id: str,
        sender: str,
        receiver: str,
        timestamp: datetime | str | None,
        amount: Decimal | int | float | str,
        currency: str,
        **metadata: Any,
    ) -> CircularEdge:
        if not txn_id:
            raise ValueError("txn_id is required")
        if not sender:
            raise ValueError("sender is required")
        if not receiver:
            raise ValueError("receiver is required")

        code = str(currency).strip().upper()
        if not code:
            raise ValueError(f"currency is required for {txn_id!r}")

        dt = _parse_datetime(timestamp)
        if dt is None:
            raise ValueError(f"Invalid timestamp for {txn_id!r}: {timestamp!r}")

        edge = CircularEdge(
            txn_id=str(txn_id),
            sender=str(sender),
            receiver=str(receiver),
            timestamp=dt,
            amount=_as_decimal(amount),
            currency=code,
            metadata=dict(metadata),
        )
        self._nodes.add(edge.sender)
        self._nodes.add(edge.receiver)
        self._adjacency[edge.sender].append(edge)
        self._edges[edge.txn_id] = edge
        return edge

    def add_transfer(self, record: Mapping[str, Any]) -> CircularEdge:
        if not isinstance(record, Mapping):
            raise TypeError("record must be a mapping")

        txn_id = (
            record.get("txn_id")
            or record.get("transaction_id")
            or record.get("Transaction_ID")
            or record.get("id")
            or record.get("transactionId")
        )
        if txn_id is None:
            raise ValueError("Unable to derive transaction id from record")

        status = (
            record.get("status")
            or record.get("Transaction_Status")
            or record.get("transaction_status")
        )
        if status is not None and str(status).upper() not in {"POSTED", "COMPLETED", "SUCCESS"}:
            raise ValueError(f"Only posted circular transfers may be added: {txn_id}")

        sender = (
            record.get("sender_account_id")
            or record.get("sender")
            or record.get("from_account_id")
            or record.get("account_from")
            or record.get("source")
            or record.get("Transaction_Source")
            or record.get("source_account")
            or record.get("Account_Number")
        )
        receiver = (
            record.get("receiver_account_id")
            or record.get("receiver")
            or record.get("to_account_id")
            or record.get("account_to")
            or record.get("destination")
            or record.get("Transaction_Destination")
            or record.get("destination_account")
        )
        if sender is None or receiver is None:
            raise ValueError(f"Transfer record {txn_id!r} missing sender/receiver")

        ts = (
            record.get("timestamp")
            or record.get("occurred_at")
            or record.get("posted_at")
            or record.get("transaction_date")
            or record.get("posting_date")
            or record.get("Transaction_Date")
            or record.get("Posting_Date")
        )
        amount_value = (
            record.get("amount")
            or record.get("amount_minor")
            or record.get("transaction_amount")
            or record.get("minor_amount")
            or record.get("Transaction_Amount")
        )
        if amount_value is None:
            raise ValueError(f"Transfer record {txn_id!r} missing amount")

        currency = (
            record.get("currency")
            or record.get("currency_code")
            or record.get("Currency")
        )
        if currency is None:
            raise ValueError(f"Transfer record {txn_id!r} missing currency")

        metadata = {k: v for k, v in record.items() if k not in {
            "txn_id",
            "transaction_id",
            "Transaction_ID",
            "id",
            "transactionId",
            "sender_account_id",
            "sender",
            "from_account_id",
            "account_from",
            "source",
            "Transaction_Source",
            "source_account",
            "receiver_account_id",
            "receiver",
            "to_account_id",
            "account_to",
            "destination",
            "Transaction_Destination",
            "destination_account",
            "amount",
            "amount_minor",
            "transaction_amount",
            "minor_amount",
            "Transaction_Amount",
            "currency",
            "currency_code",
            "Currency",
            "timestamp",
            "occurred_at",
            "posted_at",
            "transaction_date",
            "posting_date",
            "Transaction_Date",
            "Posting_Date",
            "status",
            "Transaction_Status",
            "transaction_status",
            "Account_Number",
        }}

        return self.add_edge(
            txn_id=txn_id,
            sender=sender,
            receiver=receiver,
            timestamp=ts,
            amount=amount_value,
            currency=currency,
            **metadata,
        )

    def neighbors(self, node: str) -> list[CircularEdge]:
        return list(self._adjacency.get(node, ()))

    def has_node(self, node: str) -> bool:
        return node in self._nodes

    def has_edge(self, txn_id: str) -> bool:
        return txn_id in self._edges

    def out_degree(self, node: str) -> int:
        return len(self._adjacency.get(node, ()))

    def __iter__(self) -> Iterator[str]:
        return iter(self._nodes)

    @classmethod
    def from_records(cls, records: Iterable[Mapping[str, Any]]) -> "MultiDiGraph":
        graph = cls()
        for record in records:
            if record is None:
                continue
            graph.add_transfer(record)
        return graph

    @classmethod
    def from_csv(cls, path: str | Path) -> "MultiDiGraph":
        csv_path = Path(path)
        if not csv_path.is_absolute():
            project_root = Path(__file__).resolve().parents[4]
            csv_path = project_root / csv_path
        with csv_path.open("r", newline="") as handle:
            rows = list(csv.DictReader(handle))
        return cls.from_records(rows)

    def self_loops(self) -> list[str]:
        return [edge.txn_id for edge in self._edges.values() if edge.sender == edge.receiver]


CircularTransferGraph = MultiDiGraph

__all__ = [
    "CircularEdge",
    "CircularTransferGraph",
    "MultiDiGraph",
]
