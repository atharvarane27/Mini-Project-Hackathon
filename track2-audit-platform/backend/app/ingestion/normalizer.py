from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.ingestion.csv_reader import RawRowRecord


@dataclass(frozen=True)
class NormalizedRow:
    """A successfully normalized and validated transaction row."""

    row_number: int
    external_ref: str
    source_revision: int
    sender_account_id: str
    receiver_account_id: str
    amount_minor: int
    currency: str
    occurred_at: datetime
    posted_at: datetime
    direction: str
    txn_type: str
    status: str
    branch_id: str | None
    description: str
    payload_hash: str
    raw_payload: dict[str, str]


@dataclass(frozen=True)
class QuarantinedRowError:
    """A row validation failure quarantined with a stable diagnostic code."""

    row_number: int
    external_ref: str | None
    error_code: str
    error_message: str
    raw_data: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_number": self.row_number,
            "external_ref": self.external_ref,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "raw_data": self.raw_data,
        }


# Known date format patterns for robust streaming ingestion
DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%d %H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%Y-%m-%d",
    "%d-%m-%Y",
)


def _get_field(data: dict[str, str], *candidate_keys: str) -> str:
    """Case-insensitive helper to retrieve the first matching non-empty column value."""
    # First exact match
    for k in candidate_keys:
        if k in data and data[k].strip():
            return data[k].strip()

    # Case-insensitive / normalized lookup
    normalized_keys = {re.sub(r"[\s_-]+", "", k).lower(): v for k, v in data.items()}
    for k in candidate_keys:
        clean = re.sub(r"[\s_-]+", "", k).lower()
        if clean in normalized_keys and normalized_keys[clean].strip():
            return normalized_keys[clean].strip()

    return ""


def parse_timestamp_to_utc(value_str: str) -> datetime:
    """Parse various datetime string formats into timezone-aware UTC datetime."""
    clean_val = value_str.strip()
    if not clean_val:
        raise ValueError("Timestamp string is empty")

    # If it ends with Z, replace with +00:00 for ISO parsing
    if clean_val.endswith("Z"):
        clean_val = clean_val[:-1] + "+00:00"

    # Try ISO fromisoformat
    try:
        dt = datetime.fromisoformat(clean_val)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        pass

    # Try known strptime patterns
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(clean_val, fmt)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except ValueError:
            continue

    raise ValueError(f"Unrecognized timestamp format: '{value_str}'")


def parse_amount_to_minor(amount_str: str) -> int:
    """Parse decimal amount string (e.g. '125000.50') to positive integer minor units."""
    clean_val = amount_str.replace(",", "").replace("$", "").replace("₹", "").strip()
    if not clean_val:
        raise ValueError("Amount string is empty")

    try:
        dec = Decimal(clean_val)
    except InvalidOperation as err:
        raise ValueError(f"Non-numeric amount: '{amount_str}'") from err

    if dec <= 0:
        raise ValueError(f"Amount must be strictly positive, got: {dec}")

    # Convert to minor units (multiply by 100 and round)
    minor = int(round(dec * 100))
    if minor <= 0:
        raise ValueError(f"Amount converted to 0 minor units from: '{amount_str}'")
    return minor


class RowNormalizer:
    """Normalizes and validates raw CSV records into typed NormalizedRow or QuarantinedRowError."""

    def normalize(self, raw_record: RawRowRecord) -> NormalizedRow | QuarantinedRowError:
        data = raw_record.data
        row_num = raw_record.row_number

        # 1. External Reference
        ext_ref = _get_field(
            data,
            "External_Reference",
            "external_ref",
            "Transaction_ID",
            "external_txn_ref",
            "txn_id",
            "reference",
        )
        if not ext_ref:
            return QuarantinedRowError(
                row_number=row_num,
                external_ref=None,
                error_code="MISSING_EXTERNAL_REF",
                error_message="External transaction reference is missing or empty.",
                raw_data=data,
            )

        # 2. Source Revision
        rev_str = _get_field(data, "Source_Revision", "source_revision", "revision")
        revision = 1
        if rev_str:
            try:
                revision = int(rev_str)
                if revision < 1:
                    revision = 1
            except ValueError:
                revision = 1

        # 3. Amount Minor Units
        amt_str = _get_field(data, "Transaction_Amount", "amount", "amount_minor", "amount_decimal")
        if not amt_str:
            return QuarantinedRowError(
                row_number=row_num,
                external_ref=ext_ref,
                error_code="MISSING_AMOUNT",
                error_message="Transaction amount is missing.",
                raw_data=data,
            )
        try:
            amount_minor = parse_amount_to_minor(amt_str)
        except ValueError as err:
            return QuarantinedRowError(
                row_number=row_num,
                external_ref=ext_ref,
                error_code="INVALID_AMOUNT",
                error_message=str(err),
                raw_data=data,
            )

        # 4. Currency
        curr = _get_field(data, "Currency", "currency", "curr").upper()
        if not curr:
            curr = "INR"
        if len(curr) != 3 or not curr.isalpha():
            return QuarantinedRowError(
                row_number=row_num,
                external_ref=ext_ref,
                error_code="INVALID_CURRENCY",
                error_message=f"Currency must be a 3-letter ISO code, got '{curr}'.",
                raw_data=data,
            )

        # 5. Timestamps
        occurred_str = _get_field(
            data,
            "Transaction_Date",
            "occurred_at",
            "txn_time",
            "date",
            "timestamp",
        )
        if not occurred_str:
            return QuarantinedRowError(
                row_number=row_num,
                external_ref=ext_ref,
                error_code="MISSING_TIMESTAMP",
                error_message="Transaction occurred date is missing.",
                raw_data=data,
            )
        try:
            occurred_at = parse_timestamp_to_utc(occurred_str)
        except ValueError as err:
            return QuarantinedRowError(
                row_number=row_num,
                external_ref=ext_ref,
                error_code="INVALID_TIMESTAMP",
                error_message=str(err),
                raw_data=data,
            )

        posted_str = _get_field(data, "Posting_Date", "posted_at", "posting_time")
        if posted_str:
            try:
                posted_at = parse_timestamp_to_utc(posted_str)
            except ValueError:
                posted_at = occurred_at
        else:
            posted_at = occurred_at

        # 6. Direction & Accounts
        dir_val = _get_field(data, "Entry_Direction", "direction", "direction_type").upper()
        mode_val = _get_field(data, "Transaction_Mode", "mode", "txn_mode")

        if not dir_val:
            if "OUT" in mode_val.upper() or "DEBIT" in mode_val.upper():
                dir_val = "DEBIT"
            elif "IN" in mode_val.upper() or "CREDIT" in mode_val.upper():
                dir_val = "CREDIT"
            else:
                dir_val = "DEBIT"

        if dir_val not in ("DEBIT", "CREDIT"):
            return QuarantinedRowError(
                row_number=row_num,
                external_ref=ext_ref,
                error_code="INVALID_DIRECTION",
                error_message=f"Direction must be DEBIT or CREDIT, got '{dir_val}'.",
                raw_data=data,
            )

        # Counterparty accounts
        sender = _get_field(
            data,
            "Transaction_Source",
            "sender_account_id",
            "source",
            "sender",
            "from_account",
        )
        receiver = _get_field(
            data,
            "Transaction_Destination",
            "receiver_account_id",
            "destination",
            "receiver",
            "to_account",
        )

        acc_num = _get_field(data, "Account_Number", "account_id", "account")
        if not sender and acc_num and dir_val == "DEBIT":
            sender = acc_num
        if not receiver and acc_num and dir_val == "CREDIT":
            receiver = acc_num

        # If one party is still missing, set a default system or counterparty identifier
        if not sender and receiver:
            sender = f"EXT-SND-{receiver}"
        elif not receiver and sender:
            receiver = f"EXT-RCV-{sender}"
        elif not sender and not receiver:
            return QuarantinedRowError(
                row_number=row_num,
                external_ref=ext_ref,
                error_code="MISSING_COUNTERPARTY",
                error_message="Both sender and receiver accounts are missing.",
                raw_data=data,
            )

        if sender == receiver:
            return QuarantinedRowError(
                row_number=row_num,
                external_ref=ext_ref,
                error_code="IDENTICAL_COUNTERPARTY",
                error_message=f"Sender and receiver cannot be identical account '{sender}'.",
                raw_data=data,
            )

        # Branch
        branch_id = _get_field(data, "Branch_ID", "branch_id", "branch") or None

        # Txn Type & Description
        txn_type = _get_field(data, "Transaction_Type", "txn_type", "type") or "TRANSFER"
        status_val = _get_field(data, "Transaction_Status", "status") or "POSTED"
        desc = (
            _get_field(data, "Description", "description", "narrative") or f"{txn_type} {ext_ref}"
        )

        return NormalizedRow(
            row_number=row_num,
            external_ref=ext_ref,
            source_revision=revision,
            sender_account_id=sender,
            receiver_account_id=receiver,
            amount_minor=amount_minor,
            currency=curr,
            occurred_at=occurred_at,
            posted_at=posted_at,
            direction=dir_val,
            txn_type=txn_type,
            status=status_val,
            branch_id=branch_id,
            description=desc,
            payload_hash=raw_record.payload_hash,
            raw_payload=data,
        )
