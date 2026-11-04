# ambis.in Backend

Backend API untuk **AMBIS.IN**, platform belajar adaptif untuk siswa SD–SMP. Bukan bot pengerja PR: sistem menilai jawaban siswa, mencari tahu *kenapa* salah, lalu menjelaskan dengan **kanvas visual** (alur, analogi, gambar) alih-alih teks chat.

Teknologi: FastAPI · SQLAlchemy (async) + asyncpg · PostgreSQL (Supabase) + pgvector · Alembic · Jinja2 (prompt) · httpx (klien LLM OpenAI-compatible) · pytest.

## Cara kerja singkat

Dua jalur utama, keduanya mengembalikan **VisualSpec** (JSON terstruktur yang divalidasi backend dan digambar frontend; LLM tidak pernah menggambar atau memilih warna):

1. **Latihan soal** (`POST /api/v1/agent/hermes`): siswa mengirim jawaban untuk satu soal. Pipeline per percobaan:
   `Evaluator` (menilai) → `Diagnostician` (mencocokkan miskonsepsi) → `PolicyEngine` (memilih jenis bantuan: pertanyaan pemandu, petunjuk, penjelasan, contoh langkah) → `InterventionGenerator` (membuat kanvas) → `StateManager` (memperbarui penguasaan konsep, selalu dipanggil terakhir). Jawaban benar hanya menjalankan `Evaluator` dan `StateManager`. Hasil dikirim lewat SSE (event `thinking`, `tool_call`, `tool_result`, `visual`, `done`, `error`) atau satu JSON bila `stream: false`.
2. **Tanya bebas** (`POST /api/v1/ask/visual`): pertanyaan bebas (maks. 500 karakter) menjadi kanvas penjelasan, tanpa menyimpan percobaan.

Aturan yang dijaga di kode: jawaban akhir soal tidak boleh muncul di kanvas, angka di langkah dihitung ulang, dan bila LLM gagal atau keluarannya tidak valid (setelah satu kali coba ulang) kanvas jatuh ke satu catatan teks sehingga penguasaan konsep tetap tercatat. Rincian kontrak tiap tool ada di [`docs/TOOL_SIGNATURES.md`](docs/TOOL_SIGNATURES.md).

## Prasyarat

- Python 3.11 (sama dengan `Dockerfile`; Python 3.12+ belum dicoba)
- Akses ke project Supabase **ambis.in** (database dev bersama, tidak perlu PostgreSQL lokal). Credential (`DATABASE_URL`, dll.) ada di [Notion — Reference](https://app.notion.com/p/Reference-3cfd9c268ab680a194cbf57024c48541?source=copy_link); detail tiap variabel ada di [`docs/SUPABASE_SETUP.md`](docs/SUPABASE_SETUP.md).
- Kunci LLM bersifat opsional untuk pengembangan, lihat [Menjalankan tanpa kunci LLM](#menjalankan-tanpa-kunci-llm).

> **Database dev dipakai bersama seluruh tim.** Tidak ada database per-developer: skrip yang menulis data dan migrasi berdampak ke semua orang. Jangan membuat project Supabase atau Postgres sendiri.

## Instalasi

```bash
git clone <repo-url>
cd dcc-backend-ambis.in
python -m venv .venv
```

Aktifkan virtual environment:

| Shell | Perintah |
|---|---|
| Windows PowerShell | `.venv\Scripts\Activate.ps1` |
| Windows Git Bash | `source .venv/Scripts/activate` |
| Linux / macOS | `source .venv/bin/activate` |

```bash
pip install -r requirements.txt
cp .env.example .env     # lalu isi nilainya (lihat tabel Konfigurasi)
alembic current          # lihat posisi migrasi database dulu
alembic upgrade head     # hanya bila perlu; ini mengubah database BERSAMA
uvicorn app.main:app --reload --port 8001
```

API berjalan di `http://localhost:8001`, dokumentasi interaktif di `/docs`, cek kesehatan di `/api/v1/health` (status `degraded` berarti database tidak terjangkau).

Lewat Docker: `docker build -t ambis-backend .` lalu `docker run --rm -p 8001:8001 --env-file .env ambis-backend`. Kode ikut ter-*bake* ke image saat build (`COPY . .`), jadi **build ulang** setiap kali kode berubah.

## Konfigurasi (`.env`)

Dibaca oleh `app/core/config.py`. Variabel lingkungan (shell) mengalahkan isi `.env`. Jangan pernah meng-commit `.env` atau menempelkan nilainya di chat/issue.

| Variabel | Fungsi |
|---|---|
| `DATABASE_URL` | Koneksi Postgres, format `postgresql+asyncpg://...` |
| `SECRET_KEY`, `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT |
| `LLM_BASE_URL`, `LLM_API_KEY` | Endpoint LLM OpenAI-compatible untuk chat **dan** embeddings (satu base URL). Contoh Gemini: `https://generativelanguage.googleapis.com/v1beta/openai` |
| `LLM_MODEL_GRADING`, `LLM_MODEL_DIAGNOSIS`, `LLM_MODEL_INTERVENTION` | Nama model untuk penilaian, diagnosis miskonsepsi, dan pembuatan kanvas (juga dipakai `ask/visual`) |
| `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS` | Default `gemini-embedding-001` dan `768` (harus cocok dengan kolom `vector(768)`) |
| `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY` | Kunci provider untuk jalur chat lama (`multi_ai.py`) |

Tanpa `LLM_BASE_URL` dan `LLM_API_KEY`, bagian yang butuh LLM (penilaian jawaban isian, diagnosis, kanvas) tidak akan jalan; soal pilihan ganda tetap dinilai tanpa LLM.

## Menjalankan tanpa kunci LLM

`scripts/fake_llm_server.py` adalah server tiruan OpenAI-compatible (hanya library standar) yang membalas dengan kanvas yang valid. Cocok untuk mengembangkan UI atau menguji alur tanpa kunci. Isinya untuk topik Penjumlahan Pecahan.

```bash
python -m scripts.fake_llm_server --port 9099
```

Di terminal lain, arahkan backend ke sana (PowerShell; variabel hanya berlaku di terminal itu):

```powershell
$env:LLM_BASE_URL="http://127.0.0.1:9099"; $env:LLM_API_KEY="apa-saja"
$env:LLM_MODEL_GRADING="fake"; $env:LLM_MODEL_DIAGNOSIS="fake"; $env:LLM_MODEL_INTERVENTION="fake"
uvicorn app.main:app --reload --port 8001
```

Untuk jalur **Tanya bebas** saja, database tidak diperlukan; tambahkan `$env:DATABASE_URL="postgresql+asyncpg://x:y@127.0.0.1:1/none"` bila ingin memastikan database bersama tidak tersentuh. Tab **Latihan soal** butuh database yang sudah berisi skema dan seed.

## Memeriksa kunci LLM asli

```bash
python -m scripts.check_llm
```

Tidak butuh database. Mengecek chat dengan `response_format=json_object`, embeddings (non-kritis), dan membuat satu kanvas per jenis intervensi dengan menghitung berapa panggilan LLM yang dipakai (`llm_calls=2` artinya lolos setelah coba ulang).

## Endpoint

Semua di bawah prefix `/api/v1`.

| Endpoint | Fungsi |
|---|---|
| `GET /health` | Status layanan dan database |
| `POST /agent/hermes` | Latihan soal: SSE (`stream: true`, bawaan) atau JSON |
| `GET /curriculum/practice` | Katalog soal **aman untuk siswa** (tanpa kunci jawaban, langkah solusi, atau id miskonsepsi) |
| `POST /ask/visual` | Tanya bebas menjadi kanvas |
| `GET /curriculum/subjects`, `/subjects/{id}/units`, `/units/{id}/concepts`, `/concepts/{id}`, `/concepts/{id}/exercises` | Navigasi kurikulum |
| `GET /curriculum/exercises/{id}` | **Mengembalikan kunci jawaban**; jangan dipakai di UI siswa |
| `POST/GET /learning-paths/`, `/learning-paths/{id}`, `POST /learning-paths/generate-roadmap`, `/learning-paths/lesson-intro` | Learning path |
| `POST /ask/`, `POST /chat/stream`, `GET/POST /chat/memory`, `GET /models/` | Jalur chat lama berbasis teks (dibekukan, masih dipakai halaman `/` frontend) |

## Struktur

```
app/
  main.py                  FastAPI entry point
  core/
    config.py              Settings dari .env
    database.py            Koneksi DB async
    llm_client.py          Klien LLM OpenAI-compatible (chat JSON + embeddings, retry)
    prompts.py             Pemuat template prompt (prompts/*.j2)
    visual_spec.py         Kontrak VisualSpec + validator (layout, angka, anti-bocor)
  tools/                   Lima tool Hermes + attempt_repository
    evaluator.py  diagnostician.py  policy_engine.py
    intervention_generator.py  state_manager.py
  api/v1/
    routes/                Endpoint HTTP
    schemas/               Model Pydantic request/response
    services/              hermes_agent (orkestrasi), visual_ask, retriever (RAG),
                           curriculum, learning_path, dan jalur chat lama
                           (ask, chat, multi_ai, canvas_builder, student_memory)
  models/                  Model SQLAlchemy
prompts/                   Template Jinja2 (penilaian, diagnosis, kanvas per jenis, tanya bebas)
alembic/versions/          Migrasi (skema, seed Penjumlahan Pecahan, memori siswa, FK)
scripts/                   Alat manual (lihat tabel di bawah)
eval/                      Kasus emas dan runner evaluasi (python -m eval.run_eval)
tests/                     Tes unit (fake untuk DB dan LLM, tidak butuh jaringan)
docs/                      Setup Supabase dan kontrak tool Hermes
```

## Skrip manual

Bukan bagian dari `pytest`. Yang bertanda ⚠ **menulis ke database bersama**.

| Perintah | Fungsi |
|---|---|
| `python -m scripts.fake_llm_server` | LLM tiruan tanpa kunci |
| `python -m scripts.check_llm` | Cek kunci/endpoint LLM, tanpa database |
| `python -m scripts.smoke_hermes_pipeline` ⚠ | Menjalankan pipeline Hermes ke DB asli (1 session, problem, attempt per skenario) |
| `python -m scripts.backfill_embeddings` ⚠ | Mengisi vektor `curriculum_chunks` yang masih kosong |
| `python -m eval.run_eval` | Evaluasi penilaian, diagnosis, dan kebijakan dengan LLM asli (set LLM yang belum dikonfigurasi dilewati) |

## Migrasi database

```bash
alembic current            # SELALU cek dulu posisi sebenarnya
alembic upgrade head
```

Database dipakai bersama, jadi: jangan menjalankan `alembic downgrade` tanpa memeriksa `alembic current` lebih dulu (kegagalan upgrade tidak memajukan revisi, sehingga `downgrade -1` bisa menargetkan migrasi yang salah). Migrasi terbaru `b7d41e9c8a52` menghapus foreign key `student_id` pada lima tabel pipeline karena siswa demo tidak punya baris di `profiles`; cek `alembic current` untuk tahu apakah sudah diterapkan.

## Testing

```bash
pytest
```

Semua tes memakai fake untuk database dan LLM (termasuk server tiruan lewat HTTP lokal), jadi bisa dijalankan tanpa kunci maupun akses Supabase. Setelah mengubah template di `prompts/`, jalankan `tests/test_fake_llm_server.py`: tes itu menjaga agar penanda yang dikenali server tiruan tetap ada di template.

## Dokumentasi

- [`docs/SUPABASE_SETUP.md`](docs/SUPABASE_SETUP.md): cara mengisi `.env` dan kegagalan koneksi yang umum.
- [`docs/TOOL_SIGNATURES.md`](docs/TOOL_SIGNATURES.md): kontrak lima tool Hermes, urutan pemanggilan, dan format event SSE.
- Dokumen arsitektur database, kontrak VisualSpec lengkap, dan diagram saat ini disimpan di luar repo ini (folder kerja pengembang AI/arsitektur). Docstring di beberapa modul merujuk ke dokumen itu.
