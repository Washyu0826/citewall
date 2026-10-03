"""Start-up warm-up (research 09 BE-13).

Without it the first analysis after a (re)start pays every lazy load: the
Qwen3 embedder and reranker (loaded on first use so tests and mock deployments
never pay for them) and, in ``LLM_MODE=local``, Ollama loading the model into
VRAM — together tens of seconds on the 8 GB target, charged to whichever
attorney happens to be first.

Runs once in a background thread from the AI Engine's startup hook so boot is
not delayed; ``/readyz`` reports not-ready until it has finished. Every step is
best effort: a failure is logged and the step is simply paid on first use, as
before — warm-up never makes a working instance unready for good.
"""

from __future__ import annotations

import logging
import threading
import time

import httpx

from backend.shared.config import settings

logger = logging.getLogger(__name__)

_done = threading.Event()
_started = False
_start_lock = threading.Lock()


def _ollama_root() -> str:
    """OLLAMA_BASE_URL is the OpenAI-compatible base (…/v1); the native API
    (``/api/generate``) lives at its root."""
    base = settings.OLLAMA_BASE_URL.rstrip("/")
    return base[: -len("/v1")] if base.endswith("/v1") else base


def _steps() -> list[tuple[str, object]]:
    from backend.ai_engine import rag

    steps: list[tuple[str, object]] = []
    embedder = rag._embedder  # noqa: SLF001 — warm the module's own instance
    if embedder.backend in ("bge-m3", "qwen3"):
        steps.append(("embedder", lambda: embedder.dim))  # .dim loads the model
    reranker = rag._reranker  # noqa: SLF001
    if reranker.enabled:
        steps.append(("reranker", lambda: reranker.score("warm-up", ["warm-up"])))
    if settings.LLM_MODE == "local":
        # Native API: a generate with no prompt only loads the model, and
        # keep_alive keeps it resident (also set OLLAMA_KEEP_ALIVE on the
        # Ollama server — the OpenAI-compatible calls use the server default).
        steps.append(
            (
                "ollama",
                lambda: httpx.post(
                    f"{_ollama_root()}/api/generate",
                    json={"model": settings.LLM_MODEL_LOCAL, "keep_alive": settings.OLLAMA_KEEP_ALIVE},
                    timeout=float(settings.OLLAMA_TIMEOUT_SEC),
                ).raise_for_status(),
            )
        )
    return steps


def needed() -> bool:
    return bool(_steps())


def run() -> None:
    try:
        for name, step in _steps():
            started = time.monotonic()
            try:
                step()
                logger.info("warm-up: %s ready in %.1f s", name, time.monotonic() - started)
            except Exception as exc:  # noqa: BLE001 — best effort, see module doc
                logger.warning(
                    "warm-up: %s failed after %.1f s (%s) — the first request pays the load",
                    name,
                    time.monotonic() - started,
                    exc.__class__.__name__,
                )
    finally:
        _done.set()


def start_background() -> None:
    """Start warm-up once per process (idempotent)."""
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
    if not needed():
        _done.set()
        return
    threading.Thread(target=run, name="warm-up", daemon=True).start()


def is_done() -> bool:
    """True once warm-up finished — or when there is nothing to warm."""
    return _done.is_set() or not needed()
