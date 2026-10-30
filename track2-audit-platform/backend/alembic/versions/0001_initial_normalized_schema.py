"""Initial normalized banking-audit schema."""

from alembic import op

from app.db.models import Base


revision = "0001_normalized"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=False)
    roles = Base.metadata.tables["roles"]
    op.bulk_insert(
        roles,
        [
            {"id": "00000000-0000-0000-0000-000000000001", "name": "ADMIN"},
            {"id": "00000000-0000-0000-0000-000000000002", "name": "AUDITOR"},
            {"id": "00000000-0000-0000-0000-000000000003", "name": "REVIEWER"},
            {"id": "00000000-0000-0000-0000-000000000004", "name": "VIEWER"},
        ],
    )


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=True)
