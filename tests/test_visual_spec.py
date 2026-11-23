import copy

import pytest

from app.core.visual_spec import (
    VisualSpecError,
    fallback_note_spec,
    parse_visual_spec,
)

ANSWER = "17/20"


def _worked_example() -> dict:
    return {
        "spec_version": "0.1",
        "intervention_kind": "worked_example",
        "title": "Menyamakan penyebut dulu",
        "blocks": [
            {
                "type": "analogy_scene",
                "template": "pizza",
                "story": "Potongan pizza beda ukuran tidak bisa langsung digabung.",
                "items": [{"fraction": "3/5"}, {"fraction": "1/4"}],
            },
            {
                "type": "step_flow",
                "steps": [
                    {"n": 1, "title": "Cari penyebut yang sama", "detail": "KPK 5 dan 4 adalah 20", "math": "5 x 4 = 20"},
                    {"n": 2, "title": "Ubah kedua pecahan", "math": "3/5 = 12/20 ; 1/4 = 5/20"},
                    {"n": 3, "title": "Jumlahkan pembilangnya", "math": "12/20 + 5/20 = ?/20", "locked": True},
                ],
            },
            {
                "type": "number_line",
                "start": "0",
                "end": "1",
                "ticks": 20,
                "points": [{"at": "12/20", "label": "12/20"}],
                "arrows": [{"from": "12/20", "by": "5/20", "label": "+ 5/20", "hidden_end": True}],
            },
            {"type": "answer_input", "mode": "fraction", "prompt": "Sekarang coba isi hasil akhirnya."},
        ],
    }


def _hint() -> dict:
    return {
        "intervention_kind": "hint",
        "title": "Lihat penyebutnya",
        "blocks": [
            {"type": "note", "text": "Penyebut 5 dan 4 beda ukuran potongannya."},
            {"type": "fraction_bar", "rows": [
                {"label": "3/5", "numerator": 3, "denominator": 5},
                {"label": "1/4", "numerator": 1, "denominator": 4},
            ]},
        ],
    }


def test_golden_worked_example_is_valid():
    spec = parse_visual_spec(_worked_example(), correct_answer=ANSWER)
    assert spec.intervention_kind == "worked_example"
    assert len(spec.blocks) == 4


def test_serialization_uses_from_alias_and_drops_none():
    spec = parse_visual_spec(_worked_example(), correct_answer=ANSWER)
    dumped = spec.model_dump(mode="json", by_alias=True, exclude_none=True)
    arrow = dumped["blocks"][2]["arrows"][0]
    assert arrow["from"] == "12/20"
    assert "from_" not in arrow


def test_hidden_end_arrow_extra_to_field_is_dropped_not_forwarded():
    raw = _worked_example()
    raw["blocks"][2]["arrows"][0]["to"] = ANSWER
    spec = parse_visual_spec(raw, correct_answer=ANSWER)
    dumped = spec.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert "to" not in dumped["blocks"][2]["arrows"][0]
    assert ANSWER not in str(dumped)


def test_rejects_more_than_six_steps():
    raw = _worked_example()
    raw["blocks"][1]["steps"] = [
        {"n": i, "title": f"Langkah {i}"} for i in range(1, 8)
    ]
    with pytest.raises(VisualSpecError):
        parse_visual_spec(raw)


def test_rejects_unknown_block_type():
    raw = _hint()
    raw["blocks"].append({"type": "video", "url": "x"})
    with pytest.raises(VisualSpecError):
        parse_visual_spec(raw)


def test_rejects_step_numbers_out_of_order():
    raw = _worked_example()
    raw["blocks"][1]["steps"][0]["n"] = 2
    with pytest.raises(VisualSpecError):
        parse_visual_spec(raw)


def test_rejects_numerically_inconsistent_math():
    raw = _worked_example()
    raw["blocks"][1]["steps"][1]["math"] = "3/5 = 13/20"
    with pytest.raises(VisualSpecError, match="not numerically consistent"):
        parse_visual_spec(raw)


def test_unverifiable_math_with_placeholder_is_skipped():
    raw = _worked_example()
    spec = parse_visual_spec(raw)
    assert spec.blocks[1].steps[2].locked is True


def test_rejects_locked_step_without_placeholder():
    raw = _worked_example()
    raw["blocks"][1]["steps"][2]["math"] = "12/20 + 5/20"
    with pytest.raises(VisualSpecError):
        parse_visual_spec(raw)


@pytest.mark.parametrize("leaked", ["12/20 + 5/20 = 17/20", "= 34/40", "hasilnya 0.85", "hasilnya 0,85"])
def test_rejects_final_answer_in_any_equivalent_form(leaked):
    raw = _worked_example()
    raw["blocks"][0]["story"] = f"Jadi {leaked}"
    with pytest.raises(VisualSpecError, match="final answer"):
        parse_visual_spec(raw, correct_answer=ANSWER)


def test_leak_check_skipped_without_correct_answer():
    raw = _worked_example()
    raw["blocks"][0]["story"] = "Hasilnya 17/20"
    parse_visual_spec(raw)


def test_intermediate_fractions_are_not_flagged():
    parse_visual_spec(_worked_example(), correct_answer=ANSWER)


def test_rejects_unhidden_arrow_ending_on_answer():
    raw = _worked_example()
    raw["blocks"][2]["arrows"][0]["hidden_end"] = False
    with pytest.raises(VisualSpecError, match="arrow"):
        parse_visual_spec(raw, correct_answer=ANSWER)


def test_rejects_number_line_point_on_answer():
    raw = _worked_example()
    raw["blocks"][2]["points"].append({"at": "17/20", "label": "?"})
    with pytest.raises(VisualSpecError, match="final answer"):
        parse_visual_spec(raw, correct_answer=ANSWER)


def test_rejects_fraction_bar_drawing_the_answer():
    raw = _hint()
    raw["blocks"][1]["rows"] = [{"label": "hasil", "numerator": 17, "denominator": 20}]
    with pytest.raises(VisualSpecError, match="fraction_bar"):
        parse_visual_spec(raw, correct_answer=ANSWER)


def test_non_numeric_answer_is_matched_as_text():
    raw = _hint()
    raw["blocks"][0]["text"] = "Jawabannya sama dengan hasil pembagian"
    with pytest.raises(VisualSpecError):
        parse_visual_spec(raw, correct_answer="hasil pembagian")


def test_rejects_improper_fraction_bar_row():
    raw = _hint()
    raw["blocks"][1]["rows"][0]["numerator"] = 6
    with pytest.raises(VisualSpecError):
        parse_visual_spec(raw)


def test_rejects_unalignable_denominator():
    raw = _hint()
    raw["blocks"][1]["align_denominator"] = 12
    with pytest.raises(VisualSpecError):
        parse_visual_spec(raw)


def test_accepts_alignable_denominator():
    raw = _hint()
    raw["blocks"][1]["align_denominator"] = 20
    parse_visual_spec(raw)


def test_rejects_arrow_leaving_number_line():
    raw = _worked_example()
    raw["blocks"][2]["arrows"][0]["by"] = "9/20"
    with pytest.raises(VisualSpecError):
        parse_visual_spec(raw)


def test_rejects_bad_fraction_string():
    raw = _worked_example()
    raw["blocks"][0]["items"][0]["fraction"] = "3/0"
    with pytest.raises(VisualSpecError):
        parse_visual_spec(raw)


def test_rejects_math_with_disallowed_characters():
    raw = _worked_example()
    raw["blocks"][1]["steps"][0]["math"] = "5 x 4 = 20 <script>"
    with pytest.raises(VisualSpecError):
        parse_visual_spec(raw)


def test_hint_may_not_contain_step_flow():
    raw = _hint()
    raw["blocks"].append({"type": "step_flow", "steps": [{"n": 1, "title": "Langkah"}]})
    with pytest.raises(VisualSpecError, match="may not contain"):
        parse_visual_spec(raw)


def test_worked_example_needs_locked_last_step():
    raw = _worked_example()
    raw["blocks"][1]["steps"][2] = {"n": 3, "title": "Jumlahkan", "math": "12/20 + 5/20 = 1"}
    with pytest.raises(VisualSpecError):
        parse_visual_spec(raw)


def test_answer_input_must_be_last_block():
    raw = _worked_example()
    raw["blocks"].insert(0, copy.deepcopy(raw["blocks"][-1]))
    with pytest.raises(VisualSpecError, match="last block"):
        parse_visual_spec(raw)


def test_mcq_answer_input_needs_options():
    raw = _worked_example()
    raw["blocks"][-1] = {"type": "answer_input", "mode": "mcq", "prompt": "Pilih"}
    with pytest.raises(VisualSpecError):
        parse_visual_spec(raw)


def test_fallback_note_spec_is_valid_for_every_kind():
    for kind in ("guiding_question", "hint", "explanation", "worked_example"):
        spec = fallback_note_spec(kind, "Perhatikan penyebutnya ya.")
        assert spec.blocks[0].type == "note"
        assert spec.intervention_kind == kind
