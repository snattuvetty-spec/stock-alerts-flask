# Stock Alerts Pro — Final Setup Checklist

## 1. Supabase (run SQL first)
- [ ] Open Supabase → SQL Editor
- [ ] Paste and run `supabase_setup.sql`
- [ ] Confirm `feedback` table appears in Table Editor

---

## 2. Render Environment Variables
Add/confirm these in Render → Environment:

| Variable | Value |
|---|---|
| `STRIPE_SECRET_KEY` | sk_live_... (from Stripe dashboard) |
| `STRIPE_PUBLISHABLE_KEY` | pk_live_... |
| `STRIPE_PRICE_MONTHLY` | price_1T2isyEX5QghswoUgNNcfJCN |
| `STRIPE_PRICE_ANNUAL` | price_1T2iusEX5QghswoUFfYVYedR |
| `STRIPE_WEBHOOK_SECRET` | whsec_... (from Stripe webhook setup) |
| `EMAIL_SENDER` | your Gmail address |
| `EMAIL_PASSWORD` | Gmail App Password (not your login password) |
| `SMTP_SERVER` | smtp.gmail.com |
| `SMTP_PORT` | 587 |

> **Gmail App Password**: Google Account → Security → 2-Step Verification → App passwords

---

## 3. Stripe Dashboard Setup

### Webhook (critical)
1. Stripe Dashboard → Developers → Webhooks → Add endpoint
2. URL: `https://stock-alerts-flask.onrender.com/stripe-webhook`
3. Events to listen for:
   - `checkout.session.completed`
   - `customer.subscription.deleted`
   - `customer.subscription.updated`
4. Copy the **Signing secret** → paste as `STRIPE_WEBHOOK_SECRET` in Render

### Customer Portal
1. Stripe Dashboard → Settings → Billing → Customer portal
2. Click **Activate test link** (then activate for live)
3. Enable: Cancel subscription, Update payment method, View billing history

---

## 4. File Changes Summary

### `app.py` changes:
- **Fixed** `create_checkout_session` — now fetches email from DB (was using `session.get('email')` which was always empty)
- **Fixed** `create_checkout_session` — reuses existing Stripe customer ID to avoid duplicate customers
- **Added** `/customer-portal` route — redirects to Stripe billing portal
- **Added** `/feedback` route (GET+POST) — form page
- **Added** `/api/feedback` route (POST) — AJAX endpoint for modal use

### New files:
- `templates/feedback.html` — feedback form page

---

## 5. Add Feedback Link to Your Templates

Add this wherever suits (e.g. in `base.html` sidebar/footer or `dashboard.html`):

```html
<!-- Feedback link -->
<a href="{{ url_for('feedback') }}" style="color:#6c63ff; font-size:13px; text-decoration:none;">
  💬 Send Feedback
</a>
```

Or as a floating button (paste before `</body>` in `base.html`):

```html
<a href="{{ url_for('feedback') }}"
   style="position:fixed; bottom:24px; right:24px; background:linear-gradient(135deg,#6c63ff,#4ecdc4);
          color:#fff; padding:12px 18px; border-radius:50px; font-size:13px; font-weight:700;
          text-decoration:none; box-shadow:0 4px 16px rgba(108,99,255,0.4); z-index:999;">
  💬 Feedback
</a>
```

---

## 6. Add Customer Portal Button to `settings.html`

Find your existing subscription section and add:

```html
<!-- Manage Subscription via Stripe Portal -->
{% if settings.premium %}
<form action="{{ url_for('customer_portal') }}" method="POST" style="margin-top:12px;">
  <button type="submit"
    style="padding:10px 20px; background:#fff; border:2px solid #6c63ff; color:#6c63ff;
           border-radius:8px; font-size:14px; font-weight:600; cursor:pointer;">
    🔧 Manage Subscription &amp; Billing
  </button>
</form>
{% endif %}
```

---

## 7. support@stockalertspro.com Setup

You have two options:

### Option A — Forward to your Gmail (easiest)
1. Buy/use domain `stockalertspro.com` (via Namecheap, GoDaddy etc.)
2. Set up email forwarding: `support@stockalertspro.com` → your Gmail
3. Replies come to your Gmail inbox

### Option B — Use nattsdigital.com.au email
- Set `EMAIL_SENDER` = your nattsdigital email
- Send from that address, branded as Stock Alerts Pro
- Costs nothing extra since you already own the domain

### Fastest right now:
Use `support@nattsdigital.com.au` as sender in Render ENV, but display it as Stock Alerts Pro support in email signatures. You can migrate to `support@stockalertspro.com` once domain is set up.

---

## Quick Test Checklist After Deploy

- [ ] Visit `/feedback` — form loads
- [ ] Submit feedback → check Supabase `feedback` table for new row
- [ ] Check your email for notification to support@stockalertspro.com
- [ ] Click "Subscribe" → Stripe checkout loads with correct price
- [ ] Complete test payment → premium activates (check users table)
- [ ] Click "Manage Subscription" → redirects to Stripe portal
- [ ] Cancel from portal → `customer.subscription.deleted` webhook fires → premium removed
