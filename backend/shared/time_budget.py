"""Whole-request time budget, passed down every hop (research 09 BE-4).

The gateway fixes ONE deadline per analysis and sends the AI Engine the
SECONDS LEFT in ``X-Time-Budget`` (relative, like gRPC's ``grpc-timeout``:
an absolute epoch would make every hop depend on the two hosts' clocks
agreeing — review W2-B6). The engine turns it back into a deadline on its own
clock on arrival. Each inner wait — the gateway's per-call HTTP timeout, the
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
import math
import time

BUDGET_HEADER = "X-Time-Budget"  # seconds left in the request's budget

# Never trust a budget larger than this (budget() takes the min with each
# call's own timeout anyway; this only rejects nonsense values).
_MAX_AHEAD_SEC = 3600.0

_deadline_var: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "citewall_request_deadline", default=None
)


class BudgetExhausted(TimeoutError):
    """The request's deadline leaves no useful time for this step."""


def format_budget(deadline: float, *, now: float | None = None) -> str:
    """The ``X-Time-Budget`` value for an absolute local deadline."""
    left = deadline - (time.time() if now is None else now)
    return f"{max(0.0, left):.3f}"


def parse_budget(raw: str | None, *, now: float | None = None) -> float | None:
    """A local absolute deadline from an ``X-Time-Budget`` value, else None.

    A zero or negative budget is a deadline that has already passed (every
    wait then raises BudgetExhausted) — never "no deadline"."""
    if not raw:
        return None
    try:
        left = float(raw)
    except (TypeError, ValueError):
        return None
    if math.isnan(left) or left > _MAX_AHEAD_SEC:
        return None
    return (time.time() if now is None else now) + max(0.0, left)


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


def out_of_time(*, margin: float = 2.0, minimum: float = 1.0) -> bool:
    """True when the request's deadline leaves no useful time — e.g. to tell
    a timeout caused by the deadline-capped wait (raise BudgetExhausted → 504)
    from a backend that is merely slow within its own timeout (degrade)."""
    left = remaining_sec()
    return left is not None and left - margin < minimum
