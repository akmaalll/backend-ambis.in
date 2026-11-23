"""Fake OpenAI-compatible LLM server for running the whole stack with NO API key.

Answers POST /chat/completions and POST /embeddings (also under a /v1 prefix) with canned
but contract-valid content, picking the reply by recognising which prompt template the
backend sent. The canned canvases are written for the seeded Penjumlahan Pecahan topic
(3/5 + 1/4); for other topics they are still valid, just not on-topic. Grading is real for
the seeded free-form exercise: a student answer equivalent to the reference answer is correct.

Stdlib only. Manual dev tool, not part of the test suite (tests/test_fake_llm_server.py
checks that its prompt markers still match the real templates).

Usage:
    python -m scripts.fake_llm_server --port 9099
then in .env:
    LLM_BASE_URL=http://127.0.0.1:9099
    LLM_API_KEY=anything
    LLM_MODEL_GRADING=fake
    LLM_MODEL_DIAGNOSIS=fake
    LLM_MODEL_INTERVENTION=fake
"""
import argparse
import hashlib
import json
import math
import re
from fractions import Fraction
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MISCONCEPTION_ANSWER = "4/9"


def _note(text: str, tone: str = "info") -> dict:
    return {"type": "note", "tone": tone, "text": text}


CANNED = {
    "guiding_question": {
        "title": "Mulai dari mana?",
        "blocks": [
            _note("Menurutmu, apa yang harus disamakan dulu sebelum dua pecahan ini dijumlahkan?"),
            {"type": "fraction_bar", "rows": [
                {"label": "3/5", "numerator": 3, "denominator": 5},
                {"label": "1/4", "numerator": 1, "denominator": 4},
            ]},
        ],
    },
    "hint": {
        "title": "Cek penyebutnya",
        "blocks": [
            _note("Hampir! Coba lihat lagi penyebutnya. Ukuran potongannya masih berbeda.", "warn"),
            {"type": "number_line", "start": "0", "end": "1", "ticks": 20,
             "points": [{"at": "12/20", "label": "3/5"}, {"at": "5/20", "label": "1/4"}]},
        ],
    },
    "explanation": {
        "title": "Kenapa penyebut harus sama?",
        "blocks": [
            {"type": "analogy_scene", "template": "pizza",
             "story": "Seperempat pizza dan sepertiga pizza punya ukuran potongan berbeda, jadi tidak bisa langsung digabung.",
             "items": [{"fraction": "1/4"}, {"fraction": "1/3"}]},
            {"type": "step_flow", "steps": [
                {"n": 1, "title": "Cara yang keliru", "detail": "Atas ditambah atas, bawah ditambah bawah.",
                 "math": "1 + 1 = 2 ; 2 + 3 = 5"},
                {"n": 2, "title": "Samakan ukuran potongan dulu", "detail": "KPK 2 dan 3 adalah 6",
                 "math": "1/2 = 3/6 ; 1/3 = 2/6"},
                {"n": 3, "title": "Baru gabungkan", "detail": "Penyebut tetap 6", "math": "3/6 + 2/6 = 5/6"},
            ]},
            _note("Sekarang coba soalmu lagi dengan cara yang sama ya!", "success"),
        ],
    },
    "worked_example": {
        "title": "Menyamakan penyebut dulu",
        "blocks": [
            {"type": "analogy_scene", "template": "coklat",
             "story": "Dua batang coklat beda ukuran potongan. Potong dulu sama besar.",
             "items": [{"fraction": "3/5"}, {"fraction": "1/4"}]},
            {"type": "step_flow", "steps": [
                {"n": 1, "title": "Cari penyebut yang sama", "detail": "KPK dari 5 dan 4 adalah 20", "math": "5 x 4 = 20"},
                {"n": 2, "title": "Ubah kedua pecahan", "math": "3/5 = 12/20 ; 1/4 = 5/20"},
                {"n": 3, "title": "Jumlahkan pembilangnya", "detail": "Hitung sendiri hasilnya ya!",
                 "math": "12/20 + 5/20 = ?/20", "locked": True},
            ]},
            {"type": "number_line", "start": "0", "end": "1", "ticks": 20,
             "points": [{"at": "12/20", "label": "12/20"}],
             "arrows": [{"from": "12/20", "by": "5/20", "label": "+ 5/20", "hidden_end": True}]},
        ],
    },
    "ask_visual": {
        "title": "Menjumlahkan pecahan",
        "blocks": [
            {"type": "step_flow", "steps": [
                {"n": 1, "title": "Samakan penyebut", "detail": "KPK 2 dan 3 adalah 6", "math": "1/2 = 3/6 ; 1/3 = 2/6"},
                {"n": 2, "title": "Jumlahkan pembilang", "detail": "Penyebut tetap", "math": "3/6 + 2/6 = 5/6"},
            ]},
            _note("Jadi hasilnya 5/6. Mau coba soal lain?", "success"),
        ],
    },
}

KIND_MARKERS = [
    ("A student typed a free question", "ask_visual"),
    ("about to attempt this problem for the first time", "guiding_question"),
    ("made several attempts at this same problem", "worked_example"),
    ("shown a specific, identified misconception", "explanation"),
    ("no specific misconception was detected", "hint"),
]

_FRACTION_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")


def _value(text: str) -> Fraction | None:
    match = _FRACTION_RE.match(text)
    if match and int(match.group(2)) != 0:
        return Fraction(int(match.group(1)), int(match.group(2)))
    try:
        return Fraction(text.strip().replace(",", "."))
    except (ValueError, ZeroDivisionError):
        return None


def _student_answer(prompt: str) -> str:
    match = re.search(r"<<<STUDENT_ANSWER_START>>>\n(.*?)\n<<<STUDENT_ANSWER_END>>>", prompt, re.DOTALL)
    return match.group(1).strip() if match else ""


def _reply_for(prompt: str) -> dict:
    if 'Return exactly this JSON object: {"ok": true}' in prompt:
        return {"ok": True}

    if "You are grading a middle-school" in prompt:
        reference = re.search(r"Reference correct answer:\n(.*)", prompt)
        expected = _value(reference.group(1)) if reference else None
        given = _value(_student_answer(prompt))
        correct = expected is not None and given is not None and expected == given
        return {"is_correct": correct, "error_type": None if correct else "conceptual"}

    if "You are diagnosing WHY" in prompt:
        codes = re.findall(r'- code: "([^"]+)"', prompt)
        hit = codes[0] if codes and _student_answer(prompt).replace(" ", "") == MISCONCEPTION_ANSWER else None
        return {"misconception_code": hit}

    for marker, kind in KIND_MARKERS:
        if marker in prompt:
            return CANNED[kind]

    return {}


def _embedding(text: str, dimensions: int) -> list[float]:
    values: list[float] = []
    counter = 0
    while len(values) < dimensions:
        digest = hashlib.sha256(f"{counter}:{text}".encode("utf-8")).digest()
        values.extend((byte - 127.5) / 127.5 for byte in digest)
        counter += 1
    vector = values[:dimensions]
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: dict) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid json"})
            return

        path = self.path.split("?")[0].removeprefix("/v1")
        if path == "/chat/completions":
            prompt = "\n".join(m.get("content", "") for m in payload.get("messages", []) if m.get("role") == "user")
            reply = _reply_for(prompt)
            self._send(200, {"choices": [{"message": {"role": "assistant", "content": json.dumps(reply, ensure_ascii=False)}}]})
        elif path == "/embeddings":
            texts = payload.get("input", [])
            texts = [texts] if isinstance(texts, str) else texts
            dimensions = int(payload.get("dimensions") or 768)
            self._send(200, {"data": [{"index": i, "embedding": _embedding(t, dimensions)} for i, t in enumerate(texts)]})
        else:
            self._send(404, {"error": f"unknown path {self.path}"})

    def log_message(self, format: str, *args) -> None:
        print(f"[fake-llm] {self.address_string()} {format % args}")


def make_server(port: int = 9099, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fake OpenAI-compatible LLM server")
    parser.add_argument("--port", type=int, default=9099)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    server = make_server(args.port, args.host)
    print(f"[fake-llm] listening on http://{args.host}:{args.port}")
    server.serve_forever()
