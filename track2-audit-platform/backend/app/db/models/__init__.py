"""3NF SQLAlchemy Models for Track 2 AuditForge Platform.

All models adhere strictly to:
- 3NF relational normalization
- RESTRICT / NO ACTION foreign keys on financial & audit records
- Immutability and idempotency constraints
- CHECK constraints on money, double-entry, and priority bounds
- Explicit performance indexes per PRD Section 6
"""

from app.db.models.accounts import Account, Branch
from app.db.models.audit import ActivityLog
from app.db.models.auth import (
    Role,
    User,
    UserRole,
)
from app.db.models.base import Base, utc_now
from app.db.models.cases import (
    AuditCase,
    CaseFinding,
    CaseTask,
)
from app.db.models.findings import (
    DetectorConfig,
    Finding,
    FindingTransaction,
)
from app.db.models.ingestion import (
    IngestionJob,
    SourceRecord,
    SourceRecordTransaction,
    SourceSystem,
)
from app.db.models.journals import Journal, JournalLine
from app.db.models.outbox import OutboxEvent
from app.db.models.reconciliation import (
    ReconciliationResult,
    ReconciliationRun,
)
from app.db.models.rules import Rule
from app.db.models.transactions import Transaction
from app.db.models.workflow import (
    WorkflowEdge,
    WorkflowTaskTemplate,
    WorkflowTemplate,
)

__all__ = [
    "Base",
    "utc_now",
    "Branch",
    "Account",
    "SourceSystem",
    "IngestionJob",
    "SourceRecord",
    "SourceRecordTransaction",
    "Transaction",
    "Journal",
    "JournalLine",
    "ReconciliationRun",
    "ReconciliationResult",
    "DetectorConfig",
    "Finding",
    "FindingTransaction",
    "Rule",
    "AuditCase",
    "CaseFinding",
    "CaseTask",
    "WorkflowTemplate",
    "WorkflowTaskTemplate",
    "WorkflowEdge",
    "User",
    "Role",
    "UserRole",
    "ActivityLog",
    "OutboxEvent",
]
