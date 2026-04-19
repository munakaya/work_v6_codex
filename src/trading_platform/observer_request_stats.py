from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable


def _round_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 3)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile
    lower_index = int(rank)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    weight = rank - lower_index
    lower = ordered[lower_index]
    upper = ordered[upper_index]
    return lower + (upper - lower) * weight


def _latency_summary(values: Iterable[float]) -> dict[str, float | int | None]:
    samples = [float(value) for value in values]
    if not samples:
        return {
            "count": 0,
            "avg": None,
            "min": None,
            "max": None,
            "p50": None,
            "p95": None,
            "p99": None,
            "over_100ms": 0,
            "over_500ms": 0,
            "over_1000ms": 0,
        }
    average = sum(samples) / len(samples)
    return {
        "count": len(samples),
        "avg": _round_or_none(average),
        "min": _round_or_none(min(samples)),
        "max": _round_or_none(max(samples)),
        "p50": _round_or_none(_percentile(samples, 0.50)),
        "p95": _round_or_none(_percentile(samples, 0.95)),
        "p99": _round_or_none(_percentile(samples, 0.99)),
        "over_100ms": sum(1 for sample in samples if sample > 100.0),
        "over_500ms": sum(1 for sample in samples if sample > 500.0),
        "over_1000ms": sum(1 for sample in samples if sample > 1000.0),
    }


@dataclass
class ExchangeRequestStats:
    attempt_count: int = 0
    success_count: int = 0
    error_count: int = 0
    latency_all_ms: list[float] = field(default_factory=list)
    latency_success_ms: list[float] = field(default_factory=list)
    latency_error_ms: list[float] = field(default_factory=list)
    error_code_counts: Counter[str] = field(default_factory=Counter)

    def record_success(self, *, latency_ms: float) -> None:
        self.attempt_count += 1
        self.success_count += 1
        self.latency_all_ms.append(latency_ms)
        self.latency_success_ms.append(latency_ms)

    def record_error(self, *, code: str, latency_ms: float) -> None:
        self.attempt_count += 1
        self.error_count += 1
        self.latency_all_ms.append(latency_ms)
        self.latency_error_ms.append(latency_ms)
        self.error_code_counts[code] += 1

    def as_dict(self) -> dict[str, object]:
        success_rate = (
            float(self.success_count / self.attempt_count)
            if self.attempt_count > 0
            else 0.0
        )
        error_rate = (
            float(self.error_count / self.attempt_count)
            if self.attempt_count > 0
            else 0.0
        )
        return {
            "attempt_count": self.attempt_count,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "success_rate": round(success_rate, 6),
            "error_rate": round(error_rate, 6),
            "latency_ms": _latency_summary(self.latency_all_ms),
            "success_latency_ms": _latency_summary(self.latency_success_ms),
            "error_latency_ms": _latency_summary(self.latency_error_ms),
            "error_code_breakdown": {
                code: count for code, count in sorted(self.error_code_counts.items())
            },
        }


@dataclass
class RequestStatsTracker:
    by_exchange: dict[str, ExchangeRequestStats] = field(default_factory=dict)

    def _get(self, exchange: str) -> ExchangeRequestStats:
        normalized = exchange.strip().lower()
        stats = self.by_exchange.get(normalized)
        if stats is None:
            stats = ExchangeRequestStats()
            self.by_exchange[normalized] = stats
        return stats

    def record_success(self, *, exchange: str, latency_ms: float) -> None:
        self._get(exchange).record_success(latency_ms=latency_ms)

    def record_error(self, *, exchange: str, code: str, latency_ms: float) -> None:
        self._get(exchange).record_error(code=code, latency_ms=latency_ms)

    def snapshot(self) -> dict[str, object]:
        aggregate = ExchangeRequestStats()
        for stats in self.by_exchange.values():
            aggregate.attempt_count += stats.attempt_count
            aggregate.success_count += stats.success_count
            aggregate.error_count += stats.error_count
            aggregate.latency_all_ms.extend(stats.latency_all_ms)
            aggregate.latency_success_ms.extend(stats.latency_success_ms)
            aggregate.latency_error_ms.extend(stats.latency_error_ms)
            aggregate.error_code_counts.update(stats.error_code_counts)
        return {
            "total": aggregate.as_dict(),
            "by_exchange": {
                exchange: stats.as_dict()
                for exchange, stats in sorted(self.by_exchange.items())
            },
        }
