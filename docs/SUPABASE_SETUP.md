# Supabase Setup & Credentials

How to get every value in `.env` (see `.env.example` for the full template) from the Supabase
dashboard, what each one is for, and gotchas that will otherwise cost you an afternoon.

This document never contains real secret values — only where to find them and what they mean.
Real values live only in your local `.env`, which is gitignored and must never be committed.

## 0. This is a shared team dev database — don't create your own

The whole team connects to the **same** Supabase project (`ambis.in`), not a per-developer
Postgres instance. There's nothing to "set up" locally beyond getting the connection string —
Supabase is already the shared instance. The real `DATABASE_URL` (and `SUPABASE_URL`/keys once
those are needed) live in
[Notion — Reference](https://app.notion.com/p/Reference-3cfd9c268ab680a194cbf57024c48541?source=copy_link) —
Never paste the real values into git, a repo file, or a
public/team-wide chat channel.

Trade-off worth knowing: since everyone hits the same DB, there's no per-developer data isolation —
two people testing at the same time can see or overwrite each other's rows. Acceptable for a
hackathon timeline; just don't be surprised by it.

## 1. `DATABASE_URL`

**Where:** Supabase Dashboard → your project → **Project Settings → Database → Connection string**
→ tab **URI**.

**What it's for:** the async SQLAlchemy connection string the backend uses for every DB query
(via Alembic migrations and the app's own session factory).

**Two things you must change from what the dashboard gives you:**

1. **Scheme.** The dashboard gives you `postgresql://...`. Rewrite it to
   `postgresql+asyncpg://...` — the app uses the async `asyncpg` driver, and SQLAlchemy needs the
   `+asyncpg` suffix to pick it.
2. **Port / pooler mode.** Use the **Session pooler** connection (port `5432`), not the
   **Transaction pooler** (port `6543`). `asyncpg` issues prepared statements automatically, and
   those are not compatible with Supavisor's transaction-pooling mode unless you explicitly set
   `statement_cache_size=0` in the connect args — the Session pooler avoids the problem entirely,
   so it's the default here.

Result should look like:

```
DATABASE_URL=postgresql+asyncpg://postgres.xxxxxxxxxxxx:[YOUR-PASSWORD]@aws-0-xx-xxxx-1.pooler.supabase.com:5432/postgres
```

**Local fallback:** if you're working offline from Supabase, a local Docker Postgres works too —
see the commented-out fallback line in `.env.example`.

## 2. `SECRET_KEY`, `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`

**Where:** not from Supabase — generate these yourself.

**What they're for:** this backend's own local JWT issuing/verification (login tokens it hands
out), completely separate from Supabase Auth. `ALGORITHM` should stay `HS256` unless you have a
reason to change it; `ACCESS_TOKEN_EXPIRE_MINUTES` controls how long an issued token is valid.

Generate a random `SECRET_KEY`, e.g.:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## 3. `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`

**Where:** Supabase Dashboard → your project → **Project Settings → API**.

- `SUPABASE_URL` — the "Project URL" field.
- `SUPABASE_ANON_KEY` — the "anon / public" key under Project API keys.
- `SUPABASE_SERVICE_ROLE_KEY` — the "service_role" key under the same section. **Never expose this
  one to a client/frontend** — it bypasses Row Level Security entirely.

**Current status:** not consumed by any code path yet. They're only needed once we integrate
Supabase Storage (e.g. PR/homework photo uploads) or verify Supabase Auth JWTs directly — see
`AMBIS_DB_Architecture.md` §2. It's fine to leave these blank for now; fill them in ahead of time
if you'd rather not set up twice.

## 4. Getting a fresh local `.env`

1. `cp .env.example .env` (or copy manually on Windows).
2. Fill in each variable per the sections above.
3. Never commit `.env` — it's already covered by `.gitignore` (`.env`, `.env.local`,
   `.env.*.local`, with `.env.example` explicitly un-ignored so the template itself stays tracked).
4. Run migrations once `DATABASE_URL` is set: `alembic upgrade head` (or via Docker — see
   `README.md`).

## 5. Common failure modes

| Symptom                                                                  | Likely cause                                                                                                                    |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| `asyncpg.exceptions.InvalidAuthorizationSpecificationError`              | Wrong password, or connection string copied from the wrong project                                                              |
| Prepared-statement / `DuplicatePreparedStatementError` errors under load | You're on the Transaction pooler (port `6543`) without `statement_cache_size=0` — switch to the Session pooler (`5432`) instead |
| `sqlalchemy.exc.ArgumentError` about the dialect                         | Forgot to rewrite `postgresql://` to `postgresql+asyncpg://`                                                                    |
| Tables missing after a fresh setup                                       | Migrations not run yet — `alembic upgrade head`                                                                                 |
