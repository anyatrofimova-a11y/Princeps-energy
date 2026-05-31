-- WhatsApp inbox + outbox so the builder agent can DM us back.

CREATE SCHEMA IF NOT EXISTS whatsapp;

CREATE TABLE IF NOT EXISTS whatsapp.messages (
  message_id       text PRIMARY KEY,            -- WA message id (wamid.HBgL…)
  wa_from          text NOT NULL,               -- E.164 phone
  wa_to            text,
  direction        text NOT NULL CHECK (direction IN ('inbound','outbound')),
  body             text,
  intent           text,                        -- build | research | ask | other
  task_id          uuid REFERENCES builder.queue(task_id),
  raw              jsonb,                       -- full WA payload for replay
  created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_wa_msgs_from_created
  ON whatsapp.messages (wa_from, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_wa_msgs_task ON whatsapp.messages (task_id);

-- Operator allowlist — only these numbers can prompt the agent.
CREATE TABLE IF NOT EXISTS whatsapp.operators (
  phone_e164       text PRIMARY KEY,
  display_name     text,
  role             text DEFAULT 'owner',
  created_at       timestamptz NOT NULL DEFAULT now()
);
