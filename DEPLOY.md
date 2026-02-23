# Deploying to Production

## What Was Added

- **Dockerfile** – Builds the app image, runs migrations on startup, then starts uvicorn
- **Alembic** – Schema migrations for `events` and `dlq` tables
- **Postgres support** – `asyncpg` driver for `postgresql+asyncpg://` URLs
- **DLQ in Postgres** – Dead-letter queue stored in `dlq` table instead of files

## Prerequisites

1. **Supabase Postgres** (or any Postgres)
2. **Container registry** (Docker Hub, GitHub Container Registry, etc.)
3. **Deployment target** (Railway, Render, Fly.io, AWS ECS, Cloud Run, etc.)

---

## 1. Set Environment Variables

Create a `.env` (or set in your platform) with:

```bash
# Required: Supabase/Postgres URL (use connection pooling URL if available)
DATABASE_URL=postgresql+asyncpg://postgres:YOUR_PASSWORD@db.xxxx.supabase.co:5432/postgres?ssl=require

# Optional
LOG_LEVEL=INFO
ENV=production
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW_SECONDS=60.0
NOTIFICATION_WEBHOOK_URL=https://hooks.slack.com/...
```

**Supabase note:** Use the "Connection string" from Supabase Dashboard → Project Settings → Database. Choose "URI" and replace `postgresql://` with `postgresql+asyncpg://`, and add `?ssl=require`.

---

## 2. Build and Run with Docker

```bash
# Build
docker build -t webhook-adapter .

# Run (pass DATABASE_URL or use .env)
docker run -p 8000:8000 \
  -e DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/postgres?ssl=require" \
  webhook-adapter
```

The container:

1. Runs `alembic upgrade head` to apply migrations
2. Starts `uvicorn app.main:app --host 0.0.0.0 --port 8000`

---

## 3. Deploy to Common Platforms

### Railway

1. Connect your repo
2. Add Postgres from the Railway dashboard
3. Set `DATABASE_URL` from the Postgres variable (Railway injects it)
4. Add `?ssl=require` to the URL if needed
5. Deploy from the Dockerfile

### Render

1. New → Web Service
2. Connect repo, use Docker
3. Add Postgres from Render dashboard
4. Set `DATABASE_URL` in Environment
5. Deploy

### Fly.io

```bash
fly launch
fly postgres create   # if not using external DB
fly secrets set DATABASE_URL="postgresql+asyncpg://..."
fly deploy
```

### AWS ECS / Fargate

1. Push image to ECR
2. Create ECS task definition with `DATABASE_URL` from Secrets Manager or Parameter Store
3. Ensure security group allows outbound to RDS/Supabase

---

## 4. Verify Deployment

- **Health:** `GET /health` → `{"status": "ok"}`
- **Ready (DB check):** `GET /readyz` → `{"status": "ready"}` (returns 503 if DB unreachable)
- **Webhook:** `POST /webhook` with valid JSON body

---

## 5. Inspect DLQ (Supabase)

Failed/invalid webhooks are in the `dlq` table:

```sql
SELECT id, request_id, reason, payload, created_at FROM dlq ORDER BY created_at DESC LIMIT 20;
```

Use Supabase Studio → Table Editor → `dlq`.

---

## 6. Migrations

- **New schema changes:** Create a migration with `alembic revision --autogenerate -m "description"`, edit if needed, then `alembic upgrade head`
- **Rollback:** `alembic downgrade -1`

---

## Checklist Before Prod

- [ ] `DATABASE_URL` set with `postgresql+asyncpg://` and `?ssl=require` for Supabase
- [ ] `ENV=production`
- [ ] `NOTIFICATION_WEBHOOK_URL` set if you want Slack alerts
- [ ] Rate limits tuned (`RATE_LIMIT_REQUESTS`, `RATE_LIMIT_WINDOW_SECONDS`)
- [ ] Platform health check uses `/readyz`
- [ ] Container has network access to Postgres
