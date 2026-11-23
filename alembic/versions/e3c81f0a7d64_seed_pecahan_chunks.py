"""seed pecahan curriculum chunks

Revision ID: e3c81f0a7d64
Revises: a5eb4455c932
Create Date: 2026-09-29

Expands curriculum_chunks from the single row seeded by cdb08861f8b3 to eleven,
covering all three seeded concepts instead of only the target one.

Why this matters beyond row count: CurriculumRetriever.search() asks for the
top_k nearest chunks and then drops anything below a similarity threshold
(0.70 as called from AskService). With one chunk in the corpus, "nearest" was
meaningless — a question about KPK or about simplifying a result had nothing to
match except a paragraph on adding unlike denominators. Retrieval only starts
behaving like retrieval once the corpus distinguishes between the concepts a
student can actually ask about.

Chunk design, one idea per row at roughly 50-150 words:
  - 0502-0503  MTK.PECAHAN.SENILAI      (prerequisite)
  - 0504-0505  MTK.PECAHAN.KPK          (prerequisite)
  - 0506-0508  remediation, one per seeded misconception (301/302/303)
  - 0509-0510  worked examples, mirroring exercises 401 and 404
  - 0511       simplifying via FPB — the step FORGETS_SIMPLIFY keeps missing

The remediation chunks deliberately restate each misconception's
`remediation_hint` as student-facing prose. The hint column is written for the
intervention generator, not for RAG; retrieval needs text that reads like an
explanation, because it is injected into the prompt as reference material.

embedding is left NULL here, exactly as in cdb08861f8b3 — the vectors come from
scripts/backfill_embeddings.py, which selects on `embedding IS NULL`. Faking a
vector in a seed would poison the HNSW index with meaningless neighbours.

Uses op.get_bind().exec_driver_sql(...) rather than op.execute(sa.text(...)),
matching cdb08861f8b3: the content strings contain Indonesian prose with colons
and the metadata literals contain `::jsonb` casts, and driver-level SQL skips
sa.text()'s bind-parameter parsing entirely rather than relying on every colon
in every sentence being unambiguous.

IDs continue the reserved 00000000-0000-0000-0000-00000000XXXX seed/demo range
established by cdb08861f8b3.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3c81f0a7d64"
down_revision: Union[str, None] = "a5eb4455c932"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONCEPT_SENILAI = "00000000-0000-0000-0000-000000000201"
CONCEPT_KPK = "00000000-0000-0000-0000-000000000202"
CONCEPT_PENJUMLAHAN = "00000000-0000-0000-0000-000000000203"

CHUNK_IDS = [f"00000000-0000-0000-0000-0000000005{n:02d}" for n in range(2, 12)]


def upgrade() -> None:
    bind = op.get_bind()

    bind.exec_driver_sql(
        f"""
        insert into curriculum_chunks (id, concept_id, content, embedding, metadata) values

          ('00000000-0000-0000-0000-000000000502', '{CONCEPT_SENILAI}',
           'Dua pecahan disebut senilai jika keduanya mewakili besar bagian yang sama, '
           || 'walaupun angka pembilang dan penyebutnya berbeda. Contohnya 1/2, 2/4, dan 3/6 '
           || 'adalah pecahan senilai karena ketiganya menunjukkan setengah bagian. Cara '
           || 'mengujinya: kalikan pembilang pecahan pertama dengan penyebut pecahan kedua, '
           || 'lalu bandingkan dengan hasil kali sebaliknya. Jika kedua hasilnya sama, kedua '
           || 'pecahan itu senilai. Memahami pecahan senilai adalah dasar untuk menyamakan '
           || 'penyebut, karena mengubah 1/2 menjadi 3/6 tidak mengubah nilainya sama sekali.',
           null,
           '{{"representation": "text", "source": "internal_draft", "needs_embedding": true, "role": "concept_explanation"}}'::jsonb),

          ('00000000-0000-0000-0000-000000000503', '{CONCEPT_SENILAI}',
           'Untuk membuat pecahan senilai, kalikan atau bagi pembilang dan penyebut dengan '
           || 'bilangan yang sama, bukan dengan bilangan yang berbeda. Misalnya 2/3 dikalikan '
           || '4 pada pembilang dan penyebutnya menjadi 8/12, yang nilainya tetap sama. Aturan '
           || 'ini berlaku karena mengalikan pembilang dan penyebut dengan bilangan yang sama '
           || 'sama artinya dengan mengalikan pecahan itu dengan 1. Analogi: memotong sepotong '
           || 'kue menjadi dua bagian lebih kecil tidak membuat kuenya bertambah — hanya '
           || 'jumlah potongannya yang berubah, ukuran tiap potong jadi separuh.',
           null,
           '{{"representation": "text", "source": "internal_draft", "needs_embedding": true, "role": "procedure"}}'::jsonb),

          ('00000000-0000-0000-0000-000000000504', '{CONCEPT_KPK}',
           'KPK (Kelipatan Persekutuan Terkecil) dari dua bilangan adalah bilangan terkecil '
           || 'yang bisa dibagi habis oleh kedua bilangan tersebut. Cara paling sederhana: '
           || 'tulis kelipatan masing-masing bilangan, lalu cari angka terkecil yang muncul di '
           || 'kedua daftar. Contoh untuk 4 dan 6 — kelipatan 4 adalah 4, 8, 12, 16, 20, 24; '
           || 'kelipatan 6 adalah 6, 12, 18, 24. Angka yang sama-sama muncul adalah 12 dan 24, '
           || 'dan yang terkecil adalah 12. Jadi KPK dari 4 dan 6 adalah 12. Dalam penjumlahan '
           || 'pecahan, KPK penyebut inilah yang dipakai sebagai penyebut baru.',
           null,
           '{{"representation": "text", "source": "internal_draft", "needs_embedding": true, "role": "concept_explanation"}}'::jsonb),

          ('00000000-0000-0000-0000-000000000505', '{CONCEPT_KPK}',
           'Untuk bilangan yang agak besar, mendaftar kelipatan satu per satu jadi lama. '
           || 'Gunakan faktorisasi prima: pecah tiap bilangan menjadi perkalian bilangan prima, '
           || 'lalu ambil setiap faktor prima dengan pangkat tertinggi yang muncul. Contoh untuk '
           || '12 dan 18 — 12 = 2 pangkat 2 dikali 3, dan 18 = 2 dikali 3 pangkat 2. Ambil '
           || '2 pangkat 2 dan 3 pangkat 2, hasilnya 4 dikali 9 sama dengan 36. Jadi KPK dari '
           || '12 dan 18 adalah 36. Catatan penting: KPK bukan hasil kali kedua bilangan. '
           || '12 dikali 18 adalah 216, jauh lebih besar dari KPK-nya.',
           null,
           '{{"representation": "text", "source": "internal_draft", "needs_embedding": true, "role": "procedure"}}'::jsonb),

          ('00000000-0000-0000-0000-000000000506', '{CONCEPT_PENJUMLAHAN}',
           'Kesalahan paling sering pada penjumlahan pecahan adalah menjumlahkan pembilang '
           || 'dengan pembilang dan penyebut dengan penyebut, misalnya 1/2 + 1/3 dijawab 2/5. '
           || 'Cara ini salah karena penyebut menyatakan ukuran potongan, bukan jumlah yang '
           || 'ikut dijumlahkan. Coba periksa dengan logika: 1/2 saja sudah setengah, dan '
           || 'menambah 1/3 pasti membuat hasilnya lebih dari setengah. Tetapi 2/5 justru lebih '
           || 'kecil dari setengah, jadi jawaban itu mustahil. Bayangkan dua potong kue dengan '
           || 'ukuran berbeda: potongannya harus dipotong ulang agar sama besar dulu, baru '
           || 'boleh dihitung berapa total potongnya.',
           null,
           '{{"representation": "text", "source": "internal_draft", "needs_embedding": true, "role": "remediation", "misconception_code": "ADDS_NUM_DENOM_DIRECTLY"}}'::jsonb),

          ('00000000-0000-0000-0000-000000000507', '{CONCEPT_PENJUMLAHAN}',
           'Jika hasil penjumlahan pecahan terasa aneh padahal caranya sudah benar, biasanya '
           || 'KPK penyebutnya salah. Dua tanda yang mudah dicek: penyebut baru harus bisa '
           || 'dibagi habis oleh kedua penyebut asli, dan penyebut baru tidak boleh lebih kecil '
           || 'dari penyebut terbesar. Untuk 1/4 + 1/6, penyebut baru 12 benar karena 12 habis '
           || 'dibagi 4 dan habis dibagi 6. Kalau seseorang memakai 10, itu salah karena 10 '
           || 'tidak habis dibagi 4. Saat masih bingung, kembali dulu ke latihan KPK dengan '
           || 'angka kecil sebelum melanjutkan ke penjumlahan pecahan.',
           null,
           '{{"representation": "text", "source": "internal_draft", "needs_embedding": true, "role": "remediation", "misconception_code": "WRONG_LCM"}}'::jsonb),

          ('00000000-0000-0000-0000-000000000508', '{CONCEPT_PENJUMLAHAN}',
           'Jawaban penjumlahan pecahan bisa benar nilainya tetapi belum selesai, karena '
           || 'belum disederhanakan. Misalnya 1/4 + 1/4 menghasilkan 2/4, dan nilainya memang '
           || 'benar, tetapi bentuk paling sederhananya adalah 1/2. Jadikan langkah terakhir '
           || 'sebagai kebiasaan: setelah pembilang dijumlahkan, periksa apakah pembilang dan '
           || 'penyebut masih punya faktor yang sama selain 1. Jika ada, bagi keduanya dengan '
           || 'faktor itu. Kalau faktor sekutunya hanya 1, pecahan itu sudah paling sederhana '
           || 'dan pekerjaan selesai.',
           null,
           '{{"representation": "text", "source": "internal_draft", "needs_embedding": true, "role": "remediation", "misconception_code": "FORGETS_SIMPLIFY"}}'::jsonb),

          ('00000000-0000-0000-0000-000000000509', '{CONCEPT_PENJUMLAHAN}',
           'Contoh lengkap menghitung 1/2 + 1/3. Langkah pertama, cari KPK dari penyebut 2 '
           || 'dan 3, hasilnya 6. Langkah kedua, ubah kedua pecahan menjadi berpenyebut 6 — '
           || '1/2 menjadi 3/6 karena pembilang dan penyebut dikali 3, dan 1/3 menjadi 2/6 '
           || 'karena dikali 2. Langkah ketiga, jumlahkan pembilangnya saja sementara penyebut '
           || 'tetap: 3/6 + 2/6 sama dengan 5/6. Langkah keempat, periksa penyederhanaan — 5 '
           || 'dan 6 tidak punya faktor sekutu selain 1, jadi 5/6 sudah bentuk paling '
           || 'sederhana. Jawaban akhirnya 5/6.',
           null,
           '{{"representation": "text", "source": "internal_draft", "needs_embedding": true, "role": "worked_example", "exercise_id": "00000000-0000-0000-0000-000000000401"}}'::jsonb),

          ('00000000-0000-0000-0000-000000000510', '{CONCEPT_PENJUMLAHAN}',
           'Contoh soal cerita. Ibu punya 3/5 kg gula lalu menambah 1/4 kg lagi, berapa total '
           || 'gula Ibu? Yang ditanyakan adalah jumlah, jadi kedua pecahan dijumlahkan. KPK '
           || 'dari 5 dan 4 adalah 20. Ubah 3/5 menjadi 12/20 dengan mengali 4, dan 1/4 menjadi '
           || '5/20 dengan mengali 5. Jumlahkan pembilangnya: 12/20 + 5/20 sama dengan 17/20. '
           || 'Periksa penyederhanaan — 17 adalah bilangan prima dan bukan faktor dari 20, jadi '
           || '17/20 sudah paling sederhana. Total gula Ibu adalah 17/20 kg, yaitu sedikit '
           || 'kurang dari 1 kg, dan itu masuk akal karena 3/5 ditambah 1/4 memang belum '
           || 'mencapai satu.',
           null,
           '{{"representation": "text", "source": "internal_draft", "needs_embedding": true, "role": "worked_example", "exercise_id": "00000000-0000-0000-0000-000000000404"}}'::jsonb),

          ('00000000-0000-0000-0000-000000000511', '{CONCEPT_PENJUMLAHAN}',
           'Menyederhanakan pecahan berarti membagi pembilang dan penyebut dengan FPB (Faktor '
           || 'Persekutuan Terbesar) keduanya. Contoh untuk 8/12 — faktor 8 adalah 1, 2, 4, 8; '
           || 'faktor 12 adalah 1, 2, 3, 4, 6, 12. Faktor sekutu terbesarnya adalah 4, jadi '
           || '8/12 dibagi 4 menjadi 2/3. Perhatikan bedanya dengan menyamakan penyebut: saat '
           || 'menyamakan penyebut kita memakai KPK dan mengalikan, sedangkan saat '
           || 'menyederhanakan kita memakai FPB dan membagi. Dua langkah ini muncul di ujung '
           || 'yang berbeda dari pengerjaan soal, dan sering tertukar.',
           null,
           '{{"representation": "text", "source": "internal_draft", "needs_embedding": true, "role": "concept_explanation"}}'::jsonb)

        on conflict (id) do nothing
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    ids = ", ".join(f"'{cid}'" for cid in CHUNK_IDS)
    bind.exec_driver_sql(f"delete from curriculum_chunks where id in ({ids})")
