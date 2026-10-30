"""Bounded DFS recursion-stack search for directed transfer cycles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from .graph import TransferMultigraph
from .temporal_validator import CircularTransfer, CycleCandidate


@dataclass(frozen=True, slots=True)
class CycleSearchLimits:
    max_hops: int = 8
    max_window_minutes: int = 1_440
    max_candidates: int = 10_000

    def __post_init__(self) -> None:
        if self.max_hops <= 0 or self.max_window_minutes <= 0 or self.max_candidates <= 0:
            raise ValueError("cycle search limits must be positive")


@dataclass(frozen=True, slots=True)
class TraversalStats:
    start_nodes: int
    edges_examined: int
    hop_prunes: int
    window_prunes: int
    repeated_node_prunes: int
    duplicate_cycles: int
    candidates_found: int
    maximum_depth: int


@dataclass(frozen=True, slots=True)
class CycleSearchResult:
    candidates: tuple[CycleCandidate, ...]
    stats: TraversalStats


def find_cycle_candidates(
    graph: TransferMultigraph,
    limits: CycleSearchLimits | None = None,
) -> CycleSearchResult:
    configured = limits or CycleSearchLimits()
    found: dict[tuple[str, ...], CycleCandidate] = {}
    edges_examined = hop_prunes = window_prunes = repeated_prunes = duplicates = 0
    maximum_depth = 0

    for start in graph.nodes():
        path_accounts = [start]
        path_edges: list[CircularTransfer] = []
        recursion_stack = {start}

        def visit(account_id: str) -> None:
            nonlocal edges_examined, hop_prunes, window_prunes
            nonlocal repeated_prunes, duplicates, maximum_depth
            maximum_depth = max(maximum_depth, len(path_edges))
            for edge in graph.outgoing(account_id):
                edges_examined += 1
                next_depth = len(path_edges) + 1
                maximum_depth = max(maximum_depth, next_depth)
                if next_depth > configured.max_hops:
                    hop_prunes += 1
                    continue
                proposed = (*path_edges, edge)
                timestamps = [item.occurred_at for item in proposed]
                if max(timestamps) - min(timestamps) > timedelta(
                    minutes=configured.max_window_minutes
                ):
                    window_prunes += 1
                    continue
                target = edge.receiver_account_id
                if target == start:
                    key = tuple(sorted(item.transaction_id for item in proposed))
                    if key in found:
                        duplicates += 1
                    elif len(found) < configured.max_candidates:
                        found[key] = CycleCandidate(
                            tuple((*path_accounts, start)), tuple(proposed)
                        )
                    continue
                if target in recursion_stack:
                    repeated_prunes += 1
                    continue
                if next_depth == configured.max_hops:
                    hop_prunes += 1
                    continue
                recursion_stack.add(target)
                path_accounts.append(target)
                path_edges.append(edge)
                visit(target)
                path_edges.pop()
                path_accounts.pop()
                recursion_stack.remove(target)

        visit(start)

    candidates = tuple(found[key] for key in sorted(found))
    return CycleSearchResult(
        candidates,
        TraversalStats(
            start_nodes=graph.node_count,
            edges_examined=edges_examined,
            hop_prunes=hop_prunes,
            window_prunes=window_prunes,
            repeated_node_prunes=repeated_prunes,
            duplicate_cycles=duplicates,
            candidates_found=len(candidates),
            maximum_depth=maximum_depth,
        ),
    )
