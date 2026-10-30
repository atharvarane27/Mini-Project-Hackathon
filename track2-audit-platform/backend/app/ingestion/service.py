from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, BinaryIO, TextIO

from sqlalchemy.orm import Session

from app.db.models import IngestionJob as IngestionJobModel
from app.db.models import OutboxEvent, SourceRecord, SourceSystem
from app.db.session import get_db_context
from app.ingestion.canonicalizer import Canonicalizer
from app.ingestion.csv_reader import BoundedCSVReader, RawRowRecord
from app.ingestion.normalizer import QuarantinedRowError, RowNormalizer
from app.schemas.ingestion import IngestionJob, IngestionJobCounts, IngestionJobState

logger = logging.getLogger("auditforge.ingestion")


class IngestionService:
    """Bounded-batch streaming CSV ingestion engine.

    Invariants:
    - Never loads the whole CSV file into memory; iterates in bounded chunks.
    - Idempotent re-imports: exact duplicate payloads increment duplicate counts
      without double-creating transactions.
    - Revision conflicts: changed rows with identical (source_system, ref, revision)
      are quarantined for review.
    - Malformed rows are captured with stable diagnostic error codes while preserving
      the valid rows in the batch.
    - Atomically writes SourceRecord, CanonicalTransaction, and OutboxEvent in batches.
    """

    def __init__(self, batch_size: int = 500) -> None:
        self.batch_size = batch_size
        self.reader = BoundedCSVReader(batch_size=batch_size)
        self.normalizer = RowNormalizer()
        self.canonicalizer = Canonicalizer()

    def _ensure_source_system(self, db: Session, source_system_id: str) -> None:
        """Ensure the source system exists in DB to prevent foreign key errors."""
        existing = db.query(SourceSystem).filter_by(id=source_system_id).first()
        if not existing:
            db.add(
                SourceSystem(
                    id=source_system_id,
                    name=source_system_id,
                    description=f"Auto-registered source {source_system_id}",
                )
            )
            db.flush()

    def process_file_or_stream(
        self,
        stream_or_file: TextIO | BinaryIO | str,
        source_system_id: str,
        idempotency_key: str | None = None,
        job_id: str | None = None,
        db_session: Session | None = None,
    ) -> IngestionJob:
        """Stream and process a CSV input in bounded batches."""
        if db_session is not None:
            return self._execute_ingestion(
                db_session, stream_or_file, source_system_id, idempotency_key, job_id
            )
        with get_db_context() as db:
            return self._execute_ingestion(
                db, stream_or_file, source_system_id, idempotency_key, job_id
            )

    def _execute_ingestion(
        self,
        db: Session,
        stream_or_file: TextIO | BinaryIO | str,
        source_system_id: str,
        idempotency_key: str | None,
        job_id: str | None,
    ) -> IngestionJob:
        # Check idempotency key if provided
        if idempotency_key:
            existing_job = (
                db.query(IngestionJobModel)
                .filter(
                    IngestionJobModel.counts_json["idempotency_key"].as_string() == idempotency_key
                )
                .first()
            )
            valid_states = (IngestionJobState.COMPLETED, IngestionJobState.PARTIAL)
            if existing_job and existing_job.state in valid_states:
                logger.info(
                    f"Idempotent hit for key {idempotency_key}, returning job {existing_job.id}"
                )
                return self._to_schema(existing_job)

        self._ensure_source_system(db, source_system_id)

        job_uuid = job_id or f"ingest-{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC)

        db_job = IngestionJobModel(
            id=job_uuid,
            source_system_id=source_system_id,
            received_at=now,
            state=IngestionJobState.RUNNING,
            counts_json={
                "total_rows": 0,
                "accepted": 0,
                "rejected": 0,
                "duplicate": 0,
                "conflict": 0,
                "idempotency_key": idempotency_key,
                "errors": [],
            },
        )
        db.add(db_job)
        db.commit()

        # Determine batch generator based on input type
        if isinstance(stream_or_file, str):
            batch_generator = self.reader.stream_file_batches(stream_or_file)
        elif hasattr(stream_or_file, "mode") and "b" in getattr(stream_or_file, "mode", ""):
            batch_generator = self.reader.stream_binary_batches(stream_or_file)  # type: ignore[arg-type]
        else:
            # Check if read() produces bytes or str
            pos = getattr(stream_or_file, "tell", lambda: 0)()
            peek = stream_or_file.read(4)
            if hasattr(stream_or_file, "seek"):
                stream_or_file.seek(pos)
            if isinstance(peek, bytes):
                batch_generator = self.reader.stream_binary_batches(stream_or_file)  # type: ignore[arg-type]
            else:
                batch_generator = self.reader.stream_batches(stream_or_file)  # type: ignore[arg-type]

        total_rows = 0
        accepted = 0
        rejected = 0
        duplicate = 0
        conflict = 0
        quarantined_errors: list[dict[str, Any]] = []

        for batch in batch_generator:
            b_total, b_acc, b_rej, b_dup, b_con, b_errs = self._process_batch(
                db, batch, job_uuid, source_system_id
            )
            total_rows += b_total
            accepted += b_acc
            rejected += b_rej
            duplicate += b_dup
            conflict += b_con
            quarantined_errors.extend(b_errs)

            # Checkpoint job progress after each batch commit
            db.commit()

        # Finalize job status
        final_state = IngestionJobState.COMPLETED
        if rejected > 0 or conflict > 0:
            final_state = IngestionJobState.PARTIAL if accepted > 0 else IngestionJobState.FAILED

        db_job.state = final_state
        db_job.counts_json = {
            "total_rows": total_rows,
            "accepted": accepted,
            "rejected": rejected,
            "duplicate": duplicate,
            "conflict": conflict,
            "idempotency_key": idempotency_key,
            "errors": quarantined_errors[:100],  # cap stored error samples to prevent bloat
        }
        db.commit()
        db.refresh(db_job)

        return self._to_schema(db_job)

    def _process_batch(
        self,
        db: Session,
        batch: list[RawRowRecord],
        job_id: str,
        source_system_id: str,
    ) -> tuple[int, int, int, int, int, list[dict[str, Any]]]:
        """Process a single bounded batch of raw records in an isolated transaction."""
        b_total = len(batch)
        b_accepted = 0
        b_rejected = 0
        b_duplicate = 0
        b_conflict = 0
        b_errors: list[dict[str, Any]] = []

        for raw_row in batch:
            result = self.normalizer.normalize(raw_row)

            if isinstance(result, QuarantinedRowError):
                b_rejected += 1
                b_errors.append(result.to_dict())
                continue

            # Check uniqueness: (source_system_id, external_ref, source_revision)
            existing_src = (
                db.query(SourceRecord)
                .filter_by(
                    source_system_id=source_system_id,
                    external_ref=result.external_ref,
                    source_revision=result.source_revision,
                )
                .first()
            )

            if existing_src is not None:
                if existing_src.payload_hash == result.payload_hash:
                    # Identical replay / exact duplicate -> idempotent no-op
                    b_duplicate += 1
                else:
                    # Changed row with same external reference & revision -> conflict!
                    b_conflict += 1
                    err = QuarantinedRowError(
                        row_number=result.row_number,
                        external_ref=result.external_ref,
                        error_code="EXTERNAL_REF_REVISION_CONFLICT",
                        error_message=(
                            f"Row has external_ref '{result.external_ref}' and revision "
                            f"{result.source_revision} matching existing record {existing_src.id} "
                            f"with differing payload hash."
                        ),
                        raw_data=result.raw_payload,
                    )
                    b_errors.append(err.to_dict())
                continue

            # Canonicalize row with duplicate reference collapsing and double-entry journals
            canon_res = self.canonicalizer.canonicalize_row(
                db, result, job_id, source_system_id
            )
            src_rec = canon_res.source_record
            txn = canon_res.transaction
            junction = canon_res.junction

            if canon_res.is_ambiguous:
                # Ambiguous duplicate: conflicting facts for same external reference
                db.add_all([src_rec, junction])
                b_rejected += 1
                b_conflict += 1
                err = QuarantinedRowError(
                    row_number=result.row_number,
                    external_ref=result.external_ref,
                    error_code="AMBIGUOUS_DUPLICATE_REFERENCE",
                    error_message=(
                        f"Row with external_ref '{result.external_ref}' conflicts with existing "
                        f"canonical transaction '{txn.id}'."
                    ),
                    raw_data=result.raw_payload,
                )
                b_errors.append(err.to_dict())
                continue

            if canon_res.is_new:
                db.add_all([src_rec, txn, junction])
            else:
                # Repeated transport copy / duplicate reference -> collapsed to existing canonical transaction!
                db.add_all([src_rec, junction])

            # Durable Outbox Event
            outbox_payload = {
                "source_record_id": src_rec.id,
                "transaction_id": txn.id,
                "external_ref": result.external_ref,
                "amount_minor": result.amount_minor,
                "currency": result.currency,
                "occurred_at": result.occurred_at.isoformat(),
            }
            outbox_evt = OutboxEvent(
                id=f"evt-{uuid.uuid4().hex[:16]}",
                event_type="SOURCE_RECORD_ACCEPTED",
                entity_id=src_rec.id,
                payload_json=outbox_payload,
                payload_hash=result.payload_hash,
                status="PENDING",
            )
            db.add(outbox_evt)

            b_accepted += 1

        db.flush()
        return b_total, b_accepted, b_rejected, b_duplicate, b_conflict, b_errors

    def get_job(self, job_id: str, db_session: Session | None = None) -> IngestionJob | None:
        """Fetch ingestion job status by ID."""
        if db_session is not None:
            job = db_session.query(IngestionJobModel).filter_by(id=job_id).first()
            return self._to_schema(job) if job else None

        with get_db_context() as db:
            job = db.query(IngestionJobModel).filter_by(id=job_id).first()
            return self._to_schema(job) if job else None

    def _to_schema(self, db_job: IngestionJobModel) -> IngestionJob:
        """Convert SQLAlchemy model to frozen Pydantic schema.

        SQLite strips timezone info on datetime round-trip; explicitly add UTC
        to keep the UtcDatetime validator happy in both SQLite (tests) and
        Postgres (production with timestamptz) environments.
        """
        counts = db_job.counts_json or {}
        job_counts = IngestionJobCounts(
            total_rows=counts.get("total_rows", 0),
            accepted=counts.get("accepted", 0),
            rejected=counts.get("rejected", 0),
            duplicate=counts.get("duplicate", 0),
            conflict=counts.get("conflict", 0),
            pending_review=counts.get("pending_review", 0),
        )
        started_at = db_job.received_at
        if started_at is not None and started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        return IngestionJob(
            id=db_job.id,
            source_system_id=db_job.source_system_id,
            state=IngestionJobState(db_job.state),
            counts=job_counts,
            errors=tuple(counts.get("errors", [])),
            started_at=started_at,
            completed_at=None,
        )
