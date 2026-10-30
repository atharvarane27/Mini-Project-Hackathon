"""P08 directed multigraph and bounded cycle-search tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.engines.circular.dfs import CycleSearchLimits, find_cycle_candidates
from app.engines.circular.graph import DuplicateTransferConflict, TransferMultigraph
from app.engines.circular.temporal_validator import (
    CircularPolicy,
    CircularTransfer,
    validate_cycle,
)


START = datetime(2026, 1, 1, tzinfo=UTC)


def edge(
    transaction_id: str,
    sender: str,
    receiver: str,
    minute: int,
    *,
    status: str = "POSTED",
) -> CircularTransfer:
    return CircularTransfer(
        transaction_id,
        sender,
        receiver,
        1_000_000,
        "INR",
        START + timedelta(minutes=minute),
        status,
    )


def test_known_three_account_cycle_returns_candidate_path() -> None:
    graph = TransferMultigraph(
        (edge("T1", "A", "B", 0), edge("T2", "B", "C", 1), edge("T3", "C", "A", 2))
    )
    result = find_cycle_candidates(graph)
    assert len(result.candidates) == 1
    assert result.candidates[0].account_path == ("A", "B", "C", "A")
    assert tuple(item.transaction_id for item in result.candidates[0].transfers) == (
        "T1", "T2", "T3"
    )
    assert result.stats.candidates_found == 1


def test_acyclic_chain_returns_no_cycle() -> None:
    graph = TransferMultigraph(
        (edge("T1", "A", "B", 0), edge("T2", "B", "C", 1), edge("T3", "C", "D", 2))
    )
    assert find_cycle_candidates(graph).candidates == ()


def test_self_loop_and_parallel_edges_remain_distinct() -> None:
    self_loop = find_cycle_candidates(TransferMultigraph((edge("SELF", "A", "A", 0),)))
    assert self_loop.candidates[0].account_path == ("A", "A")

    graph = TransferMultigraph(
        (
            edge("AB-1", "A", "B", 0),
            edge("AB-2", "A", "B", 1),
            edge("BA", "B", "A", 2),
        )
    )
    result = find_cycle_candidates(graph)
    assert len(result.candidates) == 2
    assert {candidate.transfers[0].transaction_id for candidate in result.candidates} == {
        "AB-1", "AB-2"
    }


def test_posted_filter_and_duplicate_transaction_contract() -> None:
    graph = TransferMultigraph(
        (edge("POSTED", "A", "B", 0), edge("REJECTED", "B", "A", 1, status="REJECTED"))
    )
    assert graph.edge_count == 1
    graph.add(edge("POSTED", "A", "B", 0))
    assert graph.edge_count == 1
    with pytest.raises(DuplicateTransferConflict):
        graph.add(edge("POSTED", "A", "C", 0))


def test_hop_and_window_bounds_are_enforced() -> None:
    graph = TransferMultigraph(
        (edge("T1", "A", "B", 0), edge("T2", "B", "C", 1), edge("T3", "C", "A", 120))
    )
    assert find_cycle_candidates(graph, CycleSearchLimits(max_hops=2)).candidates == ()
    windowed = find_cycle_candidates(
        graph, CycleSearchLimits(max_hops=3, max_window_minutes=60)
    )
    assert windowed.candidates == ()
    assert windowed.stats.window_prunes > 0
    assert len(
        find_cycle_candidates(
            graph, CycleSearchLimits(max_hops=3, max_window_minutes=180)
        ).candidates
    ) == 1


def test_static_cycle_with_invalid_event_order_is_left_for_p09_rejection() -> None:
    graph = TransferMultigraph(
        (edge("T1", "A", "B", 10), edge("T2", "B", "C", 5), edge("T3", "C", "A", 15))
    )
    candidate = find_cycle_candidates(graph).candidates[0]
    assert validate_cycle(candidate, CircularPolicy(version=1)) is None


def test_large_sparse_graph_search_stays_bounded() -> None:
    graph = TransferMultigraph(
        edge(f"T-{index}", f"A-{index}", f"A-{index + 1}", index)
        for index in range(2_000)
    )
    result = find_cycle_candidates(
        graph, CycleSearchLimits(max_hops=6, max_window_minutes=60)
    )
    assert result.candidates == ()
    assert result.stats.maximum_depth <= 6
    assert result.stats.edges_examined < 12_100
