# Webhook Adapter

Ingest payment webhooks from **Stripe**, **Adyen**, and **PayPal**, normalize them to a single canonical schema, and persist to SQLite or Postgres. One endpoint, one schema, multiple providers.

---

## Features

- **Single endpoint** — `POST /webhook` accepts all three providers; source is detected from headers/body.
- **Canonical schema** — Every event is normalized to the same `extracted` shape (see [docs/SCHEMA.md](docs/SCHEMA.md)).
- **Signature verification** — Optional verification using each provider’s secret (Stripe signing secret, Adyen HMAC, PayPal webhook ID).
- **Idempotency** — Duplicate events (same provider + id) return 200 with existing payload.
- **Rate limiting** — Configurable in-memory rate limiter.
- **Optional notification** — POST to a URL (e.g. Slack) on successful ingest.
- **DLQ** — Invalid or failed payloads can be written to a dead-letter queue (file or Postgres).

---

## Prerequisites

- **Python 3.11+**
- **SQLite** (default) or **PostgreSQL** for persistence

---

## Quick start

### 1. Clone and install

```bash
git clone <repo-url>
cd th1
```

Using a virtual environment and pip:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Or with [uv](https://github.com/astral-sh/uv):

```bash
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
```

### 2. Environment variables

Copy the example env and edit as needed:

```bash
cp .env.example .env
```

For local development you can leave everything commented; the app uses defaults (SQLite, no verification, no notification). See [Environment variables](#environment-variables) below for all options.

### 3. Database and migrations

Using default SQLite, the DB file is created on first run. For Postgres, set `DATABASE_URL` and run migrations:

```bash
export DATABASE_URL="postgresql+asyncpg://user:password@host:5432/dbname?ssl=require"
alembic upgrade head
```

### 4. Run the app

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- **Health:** [http://localhost:8000/health](http://localhost:8000/health)  
- **Readiness (DB):** [http://localhost:8000/readyz](http://localhost:8000/readyz)  
- **Webhook:** `POST http://localhost:8000/webhook` with provider payload and (for Stripe/PayPal) appropriate headers.

---

## Environment variables

All are optional; defaults are shown. Set them in `.env` or in the shell.

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./webhook.db` | Database URL. Use `postgresql+asyncpg://...` for Postgres (e.g. Supabase). |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `ENV` | `development` | Environment name (e.g. `production`). |
| `RATE_LIMIT_REQUESTS` | `100` | Max requests per window. Set `0` to disable rate limiting. |
| `RATE_LIMIT_WINDOW_SECONDS` | `60.0` | Rate limit window in seconds. |
| `NOTIFICATION_WEBHOOK_URL` | — | Optional URL to POST on successful ingest (e.g. Slack incoming webhook). |
| `STRIPE_WEBHOOK_SECRET` | — | Stripe webhook signing secret (`whsec_...`) for signature verification. If unset, Stripe payloads are accepted without verification. |
| `ADYEN_HMAC_KEY` | — | Adyen HMAC key (hex) from Customer Area → Developers → Webhooks. If unset, Adyen payloads are accepted without verification. |
| `PAYPAL_WEBHOOK_ID` | — | PayPal webhook subscription ID for signature verification. If unset, PayPal payloads are accepted without verification. |
| `MAX_BODY_SIZE` | `1048576` | Max request body size in bytes (default 1 MB). Larger payloads receive 413. |

### Example `.env` (development)

```env
DATABASE_URL=sqlite+aiosqlite:///./webhook.db
LOG_LEVEL=INFO
ENV=development
# NOTIFICATION_WEBHOOK_URL=https://hooks.slack.com/services/xxx/yyy/zzz
# RATE_LIMIT_REQUESTS=100
# RATE_LIMIT_WINDOW_SECONDS=60.0
# Stripe: Dashboard → Developers → Webhooks → Signing secret
# STRIPE_WEBHOOK_SECRET=whsec_...
# Adyen: Customer Area → Developers → Webhooks → HMAC key (hex)
# ADYEN_HMAC_KEY=...
# PayPal: from your webhook subscription (e.g. 29W349713X5515543)
# PAYPAL_WEBHOOK_ID=...
```

### Example `.env` (production with Postgres)

```env
DATABASE_URL=postgresql+asyncpg://postgres:PASSWORD@db.xxxx.supabase.co:5432/postgres?ssl=require
LOG_LEVEL=INFO
ENV=production
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW_SECONDS=60.0
NOTIFICATION_WEBHOOK_URL=https://hooks.slack.com/services/xxx/yyy/zzz
STRIPE_WEBHOOK_SECRET=whsec_...
ADYEN_HMAC_KEY=...
PAYPAL_WEBHOOK_ID=...
```

---

## Reproducing the setup

To get the same behaviour as “from scratch”:

1. **Python 3.11+** and a venv.
2. **Install:** `pip install -r requirements.txt` (or `uv pip install -r requirements.txt`).
3. **Config:** Copy `.env.example` to `.env` and set at least `DATABASE_URL` if using Postgres.
4. **Migrations (Postgres only):** `alembic upgrade head`.
5. **Run:** `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`.

For Stripe/PayPal verification in local testing, use the Stripe CLI or each provider’s test webhook UI and set the corresponding secret in `.env`.

---

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness; returns `{"status":"ok"}`. |
| `GET` | `/readyz` | Readiness; 200 if DB is reachable, 503 otherwise. |
| `POST` | `/webhook` | Ingest webhook. Body = raw provider payload. For Stripe, send `Stripe-Signature` header; for PayPal, `paypal-transmission-id` (and related). Content-Type typically `application/json`. |

### Webhook response

- **201** — Event created (body = normalized event with `event_id`, `source`, `extracted`, `raw`).
- **200** — Duplicate (same event already stored).
- **202** — Invalid (e.g. signature failure or bad payload); may be written to DLQ.
- **413** — Body larger than `MAX_BODY_SIZE`.
- **429** — Rate limited.

---

## Canonical schema

Stored and API output use only: `event_id`, `source`, `extracted`, `raw`. All normalized fields live in `extracted`. See **[docs/SCHEMA.md](docs/SCHEMA.md)** for the full field list and types.

- **Sources:** `stripe` \| `adyen` \| `paypal` \| `unknown`
- **Canonical event types** (in `extracted.canonical_event_type`): `payment.authorised`, `payment.captured`, `payment.refunded`, `payment.cancelled`, `payment.failed`, `invoice.paid`, `customer.created`, `dispute`, `other`

---

## Project structure

```
├── app/
│   ├── api/routes.py      # Health, readyz, POST /webhook
│   ├── core/              # Config, rate limit, DLQ, logging, retry
│   ├── db/                # Session, models, events table, migrations
│   ├── services/webhook_service.py  # Ingest, verify, normalize, persist
│   ├── utils/             # normalize, event_id, stripe/adyen/paypal signature
│   └── main.py
├── alembic/               # Migrations
├── tests/
├── docs/SCHEMA.md
├── .env.example
├── requirements.txt
├── pyproject.toml
└── Dockerfile
```

---

## Tests

```bash
# All tests
pytest

# With coverage (if you add pytest-cov)
pytest --cov=app
```

Tests include: API (webhook, health, readyz), normalization (Stripe, Adyen, PayPal), signature verification (Stripe, Adyen, PayPal), rate limiting, and DLQ behaviour.

---

## Deployment

See **[DEPLOY.md](DEPLOY.md)** for Docker build, Postgres (e.g. Supabase), and platform notes (Railway, Render, Fly.io). Run `alembic upgrade head` against the production DB before or after deploy as described there.

---

## License

See repository license file.
