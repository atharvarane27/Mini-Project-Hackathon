"""Directed multigraph of canonical posted account transfers."""

from __future__ import annotations

from collections.abc import Iterable

from .temporal_validator import CircularTransfer


class DuplicateTransferConflict(ValueError):
    pass


class TransferMultigraph:
    def __init__(self, transfers: Iterable[CircularTransfer] = ()) -> None:
        self._adjacency: dict[str, list[CircularTransfer]] = {}
        self._transfers: dict[str, CircularTransfer] = {}
        for transfer in transfers:
            self.add(transfer)
        for edges in self._adjacency.values():
            edges.sort(key=lambda item: (item.occurred_at, item.transaction_id))

    def add(self, transfer: CircularTransfer) -> None:
        if transfer.status != "POSTED":
            return
        existing = self._transfers.get(transfer.transaction_id)
        if existing is not None:
            if existing != transfer:
                raise DuplicateTransferConflict(
                    f"transaction {transfer.transaction_id!r} has conflicting payloads"
                )
            return
        self._transfers[transfer.transaction_id] = transfer
        self._adjacency.setdefault(transfer.sender_account_id, []).append(transfer)
        self._adjacency.setdefault(transfer.receiver_account_id, [])

    @property
    def node_count(self) -> int:
        return len(self._adjacency)

    @property
    def edge_count(self) -> int:
        return len(self._transfers)

    def nodes(self) -> tuple[str, ...]:
        return tuple(sorted(self._adjacency))

    def outgoing(self, account_id: str) -> tuple[CircularTransfer, ...]:
        return tuple(
            sorted(
                self._adjacency.get(account_id, ()),
                key=lambda item: (item.occurred_at, item.transaction_id),
            )
        )
