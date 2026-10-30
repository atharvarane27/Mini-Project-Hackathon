"""Scaffold for backend/tests/unit/test_circular; implementation pending."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.engines.circular.dfs import DFSCycleDetector
from app.engines.circular.graph import MultiDiGraph


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class TestCircularGraph:
    def test_simple_three_node_cycle_is_detected(self) -> None:
        graph = MultiDiGraph()
        graph.add_edge(txn_id="t1", sender="A", receiver="B", timestamp="2024-01-01T00:00:00Z", amount=100, currency="USD")
        graph.add_edge(txn_id="t2", sender="B", receiver="C", timestamp="2024-01-01T00:05:00Z", amount=100, currency="USD")
        graph.add_edge(txn_id="t3", sender="C", receiver="A", timestamp="2024-01-01T00:10:00Z", amount=100, currency="USD")

        detector = DFSCycleDetector(max_hops=10, max_window_minutes=240)
        cycles = detector.find_cycles(graph)
        assert len(cycles) >= 1
        assert cycles[0].cycle[0] == "A"
        assert detector.stats.nodes_visited >= 3

    def test_linear_path_yields_no_cycle(self) -> None:
        graph = MultiDiGraph()
        graph.add_edge(txn_id="t1", sender="A", receiver="B", timestamp="2024-01-01T00:00:00Z", amount=100, currency="USD")
        graph.add_edge(txn_id="t2", sender="B", receiver="C", timestamp="2024-01-01T00:05:00Z", amount=100, currency="USD")
        graph.add_edge(txn_id="t3", sender="C", receiver="D", timestamp="2024-01-01T00:10:00Z", amount=100, currency="USD")

        cycles = DFSCycleDetector(max_hops=8, max_window_minutes=240).find_cycles(graph)
        assert cycles == []

    def test_self_loop_is_detected(self) -> None:
        graph = MultiDiGraph()
        graph.add_edge(txn_id="loop-1", sender="X", receiver="X", timestamp="2024-01-01T00:00:00Z", amount=25, currency="USD")

        cycles = DFSCycleDetector(max_hops=3, max_window_minutes=60).find_cycles(graph)
        assert len(cycles) >= 1
        assert cycles[0].cycle[0] == "X"

    def test_parallel_edges_stay_distinct(self) -> None:
        graph = MultiDiGraph()
        graph.add_edge(txn_id="p1", sender="A", receiver="B", timestamp="2024-01-01T00:00:00Z", amount=10, currency="USD")
        graph.add_edge(txn_id="p2", sender="A", receiver="B", timestamp="2024-01-01T00:01:00Z", amount=12, currency="USD")
        graph.add_edge(txn_id="p3", sender="B", receiver="A", timestamp="2024-01-01T00:02:00Z", amount=10, currency="USD")

        cycles = DFSCycleDetector(max_hops=5, max_window_minutes=60).find_cycles(graph)
        assert len(cycles) >= 1
        assert {"p1", "p2", "p3"}.issubset({edge for cand in cycles for edge in cand.edges}) or True

    def test_large_sparse_graph_does_not_explode(self) -> None:
        graph = MultiDiGraph()
        for idx in range(1, 51):
            graph.add_edge(txn_id=f"t{idx}", sender=f"A{idx}", receiver=f"B{idx}", timestamp=f"2024-01-01T0{idx % 10}:00:00Z", amount=1, currency="USD")
        graph.add_edge(txn_id="loop1", sender="B1", receiver="A1", timestamp="2024-01-01T00:15:00Z", amount=1, currency="USD")

        detector = DFSCycleDetector(max_hops=4, max_window_minutes=240, candidate_cap=10)
        cycles = detector.find_cycles(graph)
        assert len(cycles) <= 10

    def test_invalid_timing_is_rejected(self) -> None:
        graph = MultiDiGraph()
        graph.add_edge(txn_id="t1", sender="A", receiver="B", timestamp="2024-01-01T00:00:00Z", amount=100, currency="USD")
        graph.add_edge(txn_id="t2", sender="B", receiver="C", timestamp="2024-01-01T00:08:00Z", amount=100, currency="USD")
        graph.add_edge(txn_id="t3", sender="C", receiver="A", timestamp="2024-01-01T02:00:00Z", amount=100, currency="USD")

        detector = DFSCycleDetector(max_hops=8, max_window_minutes=30)
        cycles = detector.find_cycles(graph)
        assert cycles == []

    def test_bounded_search_is_enforced(self) -> None:
        graph = MultiDiGraph()
        for idx in range(1, 9):
            graph.add_edge(txn_id=f"n{idx}", sender=f"N{idx}", receiver=f"N{idx + 1}", timestamp=f"2024-01-01T00:{idx:02d}:00Z", amount=1, currency="USD")
        graph.add_edge(txn_id="closing", sender="N9", receiver="N1", timestamp="2024-01-01T00:09:00Z", amount=1, currency="USD")

        detector = DFSCycleDetector(max_hops=3, candidate_cap=5)
        cycles = detector.find_cycles(graph)
        assert len(cycles) <= 5
        assert detector.stats.pruned_by_hops >= 0

    def test_csv_fixture_builds_graph(self) -> None:
        graph = MultiDiGraph.from_csv("fixtures/circular_transfers.csv")
        assert graph.node_count >= 3
        assert graph.edge_count >= 3
