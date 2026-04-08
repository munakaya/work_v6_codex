from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from hmac import compare_digest
import threading
from time import monotonic


def parse_bearer_token(header_value: str | None) -> str | None:
    if not header_value:
        return None
    scheme, _, token = header_value.partition(" ")
    if scheme.strip().lower() != "bearer":
        return None
    token = token.strip()
    return token or None


@dataclass(frozen=True)
class WriteRequestGuardConfig:
    admin_token: str | None
    window_ms: int
    max_requests: int

    @property
    def auth_enabled(self) -> bool:
        return bool(self.admin_token)

    @property
    def rate_limit_enabled(self) -> bool:
        return self.window_ms > 0 and self.max_requests > 0


class WriteRequestRateLimiter:
    def __init__(self, *, window_ms: int, max_requests: int):
        self.window_ms = max(window_ms, 0)
        self.max_requests = max(max_requests, 0)
        self._lock = threading.Lock()
        self._entries: dict[str, deque[int]] = {}

    @property
    def enabled(self) -> bool:
        return self.window_ms > 0 and self.max_requests > 0

    def check_and_consume(self, client_id: str) -> int | None:
        if not self.enabled:
            return None
        now_ms = int(monotonic() * 1000)
        cutoff_ms = now_ms - self.window_ms
        with self._lock:
            queue = self._entries.setdefault(client_id, deque())
            while queue and queue[0] <= cutoff_ms:
                queue.popleft()
            if len(queue) >= self.max_requests:
                retry_after_ms = max(1, self.window_ms - (now_ms - queue[0]))
                return retry_after_ms
            queue.append(now_ms)
        return None


class WriteRequestGuard:
    def __init__(self, config: WriteRequestGuardConfig):
        self.config = config
        self.rate_limiter = WriteRequestRateLimiter(
            window_ms=config.window_ms,
            max_requests=config.max_requests,
        )

    def authenticate(self, header_value: str | None) -> bool:
        if not self.config.auth_enabled:
            return True
        token = parse_bearer_token(header_value)
        if token is None or self.config.admin_token is None:
            return False
        return compare_digest(token, self.config.admin_token)

    def check_rate_limit(self, client_id: str) -> int | None:
        return self.rate_limiter.check_and_consume(client_id)
