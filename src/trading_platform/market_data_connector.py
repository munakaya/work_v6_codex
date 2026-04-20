from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from http import HTTPStatus
import json
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .market_data_freshness import choose_freshness_observed_at
from .rate_limit import ExponentialBackoffPolicy, RateLimitPolicy, TokenBucketRateLimiter


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _iso_from_epoch_ms(value: object) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        timestamp_ms = int(str(value))
    except ValueError:
        return None
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).isoformat().replace(
        "+00:00", "Z"
    )


def _number_text(value: object) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not decimal.is_finite():
        return None
    normalized = format(decimal.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


@dataclass(frozen=True)
class MarketDataError(Exception):
    status: HTTPStatus
    code: str
    message: str


class PublicMarketDataConnector:
    def __init__(
        self,
        *,
        timeout_ms: int,
        stale_threshold_ms: int,
        orderbook_depth_levels: int = 5,
        retry_count: int,
        retry_backoff: ExponentialBackoffPolicy,
        rate_limit_policies: dict[str, RateLimitPolicy] | None,
        upbit_base_url: str,
        bithumb_base_url: str,
        coinone_base_url: str,
    ) -> None:
        self.timeout_seconds = max(timeout_ms, 100) / 1000
        self.stale_threshold_ms = max(stale_threshold_ms, 0)
        self.orderbook_depth_levels = max(orderbook_depth_levels, 1)
        self.retry_count = max(retry_count, 0)
        self.retry_backoff = retry_backoff
        self.upbit_base_url = upbit_base_url.rstrip("/")
        self.bithumb_base_url = bithumb_base_url.rstrip("/")
        self.coinone_base_url = coinone_base_url.rstrip("/")
        self.rate_limit_policies = dict(rate_limit_policies or {})
        self._rate_limiters = {
            exchange: TokenBucketRateLimiter(policy)
            for exchange, policy in self.rate_limit_policies.items()
        }
        self._snapshot_lock = threading.Lock()
        self._latest_snapshots: dict[tuple[str, str], dict[str, object]] = {}

    def get_orderbook_top(self, *, exchange: str, market: str) -> dict[str, object]:
        normalized_exchange = exchange.strip().lower()
        normalized_market = market.strip().upper()
        if not normalized_exchange:
            raise MarketDataError(
                HTTPStatus.BAD_REQUEST,
                "INVALID_REQUEST",
                "exchange is required",
            )
        if not normalized_market:
            raise MarketDataError(
                HTTPStatus.BAD_REQUEST,
                "INVALID_REQUEST",
                "market is required",
            )

        if normalized_exchange == "upbit":
            snapshot = self._get_upbit_orderbook_top(normalized_market)
        elif normalized_exchange == "bithumb":
            snapshot = self._get_bithumb_orderbook_top(normalized_market)
        elif normalized_exchange == "coinone":
            snapshot = self._get_coinone_orderbook_top(normalized_market)
        elif normalized_exchange == "sample":
            snapshot = self._get_sample_orderbook_top(normalized_market)
        else:
            raise MarketDataError(
                HTTPStatus.BAD_REQUEST,
                "EXCHANGE_NOT_SUPPORTED",
                "exchange is not supported",
            )
        self.sync_cached_orderbook_top(snapshot=snapshot)
        return dict(snapshot)

    def get_cached_orderbook_top(self, *, exchange: str, market: str) -> dict[str, object] | None:
        normalized_exchange = exchange.strip().lower()
        normalized_market = market.strip().upper()
        if not normalized_exchange or not normalized_market:
            return None
        with self._snapshot_lock:
            snapshot = self._latest_snapshots.get((normalized_exchange, normalized_market))
            if snapshot is None:
                return None
            return dict(snapshot)

    def sync_cached_orderbook_top(self, *, snapshot: dict[str, object]) -> None:
        exchange = str(snapshot.get("exchange") or "").strip().lower()
        market = str(snapshot.get("market") or "").strip().upper()
        if not exchange or not market:
            return
        with self._snapshot_lock:
            self._latest_snapshots[(exchange, market)] = dict(snapshot)

    def _get_upbit_orderbook_top(self, market: str) -> dict[str, object]:
        url = "%s/v1/orderbook?%s" % (
            self.upbit_base_url,
            urlencode({"markets": market, "count": self.orderbook_depth_levels}),
        )
        payload = self._fetch_json(url, exchange="upbit")
        if not isinstance(payload, list) or not payload:
            raise MarketDataError(
                HTTPStatus.BAD_GATEWAY,
                "UPSTREAM_INVALID_RESPONSE",
                "upbit orderbook response is empty",
            )

        item = payload[0]
        if not isinstance(item, dict):
            raise MarketDataError(
                HTTPStatus.BAD_GATEWAY,
                "UPSTREAM_INVALID_RESPONSE",
                "upbit orderbook response has invalid shape",
            )

        units = item.get("orderbook_units")
        if not isinstance(units, list) or not units or not isinstance(units[0], dict):
            raise MarketDataError(
                HTTPStatus.BAD_GATEWAY,
                "UPSTREAM_INVALID_RESPONSE",
                "upbit orderbook response is missing orderbook_units",
            )
        asks = self._normalize_levels(
            list(units[: self.orderbook_depth_levels]),
            price_key="ask_price",
            quantity_key="ask_size",
        )
        bids = self._normalize_levels(
            list(units[: self.orderbook_depth_levels]),
            price_key="bid_price",
            quantity_key="bid_size",
        )
        return self._build_snapshot(
            exchange="upbit",
            market=str(item.get("market") or market),
            bids=bids,
            asks=asks,
            exchange_timestamp=_iso_from_epoch_ms(item.get("timestamp")),
            source_type="rest",
        )

    def _get_sample_orderbook_top(self, market: str) -> dict[str, object]:
        sample_quotes = {
            "KRW-BTC": {
                "bids": [
                    {"price": "101574000", "quantity": "0.00035401"},
                    {"price": "101573000", "quantity": "0.00125"},
                    {"price": "101572000", "quantity": "0.0025"},
                    {"price": "101571000", "quantity": "0.00375"},
                    {"price": "101570000", "quantity": "0.005"},
                ],
                "asks": [
                    {"price": "101598000", "quantity": "0.00623162"},
                    {"price": "101599000", "quantity": "0.0045"},
                    {"price": "101600000", "quantity": "0.003"},
                    {"price": "101601000", "quantity": "0.002"},
                    {"price": "101602000", "quantity": "0.0015"},
                ],
            },
            "KRW-ETH": {
                "bids": [
                    {"price": "4718000", "quantity": "0.1821"},
                    {"price": "4717000", "quantity": "0.25"},
                    {"price": "4716000", "quantity": "0.35"},
                    {"price": "4715000", "quantity": "0.45"},
                    {"price": "4714000", "quantity": "0.55"},
                ],
                "asks": [
                    {"price": "4719000", "quantity": "0.2334"},
                    {"price": "4720000", "quantity": "0.2"},
                    {"price": "4721000", "quantity": "0.18"},
                    {"price": "4722000", "quantity": "0.16"},
                    {"price": "4723000", "quantity": "0.14"},
                ],
            },
            "BTC-KRW": {
                "bids": [
                    {"price": "101574000", "quantity": "0.00035401"},
                    {"price": "101573000", "quantity": "0.00125"},
                    {"price": "101572000", "quantity": "0.0025"},
                    {"price": "101571000", "quantity": "0.00375"},
                    {"price": "101570000", "quantity": "0.005"},
                ],
                "asks": [
                    {"price": "101598000", "quantity": "0.00623162"},
                    {"price": "101599000", "quantity": "0.0045"},
                    {"price": "101600000", "quantity": "0.003"},
                    {"price": "101601000", "quantity": "0.002"},
                    {"price": "101602000", "quantity": "0.0015"},
                ],
            },
        }
        quote = sample_quotes.get(market)
        if quote is None:
            raise MarketDataError(
                HTTPStatus.NOT_FOUND,
                "MARKET_NOT_SUPPORTED",
                "sample market is not available",
            )
        exchange_timestamp = _iso_now()
        return self._build_snapshot(
            exchange="sample",
            market=market,
            bids=list(quote["bids"][: self.orderbook_depth_levels]),
            asks=list(quote["asks"][: self.orderbook_depth_levels]),
            exchange_timestamp=exchange_timestamp,
            source_type="sample",
        )

    def _get_bithumb_orderbook_top(self, market: str) -> dict[str, object]:
        url = "%s/v1/orderbook?%s" % (
            self.bithumb_base_url,
            urlencode({"markets": market}),
        )
        payload = self._fetch_json(url, exchange="bithumb")
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                error_name = str(error.get("name") or "").strip()
                error_message = str(
                    error.get("message") or "market not found on upstream exchange"
                ).strip()
                if error_name == "404" or error_message.lower() == "code not found":
                    raise MarketDataError(
                        HTTPStatus.NOT_FOUND,
                        "MARKET_NOT_FOUND",
                        error_message or "market not found on upstream exchange",
                    )
        if isinstance(payload, list) and not payload:
            raise MarketDataError(
                HTTPStatus.NOT_FOUND,
                "MARKET_NOT_FOUND",
                "market not found on upstream exchange",
            )
        if not isinstance(payload, list):
            raise MarketDataError(
                HTTPStatus.BAD_GATEWAY,
                "UPSTREAM_INVALID_RESPONSE",
                "bithumb orderbook response is empty",
            )
        item = payload[0]
        if not isinstance(item, dict):
            raise MarketDataError(
                HTTPStatus.BAD_GATEWAY,
                "UPSTREAM_INVALID_RESPONSE",
                "bithumb orderbook response has invalid shape",
            )
        units = item.get("orderbook_units")
        if not isinstance(units, list) or not units or not isinstance(units[0], dict):
            raise MarketDataError(
                HTTPStatus.BAD_GATEWAY,
                "UPSTREAM_INVALID_RESPONSE",
                "bithumb orderbook response is missing orderbook_units",
            )
        asks = self._normalize_levels(
            list(units[: self.orderbook_depth_levels]),
            price_key="ask_price",
            quantity_key="ask_size",
        )
        bids = self._normalize_levels(
            list(units[: self.orderbook_depth_levels]),
            price_key="bid_price",
            quantity_key="bid_size",
        )
        return self._build_snapshot(
            exchange="bithumb",
            market=str(item.get("market") or market),
            bids=bids,
            asks=asks,
            exchange_timestamp=_iso_from_epoch_ms(item.get("timestamp")),
            source_type="rest",
        )

    def _get_coinone_orderbook_top(self, market: str) -> dict[str, object]:
        quote_currency, target_currency = self._coinone_market_parts(market)
        url = "%s/public/v2/orderbook/%s/%s?%s" % (
            self.coinone_base_url,
            quote_currency,
            target_currency,
            urlencode({"size": self._coinone_request_depth_levels()}),
        )
        payload = self._fetch_json(url, exchange="coinone")
        if not isinstance(payload, dict):
            raise MarketDataError(
                HTTPStatus.BAD_GATEWAY,
                "UPSTREAM_INVALID_RESPONSE",
                "coinone orderbook response has invalid shape",
            )
        if str(payload.get("result") or "").strip().lower() != "success":
            error_code = str(payload.get("error_code") or "").strip()
            error_message = str(
                payload.get("error_msg") or "coinone orderbook request failed"
            ).strip()
            if error_code in {"108", "107"}:
                raise MarketDataError(
                    HTTPStatus.NOT_FOUND,
                    "MARKET_NOT_FOUND",
                    error_message or "market not found on upstream exchange",
                )
            raise MarketDataError(
                HTTPStatus.BAD_GATEWAY,
                "UPSTREAM_HTTP_ERROR",
                error_message or "coinone orderbook request failed",
            )
        bids = payload.get("bids")
        asks = payload.get("asks")
        if (
            not isinstance(bids, list)
            or not bids
            or not isinstance(bids[0], dict)
            or not isinstance(asks, list)
            or not asks
            or not isinstance(asks[0], dict)
        ):
            raise MarketDataError(
                HTTPStatus.BAD_GATEWAY,
                "UPSTREAM_INVALID_RESPONSE",
                "coinone orderbook response is missing bids or asks",
            )
        normalized_bids = self._normalize_levels(
            list(bids[: self.orderbook_depth_levels]),
            price_key="price",
            quantity_key="qty",
        )
        normalized_asks = self._normalize_levels(
            list(asks[: self.orderbook_depth_levels]),
            price_key="price",
            quantity_key="qty",
        )
        return self._build_snapshot(
            exchange="coinone",
            market=f"{quote_currency}-{target_currency}",
            bids=normalized_bids,
            asks=normalized_asks,
            exchange_timestamp=_iso_from_epoch_ms(payload.get("timestamp")),
            source_type="rest",
        )

    def _coinone_market_parts(self, market: str) -> tuple[str, str]:
        parts = [part.strip().upper() for part in market.split("-") if part.strip()]
        if len(parts) != 2:
            raise MarketDataError(
                HTTPStatus.BAD_REQUEST,
                "INVALID_REQUEST",
                "coinone market must be in QUOTE-BASE format",
            )
        return parts[0], parts[1]


    def _coinone_request_depth_levels(self) -> int:
        for supported_depth in (5, 10, 15):
            if self.orderbook_depth_levels <= supported_depth:
                return supported_depth
        return 15

    def _build_snapshot(
        self,
        *,
        exchange: str,
        market: str,
        bids: list[dict[str, str]],
        asks: list[dict[str, str]],
        exchange_timestamp: str | None,
        source_type: str,
    ) -> dict[str, object]:
        received_at = _iso_now()
        if not bids or not asks or not exchange_timestamp:
            raise MarketDataError(
                HTTPStatus.BAD_GATEWAY,
                "UPSTREAM_INVALID_RESPONSE",
                "market data payload is missing required fields",
            )
        best_bid = bids[0]
        best_ask = asks[0]
        exchange_dt = datetime.fromisoformat(exchange_timestamp.replace("Z", "+00:00"))
        received_dt = datetime.fromisoformat(received_at.replace("Z", "+00:00"))
        age_ms = max(int((received_dt - exchange_dt).total_seconds() * 1000), 0)
        snapshot = {
            "exchange": exchange,
            "market": market,
            "best_bid": best_bid["price"],
            "best_ask": best_ask["price"],
            "bid_volume": best_bid["quantity"],
            "ask_volume": best_ask["quantity"],
            "bids": bids,
            "asks": asks,
            "depth_level_count": min(len(bids), len(asks)),
            "exchange_timestamp": exchange_timestamp,
            "received_at": received_at,
            "exchange_age_ms": age_ms,
            "stale": age_ms > self.stale_threshold_ms,
            "source_type": source_type,
        }
        freshness_observed_at, freshness_observed_at_source = choose_freshness_observed_at(snapshot)
        snapshot["freshness_observed_at"] = freshness_observed_at
        snapshot["freshness_observed_at_source"] = freshness_observed_at_source
        return snapshot

    def _normalize_levels(
        self,
        raw_levels: list[object],
        *,
        price_key: str,
        quantity_key: str,
    ) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        for raw_level in raw_levels:
            if not isinstance(raw_level, dict):
                continue
            price_text = _number_text(raw_level.get(price_key))
            quantity_text = _number_text(raw_level.get(quantity_key))
            if not price_text or not quantity_text:
                continue
            normalized.append({"price": price_text, "quantity": quantity_text})
        return normalized

    def describe_rate_limits(self) -> dict[str, object]:
        items = [
            policy.as_dict()
            for _exchange, policy in sorted(
                self.rate_limit_policies.items(), key=lambda item: item[0]
            )
        ]
        return {
            "items": items,
            "count": len(items),
            "retry_count": self.retry_count,
            "retry_backoff": self.retry_backoff.as_dict(),
            "orderbook_depth_levels": self.orderbook_depth_levels,
        }

    def _fetch_json(self, url: str, *, exchange: str) -> object:
        limiter = self._rate_limiters.get(exchange)
        if limiter is not None:
            limiter.acquire()
        attempt = 0
        while True:
            try:
                return self._fetch_json_once(url)
            except MarketDataError as exc:
                if not self._should_retry(exc=exc, attempt=attempt):
                    raise
                time.sleep(self.retry_backoff.delay_seconds(attempt))
                attempt += 1

    def _fetch_json_once(self, url: str) -> object:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "work_v6_codex-control-plane/0.1",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            error_message = self._http_error_message(exc)
            if exc.code == 404:
                raise MarketDataError(
                    HTTPStatus.NOT_FOUND,
                    "MARKET_NOT_FOUND",
                    error_message or "market not found on upstream exchange",
                ) from exc
            if exc.code == 429:
                raise MarketDataError(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "UPSTREAM_RATE_LIMITED",
                    error_message or "upstream market data provider rate limited",
                ) from exc
            raise MarketDataError(
                HTTPStatus.BAD_GATEWAY,
                "UPSTREAM_HTTP_ERROR",
                error_message or f"upstream http error: {exc.code}",
            ) from exc
        except URLError as exc:
            raise MarketDataError(
                HTTPStatus.BAD_GATEWAY,
                "UPSTREAM_NETWORK_ERROR",
                "failed to reach upstream market data provider",
            ) from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MarketDataError(
                HTTPStatus.BAD_GATEWAY,
                "UPSTREAM_INVALID_RESPONSE",
                "upstream response is not valid json",
            ) from exc

    def _should_retry(self, *, exc: MarketDataError, attempt: int) -> bool:
        if attempt >= self.retry_count:
            return False
        return exc.code in {
            "UPSTREAM_RATE_LIMITED",
            "UPSTREAM_HTTP_ERROR",
            "UPSTREAM_NETWORK_ERROR",
        }

    def _http_error_message(self, exc: HTTPError) -> str | None:
        try:
            raw = exc.read().decode("utf-8")
        except OSError:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        error = payload.get("error")
        if not isinstance(error, dict):
            return None
        message = error.get("message")
        if not isinstance(message, str) or not message:
            return None
        return message
