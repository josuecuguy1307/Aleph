-- Shared admission leases for inspection, across workers and hosts.
CREATE TABLE IF NOT EXISTS inspect_leases (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    expires_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inspect_leases_owner ON inspect_leases(owner_id);
CREATE INDEX IF NOT EXISTS idx_inspect_leases_expiry ON inspect_leases(expires_at);
