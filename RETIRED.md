# Stock Alerts Pro — retired (Sep 2026)

The live service (Render + Supabase) was shut down to free resources. Everything needed to bring it back is here or listed below.

## What's in this repo
- `app.py` — Flask app (entry point `app`; APScheduler background jobs for price checks/reminders)
- `templates/`, `static/` — UI, PWA assets, Pi Network `validation-key.txt`
- `stock_alerts_schema.sql` — full database schema (run first in a new Supabase project)
- `pi_migration.sql` — Pi Network payments table/migration (run after the schema)
- `supabase_setup.sql` — feedback table + Stripe subscription columns on `users` (run last)
- `.env.example` — every environment variable the app reads
- `SETUP_CHECKLIST.md` — original Render / Stripe / Gmail setup steps

## Kept outside git (on purpose)
- Secrets: `.env`, `.env.staging`, `Important details.xlsx` → password manager
- `seed_admin.py` — creates the first admin user; contains a hard-coded admin password, so it is not committed.
  Keep it locally (or change it to read `ADMIN_EMAIL` / `ADMIN_PASSWORD` from env before committing).
- Database backup: Supabase `pg_dump` taken before deletion (store with the secrets).

## To revive
1. Create a Supabase project → SQL editor → run `stock_alerts_schema.sql`, then `pi_migration.sql`, then `supabase_setup.sql`.
2. Restore data from the backup if needed.
3. Create a Render web service from this repo: build `pip install -r requirements.txt`,
   start `gunicorn app:app` (single worker — the APScheduler jobs run in-process).
4. Set the variables from `.env.example` in Render (new keys — the old ones were revoked).
5. Re-point Stripe webhook and Pi Network app URL to the new domain; run `seed_admin.py` once.
