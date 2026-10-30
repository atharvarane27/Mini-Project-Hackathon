"""Bounded-batch CSV streaming without whole-file materialization."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TextIO


class CsvStructureError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CsvRow:
    row_number: int
    values: dict[str, str]


def stream_csv_batches(
    stream: TextIO,
    *,
    required_columns: frozenset[str],
    batch_size: int = 500,
    max_field_characters: int = 100_000,
) -> Iterator[tuple[CsvRow, ...]]:
    if batch_size <= 0 or max_field_characters <= 0:
        raise ValueError("CSV bounds must be positive")
    csv.field_size_limit(max_field_characters)
    reader = csv.DictReader(stream)
    headers = set(reader.fieldnames or ())
    missing = required_columns - headers
    if missing:
        raise CsvStructureError(f"missing mandatory columns: {sorted(missing)}")
    batch: list[CsvRow] = []
    for row_number, row in enumerate(reader, start=2):
        if None in row:
            raise CsvStructureError(f"row {row_number} has extra columns")
        values = {key: value or "" for key, value in row.items()}
        if any(len(value) > max_field_characters for value in values.values()):
            raise CsvStructureError(f"row {row_number} exceeds field limit")
        batch.append(CsvRow(row_number, values))
        if len(batch) == batch_size:
            yield tuple(batch)
            batch.clear()
    if batch:
        yield tuple(batch)
