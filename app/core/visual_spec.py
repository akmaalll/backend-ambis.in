"""VisualSpec — the structured canvas payload that replaces free-text interventions.

See AMBIS_Visual_Spec_Draft.md. The LLM only fills fields; the block layout per
intervention kind, numeric consistency and the "never reveal the final answer" rule
are enforced here, in code, before anything reaches the frontend.

Entry points:
- parse_visual_spec(raw, correct_answer=...) -> VisualSpec (raises VisualSpecError)
- fallback_note_spec(kind, text) -> VisualSpec (single note block, always valid)

Serialize with `spec.to_payload()` so `NumberLineArrow.from_` goes out as "from".
"""
import re
from fractions import Fraction
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

SPEC_VERSION = "0.1"

InterventionKind = Literal["guiding_question", "hint", "explanation", "worked_example"]


class VisualSpecError(ValueError):
    pass


_FRACTION_RE = re.compile(r"^\d+(?:/\d+)?$")
_MATH_ALLOWED_RE = re.compile(r"^[0-9\s/+\-=x×÷*?().,;]*$")


def _fraction_str(value: str) -> str:
    if not _FRACTION_RE.match(value):
        raise ValueError(f"{value!r} is not a whole number or an 'a/b' fraction")
    if "/" in value and int(value.split("/")[1]) == 0:
        raise ValueError(f"{value!r} has a zero denominator")
    return value


FractionStr = Annotated[str, AfterValidator(_fraction_str)]


def to_fraction(value: str) -> Fraction:
    numerator, _, denominator = value.partition("/")
    return Fraction(int(numerator), int(denominator) if denominator else 1)


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class _Block(_Base):
    caption: str | None = Field(default=None, max_length=140)


class NoteBlock(_Block):
    type: Literal["note"] = "note"
    tone: Literal["info", "warn", "success"] = "info"
    text: str = Field(min_length=1, max_length=300)


class FractionBarRow(_Base):
    label: str = Field(max_length=12)
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=1, le=24)

    @model_validator(mode="after")
    def _proper_fraction(self):
        if self.numerator > self.denominator:
            raise ValueError("fraction_bar rows must be proper fractions")
        return self


class FractionBarBlock(_Block):
    type: Literal["fraction_bar"] = "fraction_bar"
    rows: list[FractionBarRow] = Field(min_length=1, max_length=3)
    align_denominator: int | None = Field(default=None, ge=1, le=48)

    @model_validator(mode="after")
    def _alignable(self):
        if self.align_denominator is not None:
            for row in self.rows:
                if (Fraction(row.numerator, row.denominator) * self.align_denominator).denominator != 1:
                    raise ValueError(
                        f"{row.numerator}/{row.denominator} cannot be redrawn with "
                        f"denominator {self.align_denominator}"
                    )
        return self


class NumberLinePoint(_Base):
    at: FractionStr
    label: str = Field(max_length=12)


class NumberLineArrow(_Base):
    from_: FractionStr = Field(alias="from")
    by: FractionStr
    label: str = Field(max_length=20)
    hidden_end: bool = False


class NumberLineBlock(_Block):
    type: Literal["number_line"] = "number_line"
    start: FractionStr = "0"
    end: FractionStr = "1"
    ticks: int = Field(default=10, ge=1, le=40)
    points: list[NumberLinePoint] = Field(default_factory=list, max_length=6)
    arrows: list[NumberLineArrow] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def _in_range(self):
        lo, hi = to_fraction(self.start), to_fraction(self.end)
        if lo >= hi:
            raise ValueError("number_line start must be less than end")
        for point in self.points:
            if not lo <= to_fraction(point.at) <= hi:
                raise ValueError(f"point {point.at} is outside the number line")
        for arrow in self.arrows:
            origin = to_fraction(arrow.from_)
            if not lo <= origin <= hi or origin + to_fraction(arrow.by) > hi:
                raise ValueError(f"arrow from {arrow.from_} by {arrow.by} leaves the number line")
        return self


class AnalogyItem(_Base):
    fraction: FractionStr


class AnalogySceneBlock(_Block):
    type: Literal["analogy_scene"] = "analogy_scene"
    template: Literal["pizza", "coklat", "botol_air", "pita"]
    story: str = Field(min_length=1, max_length=200)
    items: list[AnalogyItem] = Field(min_length=1, max_length=3)


class Step(_Base):
    n: int = Field(ge=1, le=6)
    title: str = Field(min_length=1, max_length=60)
    detail: str | None = Field(default=None, max_length=140)
    math: str | None = Field(default=None, max_length=80)
    locked: bool = False

    @model_validator(mode="after")
    def _math_charset_and_lock(self):
        if self.math is not None and not _MATH_ALLOWED_RE.match(self.math):
            raise ValueError(f"step {self.n}: math contains characters outside the allowed set")
        if self.locked and (self.math is None or "?" not in self.math):
            raise ValueError(f"step {self.n}: a locked step needs math with a '?' placeholder")
        return self


class StepFlowBlock(_Block):
    type: Literal["step_flow"] = "step_flow"
    steps: list[Step] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def _sequential(self):
        if [s.n for s in self.steps] != list(range(1, len(self.steps) + 1)):
            raise ValueError("step numbers must run 1..N in order")
        return self


class AnswerOption(_Base):
    key: str = Field(min_length=1, max_length=4)
    text: str = Field(max_length=40)


class AnswerInputBlock(_Block):
    type: Literal["answer_input"] = "answer_input"
    mode: Literal["mcq", "short", "fraction"]
    prompt: str = Field(min_length=1, max_length=140)
    options: list[AnswerOption] | None = Field(default=None, max_length=6)

    @model_validator(mode="after")
    def _options_match_mode(self):
        if self.mode == "mcq":
            if not self.options or len(self.options) < 2:
                raise ValueError("mcq answer_input needs at least 2 options")
        else:
            self.options = None
        return self


Block = Annotated[
    NoteBlock
    | FractionBarBlock
    | NumberLineBlock
    | AnalogySceneBlock
    | StepFlowBlock
    | AnswerInputBlock,
    Field(discriminator="type"),
]


class VisualSpec(_Base):
    spec_version: Literal["0.1"] = SPEC_VERSION
    intervention_kind: InterventionKind
    title: str = Field(min_length=1, max_length=60)
    blocks: list[Block] = Field(min_length=1, max_length=6)

    def to_payload(self) -> dict:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


ALLOWED_BLOCKS: dict[str, set[str]] = {
    "guiding_question": {"note", "fraction_bar", "analogy_scene", "number_line", "answer_input"},
    "hint": {"note", "fraction_bar", "number_line"},
    "explanation": {"note", "analogy_scene", "step_flow", "fraction_bar"},
    "worked_example": {"note", "analogy_scene", "step_flow", "number_line", "answer_input"},
}


def fallback_note_spec(kind: InterventionKind, text: str) -> VisualSpec:
    return VisualSpec(
        intervention_kind=kind,
        title="Coba lagi ya",
        blocks=[NoteBlock(tone="info", text=text[:300] or "Coba lagi ya.")],
    )


def parse_visual_spec(raw: Any, correct_answer: str | None = None) -> VisualSpec:
    try:
        spec = VisualSpec.model_validate(raw)
    except ValidationError as exc:
        raise VisualSpecError(f"schema validation failed: {exc}") from exc

    _check_kind_layout(spec)
    _check_math_consistency(spec)
    if correct_answer:
        _check_no_answer_leak(spec, correct_answer)
    return spec


def _check_kind_layout(spec: VisualSpec) -> None:
    allowed = ALLOWED_BLOCKS[spec.intervention_kind]
    for block in spec.blocks:
        if block.type not in allowed:
            raise VisualSpecError(f"{spec.intervention_kind} may not contain a {block.type} block")

    inputs = [i for i, b in enumerate(spec.blocks) if b.type == "answer_input"]
    if inputs and inputs != [len(spec.blocks) - 1]:
        raise VisualSpecError("answer_input must appear once, as the last block")

    if spec.intervention_kind == "worked_example":
        flows = [b for b in spec.blocks if b.type == "step_flow"]
        if not flows or not flows[0].steps[-1].locked:
            raise VisualSpecError("worked_example needs a step_flow whose last step is locked")


_EXPR_TOKEN_RE = re.compile(r"\s*(\d+/\d+|\d+(?:\.\d+)?|[+\-x×*÷])")


def _eval_expression(expr: str) -> Fraction | None:
    tokens: list[str] = []
    position = 0
    stripped = expr.strip()
    while position < len(stripped):
        match = _EXPR_TOKEN_RE.match(stripped, position)
        if not match:
            return None
        tokens.append(match.group(1))
        position = match.end()
    if not tokens or len(tokens) % 2 == 0:
        return None

    def number(token: str) -> Fraction | None:
        if token in "+-x×*÷":
            return None
        return to_fraction(token) if "/" in token or token.isdigit() else Fraction(token)

    values: list[Fraction] = []
    operators: list[str] = []
    for index, token in enumerate(tokens):
        if index % 2 == 0:
            value = number(token)
            if value is None:
                return None
            values.append(value)
        else:
            if token.isdigit() or "/" in token:
                return None
            operators.append(token)

    folded_values = [values[0]]
    folded_ops: list[str] = []
    for operator, value in zip(operators, values[1:]):
        if operator in "x×*":
            folded_values[-1] *= value
        elif operator == "÷":
            if value == 0:
                return None
            folded_values[-1] /= value
        else:
            folded_ops.append(operator)
            folded_values.append(value)

    result = folded_values[0]
    for operator, value in zip(folded_ops, folded_values[1:]):
        result = result + value if operator == "+" else result - value
    return result


def _check_math_consistency(spec: VisualSpec) -> None:
    for block in spec.blocks:
        if block.type != "step_flow":
            continue
        for step in block.steps:
            if not step.math:
                continue
            for segment in step.math.split(";"):
                sides = segment.split("=")
                if len(sides) < 2:
                    continue
                known = [v for v in (_eval_expression(s) for s in sides) if v is not None]
                if len(known) >= 2 and any(v != known[0] for v in known[1:]):
                    raise VisualSpecError(
                        f"step {step.n}: '{segment.strip()}' is not numerically consistent"
                    )


_NUMBER_TOKEN_RE = re.compile(r"\d+\s*/\s*\d+|\d+[.,]\d+|\d+")


def _parse_number(token: str) -> Fraction | None:
    cleaned = token.replace(",", ".").replace(" ", "")
    try:
        if "/" in cleaned:
            numerator, denominator = cleaned.split("/")
            return Fraction(int(numerator), int(denominator))
        return Fraction(cleaned)
    except (ValueError, ZeroDivisionError):
        return None


_STRUCTURAL_KEYS = {"type", "tone", "template", "mode", "intervention_kind", "spec_version"}


def _collect_strings(node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key not in _STRUCTURAL_KEYS:
                _collect_strings(value, out)
    elif isinstance(node, list):
        for item in node:
            _collect_strings(item, out)
    elif isinstance(node, str):
        out.append(node)


def _check_no_answer_leak(spec: VisualSpec, correct_answer: str) -> None:
    answer = _parse_number(correct_answer.strip())
    strings: list[str] = []
    _collect_strings(spec.model_dump(mode="json"), strings)

    if answer is None:
        normalized = correct_answer.strip().casefold()
        if len(normalized) >= 3 and any(normalized in s.casefold() for s in strings):
            raise VisualSpecError("a block states the exercise's final answer")
        return

    for text in strings:
        for token in _NUMBER_TOKEN_RE.findall(text):
            if _parse_number(token) == answer:
                raise VisualSpecError(f"a block states the exercise's final answer ({token!r})")

    for block in spec.blocks:
        if block.type == "fraction_bar":
            for row in block.rows:
                if Fraction(row.numerator, row.denominator) == answer:
                    raise VisualSpecError("a fraction_bar row draws the exercise's final answer")
        elif block.type == "number_line":
            for point in block.points:
                if to_fraction(point.at) == answer:
                    raise VisualSpecError("a number_line point marks the exercise's final answer")
            for arrow in block.arrows:
                if not arrow.hidden_end and to_fraction(arrow.from_) + to_fraction(arrow.by) == answer:
                    raise VisualSpecError("a number_line arrow ends on the exercise's final answer")
