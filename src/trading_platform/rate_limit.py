from __future__ import annotations

from dataclasses import dataclass
import time


@dataclass(frozen=True)
class RateLimitPolicy:
    name: str
    rate_per_sec: float
    burst: int

    @property
    def enabled(self) -> bool:
        return self.rate_per_sec > 0 and self.burst > 0

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "rate_per_sec": self.rate_per_sec,
            "burst": self.burst,
            "enabled": self.enabled,
        }


@dataclass(frozen=True)
class ExponentialBackoffPolicy:
    initial_delay_ms: int
    max_delay_ms: int

    def delay_seconds(self, attempt: int) -> float:
        normalized_attempt = max(attempt, 0)
        bounded_ms = min(
            max(self.initial_delay_ms, 0) * (2**normalized_attempt),
            max(self.max_delay_ms, 0),
        )
        return bounded_ms / 1000.0

    def as_dict(self) -> dict[str, object]:
        return {
            "initial_delay_ms": self.initial_delay_ms,
            "max_delay_ms": self.max_delay_ms,
        }


class TokenBucketRateLimiter:
    def __init__(
        self,
        policy: RateLimitPolicy,
        *,
        now_fn=None,
        sleep_fn=None,
    ) -> None:
        self.policy = policy
        self._now = now_fn or time.monotonic
        self._sleep = sleep_fn or time.sleep
        self._tokens = float(max(policy.burst, 0))
        self._updated_at = self._now()

    def acquire(self) -> float:
        if not self.policy.enabled:
            return 0.0
        waited = 0.0
        while True:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return waited
            missing_tokens = 1.0 - self._tokens
            sleep_seconds = missing_tokens / self.policy.rate_per_sec
            if sleep_seconds > 0:
                self._sleep(sleep_seconds)
                waited += sleep_seconds

    def _refill(self) -> None:
        now = self._now()
        elapsed = max(now - self._updated_at, 0.0)
        self._updated_at = now
        self._tokens = min(
            float(self.policy.burst),
            self._tokens + elapsed * self.policy.rate_per_sec,
        )
