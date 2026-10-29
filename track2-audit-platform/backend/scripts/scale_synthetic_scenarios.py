"""Add 100,000 deterministic, labelled load-test rows to an augmented dataset."""

from __future__ import annotations

import argparse
import csv
import os
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

from augment_dataset import synthetic_row


ROWS_TO_ADD = 100_000


def account(namespace: int, case: int, member: int = 0) -> str:
    return str(7_000_000_000 + namespace * 10_000_000 + case * 10 + member)


def branch(case: int) -> str:
    return f"BR-{case % 20 + 1:02d}"


def timestamp(case: int, offset_minutes: int = 0) -> str:
    value = datetime(2023, 1, 1) + timedelta(minutes=case * 7 + offset_minutes)
    return value.strftime("%m/%d/%Y %H:%M")


def make_row(
    transaction_id: str,
    account_number: str,
    name: str,
    amount: str,
    date: str,
    source: str,
    destination: str,
    *,
    case: int,
    scenario: str,
    expected: str,
    mode: str = "Transfer Out",
    transaction_type: str = "NGN to NGN",
    **kwargs: str,
) -> dict[str, str]:
    return synthetic_row(
        transaction_id,
        account_number,
        name,
        amount,
        mode,
        transaction_type,
        date,
        source,
        destination,
        branch=branch(case),
        scenario=f"BULK_{scenario}",
        expected=expected,
        **kwargs,
    )


def generate_rows() -> Iterator[dict[str, str]]:
    # 8,000 rows: 4,000 exact replay pairs.
    for case in range(4_000):
        source, destination = account(1, case), account(1, case, 1)
        row = make_row(
            f"SYN-BULK-EXACT-{case:05d}", source, f"Exact Replay {case}",
            f"{10000 + case}.00", timestamp(case), source, destination,
            case=case, scenario="EXACT_REPLAY", expected="DUPLICATE_EXACT",
            external_reference=f"BULK-EXACT-REF-{case:05d}",
        )
        yield row
        yield row.copy()

    # 8,000 rows: 4,000 fuzzy pairs with spelling and description changes.
    for case in range(4_000):
        source, destination = account(2, case), account(2, case, 1)
        common = dict(
            account_number=source,
            amount=f"{20000 + case}.00",
            source=source,
            destination=destination,
            case=case,
            scenario="FUZZY_DUPLICATE",
            expected="DUPLICATE_FUZZY",
        )
        yield make_row(
            f"SYN-BULK-FUZZ-{case:05d}-A", name=f"Christopher Johnson {case}",
            date=timestamp(case), description=f"Education payment Christopher Johnson {case}",
            external_reference=f"BULK-FUZZ-A-{case:05d}", ledger="BRANCH_LEDGER_A", **common,
        )
        yield make_row(
            f"SYN-BULK-FUZZ-{case:05d}-B", name=f"Cristopher Jonson {case}",
            date=timestamp(case, 3), description=f"Educaton paymnt Cristopher Jonson {case}",
            external_reference=f"BULK-FUZZ-B-{case:05d}", ledger="BRANCH_LEDGER_B", **common,
        )

    # 4,000 rows: 2,000 source/destination inversion pairs.
    for case in range(2_000):
        left, right = account(3, case), account(3, case, 1)
        yield make_row(
            f"SYN-BULK-INV-{case:05d}-A", left, f"Inversion Test {case}",
            f"{30000 + case}.00", timestamp(case), left, right,
            case=case, scenario="INVERTED_FIELDS", expected="DUPLICATE_INVERTED",
            external_reference=f"BULK-INV-A-{case:05d}",
        )
        yield make_row(
            f"SYN-BULK-INV-{case:05d}-B", right, f"Inversion Test {case}",
            f"{30000 + case}.00", timestamp(case, 1), right, left,
            case=case, scenario="INVERTED_FIELDS", expected="DUPLICATE_INVERTED",
            mode="Transfer In", external_reference=f"BULK-INV-B-{case:05d}",
            ledger="BRANCH_LEDGER_B",
        )

    # 8,000 matched reconciliation rows.
    for case in range(4_000):
        source, destination = account(4, case), account(4, case, 1)
        for ledger, suffix in (("INTERNAL_LEDGER", "INT"), ("COUNTERPART_LEDGER", "CTR")):
            yield make_row(
                f"SYN-BULK-REC-MATCH-{case:05d}-{suffix}", source,
                f"Reconciliation Match {case}", f"{40000 + case}.00",
                timestamp(case, 0 if suffix == "INT" else 2), source, destination,
                case=case, scenario="RECONCILIATION_MATCHED", expected="MATCHED",
                ledger=ledger, external_reference=f"BULK-REC-MATCH-{case:05d}",
            )

    # 8,000 amount-mismatch reconciliation rows.
    for case in range(4_000):
        source, destination = account(5, case), account(5, case, 1)
        reference = f"BULK-REC-AMOUNT-{case:05d}"
        yield make_row(
            f"SYN-{reference}-INT", source, f"Amount Mismatch {case}",
            f"{50000 + case}.00", timestamp(case), source, destination,
            case=case, scenario="RECONCILIATION_AMOUNT_MISMATCH", expected="AMOUNT_MISMATCH",
            ledger="INTERNAL_LEDGER", external_reference=reference,
        )
        yield make_row(
            f"SYN-{reference}-CTR", source, f"Amount Mismatch {case}",
            f"{49500 + case}.00", timestamp(case, 2), source, destination,
            case=case, scenario="RECONCILIATION_AMOUNT_MISMATCH", expected="AMOUNT_MISMATCH",
            ledger="COUNTERPART_LEDGER", external_reference=reference,
        )

    # 4,000 field-mismatch reconciliation rows.
    for case in range(2_000):
        source = account(6, case)
        reference = f"BULK-REC-FIELD-{case:05d}"
        yield make_row(
            f"SYN-{reference}-INT", source, f"Field Mismatch {case}", "60000.00",
            timestamp(case), source, account(6, case, 1), case=case,
            scenario="RECONCILIATION_FIELD_MISMATCH", expected="FIELD_MISMATCH",
            ledger="INTERNAL_LEDGER", external_reference=reference,
        )
        yield make_row(
            f"SYN-{reference}-CTR", source, f"Field Mismatch {case}", "60000.00",
            timestamp(case, 2), source, account(6, case, 2), case=case,
            scenario="RECONCILIATION_FIELD_MISMATCH", expected="FIELD_MISMATCH",
            ledger="COUNTERPART_LEDGER", external_reference=reference,
        )

    # 2,000 rows for each missing-side/late classification.
    for case in range(2_000):
        source, destination = account(7, case), account(7, case, 1)
        yield make_row(
            f"SYN-BULK-REC-INTERNAL-{case:05d}", source, f"Internal Only {case}",
            "70000.00", timestamp(case), source, destination, case=case,
            scenario="RECONCILIATION_INTERNAL_ONLY", expected="INTERNAL_ONLY",
            ledger="INTERNAL_LEDGER",
        )
        yield make_row(
            f"SYN-BULK-REC-COUNTER-{case:05d}", source, f"Counterpart Only {case}",
            "71000.00", timestamp(case), source, destination, case=case,
            scenario="RECONCILIATION_COUNTERPART_ONLY", expected="COUNTERPART_ONLY",
            ledger="COUNTERPART_LEDGER",
        )
        yield make_row(
            f"SYN-BULK-REC-LATE-{case:05d}", source, f"Pending Late {case}",
            "72000.00", timestamp(case), source, destination, case=case,
            scenario="RECONCILIATION_PENDING_LATE", expected="PENDING_LATE",
            ledger="INTERNAL_LEDGER", status="PENDING",
            posting_date=timestamp(case, 2 * 24 * 60),
        )

    # 6,000 rows: 2,000 ambiguous triples.
    for case in range(2_000):
        source, destination = account(8, case), account(8, case, 1)
        for suffix, ledger, offset in (
            ("INT", "INTERNAL_LEDGER", 0),
            ("CTR-A", "COUNTERPART_LEDGER", 1),
            ("CTR-B", "COUNTERPART_LEDGER", 2),
        ):
            yield make_row(
                f"SYN-BULK-REC-AMB-{case:05d}-{suffix}", source,
                f"Ambiguous Reconciliation {case}", "73000.00", timestamp(case, offset),
                source, destination, case=case, scenario="RECONCILIATION_AMBIGUOUS",
                expected="AMBIGUOUS", ledger=ledger,
                external_reference=f"BULK-REC-AMB-{case:05d}-{suffix}",
            )

    # 12,000 rows: 4,000 valid chronological cycles.
    for case in range(4_000):
        nodes = [account(9, case, member) for member in range(3)]
        for edge, (source, destination, amount, offset) in enumerate((
            (nodes[0], nodes[1], "100000.00", 0),
            (nodes[1], nodes[2], "97000.00", 5),
            (nodes[2], nodes[0], "95000.00", 10),
        )):
            yield make_row(
                f"SYN-BULK-CYCLE-{case:05d}-{edge}", source,
                f"Circular Flow {case}", amount, timestamp(case, offset), source, destination,
                case=case, scenario="VALID_TEMPORAL_CYCLE", expected="CIRCULAR_FLOW",
            )

    # 6,000 rows: graph cycles whose timestamps cannot form a valid flow.
    for case in range(2_000):
        nodes = [account(10, case, member) for member in range(3)]
        for edge, (source, destination, offset) in enumerate((
            (nodes[0], nodes[1], 60),
            (nodes[1], nodes[2], 0),
            (nodes[2], nodes[0], 120),
        )):
            yield make_row(
                f"SYN-BULK-CYCLE-CTRL-{case:05d}-{edge}", source,
                f"Invalid Cycle Control {case}", "50000.00", timestamp(case, offset),
                source, destination, case=case, scenario="INVALID_TEMPORAL_CYCLE", expected="NONE",
            )

    # 12,000 rows: 4,000 threshold breaches within 60 minutes.
    for case in range(4_000):
        source = account(11, case)
        for part, (amount, offset) in enumerate((("40000.00", 0), ("35000.00", 20), ("30000.00", 40))):
            yield make_row(
                f"SYN-BULK-SPLIT-{case:05d}-{part}", source, f"Split Window {case}",
                amount, timestamp(case, offset), source, account(11, case, part + 1),
                case=case, scenario="SPLITTING_WITHIN_60_MIN",
                expected="TRANSACTION_SPLITTING",
            )

    # 6,000 rows: same values outside the configured window.
    for case in range(2_000):
        source = account(12, case)
        for part, offset in enumerate((0, 120, 240)):
            yield make_row(
                f"SYN-BULK-SPLIT-CTRL-{case:05d}-{part}", source,
                f"Split Window Control {case}", "40000.00", timestamp(case, offset),
                source, account(12, case, part + 1), case=case,
                scenario="SPLITTING_OUTSIDE_WINDOW", expected="NONE",
            )

    # 4,000 balanced and 4,000 unbalanced journal rows.
    for case in range(2_000):
        source, destination = account(13, case), account(13, case, 1)
        for suffix, direction, mode in (("D", "DEBIT", "Transfer Out"), ("C", "CREDIT", "Transfer In")):
            yield make_row(
                f"SYN-BULK-JRN-BAL-{case:05d}-{suffix}", source,
                f"Balanced Journal {case}", "10000.00", timestamp(case), source, destination,
                case=case, scenario="BALANCED_JOURNAL", expected="BALANCED", mode=mode,
                journal_id=f"J-BULK-BAL-{case:05d}", direction=direction,
            )
    for case in range(2_000):
        source, destination = account(14, case), account(14, case, 1)
        for suffix, direction, mode, amount in (
            ("D", "DEBIT", "Transfer Out", "10000.00"),
            ("C", "CREDIT", "Transfer In", "9000.00"),
        ):
            yield make_row(
                f"SYN-BULK-JRN-UNBAL-{case:05d}-{suffix}", source,
                f"Unbalanced Journal {case}", amount, timestamp(case), source, destination,
                case=case, scenario="UNBALANCED_JOURNAL", expected="UNBALANCED_JOURNAL",
                mode=mode, journal_id=f"J-BULK-UNBAL-{case:05d}", direction=direction,
            )

    # 4,000 rejected rows: invalid amount/date, negative amount, and missing account.
    for case in range(1_000):
        source, destination = account(15, case), account(15, case, 1)
        yield make_row(
            f"SYN-BULK-BAD-AMOUNT-{case:05d}", source, "Invalid Amount", "not-a-number",
            timestamp(case), source, destination, case=case, scenario="MALFORMED_AMOUNT",
            expected="INGEST_REJECT",
        )
        yield make_row(
            f"SYN-BULK-BAD-DATE-{case:05d}", source, "Invalid Date", "5000.00",
            "not-a-date", source, destination, case=case, scenario="MALFORMED_DATE",
            expected="INGEST_REJECT",
        )
        yield make_row(
            f"SYN-BULK-NEG-AMOUNT-{case:05d}", source, "Negative Amount", "-500.00",
            timestamp(case), source, destination, case=case, scenario="NEGATIVE_AMOUNT",
            expected="INGEST_REJECT",
        )
        yield make_row(
            f"SYN-BULK-MISSING-ACCOUNT-{case:05d}", "", "Missing Account", "5000.00",
            timestamp(case), source, destination, case=case, scenario="MISSING_ACCOUNT",
            expected="INGEST_REJECT",
        )


def scale_dataset(dataset_path: Path) -> tuple[int, int, int]:
    temporary_path = dataset_path.with_suffix(dataset_path.suffix + ".scaling")
    existing_rows = 0
    added_rows = 0
    existing_synthetic_rows = 0

    try:
        with dataset_path.open("r", encoding="utf-8-sig", newline="") as source_file:
            reader = csv.DictReader(source_file)
            if reader.fieldnames is None or "Scenario_Label" not in reader.fieldnames:
                raise ValueError("Run augment_dataset.py before scaling synthetic scenarios")

            leading_rows: list[dict[str, str]] = []
            first_baseline: dict[str, str] | None = None
            for row in reader:
                existing_rows += 1
                if row["Scenario_Label"].startswith("BULK_"):
                    raise ValueError("Bulk scenarios are already present; refusing to add them twice")
                if row["Is_Synthetic"].lower() == "true":
                    leading_rows.append(row)
                    existing_synthetic_rows += 1
                    continue
                first_baseline = row
                break

            with temporary_path.open("w", encoding="utf-8", newline="") as output_file:
                writer = csv.DictWriter(output_file, fieldnames=reader.fieldnames, lineterminator="\n")
                writer.writeheader()
                writer.writerows(leading_rows)
                for generated in generate_rows():
                    writer.writerow(generated)
                    added_rows += 1
                if added_rows != ROWS_TO_ADD:
                    raise RuntimeError(f"Expected {ROWS_TO_ADD} generated rows, got {added_rows}")
                if first_baseline is not None:
                    writer.writerow(first_baseline)
                for row in reader:
                    writer.writerow(row)
                    existing_rows += 1

        os.replace(temporary_path, dataset_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise

    return existing_rows, existing_synthetic_rows, added_rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dataset",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "SFinDSet.csv",
    )
    args = parser.parse_args()
    existing, previous_synthetic, added = scale_dataset(args.dataset.resolve())
    print(
        f"Preserved {existing} existing rows ({previous_synthetic} synthetic) and "
        f"added {added} deterministic bulk scenario rows."
    )


if __name__ == "__main__":
    main()
