"""Enrich SFinDSet.csv and inject deterministic PRD acceptance scenarios.

The transformation preserves every source row, adds explicit audit columns, and
places synthetic rows immediately after the header so spreadsheet previews show
them even though the source file already reaches Excel's row limit.
"""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path


EXTRA_COLUMNS = [
    "Branch_ID",
    "Ledger_Source",
    "Currency",
    "Counter_Currency",
    "Transaction_Status",
    "Posting_Date",
    "External_Reference",
    "Source_Revision",
    "Journal_ID",
    "Entry_Direction",
    "Description",
    "Scenario_Label",
    "Expected_Finding",
    "Is_Synthetic",
]


def synthetic_row(
    transaction_id: str,
    account_number: str,
    account_name: str,
    amount: str,
    mode: str,
    transaction_type: str,
    transaction_date: str,
    source: str,
    destination: str,
    *,
    branch: str,
    ledger: str = "INTERNAL_LEDGER",
    status: str = "POSTED",
    posting_date: str | None = None,
    external_reference: str | None = None,
    revision: str = "1",
    journal_id: str = "",
    direction: str | None = None,
    description: str = "",
    scenario: str,
    expected: str,
) -> dict[str, str]:
    currency_parts = transaction_type.split(" to ", maxsplit=1)
    return {
        "Transaction_ID": transaction_id,
        "Account_Number": account_number,
        "Account_Name": account_name,
        "Transaction_Amount": amount,
        "Transaction_Mode": mode,
        "Transaction_Type": transaction_type,
        "Transaction_Date": transaction_date,
        "Transaction_Source": source,
        "Transaction_Destination": destination,
        "Branch_ID": branch,
        "Ledger_Source": ledger,
        "Currency": currency_parts[0] if currency_parts else "",
        "Counter_Currency": currency_parts[1] if len(currency_parts) == 2 else "",
        "Transaction_Status": status,
        "Posting_Date": posting_date or transaction_date,
        "External_Reference": external_reference or transaction_id,
        "Source_Revision": revision,
        "Journal_ID": journal_id,
        "Entry_Direction": direction or ("CREDIT" if mode.endswith("In") else "DEBIT"),
        "Description": description or f"{mode} transaction for {account_name}",
        "Scenario_Label": scenario,
        "Expected_Finding": expected,
        "Is_Synthetic": "true",
    }


def build_synthetic_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    exact = synthetic_row(
        "SYN-DUP-EXACT-001", "9100000001", "Exact Replay Customer", "125000.00",
        "Transfer Out", "NGN to NGN", "1/10/2024 9:00", "9100000001", "9200000001",
        branch="BR-01", external_reference="EXT-REPLAY-001", scenario="EXACT_REPLAY",
        expected="DUPLICATE_EXACT",
    )
    rows.extend([exact, exact.copy()])

    rows.extend([
        synthetic_row(
            "SYN-DUP-FUZZY-001A", "9100000010", "Jonathan O'Connor", "250000.00",
            "Transfer Out", "NGN to NGN", "1/11/2024 10:00", "9100000010", "9200000010",
            branch="BR-01", ledger="BRANCH_LEDGER_A", external_reference="BR-A-4401",
            description="School fee transfer for Jonathan O'Connor", scenario="FUZZY_DUPLICATE",
            expected="DUPLICATE_FUZZY",
        ),
        synthetic_row(
            "SYN-DUP-FUZZY-001B", "9100000010", "Jonathon OConnor", "250000.00",
            "Transfer Out", "NGN to NGN", "1/11/2024 10:03", "9100000010", "9200000010",
            branch="BR-02", ledger="BRANCH_LEDGER_B", external_reference="BR-B-7712",
            description="Skool fee transfer for Jonathon OConnor", scenario="FUZZY_DUPLICATE",
            expected="DUPLICATE_FUZZY",
        ),
        synthetic_row(
            "SYN-DUP-INVERT-001A", "9100000020", "Inverted Fields Test", "88000.00",
            "Transfer Out", "USD to USD", "1/12/2024 11:00", "9100000020", "9200000020",
            branch="BR-03", external_reference="INV-A-001", scenario="INVERTED_FIELDS",
            expected="DUPLICATE_INVERTED",
        ),
        synthetic_row(
            "SYN-DUP-INVERT-001B", "9200000020", "Inverted Fields Test", "88000.00",
            "Transfer In", "USD to USD", "1/12/2024 11:01", "9200000020", "9100000020",
            branch="BR-04", ledger="BRANCH_LEDGER_B", external_reference="INV-B-001",
            scenario="INVERTED_FIELDS", expected="DUPLICATE_INVERTED",
        ),
    ])

    def reconciliation_pair(
        key: str, internal_amount: str, counterpart_amount: str, expected: str,
        *, counterpart_destination: str = "9300000001",
    ) -> None:
        rows.extend([
            synthetic_row(
                f"SYN-REC-{key}-INT", "9100000100", "Reconciliation Customer",
                internal_amount, "Transfer Out", "NGN to NGN", "1/15/2024 12:00",
                "9100000100", "9300000001", branch="BR-05", ledger="INTERNAL_LEDGER",
                external_reference=f"REC-{key}", scenario=f"RECONCILIATION_{key}", expected=expected,
            ),
            synthetic_row(
                f"SYN-REC-{key}-CTR", "9100000100", "Reconciliation Customer",
                counterpart_amount, "Transfer Out", "NGN to NGN", "1/15/2024 12:02",
                "9100000100", counterpart_destination, branch="BR-05",
                ledger="COUNTERPART_LEDGER", external_reference=f"REC-{key}",
                scenario=f"RECONCILIATION_{key}", expected=expected,
            ),
        ])

    reconciliation_pair("MATCH-001", "25000.00", "25000.00", "MATCHED")
    reconciliation_pair("AMOUNT-001", "25000.00", "24500.00", "AMOUNT_MISMATCH")
    reconciliation_pair(
        "FIELD-001", "15000.00", "15000.00", "FIELD_MISMATCH",
        counterpart_destination="9300000099",
    )
    rows.extend([
        synthetic_row(
            "SYN-REC-INTERNAL-ONLY", "9100000101", "Internal Only Customer", "70000.00",
            "Transfer Out", "NGN to NGN", "1/14/2024 8:00", "9100000101", "9300000101",
            branch="BR-05", ledger="INTERNAL_LEDGER", external_reference="REC-INTERNAL-ONLY",
            scenario="RECONCILIATION_INTERNAL_ONLY", expected="INTERNAL_ONLY",
        ),
        synthetic_row(
            "SYN-REC-COUNTERPART-ONLY", "9100000102", "Counterpart Only Customer", "71000.00",
            "Transfer Out", "NGN to NGN", "1/14/2024 8:05", "9100000102", "9300000102",
            branch="BR-05", ledger="COUNTERPART_LEDGER", external_reference="REC-COUNTERPART-ONLY",
            scenario="RECONCILIATION_COUNTERPART_ONLY", expected="COUNTERPART_ONLY",
        ),
        synthetic_row(
            "SYN-REC-PENDING-LATE", "9100000103", "Pending Late Customer", "72000.00",
            "Transfer Out", "NGN to NGN", "2/18/2024 11:50", "9100000103", "9300000103",
            branch="BR-05", ledger="INTERNAL_LEDGER", status="PENDING",
            posting_date="2/20/2024 11:50", external_reference="REC-PENDING-LATE",
            scenario="RECONCILIATION_PENDING_LATE", expected="PENDING_LATE",
        ),
    ])
    for suffix in ("A", "B"):
        rows.append(synthetic_row(
            f"SYN-REC-AMB-CTR-{suffix}", "9100000104", "Ambiguous Match Customer", "73000.00",
            "Transfer Out", "NGN to NGN", "1/16/2024 9:01", "9100000104", "9300000104",
            branch="BR-06", ledger="COUNTERPART_LEDGER", external_reference=f"REC-AMB-{suffix}",
            scenario="RECONCILIATION_AMBIGUOUS", expected="AMBIGUOUS",
        ))
    rows.append(synthetic_row(
        "SYN-REC-AMB-INT", "9100000104", "Ambiguous Match Customer", "73000.00",
        "Transfer Out", "NGN to NGN", "1/16/2024 9:00", "9100000104", "9300000104",
        branch="BR-06", ledger="INTERNAL_LEDGER", external_reference="REC-AMB-INT",
        scenario="RECONCILIATION_AMBIGUOUS", expected="AMBIGUOUS",
    ))

    for transaction_id, source, destination, amount, timestamp in [
        ("SYN-CYCLE-001-A", "9400000001", "9400000002", "100000.00", "1/20/2024 10:00"),
        ("SYN-CYCLE-001-B", "9400000002", "9400000003", "97000.00", "1/20/2024 10:05"),
        ("SYN-CYCLE-001-C", "9400000003", "9400000001", "95000.00", "1/20/2024 10:10"),
    ]:
        rows.append(synthetic_row(
            transaction_id, source, "Circular Flow Customer", amount, "Transfer Out",
            "NGN to NGN", timestamp, source, destination, branch="BR-07",
            scenario="VALID_TEMPORAL_CYCLE", expected="CIRCULAR_FLOW",
        ))
    for transaction_id, source, destination, timestamp in [
        ("SYN-CYCLE-BAD-A", "9410000001", "9410000002", "1/21/2024 10:00"),
        ("SYN-CYCLE-BAD-B", "9410000002", "9410000003", "1/21/2024 9:00"),
        ("SYN-CYCLE-BAD-C", "9410000003", "9410000001", "1/21/2024 11:00"),
    ]:
        rows.append(synthetic_row(
            transaction_id, source, "Invalid Cycle Control", "50000.00", "Transfer Out",
            "NGN to NGN", timestamp, source, destination, branch="BR-07",
            scenario="INVALID_TEMPORAL_CYCLE", expected="NONE",
        ))

    for index, (amount, timestamp) in enumerate([
        ("40000.00", "1/22/2024 14:00"),
        ("35000.00", "1/22/2024 14:20"),
        ("30000.00", "1/22/2024 14:40"),
    ], start=1):
        rows.append(synthetic_row(
            f"SYN-SPLIT-001-{index}", "9500000001", "Window Split Customer", amount,
            "Transfer Out", "NGN to NGN", timestamp, "9500000001", f"950000001{index}",
            branch="BR-08", scenario="SPLITTING_WITHIN_60_MIN", expected="TRANSACTION_SPLITTING",
        ))
    for index, timestamp in enumerate([
        "1/23/2024 8:00", "1/23/2024 10:00", "1/23/2024 12:00"
    ], start=1):
        rows.append(synthetic_row(
            f"SYN-SPLIT-CTRL-{index}", "9500000020", "Window Control Customer", "40000.00",
            "Transfer Out", "NGN to NGN", timestamp, "9500000020", f"950000003{index}",
            branch="BR-08", scenario="SPLITTING_OUTSIDE_WINDOW", expected="NONE",
        ))

    for transaction_id, amount, direction, journal_id, scenario, expected in [
        ("SYN-JRN-BAL-D", "10000.00", "DEBIT", "J-SYN-BAL-001", "BALANCED_JOURNAL", "BALANCED"),
        ("SYN-JRN-BAL-C", "10000.00", "CREDIT", "J-SYN-BAL-001", "BALANCED_JOURNAL", "BALANCED"),
        ("SYN-JRN-UNBAL-D", "10000.00", "DEBIT", "J-SYN-UNBAL-001", "UNBALANCED_JOURNAL", "UNBALANCED_JOURNAL"),
        ("SYN-JRN-UNBAL-C", "9000.00", "CREDIT", "J-SYN-UNBAL-001", "UNBALANCED_JOURNAL", "UNBALANCED_JOURNAL"),
    ]:
        rows.append(synthetic_row(
            transaction_id, "9600000001", "Journal Test Customer", amount,
            "Transfer Out" if direction == "DEBIT" else "Transfer In", "NGN to NGN",
            "1/24/2024 13:00", "9600000001", "9600000002", branch="BR-09",
            journal_id=journal_id, direction=direction, scenario=scenario, expected=expected,
        ))

    rows.extend([
        synthetic_row(
            "SYN-BAD-AMOUNT", "9700000001", "Malformed Amount", "not-a-number",
            "Transfer Out", "NGN to NGN", "1/25/2024 10:00", "9700000001", "9700000002",
            branch="BR-10", scenario="MALFORMED_AMOUNT", expected="INGEST_REJECT",
        ),
        synthetic_row(
            "SYN-BAD-DATE", "9700000002", "Malformed Date", "5000.00",
            "Transfer Out", "NGN to NGN", "not-a-date", "9700000002", "9700000003",
            branch="BR-10", scenario="MALFORMED_DATE", expected="INGEST_REJECT",
        ),
        synthetic_row(
            "SYN-NEG-AMOUNT", "9700000003", "Negative Amount", "-500.00",
            "Transfer Out", "NGN to NGN", "1/25/2024 10:05", "9700000003", "9700000004",
            branch="BR-10", scenario="NEGATIVE_AMOUNT", expected="INGEST_REJECT",
        ),
    ])
    return rows


def branch_for(account_number: str) -> str:
    digits = "".join(character for character in account_number if character.isdigit())
    branch_number = (int(digits[-4:]) if digits else 0) % 20 + 1
    return f"BR-{branch_number:02d}"


def enrich_source_row(row: dict[str, str]) -> dict[str, str]:
    transaction_type = row["Transaction_Type"].strip()
    currency_parts = transaction_type.split(" to ", maxsplit=1)
    mode = row["Transaction_Mode"].strip()
    transaction_date = row["Transaction_Date"].strip()
    transaction_id = row["Transaction_ID"].strip()
    account_name = row["Account_Name"].strip()
    row.update({
        "Branch_ID": branch_for(row["Account_Number"]),
        "Ledger_Source": "LEGACY_SOURCE",
        "Currency": currency_parts[0] if currency_parts else "",
        "Counter_Currency": currency_parts[1] if len(currency_parts) == 2 else "",
        "Transaction_Status": "POSTED",
        "Posting_Date": transaction_date,
        "External_Reference": transaction_id,
        "Source_Revision": "1",
        "Journal_ID": "",
        "Entry_Direction": "CREDIT" if mode.endswith("In") else "DEBIT",
        "Description": f"{mode} transaction for {account_name}",
        "Scenario_Label": "BASELINE",
        "Expected_Finding": "",
        "Is_Synthetic": "false",
    })
    return row


def augment(dataset_path: Path) -> tuple[int, int]:
    temporary_path = dataset_path.with_suffix(dataset_path.suffix + ".augmenting")
    synthetic_rows = build_synthetic_rows()
    source_rows = 0

    try:
        with dataset_path.open("r", encoding="utf-8-sig", newline="") as source_file:
            reader = csv.DictReader(source_file)
            if reader.fieldnames is None:
                raise ValueError("Dataset has no header")
            if "Scenario_Label" in reader.fieldnames:
                raise ValueError("Dataset is already augmented; refusing to duplicate scenarios")
            fieldnames = [*reader.fieldnames, *EXTRA_COLUMNS]

            with temporary_path.open("w", encoding="utf-8", newline="") as output_file:
                writer = csv.DictWriter(output_file, fieldnames=fieldnames, lineterminator="\n")
                writer.writeheader()
                writer.writerows(synthetic_rows)
                for row in reader:
                    writer.writerow(enrich_source_row(row))
                    source_rows += 1
        os.replace(temporary_path, dataset_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise

    return source_rows, len(synthetic_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dataset",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "SFinDSet.csv",
    )
    args = parser.parse_args()
    source_rows, synthetic_rows = augment(args.dataset.resolve())
    print(
        f"Augmented {args.dataset}: preserved {source_rows} source rows and "
        f"inserted {synthetic_rows} synthetic scenario rows."
    )


if __name__ == "__main__":
    main()
