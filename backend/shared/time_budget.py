"""Whole-request time budget, passed down every hop (research 09 BE-4).

The gateway fixes ONE absolute deadline per analysis (wall-clock epoch
seconds, so it survives the process boundary) and sends it to the AI Engine
as ``X-Deadline``. Each inner wait — the gateway's per-call HTTP timeout, the
AI Engine's Ollama / Dify / Anthropic timeouts and Anthropic's retry loop —
takes ``min(its own budget, time left)``. Before this, timeouts only nested
per hop: three sequential 330 s steps could add up far past the browser's
420 s, and Anthropic retries could outlive the gateway's wait, so abandoned
work kept the model busy and unaccounted (FAILURE_LOG B-13, review V-B4).

The deadline lives in a ContextVar: FastAPI copies the context into the
threadpool for sync endpoints, and ``asyncio.run`` copies it into its task,
so every call made while handling the request sees it. Outside a request
(scripts, tests) there is no deadline and every helper falls back to the
caller's own default — no behaviour change.
"""

from __future__ import annotations

import contextvars
import time

DEADLINE_HEADER = "X-Deadline"

# Never trust a deadline further out than this (a forged / skewed header must
# not extend a call beyond its configured budget — budget() takes the min
# anyway, this only rejects nonsense values).
_MAX_AHEAD_SEC = 3600.0

_deadline_var: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "citewall_request_deadline", default=None
)


class BudgetExhausted(TimeoutError):
    """The request's deadline leaves no useful time for this step."""


def parse_deadline(raw: str | None, *, now: float | None = None) -> float | None:
    """A sane absolute deadline from a header value, else None."""
    if not raw:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    now = time.time() if now is None else now
    if not (now - 60.0 < value < now + _MAX_AHEAD_SEC):
        return None
    return value


def bind_deadline(deadline: float | None) -> None:
    _deadline_var.set(deadline)


def current_deadline() -> float | None:
    return _deadline_var.get()


def remaining_sec(*, now: float | None = None) -> float | None:
    """Seconds left before the deadline (may be negative), or None."""
    deadline = _deadline_var.get()
    if deadline is None:
        return None
    return deadline - (time.time() if now is None else now)


def budget(default: float, *, margin: float = 2.0, minimum: float = 1.0) -> float:
    """The timeout for one inner wait: ``min(default, time left - margin)``.

    Raises BudgetExhausted when less than ``minimum`` would be left — starting
    a model call that cannot finish only burns the GPU for nobody.
    """
    left = remaining_sec()
    if left is None:
        return default
    usable = left - margin
    if usable < minimum:
        raise BudgetExhausted(f"request deadline leaves {left:.1f}s (< {minimum + margin:.1f}s)")
    return min(default, usable)


def can_afford(seconds: float, *, margin: float = 2.0) -> bool:
    """Whether ``seconds`` more (e.g. a retry backoff plus an attempt) fit."""
    left = remaining_sec()
    return left is None or left - margin >= seconds
