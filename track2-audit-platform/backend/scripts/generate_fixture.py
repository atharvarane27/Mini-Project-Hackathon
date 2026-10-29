"""Deterministic, seeded fixture generator for Track 2 AuditForge Platform.

Generates realistic CSV datasets in fixtures/:
- fixtures/ledger_internal.csv
- fixtures/ledger_counterpart.csv
- fixtures/malformed_records.csv
- fixtures/circular_transfers.csv
- fixtures/splitting_transfers.csv
"""

from __future__ import annotations

import csv
import os
import random
from datetime import datetime, timedelta, timezone

SEED = 42

CSV_HEADERS = [
    "Transaction_ID",
    "Account_Number",
    "Account_Name",
    "Transaction_Amount",
    "Transaction_Mode",
    "Transaction_Type",
    "Transaction_Date",
    "Transaction_Source",
    "Transaction_Destination",
    "Branch_ID",
    "Ledger_Source",
    "Currency",
    "Transaction_Status",
    "Posting_Date",
    "External_Reference",
    "Source_Revision",
    "Entry_Direction",
    "Description",
]


def make_row(
    txn_id: str,
    acc_num: str,
    acc_name: str,
    amount: str,
    date_str: str,
    source: str,
    destination: str,
    branch: str = "BR-MUMBAI",
    ledger: str = "SRC_INTERNAL_CORE",
    currency: str = "INR",
    direction: str = "DEBIT",
    status: str = "POSTED",
    ext_ref: str | None = None,
    revision: int = 1,
    desc: str | None = None,
) -> dict[str, str]:
    return {
        "Transaction_ID": txn_id,
        "Account_Number": acc_num,
        "Account_Name": acc_name,
        "Transaction_Amount": amount,
        "Transaction_Mode": "Transfer Out" if direction == "DEBIT" else "Transfer In",
        "Transaction_Type": "NEFT",
        "Transaction_Date": date_str,
        "Transaction_Source": source,
        "Transaction_Destination": destination,
        "Branch_ID": branch,
        "Ledger_Source": ledger,
        "Currency": currency,
        "Transaction_Status": status,
        "Posting_Date": date_str,
        "External_Reference": ext_ref or txn_id,
        "Source_Revision": str(revision),
        "Entry_Direction": direction,
        "Description": desc or f"Transfer {ext_ref or txn_id} from {source} to {destination}",
    }


def write_csv(file_path: str, rows: list[dict[str, str]]) -> None:
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def generate_fixtures(base_dir: str | None = None) -> None:
    rng = random.Random(SEED)
    if base_dir is None:
        base_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "fixtures")
        )

    base_time = datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc)

    # 1. Internal Ledger (Clean reference batch)
    internal_rows: list[dict[str, str]] = []
    for i in range(1, 101):
        dt = (base_time + timedelta(minutes=i * 5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        src = f"acc-mum-{1000 + (i % 20)}"
        dst = f"acc-del-{2000 + (i % 20)}"
        amt = f"{rng.randint(1000, 500000)}.{rng.randint(10, 99)}"
        internal_rows.append(
            make_row(
                txn_id=f"TXN-INT-{i:04d}",
                acc_num=src,
                acc_name=f"Customer {i}",
                amount=amt,
                date_str=dt,
                source=src,
                destination=dst,
                branch="BR-MUMBAI",
                ledger="SRC_INTERNAL_CORE",
                ext_ref=f"EXT-REF-{i:04d}",
            )
        )
    write_csv(os.path.join(base_dir, "ledger_internal.csv"), internal_rows)

    # 2. Counterpart Ledger (Matching + slight variance for reconciliation)
    counterpart_rows: list[dict[str, str]] = []
    for i, int_row in enumerate(internal_rows[:80], start=1):
        dt = int_row["Transaction_Date"]
        # Introduce a few slight amount variances for reconciliation tests
        amt = int_row["Transaction_Amount"]
        if i in (10, 20):
            amt = f"{float(amt) + 500.0:.2f}"
        counterpart_rows.append(
            make_row(
                txn_id=f"TXN-CP-{i:04d}",
                acc_num=int_row["Transaction_Destination"],
                acc_name=f"Counterparty {i}",
                amount=amt,
                date_str=dt,
                source=int_row["Transaction_Source"],
                destination=int_row["Transaction_Destination"],
                branch="BR-DELHI",
                ledger="SRC_CLEARING_HOUSE",
                ext_ref=int_row["External_Reference"],
            )
        )
    write_csv(os.path.join(base_dir, "ledger_counterpart.csv"), counterpart_rows)

    # 3. Malformed Records (Diagnostic error verification)
    malformed_rows = [
        # Valid control row
        make_row("MAL-001", "acc-1", "User 1", "5000.00", "2026-10-29T10:00:00Z", "acc-1", "acc-2", ext_ref="EXT-VAL-01"),
        # Negative amount
        make_row("MAL-002", "acc-1", "User 2", "-500.00", "2026-10-29T10:05:00Z", "acc-1", "acc-2", ext_ref="EXT-ERR-02"),
        # Zero amount
        make_row("MAL-003", "acc-1", "User 3", "0.00", "2026-10-29T10:10:00Z", "acc-1", "acc-2", ext_ref="EXT-ERR-03"),
        # Invalid date
        make_row("MAL-004", "acc-1", "User 4", "1500.00", "INVALID_DATE_STRING", "acc-1", "acc-2", ext_ref="EXT-ERR-04"),
        # Missing external reference
        make_row("MAL-005", "acc-1", "User 5", "2000.00", "2026-10-29T10:15:00Z", "acc-1", "acc-2", ext_ref=""),
        # Invalid currency
        make_row("MAL-006", "acc-1", "User 6", "2500.00", "2026-10-29T10:20:00Z", "acc-1", "acc-2", currency="TOOLONG", ext_ref="EXT-ERR-06"),
        # Identical sender and receiver
        make_row("MAL-007", "acc-1", "User 7", "3000.00", "2026-10-29T10:25:00Z", "acc-1", "acc-1", ext_ref="EXT-ERR-07"),
        # Another valid control row
        make_row("MAL-008", "acc-1", "User 8", "7500.00", "2026-10-29T10:30:00Z", "acc-1", "acc-3", ext_ref="EXT-VAL-08"),
    ]
    write_csv(os.path.join(base_dir, "malformed_records.csv"), malformed_rows)

    # 4. Circular Transfers (A -> B -> C -> A)
    circ_t = datetime(2026, 10, 29, 11, 0, tzinfo=timezone.utc)
    circular_rows = [
        make_row("CIRC-01", "acc-circ-A", "Corp A", "500000.00", circ_t.strftime("%Y-%m-%dT%H:%M:%SZ"), "acc-circ-A", "acc-circ-B", ext_ref="EXT-CIRC-01"),
        make_row("CIRC-02", "acc-circ-B", "Corp B", "495000.00", (circ_t + timedelta(minutes=8)).strftime("%Y-%m-%dT%H:%M:%SZ"), "acc-circ-B", "acc-circ-C", ext_ref="EXT-CIRC-02"),
        make_row("CIRC-03", "acc-circ-C", "Corp C", "490000.00", (circ_t + timedelta(minutes=18)).strftime("%Y-%m-%dT%H:%M:%SZ"), "acc-circ-C", "acc-circ-A", ext_ref="EXT-CIRC-03"),
    ]
    write_csv(os.path.join(base_dir, "circular_transfers.csv"), circular_rows)

    # 5. Splitting Transfers (Amounts right under 100,000 INR threshold within 60 mins)
    split_t = datetime(2026, 10, 29, 14, 0, tzinfo=timezone.utc)
    split_rows = [
        make_row("SPLIT-01", "acc-split-S", "Splitting Sender", "35000.00", split_t.strftime("%Y-%m-%dT%H:%M:%SZ"), "acc-split-S", "acc-split-R", ext_ref="EXT-SPLIT-01"),
        make_row("SPLIT-02", "acc-split-S", "Splitting Sender", "38000.00", (split_t + timedelta(minutes=12)).strftime("%Y-%m-%dT%H:%M:%SZ"), "acc-split-S", "acc-split-R", ext_ref="EXT-SPLIT-02"),
        make_row("SPLIT-03", "acc-split-S", "Splitting Sender", "32000.00", (split_t + timedelta(minutes=25)).strftime("%Y-%m-%dT%H:%M:%SZ"), "acc-split-S", "acc-split-R", ext_ref="EXT-SPLIT-03"),
    ]
    write_csv(os.path.join(base_dir, "splitting_transfers.csv"), split_rows)


if __name__ == "__main__":
    generate_fixtures()
    print("Deterministic fixtures successfully generated in fixtures/ directory.")
