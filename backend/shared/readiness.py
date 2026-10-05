"""Liveness vs readiness (research 09 OBS-9 / BE-13).

``/livez`` answers "is the process alive" and touches nothing — a liveness
probe that hits a database turns one slow dependency into a restart storm.
``/readyz`` answers "can this instance serve an analysis right now": it runs
the service's dependency checks, but at most once per ``ttl_sec`` (probes from
several watchers must not multiply load on a struggling dependency) and
replies only ok / not ok — which dependency failed goes to the log and to the
``dependency_up{dependency}`` gauge on the authenticated ``/metrics``, not to
an unauthenticated caller.

Each check is a callable that returns normally when the dependency is usable
and raises (or returns ``False``) when not. Checks must bound their own waits
(about a second). They run on a small executor of their own
(``check_async``) — not the request threadpool, and not the loop's default
executor, which carries the gateway's audit writes and quota settlements: a
probe stuck behind a slow dependency must not hold a thread those need
(review W2-C7).
"""

from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# Two threads: concurrent probes share one evaluation anyway (the probe lock).
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="readiness")

# Latest result per dependency (1 = up, 0 = down), read by the gauge.
_LAST: dict[str, float] = {}
_LAST_LOCK = threading.Lock()


def dependency_rows() -> Iterable[tuple[dict[str, str], float]]:
    with _LAST_LOCK:
        return [({"dependency": name}, value) for name, value in sorted(_LAST.items())]


Checks = dict[str, Callable[[], object]]


class ReadinessProbe:
    def __init__(self, checks: Callable[[], Checks], ttl_sec: float = 5.0):
        # A factory, not a dict: which dependencies apply follows the current
        # settings (CACHE_BACKEND, VECTOR_BACKEND, LLM_MODE …) at check time.
        self._checks = checks
        self._ttl = ttl_sec
        self._lock = threading.Lock()
        self._checked_at = -math.inf
        self._result: tuple[bool, dict[str, bool]] = (False, {})

    def check(self) -> tuple[bool, dict[str, bool]]:
        """(ready, {dependency: up}) — re-evaluated at most once per ttl."""
        with self._lock:  # concurrent probes share one evaluation
            if time.monotonic() - self._checked_at < self._ttl:
                return self._result
            results: dict[str, bool] = {}
            for name, fn in self._checks().items():
                try:
                    results[name] = fn() is not False
                except Exception as exc:  # noqa: BLE001 — any failure = not ready
                    logger.warning("readiness: %s unavailable (%s)", name, exc.__class__.__name__)
                    results[name] = False
            with _LAST_LOCK:
                for gone in set(self._result[1]) - set(results):
                    _LAST.pop(gone, None)  # no longer a dependency (config changed)
                _LAST.update({name: 1.0 if up else 0.0 for name, up in results.items()})
            self._result = (all(results.values()), results)
            self._checked_at = time.monotonic()
            return self._result

    async def check_async(self) -> tuple[bool, dict[str, bool]]:
        """``check()`` on the readiness executor (see module doc)."""
        return await asyncio.get_running_loop().run_in_executor(_EXECUTOR, self.check)

    def reset(self) -> None:
        """Forget the cached result (tests)."""
        with self._lock:
            self._checked_at = -math.inf
