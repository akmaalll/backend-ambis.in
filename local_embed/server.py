"""Local embedding service (OpenAI-compatible /v1/embeddings) for the Gemini fallback.

Runs Qwen3-Embedding-0.6B on CPU, fp32 (bf16 is far slower on CPU), truncated to
768 dims to match vector(768). Standard library HTTP server, bound to 127.0.0.1;
its own dependencies are in local_embed/requirements.txt and are NOT part of the
backend's requirements.txt.

    pip install -r local_embed/requirements.txt
    python local_embed/server.py            # listens on 127.0.0.1:8002

Request:  POST /v1/embeddings {"input": [...], "dimensions": 768, "task": "query"|"document"}
Response: {"data": [{"index": i, "embedding": [...]}], "model": "..."}
Queries get the instruction prefix (QUERY_INSTRUCTION); documents get none.
"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL_NAME = os.environ.get("EMBED_MODEL", "Qwen/Qwen3-Embedding-0.6B")
HOST = os.environ.get("EMBED_HOST", "127.0.0.1")
PORT = int(os.environ.get("EMBED_PORT", "8002"))
MAX_TEXTS = 64
QUERY_INSTRUCTION = os.environ.get(
    "QUERY_INSTRUCTION",
    "Instruct: Diberikan pertanyaan siswa SMP tentang matematika, temukan bagian buku pelajaran yang menjawabnya\nQuery:",
)

_model = None
_lock = threading.Lock()


def load_model():
    import torch
    from sentence_transformers import SentenceTransformer

    torch.set_num_threads(int(os.environ.get("EMBED_THREADS", "4")))
    model = SentenceTransformer(
        MODEL_NAME,
        device="cpu",
        truncate_dim=768,
        tokenizer_kwargs={"padding_side": "left"},
        model_kwargs={"torch_dtype": torch.float32},
    )
    model.max_seq_length = 1024
    return model


def embed(texts: list[str], task: str, dimensions: int | None) -> list[list[float]]:
    with _lock:
        vectors = _model.encode(
            texts,
            prompt=QUERY_INSTRUCTION if task == "query" else None,
            batch_size=4,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
    out = vectors.astype("float32").tolist()
    return [v[:dimensions] for v in out] if dimensions else out


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok", "model": MODEL_NAME})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/v1/embeddings":
            return self._send(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(length))
            texts = req["input"]
            if isinstance(texts, str):
                texts = [texts]
            if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
                raise ValueError("input must be a string or a list of strings")
            if not 0 < len(texts) <= MAX_TEXTS:
                raise ValueError(f"input must hold 1..{MAX_TEXTS} texts")
            task = req.get("task", "document")
            if task not in ("query", "document"):
                raise ValueError("task must be 'query' or 'document'")
            dimensions = req.get("dimensions")
            if dimensions is not None and not (isinstance(dimensions, int) and 0 < dimensions <= 768):
                raise ValueError("dimensions must be an integer in 1..768")
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            return self._send(400, {"error": str(exc)})
        vectors = embed(texts, task, dimensions)
        self._send(200, {"model": MODEL_NAME, "data": [{"index": i, "embedding": v} for i, v in enumerate(vectors)]})

    def log_message(self, fmt, *args):
        pass


def main() -> None:
    global _model
    print(f"loading {MODEL_NAME} ...", flush=True)
    _model = load_model()
    print(f"ready on http://{HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
