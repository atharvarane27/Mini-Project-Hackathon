from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Generator, Iterator
from dataclasses import dataclass
from typing import BinaryIO, TextIO


@dataclass(frozen=True)
class RawRowRecord:
    """A raw row extracted from the streaming CSV reader.

    Contains 1-based line number (data row) and deterministic payload hash.
    """

    row_number: int
    data: dict[str, str]
    payload_hash: str


def compute_payload_hash(data: dict[str, str]) -> str:
    """Compute deterministic SHA-256 hash of a raw row dictionary."""
    canonical_bytes = json.dumps(data, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()


class BoundedCSVReader:
    """Bounded streaming CSV reader that never loads the entire file into memory.

    Streams rows from a text stream, file path, or binary file object
    (e.g., FastAPI UploadFile.file). Yields batches of RawRowRecord to bound memory usage.
    """

    def __init__(self, batch_size: int = 500) -> None:
        self.batch_size = batch_size

    def stream_rows(self, stream: TextIO) -> Iterator[RawRowRecord]:
        """Stream raw row records one-by-one from an open text stream."""
        reader = csv.reader(stream)
        try:
            raw_header = next(reader)
        except StopIteration:
            return

        # Strip whitespace and BOM from headers
        headers = [h.strip().lstrip("\ufeff") for h in raw_header]

        for line_idx, row in enumerate(reader, start=1):
            if not row or not any(field.strip() for field in row):
                continue  # skip completely empty lines

            # Pad or truncate row to header length
            row_dict: dict[str, str] = {}
            for col_idx, col_name in enumerate(headers):
                if not col_name:
                    continue
                val = row[col_idx] if col_idx < len(row) else ""
                row_dict[col_name] = val.strip()

            p_hash = compute_payload_hash(row_dict)
            yield RawRowRecord(row_number=line_idx, data=row_dict, payload_hash=p_hash)

    def stream_batches(self, stream: TextIO) -> Generator[list[RawRowRecord], None, None]:
        """Yield bounded batches of RawRowRecord from a text stream."""
        batch: list[RawRowRecord] = []
        for row in self.stream_rows(stream):
            batch.append(row)
            if len(batch) >= self.batch_size:
                yield batch
                batch = []
        if batch:
            yield batch

    def stream_file_batches(self, file_path: str) -> Generator[list[RawRowRecord], None, None]:
        """Yield bounded batches from a file path."""
        with open(file_path, encoding="utf-8-sig", newline="") as f:
            yield from self.stream_batches(f)

    def stream_binary_batches(
        self, binary_stream: BinaryIO
    ) -> Generator[list[RawRowRecord], None, None]:
        """Yield bounded batches from a binary stream (e.g. UploadFile.file)."""
        text_stream = io.TextIOWrapper(binary_stream, encoding="utf-8-sig", newline="")
        try:
            yield from self.stream_batches(text_stream)
        finally:
            text_stream.detach()
