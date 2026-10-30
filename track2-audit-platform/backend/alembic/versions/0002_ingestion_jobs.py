"""Add bounded ingestion jobs and row provenance."""

from alembic import op

from app.db.models import Base


revision = "0002_ingestion"
down_revision = "0001_normalized"
branch_labels = None
depends_on = None


TABLES = (
    "ingestion_jobs", "source_files", "ingestion_source_rows",
    "ingestion_row_errors",
)


def upgrade() -> None:
    bind = op.get_bind()
    for name in TABLES:
        Base.metadata.tables[name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for name in reversed(TABLES):
        Base.metadata.tables[name].drop(bind=bind, checkfirst=True)
