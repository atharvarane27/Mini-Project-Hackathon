"""Idempotent Database Seed Script for Track 2 AuditForge Platform.

Seeds:
- 5 RBAC roles (ADMIN, AUDITOR, REVIEWER, VIEWER, SYSTEM_WORKER)
- Demo users with Argon2 password hashes
- Source systems, branches, and sample accounts
- Core detector configurations (v1)
- Mandatory Track 2 Dual Prerequisite Workflow Template
- Initial audit AST evaluation rules
"""

import logging
from datetime import UTC, datetime

from argon2 import PasswordHasher
from sqlalchemy.orm import Session

from app.db.models import (
    Account,
    Branch,
    DetectorConfig,
    Role,
    Rule,
    SourceSystem,
    User,
    UserRole,
    WorkflowEdge,
    WorkflowTaskTemplate,
    WorkflowTemplate,
)
from app.db.session import get_db_context

logger = logging.getLogger("auditforge.seed")


def seed_database(db: Session) -> dict[str, int]:
    """Seed reference tables and demo users idempotently."""
    ph = PasswordHasher()
    counts = {"roles": 0, "users": 0, "branches": 0, "accounts": 0, "workflows": 0, "rules": 0}

    # 1. Roles
    roles_data = [
        ("role-admin", "ADMIN", "System Administrator with full configuration and user access"),
        (
            "role-auditor",
            "AUDITOR",
            "Audit investigator managing assigned cases and resolving findings",
        ),
        (
            "role-reviewer",
            "REVIEWER",
            "Senior reviewer approving escalations and reviewing complex cycles",
        ),
        ("role-viewer", "VIEWER", "Read-only viewer for aggregated reports and dashboards"),
        (
            "role-worker",
            "SYSTEM_WORKER",
            "Internal worker account for background outbox dispatch and heap claims",
        ),
    ]
    for r_id, name, desc in roles_data:
        existing = db.query(Role).filter_by(name=name).first()
        if not existing:
            db.add(Role(id=r_id, name=name, description=desc))
            counts["roles"] += 1
    db.flush()

    # 2. Demo Users
    demo_users = [
        ("usr-admin-01", "admin", "Admin123!AuditPass", "ADMIN"),
        ("usr-auditor-01", "auditor", "Auditor123!Investigate", "AUDITOR"),
        ("usr-reviewer-01", "reviewer", "Reviewer123!Escalate", "REVIEWER"),
        ("usr-viewer-01", "viewer", "Viewer123!ReadOnly", "VIEWER"),
        ("usr-system-01", "system_worker", "SystemWorker123!Daemon", "SYSTEM_WORKER"),
    ]
    for u_id, username, plain_pw, role_name in demo_users:
        existing_u = db.query(User).filter_by(username=username).first()
        if not existing_u:
            pw_hash = ph.hash(plain_pw)
            user = User(id=u_id, username=username, password_hash=pw_hash, status="ACTIVE")
            db.add(user)
            db.flush()

            role = db.query(Role).filter_by(name=role_name).first()
            if role:
                db.add(UserRole(user_id=user.id, role_id=role.id))
            counts["users"] += 1
    db.flush()

    # 3. Source Systems
    sources = [
        (
            "SRC_INTERNAL_CORE",
            "Core Banking Internal Ledger (Mumbai/Delhi/BLR)",
            "Internal branch postings and CBS feed",
        ),
        (
            "SRC_CLEARING_HOUSE",
            "National Clearing House / RTGS / NEFT Feed",
            "Interbank settlement clearing house",
        ),
        (
            "SRC_SWIFT_GATEWAY",
            "Cross-Border SWIFT Messaging Gateway",
            "Foreign exchange and cross-border transfers",
        ),
    ]
    for s_id, name, desc in sources:
        if not db.query(SourceSystem).filter_by(id=s_id).first():
            db.add(SourceSystem(id=s_id, name=name, description=desc))
    db.flush()

    # 4. Branches
    branches = [
        ("br-mum-01", "BR-MUMBAI", "Mumbai Nariman Point Flagship Branch"),
        ("br-del-01", "BR-DELHI", "New Delhi Connaught Place Central Branch"),
        ("br-blr-01", "BR-BLR", "Bengaluru Electronic City Tech Hub"),
    ]
    for b_id, code, name in branches:
        if not db.query(Branch).filter_by(code=code).first():
            db.add(Branch(id=b_id, code=code, name=name))
            counts["branches"] += 1
    db.flush()

    # 5. Accounts
    accounts = [
        ("acc-mum-1001", "br-mum-01", "INR", "MUM-1001-ALPHA"),
        ("acc-mum-1002", "br-mum-01", "INR", "MUM-1002-BETA"),
        ("acc-del-2001", "br-del-01", "INR", "DEL-2001-GAMMA"),
        ("acc-del-2002", "br-del-01", "INR", "DEL-2002-DELTA"),
        ("acc-blr-3001", "br-blr-01", "INR", "BLR-3001-EPSILON"),
    ]
    for a_id, b_id, curr, label in accounts:
        if not db.query(Account).filter_by(id=a_id).first():
            db.add(Account(id=a_id, branch_id=b_id, currency=curr, masked_label=label))
            counts["accounts"] += 1
    db.flush()

    # 6. Core Detector Configurations
    detectors = [
        (
            "cfg-dup-v1",
            "DUPLICATE_DETECTION",
            1,
            {"similarity_threshold": 0.85, "block_window_days": 3},
        ),
        (
            "cfg-circ-v1",
            "CIRCULAR_FLOW",
            1,
            {
                "max_cycle_minutes": 60,
                "min_initial_amount_minor": 1000000,
                "max_amount_drop_percent": 10,
            },
        ),
        (
            "cfg-split-v1",
            "SPLITTING",
            1,
            {"window_minutes": 60, "amount_threshold_minor": 10000000, "min_count": 3},
        ),
        (
            "cfg-recon-v1",
            "RECONCILIATION",
            1,
            {"allowed_variance_minor": 50000, "cutoff_minutes": 120},
        ),
    ]
    for d_id, d_type, ver, cfg in detectors:
        if not db.query(DetectorConfig).filter_by(detector_type=d_type, version=ver).first():
            db.add(
                DetectorConfig(
                    id=d_id, detector_type=d_type, version=ver, config_json=cfg, status="ACTIVE"
                )
            )
    db.flush()

    # 7. Workflow Templates: Track 2 Dual Prerequisite Investigation
    tpl_id = "tpl-track2-dual-prereq"
    if not db.query(WorkflowTemplate).filter_by(id=tpl_id).first():
        wf_tpl = WorkflowTemplate(
            id=tpl_id,
            name="Track2_Dual_Prerequisite_Investigation",
            version=1,
            status="ACTIVE",
        )
        db.add(wf_tpl)
        db.flush()

        task_blc = WorkflowTaskTemplate(
            id="task-tpl-blc",
            template_id=tpl_id,
            stable_key="Branch_Ledge_Clearance",  # Preserves exact official PDF spelling
            display_name="Branch Ledger Clearance",
            description="Branch internal ledger reconciliation and balance verification",
        )
        task_ewa = WorkflowTaskTemplate(
            id="task-tpl-ewa",
            template_id=tpl_id,
            stable_key="External_Whistleblower_Audit",
            display_name="External Whistleblower Audit",
            description="External complaint and whistleblower tip verification",
        )
        task_esc = WorkflowTaskTemplate(
            id="task-tpl-esc",
            template_id=tpl_id,
            stable_key="Escalation_Status",
            display_name="Senior Reviewer Escalation",
            description=(
                "Senior review escalation gating; "
                "unlocked ONLY after both prerequisites complete"
            ),
        )
        db.add_all([task_blc, task_ewa, task_esc])
        db.flush()

        # Prerequisite edges: BLC -> ESC and EWA -> ESC
        edge1 = WorkflowEdge(
            template_id=tpl_id,
            predecessor_template_task_id=task_blc.id,
            successor_template_task_id=task_esc.id,
        )
        edge2 = WorkflowEdge(
            template_id=tpl_id,
            predecessor_template_task_id=task_ewa.id,
            successor_template_task_id=task_esc.id,
        )
        db.add_all([edge1, edge2])
        counts["workflows"] += 1
    db.flush()

    # 8. Rules
    r_id = "rule-audit-v1"
    if not db.query(Rule).filter_by(id=r_id).first():
        rule_expr = (
            "(Reconciliation_Variance_Minor > 50000 AND Balance_Anomaly_Flag == TRUE) "
            "OR (Circular_Flow_Detected == TRUE AND Cycle_Length >= 3)"
        )
        rule = Rule(
            id=r_id,
            name="High_Variance_Or_Circular_Alert",
            version=1,
            expression=rule_expr,
            status="ACTIVE",
            created_by="usr-admin-01",
            activated_at=datetime.now(UTC),
        )
        db.add(rule)
        counts["rules"] += 1
    db.flush()

    return counts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    with get_db_context() as session:
        result = seed_database(session)
        print(f"Seed completed successfully: {result}")
