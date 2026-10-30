-- Run Alembic first. Keep financial evidence restrictive and activity append-only.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    GRANT SELECT, INSERT ON activity_log TO authenticated;
    REVOKE UPDATE, DELETE, TRUNCATE ON activity_log FROM authenticated;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION reject_activity_log_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'activity_log is append-only';
END $$;

DROP TRIGGER IF EXISTS activity_log_no_mutation ON activity_log;
CREATE TRIGGER activity_log_no_mutation
BEFORE UPDATE OR DELETE ON activity_log
FOR EACH ROW EXECUTE FUNCTION reject_activity_log_mutation();
