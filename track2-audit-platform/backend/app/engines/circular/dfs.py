"""Bounded simple-cycle detection for the circular transfer graph."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.engines.circular.graph import CircularEdge, MultiDiGraph

WHITE = 0
GRAY = 1
BLACK = 2


@dataclass(frozen=True)
class CycleCandidate:
    cycle: tuple[str, ...]
    edges: tuple[str, ...]
    total_amount: int
    currency: str
    window_minutes: int


@dataclass
class TraversalStats:
    nodes_visited: int = 0
    edges_traversed: int = 0
    cycles_found: int = 0
    pruned_by_hops: int = 0
    pruned_by_window: int = 0
    pruned_by_cap: int = 0


class DFSCycleDetector:
    """Depth-first cycle detection for directed transfer multigraphs."""

    def __init__(
        self,
        *,
        max_hops: int = 8,
        max_window_minutes: int | None = 240,
        candidate_cap: int = 100,
        use_scc_pruning: bool = False,
    ) -> None:
        self.max_hops = max_hops
        self.max_window_minutes = max_window_minutes
        self.candidate_cap = candidate_cap
        self.use_scc_pruning = use_scc_pruning
        self.stats = TraversalStats()

    @staticmethod
    def _cycle_nodes_from_edges(edges: list[CircularEdge]) -> tuple[str, ...]:
        if not edges:
            return tuple()
        if len(edges) == 1:
            edge = edges[0]
            return (edge.sender,) if edge.sender == edge.receiver else (edge.sender, edge.receiver)
        nodes = [edges[0].sender]
        for edge in edges:
            nodes.append(edge.receiver)
        if nodes[0] == nodes[-1]:
            nodes = nodes[:-1]
        return tuple(nodes)

    @staticmethod
    def _canonical_txn_ids(edges: list[CircularEdge]) -> tuple[str, ...]:
        txn_ids = [edge.txn_id for edge in edges]
        if not txn_ids:
            return tuple()
        if len(txn_ids) == 1:
            return (txn_ids[0],)
        first = min(range(len(txn_ids)), key=lambda idx: txn_ids[idx])
        rotated = txn_ids[first:] + txn_ids[:first]
        return tuple(rotated)

    def _register_cycle(self, cycles: list[CycleCandidate], seen: set[tuple[str, ...]], path_edges: list[CircularEdge]) -> None:
        if not path_edges:
            return

        if len({edge.txn_id for edge in path_edges}) != len(path_edges):
            return

        currencies = {edge.currency for edge in path_edges}
        if len(currencies) != 1:
            return
        currency = next(iter(currencies))

        candidate_edges = list(path_edges)
        txn_signature = self._canonical_txn_ids(candidate_edges)
        if txn_signature in seen:
            return
        seen.add(txn_signature)

        cycle_nodes = self._cycle_nodes_from_edges(candidate_edges)
        total_amount = sum(int(edge.amount) for edge in candidate_edges)
        timestamps = [edge.timestamp for edge in candidate_edges]
        window_minutes = int((max(timestamps) - min(timestamps)).total_seconds() // 60) if timestamps else 0
        cycles.append(
            CycleCandidate(
                cycle=cycle_nodes,
                edges=txn_signature,
                total_amount=total_amount,
                currency=currency,
                window_minutes=window_minutes,
            )
        )

    def find_cycles(
        self,
        graph: MultiDiGraph,
        *,
        start_node: str | None = None,
        max_hops: int | None = None,
        max_window_minutes: int | None = None,
        candidate_cap: int | None = None,
    ) -> list[CycleCandidate]:
        self.stats = TraversalStats()

        limit_hops = self.max_hops if max_hops is None else max_hops
        limit_window = self.max_window_minutes if max_window_minutes is None else max_window_minutes
        limit_cap = self.candidate_cap if candidate_cap is None else candidate_cap

        ordered_nodes = sorted(graph.nodes)
        if start_node is not None:
            ordered_nodes = [start_node] + [node for node in ordered_nodes if node != start_node]

        cycles: list[CycleCandidate] = []
        seen: set[tuple[str, ...]] = set()

        def dfs(node: str, path_nodes: list[str], path_edges: list[CircularEdge], path_set: set[str]) -> None:
            if len(path_nodes) > limit_hops:
                self.stats.pruned_by_hops += 1
                return

            self.stats.nodes_visited += 1

            for edge in sorted(graph.neighbors(node), key=lambda item: (item.timestamp, item.txn_id)):
                self.stats.edges_traversed += 1
                if edge.txn_id in {item.txn_id for item in path_edges}:
                    continue

                if limit_window is not None and path_edges:
                    first_ts = path_edges[0].timestamp
                    if edge.timestamp < path_edges[-1].timestamp:
                        continue
                    if (edge.timestamp - first_ts).total_seconds() > limit_window * 60:
                        self.stats.pruned_by_window += 1
                        continue

                neighbor = edge.receiver
                if neighbor == node:
                    cycle_edges = [*path_edges, edge]
                    self._register_cycle(cycles, seen, cycle_edges)
                    self.stats.cycles_found += 1
                    if len(cycles) >= limit_cap:
                        self.stats.pruned_by_cap += 1
                        return
                    continue

                if neighbor in path_set:
                    cycle_start = path_nodes.index(neighbor)
                    cycle_edges = path_edges[cycle_start:] + [edge]
                    self._register_cycle(cycles, seen, cycle_edges)
                    self.stats.cycles_found += 1
                    if len(cycles) >= limit_cap:
                        self.stats.pruned_by_cap += 1
                        return
                    continue

                if len(path_nodes) >= limit_hops:
                    self.stats.pruned_by_hops += 1
                    continue

                if limit_window is not None and path_edges:
                    first_ts = path_edges[0].timestamp
                    if (edge.timestamp - first_ts).total_seconds() > limit_window * 60:
                        self.stats.pruned_by_window += 1
                        continue

                next_nodes = path_nodes + [neighbor]
                next_edges = path_edges + [edge]
                if len(next_nodes) > limit_hops:
                    self.stats.pruned_by_hops += 1
                    continue
                dfs(neighbor, next_nodes, next_edges, path_set | {neighbor})
                if len(cycles) >= limit_cap:
                    return

        for node in ordered_nodes:
            dfs(node, [node], [], {node})
            if len(cycles) >= limit_cap:
                break

        return cycles[:limit_cap]


def find_circular_cycles(
    graph: MultiDiGraph,
    *,
    max_hops: int = 8,
    max_window_minutes: int | None = 240,
    candidate_cap: int = 100,
    use_scc_pruning: bool = False,
) -> tuple[list[CycleCandidate], TraversalStats]:
    detector = DFSCycleDetector(
        max_hops=max_hops,
        max_window_minutes=max_window_minutes,
        candidate_cap=candidate_cap,
        use_scc_pruning=use_scc_pruning,
    )
    cycles = detector.find_cycles(graph)
    return cycles, detector.stats


__all__ = [
    "CycleCandidate",
    "DFSCycleDetector",
    "TraversalStats",
    "find_circular_cycles",
]
