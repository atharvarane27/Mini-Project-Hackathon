-- ============================================================================
-- Local PostgreSQL Initialization for Offline Demo Fallback Profile
-- ============================================================================
-- Application tables and constraints are managed via Alembic migrations.
-- This script prepares extensions and database triggers for offline parity.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Function to guarantee activity_log append-only immutability
CREATE OR REPLACE FUNCTION prevent_activity_log_tampering()
RETURNS TRIGGER AS $$
BEGIN
    IF (TG_OP = 'UPDATE') THEN
        RAISE EXCEPTION 'SECURITY ERROR: UPDATE is forbidden on activity_log table. Audit log is append-only.';
    ELSIF (TG_OP = 'DELETE') THEN
        RAISE EXCEPTION 'SECURITY ERROR: DELETE is forbidden on activity_log table. Audit log is append-only.';
    ELSIF (TG_OP = 'TRUNCATE') THEN
        RAISE EXCEPTION 'SECURITY ERROR: TRUNCATE is forbidden on activity_log table. Audit log is append-only.';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
