"""Key selection and health tracking for aliases that hold several keys."""

import hashlib
import threading
import time
from dataclasses import dataclass

RATE_LIMITED, INVALID, TRANSIENT = "rate_limited", "invalid", "transient"
INVALID_COOLDOWN = 600.0
MAX_RATE_LIMIT_COOLDOWN = 300.0


def fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def mask(key: str) -> str:
    return f"...{key[-4:]}" if len(key) > 8 else "****"


@dataclass
class KeyState:
    masked: str
    cooldown_until: float = 0.0
    consecutive_failures: int = 0
    requests: int = 0
    errors: int = 0
    last_error: str | None = None
    last_kind: str | None = None


class KeyPool:
    """Round-robin over an alias's keys; keys in cooldown go to the back.

    Cooling keys are still tried last: a key that may work beats a certain failure.
    State lives in memory, per process.
    """

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._cursor: dict[str, int] = {}
        self._state: dict[tuple[str, str], KeyState] = {}

    def _get(self, alias: str, key: str) -> KeyState:
        return self._state.setdefault((alias, fingerprint(key)), KeyState(mask(key)))

    def order(self, alias: str, keys: list[str]) -> list[str]:
        with self._lock:
            start = self._cursor.get(alias, 0) % len(keys)
            self._cursor[alias] = start + 1
            rotated = keys[start:] + keys[:start]
            now = self._clock()
            ready = [k for k in rotated if self._get(alias, k).cooldown_until <= now]
            cooling = sorted((k for k in rotated if self._get(alias, k).cooldown_until > now),
                             key=lambda k: self._get(alias, k).cooldown_until)
            return ready + cooling

    def success(self, alias: str, key: str) -> None:
        with self._lock:
            s = self._get(alias, key)
            s.requests += 1
            s.consecutive_failures = 0
            s.cooldown_until = 0.0

    def failure(self, alias: str, key: str, kind: str, error: str,
                retry_after: float | None = None) -> float:
        """Record a failed attempt; return the cooldown applied in seconds."""
        with self._lock:
            s = self._get(alias, key)
            s.requests += 1
            s.errors += 1
            s.consecutive_failures += 1
            s.last_error = error[:200]
            s.last_kind = kind
            if kind == RATE_LIMITED:
                cooldown = retry_after or min(2.0 ** s.consecutive_failures * 5, MAX_RATE_LIMIT_COOLDOWN)
            elif kind == INVALID:
                cooldown = INVALID_COOLDOWN
            else:
                cooldown = 0.0
            if cooldown:
                s.cooldown_until = self._clock() + cooldown
            return cooldown

    def snapshot(self) -> list[dict]:
        """Per-key health. status: ready, rate_limited (resting) or invalid (rejected, resting)."""
        now = self._clock()
        with self._lock:
            return [{"alias": alias, "fingerprint": fp, "key": s.masked, "requests": s.requests,
                     "errors": s.errors, "cooldown_seconds": max(0, round(s.cooldown_until - now)),
                     "status": s.last_kind if s.cooldown_until > now else "ready",
                     "last_error": s.last_error}
                    for (alias, fp), s in sorted(self._state.items())]
