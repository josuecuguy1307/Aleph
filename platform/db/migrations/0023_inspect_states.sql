-- Preserve inspection lifecycle across workers and crashes. Admission only
-- counts start/running, and expiry changes an abandoned job to failed.
ALTER TABLE inspect_leases ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'running';
ALTER TABLE inspect_leases ADD COLUMN IF NOT EXISTS finished_at BIGINT;
ALTER TABLE inspect_leases ADD COLUMN IF NOT EXISTS pid BIGINT;
ALTER TABLE inspect_leases DROP CONSTRAINT IF EXISTS inspect_leases_status_check;
ALTER TABLE inspect_leases ADD CONSTRAINT inspect_leases_status_check
  CHECK (status IN ('start','running','finished','failed','cancelled'));
