"""Canvas Builder — detects deep explanations and parses them into structured canvas payload."""
import re
from dataclasses import dataclass, field


# ── Trigger heuristics ─────────────────────────────────────────────────────────
CANVAS_KEYWORD_PATTERNS = [
    r"\bcanvas\b", r"\bkanvas\b", r"\bvisual\b", r"\bgambar\b",
    r"\bjellaskan\b", r"\bjelaskan\b", r"\bpahami\b", r"\bpembuktian\b",
    r"\bbuktikan\b", r"\balgorithm\b", r"\balgoritma\b", r"\bderivasi\b",
    r"\bturunkan\b", r"\blangkah[\s-]?demi[\s-]?langkah\b", r"\bstep by step\b",
    r"\bcara kerja\b", r"\bbagaimana cara\b", r"\bgimana cara\b",
    r"\bkonsep\b", r"\bprinsip\b", r"\bteori\b", r"\brumus\b",
    r"\bcontoh soal\b", r"\bcontoh kode\b", r"\bpseudocode\b",
    r"\bflowchart\b", r"\bdiagram\b", r"\balur\b", r"\btahap\b",
    r"\btahapan\b", r"\bsoal\b", r"\bhitung\b",
]

CANVAS_RESPONSE_SIGNALS = [
    r"###\s+Langkah",          # step-by-step headings
    r"^Langkah\s+\d+",         # explicit step lines
    r"^\d+[\.\)]\s+\*+",       # numbered steps like 1. **Buat Segitiga:**
    r"^#{1,3}\s+\*+Kemungkinan\s+\d+", # Kemungkinan 1
    r"```[a-zA-Z]+",           # code blocks
    r"\$\$[^\n]{5,}\$\$",      # display math
    r"####",                   # sub-sub-headings (deep structure)
]

MIN_RESPONSE_LEN_FOR_CANVAS = 250  # characters


def should_open_canvas(prompt: str, response: str) -> bool:
    """Return True when the response warrants a canvas panel."""
    prompt_lower = prompt.lower()
    if any(re.search(p, prompt_lower) for p in CANVAS_KEYWORD_PATTERNS):
        return True
    if len(response) >= MIN_RESPONSE_LEN_FOR_CANVAS:
        for sig in CANVAS_RESPONSE_SIGNALS:
            if re.search(sig, response, re.MULTILINE):
                return True
    return False


# ── Payload builder ────────────────────────────────────────────────────────────

@dataclass
class CanvasStep:
    number: int
    title: str
    body: str  # may contain markdown / KaTeX
    formula: str = ""
    short_desc: str = ""


@dataclass
class CanvasPayload:
    title: str = ""
    subject: str = "Matematika"   # Matematika | Informatika | Umum
    analogy: str = ""
    concept: str = ""
    core_formula: str = ""
    steps: list[CanvasStep] = field(default_factory=list)
    summary: str = ""
    final_answer: str = ""
    quiz: list[dict] = field(default_factory=list)
    raw_content: str = ""


def _extract_heading_title(text: str) -> str:
    """Pull the first markdown heading as canvas title."""
    m = re.search(r"^#{1,3}\s+(.+)$", text, re.MULTILINE)
    if m:
        t = m.group(1).strip()
        t = re.sub(r"^(Perbaikan Kode|Penjelasan|Cara|Rumus)[:\s-]*", "", t, flags=re.I)
        return t or m.group(1).strip()
    return "Peta Pemahaman Materi"


def _detect_subject(text: str, prompt: str) -> str:
    combined = (text + " " + prompt).lower()
    if any(w in combined for w in ["python", "javascript", "program", "kode", "code",
                                    "algoritma", "variabel", "fungsi", "loop", "if", "assert", "syntax"]):
        return "Informatika"
    if any(w in combined for w in ["rumus", "persamaan", "integral", "turunan", "matriks",
                                    "aljabar", "geometri", "segitiga", "luas", "keliling", "x^"]):
        return "Matematika"
    return "Umum"


GREETING_STARTS = (
    "halo", "hai", "wah", "keren", "kak ambis", "senang",
    "tentu", "selamat", "semangat", "siap", "oke", "nah"
)


def _is_conversational_noise(line: str) -> bool:
    """Check if a line is just conversational greeting or closing cheer."""
    low = line.strip().lower()
    if any(low.startswith(g) for g in GREETING_STARTS):
        return True
    if any(phrase in low for phrase in [
        "tetap semangat", "semoga membantu", "tanya ke kak ambis",
        "ada yang mau ditanyakan", "jangan ragu", "teman belajar",
    ]):
        return True
    return False


def _extract_analogy(text: str) -> str:
    """Find an actual analogy or intuitive concept, skipping conversational greetings."""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    
    # Priority 1: Look for explicit analogy keywords
    for line in lines:
        if line.startswith("#") or line.startswith("```"):
            continue
        low = line.lower()
        if any(k in low for k in ["bayangkan", "ibarat", "misalkan", "analoginya", "logikanya", "seperti"]):
            if not _is_conversational_noise(line) and len(line) > 25:
                return line[:500]

    # Priority 2: First informative paragraph that is NOT a greeting
    for line in lines:
        if line.startswith("#") or line.startswith("```"):
            continue
        if not _is_conversational_noise(line) and len(line) > 35:
            return line[:500]

    return ""


def _extract_core_formula(text: str) -> str:
    """Find display math $$...$$ or code assertion/formula."""
    m = re.search(r"\$\$([\s\S]*?)\$\$", text)
    if m:
        return m.group(0).strip()
    # Code assignment formula match (e.g. luas = 0.5 * alas * tinggi)
    m_code = re.search(r"(\w+\s*=\s*[\w\d\.\+\-\*\/\(\)\s]+)", text)
    if m_code and any(op in m_code.group(1) for op in ["*", "+", "/", "-"]):
        return m_code.group(1).strip()
    return ""


def _extract_steps(text: str) -> list[CanvasStep]:
    """Parse **Langkah N** or ### Langkah N blocks into CanvasStep objects with short summary."""
    steps: list[CanvasStep] = []

    pattern = re.compile(
        r"(?:\*{0,2}Langkah\s+(\d+)[:\.]?\*{0,2})\s*([^\n]*)\n([\s\S]*?)(?=(?:\*{0,2}Langkah\s+\d+)|$)",
        re.IGNORECASE,
    )
    for m in pattern.finditer(text):
        num = int(m.group(1))
        title = m.group(2).replace("**", "").strip() or f"Langkah {num}"
        body = m.group(3).strip()

        formula_match = re.search(r"\$\$([\s\S]*?)\$\$", body)
        formula = formula_match.group(0).strip() if formula_match else ""

        # Make a short 1-line description for node cards
        first_line = ""
        for bl in body.split("\n"):
            bls = bl.strip()
            if bls and not bls.startswith("#") and not bls.startswith("```"):
                first_line = re.sub(r"[\*\`]", "", bls)
                break
        short_desc = first_line[:120] if first_line else title

        steps.append(CanvasStep(number=num, title=title, body=body, formula=formula, short_desc=short_desc))

    # Fallback: markdown ### Langkah N headers
    if not steps:
        pattern2 = re.compile(
            r"^#{1,4}\s+(?:Langkah|Step|Tahap)\s+(\d+)[:\.]?\s*([^\n]*)\n([\s\S]*?)(?=^#{1,4}\s+|$)",
            re.MULTILINE | re.IGNORECASE,
        )
        for m in pattern2.finditer(text):
            num = int(m.group(1))
            title = m.group(2).strip() or f"Langkah {num}"
            body = m.group(3).strip()
            formula_match = re.search(r"\$\$([\s\S]*?)\$\$", body)
            formula = formula_match.group(0).strip() if formula_match else ""

            first_line = ""
            for bl in body.split("\n"):
                bls = bl.strip()
                if bls and not bls.startswith("#") and not bls.startswith("```"):
                    first_line = re.sub(r"[\*\`]", "", bls)
                    break
            short_desc = first_line[:120] if first_line else title

            steps.append(CanvasStep(number=num, title=title, body=body, formula=formula, short_desc=short_desc))

    # Fallback 3: numbered list steps (e.g. 1. **Buat Segitiga ABC:** ...)
    if not steps:
        pattern3 = re.compile(
            r"(?:^(\d+)[\.\)]\s+)\*{0,2}([^\n]+)\*{0,2}\n([\s\S]*?)(?=(?:^\d+[\.\)]\s+)|(?:^#{1,3}\s+)|$)",
            re.MULTILINE,
        )
        for m in pattern3.finditer(text):
            num = int(m.group(1))
            title = m.group(2).replace("**", "").replace(":", "").strip() or f"Langkah {num}"
            body = m.group(3).strip()
            formula_match = re.search(r"\$\$([\s\S]*?)\$\$", body)
            formula = formula_match.group(0).strip() if formula_match else ""

            first_line = ""
            for bl in body.split("\n"):
                bls = bl.strip()
                if bls and not bls.startswith("#") and not bls.startswith("```"):
                    first_line = re.sub(r"[\*\`]", "", bls)
                    break
            short_desc = first_line[:120] if first_line else title

            steps.append(CanvasStep(number=num, title=title, body=body, formula=formula, short_desc=short_desc))

    # Fallback 4: sections starting with Kemungkinan / Kasus / Opsi
    if not steps:
        pattern4 = re.compile(
            r"^#{1,3}\s+\*?(?:Kemungkinan|Kasus|Opsi)\s+(\d+)[:\s]*([^\n]*)\*?\n([\s\S]*?)(?=^#{1,3}\s+|$)",
            re.MULTILINE | re.IGNORECASE,
        )
        for m in pattern4.finditer(text):
            num = int(m.group(1))
            title = m.group(2).replace("**", "").strip() or f"Kasus {num}"
            body = m.group(3).strip()
            formula_match = re.search(r"\$\$([\s\S]*?)\$\$", body)
            formula = formula_match.group(0).strip() if formula_match else ""

            first_line = ""
            for bl in body.split("\n"):
                bls = bl.strip()
                if bls and not bls.startswith("#") and not bls.startswith("```"):
                    first_line = re.sub(r"[\*\`]", "", bls)
                    break
            short_desc = first_line[:120] if first_line else title

            steps.append(CanvasStep(number=num, title=f"Kasus {num}: {title}", body=body, formula=formula, short_desc=short_desc))

    # Re-index steps sequentially (1, 2, 3...) to guarantee uniqueness
    for idx, s in enumerate(steps, start=1):
        s.number = idx

    return steps


def _extract_summary_and_answer(text: str) -> tuple[str, str]:
    """Extract clean, meaningful conclusion and the specific final answer (avoiding cheerleading)."""
    summary = ""
    final_answer = ""

    # Check for explicit sections
    sum_match = re.search(
        r"^#{1,3}\s+(?:Kesimpulan|Ringkasan|Hasil Akhir)[:\s]*([^\n]*)\n([\s\S]*?)(?=^#{1,3}\s+|$)",
        text, re.MULTILINE | re.I
    )
    if sum_match:
        content = (sum_match.group(1) + " " + sum_match.group(2)).strip()
        lines = [l.strip() for l in content.split("\n") if l.strip() and not _is_conversational_noise(l)]
        summary = "\n".join(lines)[:600]

    # Look for specific result sentences: "Jadi, ...", "Maka, ...", "Sehingga diperoleh ..."
    if not summary:
        matches = re.findall(
            r"((?:Jadi|Maka|Kesimpulannya|Hasil akhirnya|Sehingga)[^\.\n]+\.(?:[^\.\n]+\.)?)",
            text, re.I
        )
        for cand in matches:
            if not _is_conversational_noise(cand):
                summary = cand.strip()
                break

    # Extract final numerical or formula answer
    ans_match = re.search(r"(?:Jawaban akhir|Hasil akhir|Nilai dari|assert|\=\s*)[:\s]*([^\n]+)", text, re.I)
    if ans_match:
        final_answer = ans_match.group(0).strip()[:200]

    if not summary:
        # Fallback to non-conversational last paragraphs
        paras = [p.strip() for p in text.split("\n\n") if p.strip() and not _is_conversational_noise(p)]
        summary = paras[-1][:400] if paras else "Materi telah dianalisis secara bertahap."

    return summary, final_answer


def build_canvas_payload(prompt: str, response: str) -> CanvasPayload:
    """Parse the full AI response into a structured CanvasPayload with clean non-ambiguous content."""
    summary, final_answer = _extract_summary_and_answer(response)

    payload = CanvasPayload(
        title=_extract_heading_title(response),
        subject=_detect_subject(response, prompt),
        analogy=_extract_analogy(response),
        core_formula=_extract_core_formula(response),
        steps=_extract_steps(response),
        summary=summary,
        final_answer=final_answer,
        raw_content=response,
    )

    # Concept: Find section dedicated to principle/theory or explanation (not Langkah, not greetings)
    concept_match = re.search(
        r"^#{1,3}\s+(?:Konsep|Prinsip|Teori|Penjelasan|Dasar Teori|Logika|Aturan|Perbaikan Kode)[^\n]*\n([\s\S]*?)(?=^#{1,3}\s+|$)",
        response, re.MULTILINE | re.I
    )
    if concept_match:
        payload.concept = concept_match.group(1).strip()[:700]
    else:
        # Fallback: first non-Langkah section
        other_sec = re.search(
            r"^#{1,3}\s+(?!Langkah|Kesimpulan|Ringkasan)([^\n]+)\n([\s\S]*?)(?=^#{1,3}\s+|$)",
            response, re.MULTILINE
        )
        if other_sec:
            payload.concept = (other_sec.group(1) + "\n" + other_sec.group(2)).strip()[:600]

    return payload
