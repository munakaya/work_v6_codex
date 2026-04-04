from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from http import HTTPStatus
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


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
        upbit_base_url: str,
        bithumb_base_url: str,
        coinone_base_url: str,
    ) -> None:
        self.timeout_seconds = max(timeout_ms, 100) / 1000
        self.stale_threshold_ms = max(stale_threshold_ms, 0)
        self.upbit_base_url = upbit_base_url.rstrip("/")
        self.bithumb_base_url = bithumb_base_url.rstrip("/")
        self.coinone_base_url = coinone_base_url.rstrip("/")

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
            return self._get_upbit_orderbook_top(normalized_market)
        if normalized_exchange == "bithumb":
            return self._get_bithumb_orderbook_top(normalized_market)
        if normalized_exchange == "coinone":
            return self._get_coinone_orderbook_top(normalized_market)
        if normalized_exchange == "sample":
            return self._get_sample_orderbook_top(normalized_market)
        raise MarketDataError(
            HTTPStatus.BAD_REQUEST,
            "EXCHANGE_NOT_SUPPORTED",
            "exchange is not supported",
        )

    def _get_upbit_orderbook_top(self, market: str) -> dict[str, object]:
        url = "%s/v1/orderbook?%s" % (
            self.upbit_base_url,
            urlencode({"markets": market, "count": 1}),
        )
        payload = self._fetch_json(url)
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
        top = units[0]
        return self._build_snapshot(
            exchange="upbit",
            market=str(item.get("market") or market),
            best_bid=top.get("bid_price"),
            best_ask=top.get("ask_price"),
            bid_volume=top.get("bid_size"),
            ask_volume=top.get("ask_size"),
            exchange_timestamp=_iso_from_epoch_ms(item.get("timestamp")),
            source_type="rest",
        )

    def _get_sample_orderbook_top(self, market: str) -> dict[str, object]:
        sample_quotes = {
            "KRW-BTC": ("101574000", "101598000", "0.00035401", "0.00623162"),
            "KRW-ETH": ("4718000", "4719000", "0.1821", "0.2334"),
            "BTC-KRW": ("101574000", "101598000", "0.00035401", "0.00623162"),
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
            best_bid=quote[0],
            best_ask=quote[1],
            bid_volume=quote[2],
            ask_volume=quote[3],
            exchange_timestamp=exchange_timestamp,
            source_type="sample",
        )

    def _get_bithumb_orderbook_top(self, market: str) -> dict[str, object]:
        url = "%s/v1/orderbook?%s" % (
            self.bithumb_base_url,
            urlencode({"markets": market}),
        )
        payload = self._fetch_json(url)
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
        top = units[0]
        return self._build_snapshot(
            exchange="bithumb",
            market=str(item.get("market") or market),
            best_bid=top.get("bid_price"),
            best_ask=top.get("ask_price"),
            bid_volume=top.get("bid_size"),
            ask_volume=top.get("ask_size"),
            exchange_timestamp=_iso_from_epoch_ms(item.get("timestamp")),
            source_type="rest",
        )

    def _get_coinone_orderbook_top(self, market: str) -> dict[str, object]:
        quote_currency, target_currency = self._coinone_market_parts(market)
        url = "%s/public/v2/orderbook/%s/%s?%s" % (
            self.coinone_base_url,
            quote_currency,
            target_currency,
            urlencode({"size": 5}),
        )
        payload = self._fetch_json(url)
        if not isinstance(payload, dict):
            raise MarketDataError(
                HTTPStatus.BAD_GATEWAY,
                "UPSTREAM_INVALID_RESPONSE",
                "coinone orderbook response has invalid shape",
            )
        if str(payload.get("result") or "").strip().lower() != "success":
            error_code = str(payload.get("error_code") or "").strip()
            error_message = str(payload.get("error_msg") or "coinone orderbook request failed").strip()
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
        best_bid = bids[0]
        best_ask = asks[0]
        return self._build_snapshot(
            exchange="coinone",
            market=f"{quote_currency}-{target_currency}",
            best_bid=best_bid.get("price"),
            best_ask=best_ask.get("price"),
            bid_volume=best_bid.get("qty"),
            ask_volume=best_ask.get("qty"),
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

    def _build_snapshot(
        self,
        *,
        exchange: str,
        market: str,
        best_bid: object,
        best_ask: object,
        bid_volume: object,
        ask_volume: object,
        exchange_timestamp: str | None,
        source_type: str,
    ) -> dict[str, object]:
        received_at = _iso_now()
        bid_text = _number_text(best_bid)
        ask_text = _number_text(best_ask)
        bid_volume_text = _number_text(bid_volume)
        ask_volume_text = _number_text(ask_volume)
        if not all((bid_text, ask_text, bid_volume_text, ask_volume_text, exchange_timestamp)):
            raise MarketDataError(
                HTTPStatus.BAD_GATEWAY,
                "UPSTREAM_INVALID_RESPONSE",
                "market data payload is missing required fields",
            )
        exchange_dt = datetime.fromisoformat(exchange_timestamp.replace("Z", "+00:00"))
        received_dt = datetime.fromisoformat(received_at.replace("Z", "+00:00"))
        age_ms = max(int((received_dt - exchange_dt).total_seconds() * 1000), 0)
        return {
            "exchange": exchange,
            "market": market,
            "best_bid": bid_text,
            "best_ask": ask_text,
            "bid_volume": bid_volume_text,
            "ask_volume": ask_volume_text,
            "exchange_timestamp": exchange_timestamp,
            "received_at": received_at,
            "exchange_age_ms": age_ms,
            "stale": age_ms > self.stale_threshold_ms,
            "source_type": source_type,
        }

    def _fetch_json(self, url: str) -> object:
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
