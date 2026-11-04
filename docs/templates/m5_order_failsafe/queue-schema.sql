-- Migration companion schema, never a product schema change.
CREATE SCHEMA IF NOT EXISTS migration_order_failsafe;
CREATE TABLE migration_order_failsafe.scope_admission (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  PRIMARY KEY (tenant_id, project_id)
);
CREATE TABLE migration_order_failsafe.order_journal (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  event_id text NOT NULL,
  admission_seq bigint GENERATED ALWAYS AS IDENTITY,
  owner_job_id text,
  stage text NOT NULL DEFAULT 'validate',
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'active', 'held', 'done')),
  payload_json jsonb NOT NULL,
  retry_attempt integer NOT NULL DEFAULT 0,
  validate_response jsonb NOT NULL DEFAULT '{}',
  map_response jsonb NOT NULL DEFAULT '{}',
  context_json text NOT NULL DEFAULT '{}',
  PRIMARY KEY (tenant_id, project_id, event_id),
  UNIQUE (tenant_id, project_id, admission_seq)
);
CREATE UNIQUE INDEX one_active_order_per_scope
  ON migration_order_failsafe.order_journal(tenant_id, project_id)
  WHERE status = 'active';
