-- Every inbound event, deduplicated by event id
CREATE TABLE IF NOT EXISTS webhook_events (
  event_id     TEXT PRIMARY KEY,
  source       TEXT NOT NULL,              -- 'crm' | 'zoho'
  payload      JSONB NOT NULL,
  received_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per CRM deal; "state" is the pipeline state machine
CREATE TABLE IF NOT EXISTS deals (
  crm_deal_id        TEXT PRIMARY KEY,
  title              TEXT,
  org_name           TEXT,
  tax_number         TEXT,
  currency           TEXT NOT NULL DEFAULT 'AED',
  net_amount_minor   BIGINT NOT NULL,           -- excl. VAT, in fils
  vat_rate_bp        INT NOT NULL DEFAULT 500,  -- basis points: 500 = 5%
  stage              TEXT,
  state              TEXT NOT NULL DEFAULT 'NEW',
  -- NEW, CUSTOMER_OK, SO_OK, INVOICING, DONE, NEEDS_REVIEW, FAILED
  needs_review       BOOLEAN NOT NULL DEFAULT FALSE,
  review_reason      TEXT,
  last_error         TEXT,
  zoho_customer_id   TEXT,
  zoho_so_id         TEXT,
  so_total_minor     BIGINT,
  metrics            JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Deal line items from the CRM, mapped to Zoho items
CREATE TABLE IF NOT EXISTS deal_products (
  id               BIGSERIAL PRIMARY KEY,
  crm_deal_id      TEXT NOT NULL REFERENCES deals(crm_deal_id),
  crm_product      TEXT NOT NULL,
  quantity         NUMERIC NOT NULL DEFAULT 1,
  unit_price_minor BIGINT NOT NULL
);

-- CRM product -> Zoho item (never guess)
CREATE TABLE IF NOT EXISTS product_item_map (
  crm_product    TEXT PRIMARY KEY,
  zoho_item_id   TEXT NOT NULL
);

-- Milestones of each deal; amounts are VAT-inclusive and sum exactly to SO total
CREATE TABLE IF NOT EXISTS milestones (
  crm_deal_id      TEXT NOT NULL REFERENCES deals(crm_deal_id),
  seq              INT NOT NULL,
  label            TEXT NOT NULL,
  pct_bp           INT NOT NULL,           -- 5000 = 50%
  amount_minor     BIGINT NOT NULL,
  trigger_type     TEXT NOT NULL,          -- 'signing' | 'go_live' | 'go_live_plus_days'
  trigger_days     INT NOT NULL DEFAULT 0,
  reached_at       TIMESTAMPTZ,
  due_date         DATE,
  zoho_invoice_id  TEXT,
  PRIMARY KEY (crm_deal_id, seq)
);

-- Local mirror of Zoho invoices (source for metrics + collections)
CREATE TABLE IF NOT EXISTS invoices (
  zoho_invoice_id  TEXT PRIMARY KEY,
  crm_deal_id      TEXT REFERENCES deals(crm_deal_id),
  milestone_seq    INT,
  invoice_number   TEXT,
  status           TEXT,                   -- draft, sent, paid, partially_paid, overdue, void
  total_minor      BIGINT NOT NULL,
  balance_minor    BIGINT NOT NULL,
  due_date         DATE,
  zoho_modified_at TIMESTAMPTZ,
  synced_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS payments (
  zoho_payment_id  TEXT NOT NULL,
  zoho_invoice_id  TEXT NOT NULL,
  crm_deal_id      TEXT REFERENCES deals(crm_deal_id),
  amount_minor     BIGINT NOT NULL,        -- amount applied to THIS invoice
  paid_on          DATE,
  PRIMARY KEY (zoho_payment_id, zoho_invoice_id)
);

-- Durable job queue
CREATE TABLE IF NOT EXISTS jobs (
  id          BIGSERIAL PRIMARY KEY,
  type        TEXT NOT NULL,               -- 'process_deal', 'raise_invoice', 'reconcile'
  crm_deal_id TEXT,
  payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
  dedupe_key  TEXT UNIQUE,
  status      TEXT NOT NULL DEFAULT 'queued',
  -- queued, running, done, retry, failed
  attempts    INT NOT NULL DEFAULT 0,
  run_after   TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_error  TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS jobs_pick ON jobs (status, run_after);

-- Zoho OAuth token cache (single row)
CREATE TABLE IF NOT EXISTS oauth_tokens (
  id            INT PRIMARY KEY DEFAULT 1,
  access_token  TEXT,
  expires_at    TIMESTAMPTZ,
  CHECK (id = 1)
);

-- Every call to Zoho Books and the CRM
CREATE TABLE IF NOT EXISTS integration_log (
  id            BIGSERIAL PRIMARY KEY,
  at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  crm_deal_id   TEXT,
  system        TEXT NOT NULL,             -- 'zoho' | 'crm'
  method        TEXT NOT NULL,
  url           TEXT NOT NULL,
  status_code   INT,
  duration_ms   INT,
  request_body  JSONB,
  response_body JSONB,
  error         TEXT
);
CREATE INDEX IF NOT EXISTS log_deal ON integration_log (crm_deal_id, at DESC);

alter table milestones add column if not exists net_minor bigint;
alter table deals add column if not exists crm_status text;
alter table deals add column if not exists won_at timestamptz;
alter table deals add column if not exists go_live_date date;
alter table deals add column if not exists crm_update_time text;