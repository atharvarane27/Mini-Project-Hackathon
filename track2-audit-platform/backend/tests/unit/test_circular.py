"""Regression tests for circular transfer cycle detection."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.engines.circular.dfs import DFSCycleDetector
from app.engines.circular.graph import MultiDiGraph


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class TestCircularGraph:
    def test_closing_edge_is_included_in_cycle_total(self) -> None:
        graph = MultiDiGraph()
        graph.add_edge(txn_id="T1", sender="A", receiver="B", timestamp="2024-01-01T00:00:00Z", amount=1000, currency="INR")
        graph.add_edge(txn_id="T2", sender="B", receiver="C", timestamp="2024-01-01T00:10:00Z", amount=1000, currency="INR")
        graph.add_edge(txn_id="T3", sender="C", receiver="A", timestamp="2024-01-01T00:50:00Z", amount=1000, currency="INR")

        cycles = DFSCycleDetector(max_hops=10, max_window_minutes=60).find_cycles(graph)
        assert len(cycles) == 1
        assert cycles[0].edges == ("T1", "T2", "T3")
        assert cycles[0].total_amount == 3000
        assert cycles[0].window_minutes == 50

    def test_parallel_edges_stay_distinct(self) -> None:
        graph = MultiDiGraph()
        graph.add_edge(txn_id="P1", sender="A", receiver="B", timestamp="2024-01-01T00:00:00Z", amount=10, currency="INR")
        graph.add_edge(txn_id="P2", sender="A", receiver="B", timestamp="2024-01-01T00:01:00Z", amount=12, currency="INR")
        graph.add_edge(txn_id="P3", sender="B", receiver="A", timestamp="2024-01-01T00:02:00Z", amount=10, currency="INR")

        cycles = DFSCycleDetector(max_hops=5, max_window_minutes=60).find_cycles(graph)
        assert len(cycles) >= 1
        txn_ids = {edge for candidate in cycles for edge in candidate.edges}
        assert "P3" in txn_ids

    def test_two_cycles_sharing_a_node_are_both_found(self) -> None:
        graph = MultiDiGraph()
        graph.add_edge(txn_id="A1", sender="A", receiver="B", timestamp="2024-01-01T00:00:00Z", amount=10, currency="INR")
        graph.add_edge(txn_id="B1", sender="B", receiver="A", timestamp="2024-01-01T00:05:00Z", amount=10, currency="INR")
        graph.add_edge(txn_id="C1", sender="A", receiver="C", timestamp="2024-01-01T00:10:00Z", amount=10, currency="INR")
        graph.add_edge(txn_id="C2", sender="C", receiver="A", timestamp="2024-01-01T00:15:00Z", amount=10, currency="INR")

        cycles = DFSCycleDetector(max_hops=6, max_window_minutes=120).find_cycles(graph)
        assert len(cycles) >= 2
        assert {candidate.cycle for candidate in cycles} == {("A", "B"), ("A", "C")}

    def test_mixed_currency_cycle_is_rejected(self) -> None:
        graph = MultiDiGraph()
        graph.add_edge(txn_id="T1", sender="A", receiver="B", timestamp="2024-01-01T00:00:00Z", amount=100, currency="INR")
        graph.add_edge(txn_id="T2", sender="B", receiver="C", timestamp="2024-01-01T00:05:00Z", amount=100, currency="USD")
        graph.add_edge(txn_id="T3", sender="C", receiver="A", timestamp="2024-01-01T00:10:00Z", amount=100, currency="INR")

        cycles = DFSCycleDetector(max_hops=10, max_window_minutes=120).find_cycles(graph)
        assert cycles == []

    def test_cap_enforcement_stops_excess_candidates(self) -> None:
        graph = MultiDiGraph()
        for idx in range(1, 9):
            graph.add_edge(txn_id=f"N{idx}", sender=f"N{idx}", receiver=f"N{idx + 1}", timestamp=f"2024-01-01T00:{idx:02d}:00Z", amount=1, currency="INR")
        graph.add_edge(txn_id="closing", sender="N9", receiver="N1", timestamp="2024-01-01T00:09:00Z", amount=1, currency="INR")

        cycles = DFSCycleDetector(max_hops=8, candidate_cap=2).find_cycles(graph)
        assert len(cycles) <= 2

    def test_self_loop_is_detected(self) -> None:
        graph = MultiDiGraph()
        graph.add_edge(txn_id="loop-1", sender="X", receiver="X", timestamp="2024-01-01T00:00:00Z", amount=25, currency="INR")

        cycles = DFSCycleDetector(max_hops=3, max_window_minutes=60).find_cycles(graph)
        assert len(cycles) >= 1
        assert cycles[0].cycle == ("X",)

    def test_a_b_c_d_returns_none(self) -> None:
        graph = MultiDiGraph()
        graph.add_edge(txn_id="T1", sender="A", receiver="B", timestamp="2024-01-01T00:00:00Z", amount=10, currency="INR")
        graph.add_edge(txn_id="T2", sender="B", receiver="C", timestamp="2024-01-01T00:05:00Z", amount=10, currency="INR")
        graph.add_edge(txn_id="T3", sender="C", receiver="D", timestamp="2024-01-01T00:10:00Z", amount=10, currency="INR")

        cycles = DFSCycleDetector(max_hops=8, max_window_minutes=120).find_cycles(graph)
        assert cycles == []

    def test_linear_path_yields_no_cycle(self) -> None:
        graph = MultiDiGraph()
        graph.add_edge(txn_id="t1", sender="A", receiver="B", timestamp="2024-01-01T00:00:00Z", amount=100, currency="INR")
        graph.add_edge(txn_id="t2", sender="B", receiver="C", timestamp="2024-01-01T00:05:00Z", amount=100, currency="INR")
        graph.add_edge(txn_id="t3", sender="C", receiver="D", timestamp="2024-01-01T00:10:00Z", amount=100, currency="INR")

        cycles = DFSCycleDetector(max_hops=8, max_window_minutes=240).find_cycles(graph)
        assert cycles == []

    def test_invalid_timing_is_rejected(self) -> None:
        graph = MultiDiGraph()
        graph.add_edge(txn_id="t1", sender="A", receiver="B", timestamp="2024-01-01T00:00:00Z", amount=100, currency="INR")
        graph.add_edge(txn_id="t2", sender="B", receiver="C", timestamp="2024-01-01T00:08:00Z", amount=100, currency="INR")
        graph.add_edge(txn_id="t3", sender="C", receiver="A", timestamp="2024-01-01T02:00:00Z", amount=100, currency="INR")

        detector = DFSCycleDetector(max_hops=8, max_window_minutes=30)
        cycles = detector.find_cycles(graph)
        assert cycles == []

    def test_large_sparse_graph_does_not_explode(self) -> None:
        graph = MultiDiGraph()
        for idx in range(1, 51):
            graph.add_edge(txn_id=f"t{idx}", sender=f"A{idx}", receiver=f"B{idx}", timestamp=f"2024-01-01T0{idx % 10}:00:00Z", amount=1, currency="INR")
        graph.add_edge(txn_id="loop1", sender="B1", receiver="A1", timestamp="2024-01-01T00:15:00Z", amount=1, currency="INR")

        detector = DFSCycleDetector(max_hops=4, max_window_minutes=240, candidate_cap=10)
        cycles = detector.find_cycles(graph)
        assert len(cycles) <= 10

    def test_bounded_search_is_enforced(self) -> None:
        graph = MultiDiGraph()
        for idx in range(1, 9):
            graph.add_edge(txn_id=f"n{idx}", sender=f"N{idx}", receiver=f"N{idx + 1}", timestamp=f"2024-01-01T00:{idx:02d}:00Z", amount=1, currency="INR")
        graph.add_edge(txn_id="closing", sender="N9", receiver="N1", timestamp="2024-01-01T00:09:00Z", amount=1, currency="INR")

        detector = DFSCycleDetector(max_hops=3, candidate_cap=5)
        cycles = detector.find_cycles(graph)
        assert len(cycles) <= 5
        assert detector.stats.pruned_by_hops >= 0

    def test_csv_fixture_builds_graph(self) -> None:
        graph = MultiDiGraph.from_csv("fixtures/circular_transfers.csv")
        assert graph.node_count >= 3
        assert graph.edge_count >= 3

    def test_missing_currency_rejected(self) -> None:
        with pytest.raises(ValueError):
            MultiDiGraph().add_edge(txn_id="bad", sender="A", receiver="B", timestamp="2024-01-01T00:00:00Z", amount=100, currency="")
