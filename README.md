# ambis.in Backend

Backend API untuk Ambis.in — Learning Path & Ask Mode.

Teknologi: FastAPI + SQLAlchemy + PostgreSQL (async) + Alembic + JWT.

## Prerequisites

- Python 3.11+
- Akses ke Supabase project **ambis.in** (shared dev database — tidak perlu install PostgreSQL
  lokal). Credential (`DATABASE_URL`, dll) disimpan di
  [Notion — Reference](https://app.notion.com/p/Reference-3cfd9c268ab680a194cbf57024c48541?source=copy_link), lalu lihat `docs/SUPABASE_SETUP.md` untuk detail
  tiap variable. PostgreSQL lokal hanya dibutuhkan kalau kamu sengaja mau kerja offline dari
  Supabase (lihat fallback di `.env.example`).

## Instalasi

### 1. Clone repository

```bash
git clone <repo-url>
cd backend
```

### 2. Buat virtual environment

```bash
python -m venv .venv
```

### 3. Aktifkan virtual environment

**Windows (PowerShell):**

```powershell
.venv\Scripts\Activate.ps1
```

**Windows (Git Bash):**

```bash
source .venv/Scripts/activate
```

**Linux/macOS:**

```bash
source .venv/bin/activate
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Konfigurasi environment

Buat file `.env` dari template:

```bash
cp .env.example .env
```

`DATABASE_URL` diisi dengan connection string project Supabase **ambis.in** yang sudah ada — ambil
dari [Notion — Reference](https://app.notion.com/p/Reference-3cfd9c268ab680a194cbf57024c48541?source=copy_link)
(jangan buat project Supabase/Postgres baru sendiri). Detail tiap variable, cara ambil dari
dashboard, dan gotcha koneksi ada di [`docs/SUPABASE_SETUP.md`](docs/SUPABASE_SETUP.md).

### 6. Jalankan migrasi (alembic)

```bash
alembic upgrade head
```

### 7. Jalankan server

```bash
uvicorn app.main:app --reload --port 8001
```

API akan berjalan di `http://localhost:8001` dengan docs otomatis di `/docs`.

## Struktur

```
app/
  main.py            — FastAPI app entry point
  core/
    config.py        — Settings dari .env
    database.py      — DB connection
  api/v1/
    routes/          — API endpoints
    schemas/         — Pydantic models
    services/        — Business logic
  models/            — SQLAlchemy models
```

## Testing

```bash
pytest
```

"# backend-ambis.in"
