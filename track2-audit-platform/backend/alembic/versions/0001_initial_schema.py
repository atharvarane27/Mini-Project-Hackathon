"""Initial 3NF database schema for Track 2 AuditForge Platform.

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-10-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. branches
    op.create_table(
        "branches",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_branches_code", "branches", ["code"], unique=True)

    # 2. accounts
    op.create_table(
        "accounts",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "branch_id",
            sa.String(length=64),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("masked_label", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("branch_id", "masked_label", name="uq_accounts_branch_masked_label"),
    )
    op.create_index("ix_accounts_branch_id", "accounts", ["branch_id"])

    # 3. source_systems
    op.create_table(
        "source_systems",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_source_systems_name", "source_systems", ["name"], unique=True)

    # 4. ingestion_jobs
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "source_system_id",
            sa.String(length=64),
            sa.ForeignKey("source_systems.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("counts_json", sa.JSON(), nullable=False),
    )
    op.create_index("ix_ingestion_jobs_source_system_id", "ingestion_jobs", ["source_system_id"])

    # 5. source_records
    op.create_table(
        "source_records",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "ingestion_job_id",
            sa.String(length=64),
            sa.ForeignKey("ingestion_jobs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_system_id",
            sa.String(length=64),
            sa.ForeignKey("source_systems.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("external_ref", sa.String(length=128), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=False, default=1),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("record_status", sa.String(length=32), nullable=False, default="PENDING"),
        sa.UniqueConstraint(
            "source_system_id",
            "external_ref",
            "source_revision",
            name="uq_source_records_system_ref_revision",
        ),
    )
    op.create_index(
        "ix_source_records_system_external_ref",
        "source_records",
        ["source_system_id", "external_ref"],
    )

    # 6. transactions
    op.create_table(
        "transactions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("external_canonical_ref", sa.String(length=128), nullable=True),
        sa.Column(
            "sender_account_id",
            sa.String(length=64),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "receiver_account_id",
            sa.String(length=64),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("txn_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.CheckConstraint("amount_minor > 0", name="chk_transactions_amount_minor_positive"),
        sa.UniqueConstraint("external_canonical_ref", name="uq_transactions_external_canonical_ref"),
    )
    op.create_index(
        "ix_transactions_occurred_sender",
        "transactions",
        ["occurred_at", "sender_account_id"],
    )
    op.create_index(
        "ix_transactions_receiver_occurred",
        "transactions",
        ["receiver_account_id", "occurred_at"],
    )

    # 7. source_record_transactions
    op.create_table(
        "source_record_transactions",
        sa.Column(
            "source_record_id",
            sa.String(length=64),
            sa.ForeignKey("source_records.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "transaction_id",
            sa.String(length=64),
            sa.ForeignKey("transactions.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("link_type", sa.String(length=32), nullable=False, default="CANONICAL"),
    )

    # 8. journals
    op.create_table(
        "journals",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "branch_id",
            sa.String(length=64),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("journal_ref", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, default="POSTED"),
    )
    op.create_index("ix_journals_journal_ref", "journals", ["journal_ref"], unique=True)

    # 9. journal_lines
    op.create_table(
        "journal_lines",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "journal_id",
            sa.String(length=64),
            sa.ForeignKey("journals.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.String(length=64),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("debit_minor", sa.BigInteger(), nullable=False, default=0),
        sa.Column("credit_minor", sa.BigInteger(), nullable=False, default=0),
        sa.CheckConstraint(
            "debit_minor >= 0 AND credit_minor >= 0 AND "
            "((debit_minor > 0 AND credit_minor = 0) OR (debit_minor = 0 AND credit_minor > 0))",
            name="chk_journal_lines_exactly_one_side_positive",
        ),
    )
    op.create_index("ix_journal_lines_journal_id", "journal_lines", ["journal_id"])
    op.create_index("ix_journal_lines_account_id", "journal_lines", ["account_id"])

    # 10. reconciliation_runs
    op.create_table(
        "reconciliation_runs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "source_left_id",
            sa.String(length=64),
            sa.ForeignKey("source_systems.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_right_id",
            sa.String(length=64),
            sa.ForeignKey("source_systems.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("policy_version_id", sa.String(length=64), nullable=True),
        sa.Column("input_checkpoint", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, default="PENDING"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("cutoff_at > start_at", name="chk_reconciliation_runs_cutoff_after_start"),
    )

    # 11. reconciliation_results
    op.create_table(
        "reconciliation_results",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("reconciliation_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "left_record_id",
            sa.String(length=64),
            sa.ForeignKey("source_records.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "right_record_id",
            sa.String(length=64),
            sa.ForeignKey("source_records.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("variance_minor", sa.BigInteger(), nullable=False, default=0),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.UniqueConstraint(
            "run_id",
            "left_record_id",
            "right_record_id",
            name="uq_reconciliation_results_run_records",
        ),
    )
    op.create_index("ix_reconciliation_results_run_id", "reconciliation_results", ["run_id"])

    # 12. detector_configs
    op.create_table(
        "detector_configs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("detector_type", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("detector_type", "version", name="uq_detector_configs_type_version"),
    )

    # 13. findings
    op.create_table(
        "findings",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("finding_type", sa.String(length=32), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "detector_config_id",
            sa.String(length=64),
            sa.ForeignKey("detector_configs.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, default="FLAGGED_FOR_REVIEW"),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("fingerprint", name="uq_findings_fingerprint"),
    )
    op.create_index(
        "ix_findings_type_created",
        "findings",
        ["finding_type", "created_at"],
    )

    # 14. finding_transactions
    op.create_table(
        "finding_transactions",
        sa.Column(
            "finding_id",
            sa.String(length=64),
            sa.ForeignKey("findings.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "transaction_id",
            sa.String(length=64),
            sa.ForeignKey("transactions.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("path_position", sa.Integer(), nullable=False, default=0),
    )

    # 15. users
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )

    # 16. roles
    op.create_table(
        "roles",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.UniqueConstraint("name", name="uq_roles_name"),
    )

    # 17. user_roles
    op.create_table(
        "user_roles",
        sa.Column(
            "user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "role_id",
            sa.String(length=64),
            sa.ForeignKey("roles.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
    )

    # 18. rules
    op.create_table(
        "rules",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("expression", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, default="DRAFT"),
        sa.Column(
            "created_by",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", "version", name="uq_rules_name_version"),
    )

    # 19. audit_cases
    op.create_table(
        "audit_cases",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("case_code", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False, default="QUEUED"),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False, default=1),
        sa.Column(
            "assignee_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "priority >= 0 AND priority <= 100",
            name="chk_audit_cases_priority_bounds",
        ),
        sa.UniqueConstraint("case_code", name="uq_audit_cases_case_code"),
    )
    op.create_index(
        "ix_audit_cases_state_priority",
        "audit_cases",
        ["state", "priority"],
    )

    # 20. case_findings
    op.create_table(
        "case_findings",
        sa.Column(
            "case_id",
            sa.String(length=64),
            sa.ForeignKey("audit_cases.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "finding_id",
            sa.String(length=64),
            sa.ForeignKey("findings.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
    )

    # 21. workflow_templates
    op.create_table(
        "workflow_templates",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, default="DRAFT"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", "version", name="uq_workflow_templates_name_version"),
    )

    # 22. workflow_task_templates
    op.create_table(
        "workflow_task_templates",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "template_id",
            sa.String(length=64),
            sa.ForeignKey("workflow_templates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("stable_key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "template_id",
            "stable_key",
            name="uq_workflow_task_templates_template_key",
        ),
    )
    op.create_index(
        "ix_workflow_task_templates_template_id",
        "workflow_task_templates",
        ["template_id"],
    )

    # 23. workflow_edges
    op.create_table(
        "workflow_edges",
        sa.Column(
            "template_id",
            sa.String(length=64),
            sa.ForeignKey("workflow_templates.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "predecessor_template_task_id",
            sa.String(length=64),
            sa.ForeignKey("workflow_task_templates.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "successor_template_task_id",
            sa.String(length=64),
            sa.ForeignKey("workflow_task_templates.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.CheckConstraint(
            "predecessor_template_task_id != successor_template_task_id",
            name="chk_workflow_edges_no_self_edge",
        ),
    )

    # 24. case_tasks
    op.create_table(
        "case_tasks",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(length=64),
            sa.ForeignKey("audit_cases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "task_template_id",
            sa.String(length=64),
            sa.ForeignKey("workflow_task_templates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("state", sa.String(length=32), nullable=False, default="PENDING"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, default=1),
    )
    op.create_index(
        "ix_case_tasks_case_state",
        "case_tasks",
        ["case_id", "state"],
    )

    # 25. activity_log
    op.create_table(
        "activity_log",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "actor_user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("actor_type", sa.String(length=32), nullable=False, default="SYSTEM"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("old_value", sa.JSON(), nullable=True),
        sa.Column("new_value", sa.JSON(), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
    )
    op.create_index(
        "ix_activity_log_entity_occurred",
        "activity_log",
        ["entity_type", "entity_id", "occurred_at"],
    )

    # 26. outbox_events
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, default="PENDING"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, default=0),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.UniqueConstraint(
            "event_type",
            "entity_id",
            "payload_hash",
            name="uq_outbox_events_dedup",
        ),
    )
    op.create_index(
        "ix_outbox_events_status_created",
        "outbox_events",
        ["status", "created_at"],
    )


def downgrade() -> None:
    # Drop tables in reverse dependency order
    op.drop_table("outbox_events")
    op.drop_table("activity_log")
    op.drop_table("case_tasks")
    op.drop_table("workflow_edges")
    op.drop_table("workflow_task_templates")
    op.drop_table("workflow_templates")
    op.drop_table("case_findings")
    op.drop_table("audit_cases")
    op.drop_table("rules")
    op.drop_table("user_roles")
    op.drop_table("roles")
    op.drop_table("users")
    op.drop_table("finding_transactions")
    op.drop_table("findings")
    op.drop_table("detector_configs")
    op.drop_table("reconciliation_results")
    op.drop_table("reconciliation_runs")
    op.drop_table("journal_lines")
    op.drop_table("journals")
    op.drop_table("source_record_transactions")
    op.drop_table("transactions")
    op.drop_table("source_records")
    op.drop_table("ingestion_jobs")
    op.drop_table("source_systems")
    op.drop_table("accounts")
    op.drop_table("branches")
