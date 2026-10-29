-- ============================================================================
-- Supabase Managed PostgreSQL Bootstrap Script for Track 2 AuditForge
-- ============================================================================
-- This script runs once during project provisioning.
-- Application tables and constraints are managed exclusively via Alembic migrations.
-- This script establishes required extensions, roles, and append-only audit enforcement.
-- ============================================================================

-- 1. Enable required PostgreSQL extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 2. Immutable Activity Log Enforcement (Append-Only)
-- Ensure activity_log can never be modified or deleted via SQL triggers
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

-- Apply trigger to activity_log if table exists
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'activity_log') THEN
        DROP TRIGGER IF EXISTS trg_activity_log_append_only ON activity_log;
        CREATE TRIGGER trg_activity_log_append_only
            BEFORE UPDATE OR DELETE ON activity_log
            FOR EACH ROW
            EXECUTE FUNCTION prevent_activity_log_tampering();
    END IF;
END $$;

-- 3. Revoke dangerous permissions on audit history from standard application roles
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'activity_log') THEN
        REVOKE UPDATE, DELETE, TRUNCATE ON activity_log FROM PUBLIC;
        REVOKE UPDATE, DELETE, TRUNCATE ON activity_log FROM anon, authenticated;
    END IF;
END $$;
