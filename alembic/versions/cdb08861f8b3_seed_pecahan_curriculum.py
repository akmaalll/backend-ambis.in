"""seed pecahan curriculum

Revision ID: cdb08861f8b3
Revises: 554a024e01a9
Create Date: 2026-09-14

Near-verbatim transcription of AMBIS_DB_Schema_Seed_Example.sql PART 2
(D:\\ooka\\dev\\hack\\AMBIS_DB_Schema_Seed_Example.sql, lines 313-449) — the one
seeded topic (Penjumlahan Pecahan Berpenyebut Beda, SMP Kelas VII) used
throughout AMBIS_DB_Architecture.md and EduSolve_AI_Memory.md. Fixed UUIDs,
ON CONFLICT DO NOTHING — safe to re-run. curriculum_chunks.embedding is left
NULL on purpose (backfilled later by the embedding job, not faked here).

IDs `00000000-0000-0000-0000-00000000XXXX` are a reserved range for seed/demo
data — chosen deliberately (not random) so docs and traces (e.g. the Golden
Scenario in AMBIS_DB_Schema_Seed_Example.sql PART 3) can reference stable
literal IDs. Never reuse this range for real, user-generated rows; a real
gen_random_uuid() has ~0 probability of colliding with it anyway.

Uses op.get_bind().exec_driver_sql(...) instead of op.execute(sa.text(...)):
several INSERTs below carry literal JSON containing `"...":null`, and
sa.text() scans raw SQL for `:identifier` bind-parameter placeholders — it
misreads that literal `:null` as a bind param named `null` and raises
`InvalidRequestError: A value is required for bind parameter 'null'`.
exec_driver_sql sends the string straight to the DBAPI driver with no such
parsing, which is what plain literal SQL like this needs.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cdb08861f8b3"
down_revision: Union[str, None] = "554a024e01a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # ---------- 2.1 Subject + Unit ----------
    bind.exec_driver_sql(
        """
        insert into subjects (id, code, name) values
          ('00000000-0000-0000-0000-000000000001', 'MTK', 'Matematika')
        on conflict (id) do nothing
        """
    )
    bind.exec_driver_sql(
        """
        insert into units (id, subject_id, name, position) values
          ('00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000001', 'Bilangan — Pecahan', 1)
        on conflict (id) do nothing
        """
    )

    # ---------- 2.2 Concepts (2 prerequisites + 1 target concept) ----------
    bind.exec_driver_sql(
        """
        insert into concepts (id, unit_id, code, name, description, position) values
          ('00000000-0000-0000-0000-000000000201', '00000000-0000-0000-0000-000000000101',
           'MTK.PECAHAN.SENILAI', 'Pecahan Senilai',
           'Memahami bahwa dua pecahan bisa mewakili nilai yang sama walau bentuknya beda (mis. 1/2 = 2/4).', 1),

          ('00000000-0000-0000-0000-000000000202', '00000000-0000-0000-0000-000000000101',
           'MTK.PECAHAN.KPK', 'KPK Penyebut',
           'Menentukan Kelipatan Persekutuan Terkecil dari dua penyebut sebagai langkah menyamakan penyebut.', 2),

          ('00000000-0000-0000-0000-000000000203', '00000000-0000-0000-0000-000000000101',
           'MTK.PECAHAN.PENJUMLAHAN_BEDA', 'Penjumlahan Pecahan Berpenyebut Beda',
           'Menjumlahkan dua pecahan yang penyebutnya berbeda dengan menyamakan penyebut terlebih dahulu.', 3)
        on conflict (id) do nothing
        """
    )
    bind.exec_driver_sql(
        """
        insert into concept_prerequisites (concept_id, prerequisite_id) values
          ('00000000-0000-0000-0000-000000000203', '00000000-0000-0000-0000-000000000201'),
          ('00000000-0000-0000-0000-000000000203', '00000000-0000-0000-0000-000000000202')
        on conflict do nothing
        """
    )

    # ---------- 2.3 Misconceptions (all attached to the target concept) ----------
    bind.exec_driver_sql(
        """
        insert into misconceptions (id, concept_id, code, description, remediation_hint) values
          ('00000000-0000-0000-0000-000000000301', '00000000-0000-0000-0000-000000000203',
           'ADDS_NUM_DENOM_DIRECTLY',
           'Menjumlahkan pembilang dan penyebut secara langsung tanpa menyamakan penyebut (mis. 1/2 + 1/3 dijawab 2/5).',
           'Tunjukkan mengapa penyebut harus disamakan dulu — gunakan representasi visual (potongan kue/garis bilangan).'),

          ('00000000-0000-0000-0000-000000000302', '00000000-0000-0000-0000-000000000203',
           'WRONG_LCM',
           'Salah menentukan KPK dari kedua penyebut, sehingga penyamaan penyebut jadi keliru.',
           'Ulangi konsep KPK dengan contoh yang lebih sederhana sebelum kembali ke soal penjumlahan.'),

          ('00000000-0000-0000-0000-000000000303', '00000000-0000-0000-0000-000000000203',
           'FORGETS_SIMPLIFY',
           'Hasil akhir benar secara nilai tetapi lupa disederhanakan ke bentuk paling sederhana.',
           'Ingatkan langkah terakhir: selalu cek apakah pembilang & penyebut masih punya faktor sekutu.')
        on conflict (id) do nothing
        """
    )

    # ---------- 2.4 Exercises ----------
    bind.exec_driver_sql(
        """
        insert into exercises (id, concept_id, difficulty, kind, is_diagnostic, question, options, correct_answer, solution_steps, metadata) values

          ('00000000-0000-0000-0000-000000000401', '00000000-0000-0000-0000-000000000203', 2, 'mcq', true,
           'Berapakah hasil dari 1/2 + 1/3 ?',
           '[
             {"key":"A","label":"2/5","misconception_id":"00000000-0000-0000-0000-000000000301"},
             {"key":"B","label":"5/6","misconception_id":null},
             {"key":"C","label":"1/6","misconception_id":"00000000-0000-0000-0000-000000000302"},
             {"key":"D","label":"3/5","misconception_id":"00000000-0000-0000-0000-000000000301"}
           ]'::jsonb,
           'B',
           '["Cari KPK dari 2 dan 3 = 6","Ubah 1/2 menjadi 3/6 dan 1/3 menjadi 2/6","Jumlahkan pembilang: 3/6 + 2/6 = 5/6","5/6 sudah dalam bentuk paling sederhana"]'::jsonb,
           '{"topic_example": true}'::jsonb),

          ('00000000-0000-0000-0000-000000000402', '00000000-0000-0000-0000-000000000203', 3, 'mcq', true,
           'Berapakah hasil dari 2/3 + 1/4 ?',
           '[
             {"key":"A","label":"3/7","misconception_id":"00000000-0000-0000-0000-000000000301"},
             {"key":"B","label":"11/12","misconception_id":null},
             {"key":"C","label":"3/12","misconception_id":"00000000-0000-0000-0000-000000000302"},
             {"key":"D","label":"6/8","misconception_id":"00000000-0000-0000-0000-000000000303"}
           ]'::jsonb,
           'B',
           '["Cari KPK dari 3 dan 4 = 12","Ubah 2/3 menjadi 8/12 dan 1/4 menjadi 3/12","Jumlahkan: 8/12 + 3/12 = 11/12","11/12 sudah paling sederhana"]'::jsonb,
           '{"topic_example": true}'::jsonb),

          ('00000000-0000-0000-0000-000000000403', '00000000-0000-0000-0000-000000000203', 2, 'mcq', false,
           'Berapakah hasil dari 1/4 + 1/6 ?',
           '[
             {"key":"A","label":"2/10","misconception_id":"00000000-0000-0000-0000-000000000301"},
             {"key":"B","label":"5/12","misconception_id":null},
             {"key":"C","label":"2/12","misconception_id":"00000000-0000-0000-0000-000000000302"},
             {"key":"D","label":"10/24","misconception_id":"00000000-0000-0000-0000-000000000303"}
           ]'::jsonb,
           'B',
           '["KPK dari 4 dan 6 = 12","1/4 = 3/12, 1/6 = 2/12","3/12 + 2/12 = 5/12"]'::jsonb,
           '{}'::jsonb),

          ('00000000-0000-0000-0000-000000000404', '00000000-0000-0000-0000-000000000203', 3, 'short_answer', false,
           'Ibu punya 3/5 kg gula dan menambah 1/4 kg lagi. Berapa total gula Ibu sekarang? (tulis dalam bentuk pecahan paling sederhana)',
           null,
           '17/20',
           '["KPK dari 5 dan 4 = 20","3/5 = 12/20, 1/4 = 5/20","12/20 + 5/20 = 17/20","17/20 sudah paling sederhana"]'::jsonb,
           '{"context": "word_problem", "used_for": "reassessment_after_intervention"}'::jsonb),

          ('00000000-0000-0000-0000-000000000405', '00000000-0000-0000-0000-000000000202', 1, 'mcq', true,
           'Berapakah KPK dari 4 dan 6 ?',
           '[
             {"key":"A","label":"10","misconception_id":null},
             {"key":"B","label":"12","misconception_id":null},
             {"key":"C","label":"24","misconception_id":null},
             {"key":"D","label":"2","misconception_id":null}
           ]'::jsonb,
           'B',
           '["Kelipatan 4: 4,8,12,16...","Kelipatan 6: 6,12,18...","Kelipatan sekutu terkecil = 12"]'::jsonb,
           '{}'::jsonb)

        on conflict (id) do nothing
        """
    )

    # ---------- 2.5 Curriculum chunk (RAG source for explanations) ----------
    # embedding left NULL on purpose — generated by the embedding backfill job
    # (Gemini text-embedding, 768-dim), not something to fake in a seed script.
    bind.exec_driver_sql(
        """
        insert into curriculum_chunks (id, concept_id, content, embedding, metadata) values
          ('00000000-0000-0000-0000-000000000501', '00000000-0000-0000-0000-000000000203',
           'Untuk menjumlahkan dua pecahan dengan penyebut berbeda, langkah pertama adalah menyamakan '
           || 'penyebutnya menggunakan KPK. Setelah penyebut sama, jumlahkan pembilangnya dan sederhanakan '
           || 'hasilnya jika memungkinkan. Analogi: bayangkan potongan kue berukuran berbeda — kita tidak bisa '
           || 'langsung menjumlahkan jumlah potongannya sebelum memotongnya dengan ukuran yang sama.',
           null,
           '{"representation": "text", "source": "internal_draft", "needs_embedding": true}'::jsonb)
        on conflict (id) do nothing
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Reverse dependency order — children before parents.
    bind.exec_driver_sql("delete from curriculum_chunks where id = '00000000-0000-0000-0000-000000000501'")
    bind.exec_driver_sql(
        """
        delete from exercises where id in (
          '00000000-0000-0000-0000-000000000401',
          '00000000-0000-0000-0000-000000000402',
          '00000000-0000-0000-0000-000000000403',
          '00000000-0000-0000-0000-000000000404',
          '00000000-0000-0000-0000-000000000405'
        )
        """
    )
    bind.exec_driver_sql(
        """
        delete from misconceptions where id in (
          '00000000-0000-0000-0000-000000000301',
          '00000000-0000-0000-0000-000000000302',
          '00000000-0000-0000-0000-000000000303'
        )
        """
    )
    bind.exec_driver_sql(
        """
        delete from concept_prerequisites where concept_id = '00000000-0000-0000-0000-000000000203'
          and prerequisite_id in (
            '00000000-0000-0000-0000-000000000201',
            '00000000-0000-0000-0000-000000000202'
          )
        """
    )
    bind.exec_driver_sql(
        """
        delete from concepts where id in (
          '00000000-0000-0000-0000-000000000201',
          '00000000-0000-0000-0000-000000000202',
          '00000000-0000-0000-0000-000000000203'
        )
        """
    )
    bind.exec_driver_sql("delete from units where id = '00000000-0000-0000-0000-000000000101'")
    bind.exec_driver_sql("delete from subjects where id = '00000000-0000-0000-0000-000000000001'")
