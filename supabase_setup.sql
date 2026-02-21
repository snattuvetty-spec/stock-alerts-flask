-- ============================================================
-- Stock Alerts Pro - Supabase SQL Setup
-- Run this in Supabase SQL Editor
-- ============================================================

-- 1. FEEDBACK TABLE
create table if not exists feedback (
  id          uuid default gen_random_uuid() primary key,
  username    text not null,
  type        text not null default 'general',  -- general | bug | feature | billing
  subject     text,
  message     text not null,
  created_at  timestamptz default now(),
  read        boolean default false             -- mark as read in admin
);

-- Index for admin queries
create index if not exists idx_feedback_username on feedback(username);
create index if not exists idx_feedback_created_at on feedback(created_at desc);

-- 2. VERIFY users table has all Stripe columns (run if not already done)
alter table users add column if not exists stripe_customer_id text;
alter table users add column if not exists stripe_subscription_id text;
alter table users add column if not exists subscription_plan text default 'monthly';
alter table users add column if not exists subscription_cancel_at_period_end boolean default false;
alter table users add column if not exists premium boolean default false;

-- ============================================================
-- Enable Stripe Customer Portal in your Stripe Dashboard:
-- 1. Go to https://dashboard.stripe.com/settings/billing/portal
-- 2. Activate the portal
-- 3. Configure allowed features (cancel, upgrade/downgrade, update payment)
-- ============================================================
