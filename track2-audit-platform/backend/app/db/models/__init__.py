"""Import all models so Alembic observes complete metadata."""

from .accounts import Account, Branch, SourceSystem
from .audit import ActivityLog
from .auth import Role, User, UserRole
from .base import Base
from .cases import AuditCase, CaseFinding
from .findings import (
    AuditRule,
    AuditRuleVersion,
    DetectorRun,
    Finding,
    FindingEvidence,
    ReconciliationResult,
    ReconciliationRun,
)
from .journals import Journal, JournalLine
from .ingestion import IngestionJob, IngestionRowError, IngestionSourceRow, SourceFile
from .outbox import OutboxEvent
from .transactions import CanonicalTransaction, SourceRecord, SourceRecordLink
from .workflow import (
    CaseWorkflowTask,
    WorkflowDependency,
    WorkflowTaskTemplate,
    WorkflowTemplate,
)

__all__ = [
    "Account", "ActivityLog", "AuditCase", "AuditRule", "AuditRuleVersion",
    "Base", "Branch", "CanonicalTransaction", "CaseFinding",
    "CaseWorkflowTask", "DetectorRun", "Finding", "FindingEvidence", "Journal",
    "IngestionJob", "IngestionRowError", "IngestionSourceRow", "JournalLine",
    "OutboxEvent", "ReconciliationResult", "ReconciliationRun", "SourceFile",
    "Role", "SourceRecord", "SourceRecordLink", "SourceSystem", "User",
    "UserRole", "WorkflowDependency", "WorkflowTaskTemplate", "WorkflowTemplate",
]
