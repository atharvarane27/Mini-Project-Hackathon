"""Repeatable time and peak-memory benchmarks for custom algorithms."""

from __future__ import annotations

import argparse
import gc
import json
import platform
import statistics
import tracemalloc
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter

from app.engines.circular.dfs import CycleSearchLimits, find_cycle_candidates
from app.engines.circular.graph import TransferMultigraph
from app.engines.circular.temporal_validator import CircularTransfer
from app.engines.identity.blocking import BlockingPolicy
from app.engines.identity.inverted_index import InvertedIndex
from app.engines.identity.levenshtein import bounded_levenshtein
from app.engines.identity.resolver import IdentityRecord
from app.engines.queue.binary_heap import BinaryMaxHeap, HeapEntry
from app.engines.reconciliation.matcher import LedgerEntry, reconcile_entries
from app.engines.rules.lexer import tokenize
from app.engines.rules.parser import parse_tokens
from app.engines.splitting.partition import SplittingPolicy, TransferEvent
from app.engines.splitting.window import detect_splitting_windows
from app.engines.workflow.dag import TaskEdge, TaskNode, WorkflowDag
from app.engines.workflow.toposort import topological_sort


START = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    name: str
    input_size: int
    operations: int
    median_ms: float
    minimum_ms: float
    peak_kib: float
    result_size: int
    assumption: str


def measure(
    name: str,
    input_size: int,
    operations: int,
    workload: Callable[[], int],
    assumption: str,
    *,
    repeats: int,
) -> BenchmarkResult:
    workload()
    timings: list[float] = []
    peaks: list[int] = []
    result_size = 0
    for _ in range(repeats):
        gc.collect()
        tracemalloc.start()
        started = perf_counter()
        result_size = workload()
        timings.append((perf_counter() - started) * 1_000)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peaks.append(peak)
    return BenchmarkResult(
        name=name,
        input_size=input_size,
        operations=operations,
        median_ms=round(statistics.median(timings), 3),
        minimum_ms=round(min(timings), 3),
        peak_kib=round(max(peaks) / 1_024, 1),
        result_size=result_size,
        assumption=assumption,
    )


def identity_record(index: int) -> IdentityRecord:
    return IdentityRecord(
        f"record-{index}", f"REF-{index % 500}", f"S-{index % 250}",
        f"R-{index % 300}", f"Sender {index % 500}",
        f"Receiver {index % 500}", 100_000 + index % 10_000, "INR",
        START + timedelta(seconds=index),
    )


def index_workload(size: int) -> Callable[[], int]:
    records = tuple(identity_record(index) for index in range(size))

    def execute() -> int:
        index = InvertedIndex(BlockingPolicy(max_bucket_size=1_000))
        for record in records:
            index.insert(record)
        for record in records[:: max(1, size // 100)]:
            index.candidates_for(record)
        return index.metrics().posting_count

    return execute


def edit_distance_workload(size: int) -> Callable[[], int]:
    def execute() -> int:
        matches = 0
        for index in range(size):
            left = f"transaction-reference-{index:08d}"
            right = f"transaction-refernece-{index:08d}"
            matches += bounded_levenshtein(left, right, 3) or 0
        return matches

    return execute


def graph_workload(size: int) -> Callable[[], int]:
    transfers = tuple(
        CircularTransfer(
            f"T-{index}", f"A-{index}", f"A-{index + 1}", 1_000_000,
            "INR", START + timedelta(seconds=index),
        )
        for index in range(size)
    )

    def execute() -> int:
        result = find_cycle_candidates(
            TransferMultigraph(transfers),
            CycleSearchLimits(max_hops=6, max_window_minutes=60),
        )
        return result.stats.edges_examined

    return execute


def splitting_workload(partitions: int) -> Callable[[], int]:
    events = tuple(
        TransferEvent(
            f"S-{account}-{part}", f"A-{account}", f"R-{account}-{part}",
            amount, "INR", START + timedelta(minutes=part * 10), "TRANSFER",
        )
        for account in range(partitions)
        for part, amount in enumerate((4_000_000, 3_500_000, 3_000_000))
    )
    policy = SplittingPolicy(
        version=1, window_minutes=60, amount_threshold_minor=10_000_000,
        min_count=3, individual_max_minor=9_999_999, max_window_events=100,
    )

    def execute() -> int:
        return len(detect_splitting_windows(events, policy))

    return execute


def reconciliation_workload(size: int) -> Callable[[], int]:
    left = tuple(
        LedgerEntry(
            f"left-{index}", "internal", f"REF-{index}",
            f"A-{index % 100}", f"B-{index % 100}", 100_000 + index,
            "INR", START + timedelta(seconds=index),
        )
        for index in range(size)
    )
    right = tuple(
        LedgerEntry(
            f"right-{index}", "clearing", f"REF-{index}",
            f"A-{index % 100}", f"B-{index % 100}", 100_000 + index,
            "INR", START + timedelta(seconds=index),
        )
        for index in range(size)
    )

    def execute() -> int:
        return len(reconcile_entries(left, right, cutoff_at=START))

    return execute


def parser_workload(size: int) -> Callable[[], int]:
    expression = (
        "(Reconciliation_Variance_Minor > 50000 AND Balance_Anomaly_Flag == TRUE) "
        "OR (Circular_Flow_Detected == TRUE AND Cycle_Length >= 3) "
        "OR (Splitting_Window_Sum_Minor >= 10000000 AND "
        "Splitting_Window_Count >= 3)"
    )

    def execute() -> int:
        for _ in range(size):
            parse_tokens(tokenize(expression))
        return size

    return execute


def heap_workload(size: int) -> Callable[[], int]:
    entries = tuple(
        HeapEntry(index % 101, index, f"case-{index:06d}", 1)
        for index in range(size)
    )

    def execute() -> int:
        heap = BinaryMaxHeap()
        for entry in reversed(entries):
            heap.push(entry)
        while len(heap):
            heap.pop()
        return len(entries)

    return execute


def topology_workload(size: int) -> Callable[[], int]:
    nodes = tuple(
        TaskNode(f"task-{index:06d}", f"Task {index}") for index in range(size)
    )
    edges = tuple(
        TaskEdge(f"task-{index:06d}", f"task-{index + 1:06d}")
        for index in range(size - 1)
    )

    def execute() -> int:
        return len(topological_sort(WorkflowDag(nodes, edges)))

    return execute


def run_benchmarks(*, quick: bool, repeats: int) -> dict[str, object]:
    scale = 400 if quick else 2_000
    parser_runs = 100 if quick else 1_000
    partitions = 100 if quick else 1_000
    definitions = (
        ("inverted_index", scale, scale + 100, index_workload(scale), "O(N*K) build; 100 bounded candidate lookups"),
        ("bounded_edit_distance", scale, scale, edit_distance_workload(scale), "O(A*B) worst-case with bound-based exits"),
        ("ledger_reconciliation", scale * 2, scale * 2, reconciliation_workload(scale), "Reference hash join plus bounded composite fallback; average O(N+M)"),
        ("bounded_cycle_search", scale, scale, graph_workload(scale), "Sparse chain, max_hops=6; worst case is exponential in hop bound"),
        ("sliding_windows", partitions * 3, partitions * 3, splitting_workload(partitions), "Three ordered events per independent partition"),
        ("lexer_parser", parser_runs, parser_runs, parser_workload(parser_runs), "Fixed typed rule parsed repeatedly"),
        ("binary_heap", scale, scale * 2, heap_workload(scale), "N pushes plus N pops, each O(log N)"),
        ("topological_sort", scale, scale * 2 - 1, topology_workload(scale), "Single-chain DAG; O(V+E)"),
    )
    results = [
        asdict(measure(name, size, operations, workload, assumption, repeats=repeats))
        for name, size, operations, workload, assumption in definitions
    ]
    return {
        "schema_version": 1,
        "profile": "quick" if quick else "standard",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "measurement": "median wall time; maximum tracemalloc peak across repeats",
        "repeats": repeats,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.repeats <= 0:
        raise SystemExit("--repeats must be positive")
    report = run_benchmarks(quick=args.quick, repeats=args.repeats)
    report["measured_at_utc"] = datetime.now(UTC).isoformat()
    serialized = json.dumps(report, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()
