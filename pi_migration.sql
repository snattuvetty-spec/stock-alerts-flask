-- Run this in Supabase SQL Editor
-- Adds Pi Network support columns and payments table

ALTER TABLE users ADD COLUMN IF NOT EXISTS pi_uid TEXT UNIQUE;

CREATE TABLE IF NOT EXISTS pi_payments (
    id          BIGSERIAL PRIMARY KEY,
    username    TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    payment_id  TEXT UNIQUE NOT NULL,
    txid        TEXT,
    status      TEXT DEFAULT 'pending',
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pi_payments_username ON pi_payments(username);
CREATE INDEX IF NOT EXISTS idx_pi_payments_payment_id ON pi_payments(payment_id);
