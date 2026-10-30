"""Scaffold for backend/app/engines/circular/dfs; implementation pending."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.engines.circular.graph import MultiDiGraph

WHITE = 0
GRAY = 1
BLACK = 2


@dataclass(frozen=True)
class CycleCandidate:
    cycle: tuple[str, ...]
    edges: tuple[str, ...]
    total_amount: float
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

    def _canonical_cycle(self, nodes: list[str]) -> tuple[str, ...]:
        if not nodes:
            return tuple()
        normalized = list(dict.fromkeys(nodes))
        if len(normalized) == 1:
            return (normalized[0],)
        rotations = [tuple(normalized[i:] + normalized[:i]) for i in range(len(normalized))]
        return min(rotations)

    def _register_cycle(self, cycles: list[CycleCandidate], seen: set[tuple[str, ...]], path: list[str], graph: MultiDiGraph) -> None:
        if not path:
            return
        candidate = self._canonical_cycle(path)
        if len(candidate) == 1 and path != [path[0], path[0]]:
            return
        if candidate in seen:
            return
        seen.add(candidate)
        edges: list[str] = []
        for idx, node in enumerate(candidate[:-1]):
            for edge in graph.neighbors(node):
                if edge.receiver == candidate[idx + 1]:
                    edges.append(edge.txn_id)
                    break
        if not edges and len(candidate) > 1:
            for edge in graph.neighbors(candidate[-1]):
                if edge.receiver == candidate[0]:
                    edges.append(edge.txn_id)
                    break
        amounts: list[float] = []
        currencies: set[str] = set()
        for idx, node in enumerate(candidate[:-1]):
            for edge in graph.neighbors(node):
                if edge.receiver == candidate[idx + 1]:
                    amounts.append(float(edge.amount))
                    currencies.add(edge.currency)
        if not amounts and len(candidate) > 1:
            for idx, node in enumerate(candidate):
                for edge in graph.neighbors(node):
                    if edge.receiver == candidate[(idx + 1) % len(candidate)]:
                        amounts.append(float(edge.amount))
                        currencies.add(edge.currency)
        total_amount = sum(amounts) if amounts else 0.0
        currency = sorted(currencies)[0] if currencies else "USD"
        timestamps: list[datetime] = []
        for idx, node in enumerate(candidate[:-1]):
            for edge in graph.neighbors(node):
                if edge.receiver == candidate[idx + 1]:
                    timestamps.append(edge.timestamp)
        if not timestamps and len(candidate) == 1:
            timestamps = [edge.timestamp for edge in graph.neighbors(candidate[0]) if edge.receiver == candidate[0]]
        window_minutes = int((max(timestamps) - min(timestamps)).total_seconds() // 60) if timestamps else 0
        cycles.append(
            CycleCandidate(
                cycle=candidate,
                edges=tuple(edges),
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

        color: dict[str, int] = {node: WHITE for node in ordered_nodes}
        cycles: list[CycleCandidate] = []
        seen: set[tuple[str, ...]] = set()

        def dfs(node: str, path: list[str], path_start: datetime | None) -> None:
            if len(path) > limit_hops:
                self.stats.pruned_by_hops += 1
                return

            self.stats.nodes_visited += 1
            color[node] = GRAY

            for edge in sorted(graph.neighbors(node), key=lambda item: (item.timestamp, item.txn_id)):
                self.stats.edges_traversed += 1
                if path_start is None:
                    path_start = edge.timestamp
                if limit_window is not None and path_start is not None:
                    if abs((edge.timestamp - path_start).total_seconds()) > limit_window * 60:
                        self.stats.pruned_by_window += 1
                        continue

                neighbor = edge.receiver
                if neighbor == node:
                    cycle_path = [node, node]
                    self._register_cycle(cycles, seen, cycle_path, graph)
                    self.stats.cycles_found += 1
                    if len(cycles) >= limit_cap:
                        self.stats.pruned_by_cap += 1
                        return
                    continue

                if neighbor in path:
                    cycle_path = path[path.index(neighbor):] + [neighbor]
                    self._register_cycle(cycles, seen, cycle_path, graph)
                    self.stats.cycles_found += 1
                    if len(cycles) >= limit_cap:
                        self.stats.pruned_by_cap += 1
                        return
                    continue

                if len(path) >= limit_hops:
                    self.stats.pruned_by_hops += 1
                    continue
                if color.get(neighbor, WHITE) == WHITE:
                    dfs(neighbor, path + [neighbor], path_start)
                    if len(cycles) >= limit_cap:
                        return

            color[node] = BLACK

        for node in ordered_nodes:
            if color[node] == WHITE:
                dfs(node, [node], None)
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
