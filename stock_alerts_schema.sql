-- ============================================================
-- Stock Alerts Pro — Full Supabase Schema
-- Run this in Supabase SQL Editor after creating new project
-- ============================================================

-- 1. USERS
CREATE TABLE IF NOT EXISTS users (
    id                      BIGSERIAL PRIMARY KEY,
    username                TEXT UNIQUE NOT NULL,
    password_hash           TEXT NOT NULL,
    email                   TEXT UNIQUE NOT NULL,
    name                    TEXT NOT NULL,
    premium                 BOOLEAN DEFAULT FALSE,
    trial_ends              TIMESTAMP,
    promo_code              TEXT,
    session_token           TEXT,
    last_login              TIMESTAMP,
    last_logout             TIMESTAMP,
    stripe_customer_id      TEXT,
    stripe_subscription_id  TEXT,
    subscription_plan       TEXT DEFAULT 'monthly'
);

-- 2. ALERTS
CREATE TABLE IF NOT EXISTS alerts (
    id          BIGSERIAL PRIMARY KEY,
    username    TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    symbol      TEXT NOT NULL,
    target      NUMERIC(12, 4) NOT NULL,
    type        TEXT NOT NULL CHECK (type IN ('above', 'below')),
    enabled     BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- 3. USER SETTINGS
CREATE TABLE IF NOT EXISTS user_settings (
    id                  BIGSERIAL PRIMARY KEY,
    username            TEXT UNIQUE NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    email               TEXT,
    email_enabled       BOOLEAN DEFAULT FALSE,
    telegram_enabled    BOOLEAN DEFAULT FALSE,
    telegram_chat_id    TEXT,
    notification_method TEXT DEFAULT 'telegram',
    forex_pairs         TEXT  -- stored as JSON string
);

-- 4. LOGIN HISTORY
CREATE TABLE IF NOT EXISTS login_history (
    id           BIGSERIAL PRIMARY KEY,
    username     TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    logged_in_at TIMESTAMP DEFAULT NOW()
);

-- 5. PROMO CODES
CREATE TABLE IF NOT EXISTS promo_codes (
    id          BIGSERIAL PRIMARY KEY,
    code        TEXT UNIQUE NOT NULL,
    trial_days  INTEGER NOT NULL DEFAULT 21,
    active      BOOLEAN DEFAULT TRUE,
    max_uses    INTEGER,
    uses_count  INTEGER DEFAULT 0,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- 6. WATCHLIST
CREATE TABLE IF NOT EXISTS watchlist (
    id          BIGSERIAL PRIMARY KEY,
    username    TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    symbol      TEXT NOT NULL,
    added_at    TIMESTAMP DEFAULT NOW(),
    UNIQUE(username, symbol)
);

-- ============================================================
-- Indexes for performance
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_alerts_username     ON alerts(username);
CREATE INDEX IF NOT EXISTS idx_alerts_enabled      ON alerts(enabled);
CREATE INDEX IF NOT EXISTS idx_alerts_symbol       ON alerts(symbol);
CREATE INDEX IF NOT EXISTS idx_login_history_user  ON login_history(username);
CREATE INDEX IF NOT EXISTS idx_user_settings_user  ON user_settings(username);
