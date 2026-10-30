from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import Journal, SourceRecordTransaction, Transaction
from app.db.session import get_db
from app.ingestion.canonicalizer import Canonicalizer
from app.schemas.common import ApiResponse, CursorPaginationMeta, PaginatedResponse
from app.schemas.ingestion import CanonicalTransferEvent
from app.schemas.transactions import (
    AccountingErrorDetail,
    TransactionResponseItem,
    TransactionStatus,
)

router = APIRouter(prefix="/transactions", tags=["Transactions"])
canonicalizer = Canonicalizer()


def _encode_cursor(dt: datetime, record_id: str) -> str:
    """Encode occurred_at datetime and record ID into an opaque cursor token."""
    raw = f"{dt.isoformat()}|{record_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    """Decode an opaque cursor token into occurred_at datetime and record ID."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8")
        dt_str, record_id = raw.split("|", 1)
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt, record_id
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid pagination cursor: {exc}",
        ) from exc


def _build_transaction_item(db: Session, txn: Transaction) -> TransactionResponseItem:
    """Build enriched TransactionResponseItem with linked provenance and journal status."""
    occurred_at = txn.occurred_at
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)

    posted_at = txn.posted_at
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=UTC)

    # Linked source records
    src_links = (
        db.query(SourceRecordTransaction)
        .filter_by(transaction_id=txn.id)
        .all()
    )
    src_ids = tuple(link.source_record_id for link in src_links)
    src_count = len(src_ids) or 1

    # Linked journal inspection
    journal: Journal | None = None
    if txn.external_canonical_ref:
        # Canonical reference matches JRN-prefix
        suffix = txn.external_canonical_ref.removeprefix("CANON-")
        jrn_ref = f"JRN-{suffix}"
        journal = db.query(Journal).filter_by(journal_ref=jrn_ref).first()

    journal_ref = journal.journal_ref if journal else None
    journal_status = journal.status if journal else None

    # Accounting integrity error check
    accounting_error: AccountingErrorDetail | None = None
    if journal is not None and journal.status == "UNBALANCED":
        debit_sum = sum(line.debit_minor for line in journal.lines)
        credit_sum = sum(line.credit_minor for line in journal.lines)
        imbalance = abs(debit_sum - credit_sum)
        accounting_error = AccountingErrorDetail(
            error_code="UNBALANCED_JOURNAL",
            message=(
                f"Double-entry journal '{journal.id}' is unbalanced: "
                f"debit={debit_sum}, credit={credit_sum}, variance={imbalance}"
            ),
            imbalance_minor=imbalance,
            journal_id=journal.id,
            total_debit_minor=debit_sum,
            total_credit_minor=credit_sum,
        )

    # Validate status enum safely
    txn_status = TransactionStatus.POSTED
    try:
        txn_status = TransactionStatus(txn.status)
    except ValueError:
        pass

    return TransactionResponseItem(
        id=txn.id,
        external_canonical_ref=txn.external_canonical_ref,
        sender_account_id=txn.sender_account_id,
        receiver_account_id=txn.receiver_account_id,
        amount_minor=txn.amount_minor,
        currency=txn.currency,
        occurred_at=occurred_at,
        posted_at=posted_at,
        txn_type=txn.txn_type,
        status=txn_status,
        source_record_count=src_count,
        source_record_ids=src_ids,
        journal_ref=journal_ref,
        journal_status=journal_status,
        accounting_integrity_error=accounting_error,
    )


@router.get(
    "/snapshot",
    response_model=ApiResponse[list[CanonicalTransferEvent]],
    status_code=status.HTTP_200_OK,
    summary="Get downstream snapshot of unique accepted canonical transfers",
)
def get_transactions_snapshot(
    request: Request,
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    currency: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> ApiResponse[list[CanonicalTransferEvent]]:
    """Expose a downstream snapshot of unique accepted canonical transfers."""
    req_id = getattr(request.state, "request_id", f"req-{uuid.uuid4().hex[:12]}")
    events = canonicalizer.get_downstream_snapshot(
        db_session=db,
        start_at=start_at,
        end_at=end_at,
        currency=currency,
    )
    return ApiResponse(
        data=events,
        meta={"count": len(events)},
        request_id=req_id,
    )


@router.get(
    "",
    response_model=PaginatedResponse[TransactionResponseItem],
    status_code=status.HTTP_200_OK,
    summary="Search and filter canonical transactions with cursor pagination",
)
def get_transactions(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
    account_id: str | None = Query(default=None),
    sender_account_id: str | None = Query(default=None),
    receiver_account_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    txn_type: str | None = Query(default=None),
    currency: str | None = Query(default=None),
    min_amount_minor: int | None = Query(default=None),
    max_amount_minor: int | None = Query(default=None),
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    search: str | None = Query(default=None),
    has_accounting_error: bool | None = Query(default=None),
    db: Session = Depends(get_db),
) -> PaginatedResponse[TransactionResponseItem]:
    """Retrieve canonical transactions with cursor pagination and accounting integrity."""
    req_id = getattr(request.state, "request_id", f"req-{uuid.uuid4().hex[:12]}")

    stmt = select(Transaction)

    # Filtering
    if account_id:
        stmt = stmt.filter(
            or_(
                Transaction.sender_account_id == account_id,
                Transaction.receiver_account_id == account_id,
            )
        )
    if sender_account_id:
        stmt = stmt.filter(Transaction.sender_account_id == sender_account_id)
    if receiver_account_id:
        stmt = stmt.filter(Transaction.receiver_account_id == receiver_account_id)
    if status_filter:
        stmt = stmt.filter(Transaction.status == status_filter.upper())
    if txn_type:
        stmt = stmt.filter(Transaction.txn_type == txn_type.upper())
    if currency:
        stmt = stmt.filter(Transaction.currency == currency.upper())
    if min_amount_minor is not None:
        stmt = stmt.filter(Transaction.amount_minor >= min_amount_minor)
    if max_amount_minor is not None:
        stmt = stmt.filter(Transaction.amount_minor <= max_amount_minor)
    if start_at:
        stmt = stmt.filter(Transaction.occurred_at >= start_at)
    if end_at:
        stmt = stmt.filter(Transaction.occurred_at <= end_at)
    if search:
        search_pattern = f"%{search}%"
        stmt = stmt.filter(
            or_(
                Transaction.id.ilike(search_pattern),
                Transaction.external_canonical_ref.ilike(search_pattern),
                Transaction.sender_account_id.ilike(search_pattern),
                Transaction.receiver_account_id.ilike(search_pattern),
            )
        )

    # Total matching count before cursor slicing
    total_count = len(db.scalars(stmt).all())

    # Cursor-based filtering
    if cursor:
        cursor_time, cursor_id = _decode_cursor(cursor)
        stmt = stmt.filter(
            or_(
                Transaction.occurred_at < cursor_time,
                (Transaction.occurred_at == cursor_time) & (Transaction.id < cursor_id),
            )
        )

    # Deterministic order
    stmt = stmt.order_by(Transaction.occurred_at.desc(), Transaction.id.desc())

    # Fetch limit + 1 to detect has_more
    stmt = stmt.limit(limit + 1)
    raw_results = db.scalars(stmt).all()

    has_more = len(raw_results) > limit
    results = raw_results[:limit]

    # Convert to enriched response items
    items: list[TransactionResponseItem] = []
    for txn in results:
        item = _build_transaction_item(db, txn)
        if has_accounting_error is not None:
            has_error = item.accounting_integrity_error is not None
            if has_error != has_accounting_error:
                continue
        items.append(item)

    next_cursor: str | None = None
    if has_more and len(results) > 0:
        last_txn = results[-1]
        last_occurred = last_txn.occurred_at
        if last_occurred.tzinfo is None:
            last_occurred = last_occurred.replace(tzinfo=UTC)
        next_cursor = _encode_cursor(last_occurred, last_txn.id)

    meta = CursorPaginationMeta(
        next_cursor=next_cursor,
        has_more=has_more,
        total_count=total_count,
        limit=limit,
    )

    return PaginatedResponse(
        data=tuple(items),
        meta=meta,
        request_id=req_id,
    )


@router.get(
    "/{id}",
    response_model=ApiResponse[TransactionResponseItem],
    status_code=status.HTTP_200_OK,
    summary="Get single canonical transaction by ID with full provenance",
)
def get_transaction_by_id(
    id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> ApiResponse[TransactionResponseItem]:
    """Retrieve a single canonical transaction by its ID."""
    req_id = getattr(request.state, "request_id", f"req-{uuid.uuid4().hex[:12]}")
    txn = db.query(Transaction).filter_by(id=id).first()
    if not txn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction with ID '{id}' was not found.",
        )

    item = _build_transaction_item(db, txn)
    return ApiResponse(
        data=item,
        meta={},
        request_id=req_id,
    )
