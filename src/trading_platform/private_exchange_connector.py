from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Protocol
from urllib import error, request

from .config import AppConfig
from .strategy.exchange_auth import (
    build_bearer_authorization,
    build_coinone_private_headers,
    build_query_string,
    create_bithumb_jwt_token,
    create_upbit_jwt_token,
)
from .strategy.exchange_key_loader import (
    ExchangeTradingCredentials,
    ExchangeTradingCredentialsStatus,
    inspect_exchange_trading_credentials_from_config,
    load_exchange_trading_credentials_from_config,
)


DEFAULT_TIMEOUT_MS = 3000


@dataclass(frozen=True)
class PrivateExchangeResult:
    outcome: str
    reason: str | None = None
    data: object | None = None
    error_code: str | None = None
    retryable: bool | None = None
    http_status: int | None = None
    raw_payload: object | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "outcome": self.outcome,
            "reason": self.reason,
            "data": self.data,
            "error_code": self.error_code,
            "retryable": self.retryable,
            "http_status": self.http_status,
            "raw_payload": self.raw_payload,
        }


@dataclass(frozen=True)
class PrivateExchangeConnectorInfo:
    exchange: str
    name: str
    configured: bool
    ready: bool
    state: str
    credential_source_path: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "exchange": self.exchange,
            "name": self.name,
            "configured": self.configured,
            "ready": self.ready,
            "state": self.state,
            "credential_source_path": self.credential_source_path,
        }


@dataclass(frozen=True)
class PrivateExchangeWebsocketMonitorInfo:
    exchange: str
    configured: bool
    auth_ready: bool
    connection_state: str
    disconnect_count: int
    last_connected_at: str | None
    last_failed_at: str | None
    last_close_code: int | None
    last_close_category: str | None
    endpoint: str | None
    ping_interval_seconds: int | None
    idle_timeout_seconds: int | None
    connection_limit: int | None

    def as_dict(self) -> dict[str, object]:
        return {
            "exchange": self.exchange,
            "configured": self.configured,
            "auth_ready": self.auth_ready,
            "connection_state": self.connection_state,
            "disconnect_count": self.disconnect_count,
            "last_connected_at": self.last_connected_at,
            "last_failed_at": self.last_failed_at,
            "last_close_code": self.last_close_code,
            "last_close_category": self.last_close_category,
            "endpoint": self.endpoint,
            "ping_interval_seconds": self.ping_interval_seconds,
            "idle_timeout_seconds": self.idle_timeout_seconds,
            "connection_limit": self.connection_limit,
        }


@dataclass(frozen=True)
class ExchangeMarket:
    canonical_symbol: str
    exchange_symbol: str
    quote_currency: str
    target_currency: str


@dataclass(frozen=True)
class PrivateExchangeApiError(Exception):
    exchange: str
    operation_name: str
    internal_code: str
    reason: str
    retryable: bool
    http_status: int | None = None
    raw_payload: object | None = None


class PrivateExchangeConnectorProtocol(Protocol):
    exchange: str
    name: str

    @property
    def info(self) -> PrivateExchangeConnectorInfo: ...

    @property
    def private_ws_monitor(self) -> PrivateExchangeWebsocketMonitorInfo: ...

    def get_balances(self) -> PrivateExchangeResult: ...

    def place_order(self, request_payload: dict[str, object]) -> PrivateExchangeResult: ...

    def get_order_status(
        self, *, exchange_order_id: str, market: str
    ) -> PrivateExchangeResult: ...

    def cancel_order(
        self, *, exchange_order_id: str, market: str
    ) -> PrivateExchangeResult: ...

    def list_open_orders(self, *, market: str | None = None) -> PrivateExchangeResult: ...


class MissingCredentialsPrivateExchangeConnector:
    def __init__(self, *, exchange: str, status: ExchangeTradingCredentialsStatus) -> None:
        self.exchange = exchange
        self.name = f"{exchange}:missing_credentials"
        self._status = status

    @property
    def info(self) -> PrivateExchangeConnectorInfo:
        return PrivateExchangeConnectorInfo(
            exchange=self.exchange,
            name=self.name,
            configured=self._status.configured,
            ready=False,
            state=self._status.state,
            credential_source_path=(
                None if self._status.source_path is None else str(self._status.source_path)
            ),
        )

    @property
    def private_ws_monitor(self) -> PrivateExchangeWebsocketMonitorInfo:
        return build_private_exchange_ws_monitor(
            exchange=self.exchange,
            configured=self._status.configured,
            auth_ready=False,
        )

    def get_balances(self) -> PrivateExchangeResult:
        return self._unavailable_result()

    def place_order(self, request_payload: dict[str, object]) -> PrivateExchangeResult:
        return self._unavailable_result()

    def get_order_status(
        self, *, exchange_order_id: str, market: str
    ) -> PrivateExchangeResult:
        return self._unavailable_result()

    def cancel_order(
        self, *, exchange_order_id: str, market: str
    ) -> PrivateExchangeResult:
        return self._unavailable_result()

    def list_open_orders(self, *, market: str | None = None) -> PrivateExchangeResult:
        return self._unavailable_result()

    def _unavailable_result(self) -> PrivateExchangeResult:
        return PrivateExchangeResult(
            outcome="unavailable",
            reason=(
                "trading credentials are missing or invalid "
                f"(exchange={self.exchange}, state={self._status.state})"
            ),
            error_code="AUTH_CONFIG_MISSING",
            retryable=False,
        )


class RestPrivateExchangeConnector:
    def __init__(
        self,
        *,
        exchange: str,
        credentials: ExchangeTradingCredentials,
        base_url: str,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> None:
        self.exchange = exchange
        self.name = f"{exchange}:private_rest"
        self._credentials = credentials
        self._base_url = base_url.rstrip("/")
        self._timeout_ms = max(timeout_ms, 250)

    @property
    def info(self) -> PrivateExchangeConnectorInfo:
        return PrivateExchangeConnectorInfo(
            exchange=self.exchange,
            name=self.name,
            configured=True,
            ready=True,
            state="ready_rest",
            credential_source_path=str(self._credentials.source_path),
        )

    @property
    def private_ws_monitor(self) -> PrivateExchangeWebsocketMonitorInfo:
        return build_private_exchange_ws_monitor(
            exchange=self.exchange,
            configured=True,
            auth_ready=True,
        )

    def get_balances(self) -> PrivateExchangeResult:
        raise NotImplementedError

    def place_order(self, request_payload: dict[str, object]) -> PrivateExchangeResult:
        raise NotImplementedError

    def get_order_status(
        self, *, exchange_order_id: str, market: str
    ) -> PrivateExchangeResult:
        raise NotImplementedError

    def cancel_order(
        self, *, exchange_order_id: str, market: str
    ) -> PrivateExchangeResult:
        raise NotImplementedError

    def list_open_orders(self, *, market: str | None = None) -> PrivateExchangeResult:
        raise NotImplementedError

    def _ok(self, data: object, *, raw_payload: object | None = None) -> PrivateExchangeResult:
        return PrivateExchangeResult(
            outcome="ok",
            data=data,
            raw_payload=raw_payload,
        )

    def _handle_api_error(self, exc: PrivateExchangeApiError) -> PrivateExchangeResult:
        return PrivateExchangeResult(
            outcome="error",
            reason=exc.reason,
            error_code=exc.internal_code,
            retryable=exc.retryable,
            http_status=exc.http_status,
            raw_payload=exc.raw_payload,
        )

    def _request(
        self,
        *,
        operation_name: str,
        method: str,
        path: str,
        headers: dict[str, str],
        query_pairs: tuple[tuple[str, str], ...] = (),
        json_body: dict[str, object] | None = None,
    ) -> object:
        url = self._base_url + path
        if query_pairs:
            url = f"{url}?{build_query_string(query_pairs)}"
        data = None
        request_headers = {"Accept": "application/json", **headers}
        if json_body is not None:
            data = json.dumps(json_body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        req = request.Request(url, method=method, data=data, headers=request_headers)
        try:
            with request.urlopen(req, timeout=self._timeout_ms / 1000.0) as response:
                raw_text = response.read().decode("utf-8")
                payload = _decode_json_payload(raw_text)
                return self._unwrap_success_payload(
                    operation_name=operation_name,
                    payload=payload,
                    http_status=int(getattr(response, "status", 200)),
                )
        except error.HTTPError as exc:
            raw_text = exc.read().decode("utf-8", errors="replace")
            payload = _decode_json_payload(raw_text)
            raise _map_error(
                exchange=self.exchange,
                operation_name=operation_name,
                http_status=exc.code,
                payload=payload,
            ) from exc
        except error.URLError as exc:
            raise PrivateExchangeApiError(
                exchange=self.exchange,
                operation_name=operation_name,
                internal_code="NETWORK_ERROR",
                reason=f"{self.exchange} request failed: {exc.reason}",
                retryable=True,
            ) from exc
        except TimeoutError as exc:
            raise PrivateExchangeApiError(
                exchange=self.exchange,
                operation_name=operation_name,
                internal_code="NETWORK_ERROR",
                reason=f"{self.exchange} request timed out",
                retryable=True,
            ) from exc

    def _unwrap_success_payload(
        self,
        *,
        operation_name: str,
        payload: object,
        http_status: int,
    ) -> object:
        if self.exchange != "coinone":
            return payload
        if isinstance(payload, dict):
            result = str(payload.get("result") or "").strip().lower()
            error_code = str(payload.get("error_code") or payload.get("errorCode") or "0")
            if result == "error" or (error_code and error_code != "0"):
                raise _map_error(
                    exchange=self.exchange,
                    operation_name=operation_name,
                    http_status=http_status,
                    payload=payload,
                )
        return payload


class UpbitPrivateExchangeConnector(RestPrivateExchangeConnector):
    def get_balances(self) -> PrivateExchangeResult:
        try:
            payload = self._request(
                operation_name="get_balances",
                method="GET",
                path="/v1/accounts",
                headers={
                    "Authorization": build_bearer_authorization(
                        create_upbit_jwt_token(
                            self._credentials.access_key,
                            self._credentials.secret_key,
                        )
                    )
                },
            )
            items = payload if isinstance(payload, list) else []
            return self._ok(
                {
                    "items": [_normalize_upbit_balance(item) for item in items if isinstance(item, dict)],
                    "count": len(items),
                },
                raw_payload=payload,
            )
        except PrivateExchangeApiError as exc:
            return self._handle_api_error(exc)

    def place_order(self, request_payload: dict[str, object]) -> PrivateExchangeResult:
        try:
            body = _build_upbit_order_payload(request_payload)
            query_pairs = _query_pairs_from_payload(body)
            payload = self._request(
                operation_name="place_order",
                method="POST",
                path="/v1/orders",
                headers={
                    "Authorization": build_bearer_authorization(
                        create_upbit_jwt_token(
                            self._credentials.access_key,
                            self._credentials.secret_key,
                            query_string=(build_query_string(query_pairs) if query_pairs else None),
                        )
                    )
                },
                json_body=body,
            )
            return self._ok(_normalize_upbit_order(payload), raw_payload=payload)
        except PrivateExchangeApiError as exc:
            return self._handle_api_error(exc)

    def get_order_status(
        self, *, exchange_order_id: str, market: str
    ) -> PrivateExchangeResult:
        try:
            query_pairs = (("uuid", exchange_order_id),)
            payload = self._request(
                operation_name="get_order_status",
                method="GET",
                path="/v1/order",
                headers={
                    "Authorization": build_bearer_authorization(
                        create_upbit_jwt_token(
                            self._credentials.access_key,
                            self._credentials.secret_key,
                            query_string=build_query_string(query_pairs),
                        )
                    )
                },
                query_pairs=query_pairs,
            )
            return self._ok(_normalize_upbit_order(payload), raw_payload=payload)
        except PrivateExchangeApiError as exc:
            return self._handle_api_error(exc)

    def cancel_order(
        self, *, exchange_order_id: str, market: str
    ) -> PrivateExchangeResult:
        try:
            exchange_market = _normalize_market(self.exchange, market)
            query_pairs = (("uuid", exchange_order_id),)
            payload = self._request(
                operation_name="cancel_order",
                method="DELETE",
                path="/v1/order",
                headers={
                    "Authorization": build_bearer_authorization(
                        create_upbit_jwt_token(
                            self._credentials.access_key,
                            self._credentials.secret_key,
                            query_string=build_query_string(query_pairs),
                        )
                    )
                },
                query_pairs=query_pairs,
            )
            normalized = _normalize_upbit_order(payload)
            normalized = _apply_order_market_fallback(
                normalized,
                exchange_market=exchange_market,
                exchange_order_id=exchange_order_id,
            )
            return self._ok(normalized, raw_payload=payload)
        except PrivateExchangeApiError as exc:
            return self._handle_api_error(exc)

    def list_open_orders(self, *, market: str | None = None) -> PrivateExchangeResult:
        try:
            query_pairs = (("market", _normalize_market(self.exchange, market).exchange_symbol),) if market else ()
            payload = self._request(
                operation_name="list_open_orders",
                method="GET",
                path="/v1/orders/open",
                headers={
                    "Authorization": build_bearer_authorization(
                        create_upbit_jwt_token(
                            self._credentials.access_key,
                            self._credentials.secret_key,
                            query_string=(build_query_string(query_pairs) if query_pairs else None),
                        )
                    )
                },
                query_pairs=query_pairs,
            )
            items = payload if isinstance(payload, list) else []
            normalized = [_normalize_upbit_order(item) for item in items if isinstance(item, dict)]
            return self._ok({"items": normalized, "count": len(normalized)}, raw_payload=payload)
        except PrivateExchangeApiError as exc:
            return self._handle_api_error(exc)


class BithumbPrivateExchangeConnector(RestPrivateExchangeConnector):
    def get_balances(self) -> PrivateExchangeResult:
        try:
            payload = self._request(
                operation_name="get_balances",
                method="GET",
                path="/v1/accounts",
                headers={
                    "Authorization": build_bearer_authorization(
                        create_bithumb_jwt_token(
                            self._credentials.access_key,
                            self._credentials.secret_key,
                        )
                    )
                },
            )
            items = payload if isinstance(payload, list) else []
            normalized = [_normalize_bithumb_balance(item) for item in items if isinstance(item, dict)]
            return self._ok({"items": normalized, "count": len(normalized)}, raw_payload=payload)
        except PrivateExchangeApiError as exc:
            return self._handle_api_error(exc)

    def place_order(self, request_payload: dict[str, object]) -> PrivateExchangeResult:
        try:
            body = _build_bithumb_order_payload(request_payload)
            query_pairs = _query_pairs_from_payload(body)
            payload = self._request(
                operation_name="place_order",
                method="POST",
                path="/v1/orders",
                headers={
                    "Authorization": build_bearer_authorization(
                        create_bithumb_jwt_token(
                            self._credentials.access_key,
                            self._credentials.secret_key,
                            query_string=(build_query_string(query_pairs) if query_pairs else None),
                        )
                    )
                },
                json_body=body,
            )
            return self._ok(_normalize_bithumb_order(payload), raw_payload=payload)
        except PrivateExchangeApiError as exc:
            return self._handle_api_error(exc)

    def get_order_status(
        self, *, exchange_order_id: str, market: str
    ) -> PrivateExchangeResult:
        try:
            query_pairs = (("uuid", exchange_order_id),)
            payload = self._request(
                operation_name="get_order_status",
                method="GET",
                path="/v1/order",
                headers={
                    "Authorization": build_bearer_authorization(
                        create_bithumb_jwt_token(
                            self._credentials.access_key,
                            self._credentials.secret_key,
                            query_string=build_query_string(query_pairs),
                        )
                    )
                },
                query_pairs=query_pairs,
            )
            return self._ok(_normalize_bithumb_order(payload), raw_payload=payload)
        except PrivateExchangeApiError as exc:
            return self._handle_api_error(exc)

    def cancel_order(
        self, *, exchange_order_id: str, market: str
    ) -> PrivateExchangeResult:
        try:
            exchange_market = _normalize_market(self.exchange, market)
            query_pairs = (("uuid", exchange_order_id),)
            payload = self._request(
                operation_name="cancel_order",
                method="DELETE",
                path="/v1/order",
                headers={
                    "Authorization": build_bearer_authorization(
                        create_bithumb_jwt_token(
                            self._credentials.access_key,
                            self._credentials.secret_key,
                            query_string=build_query_string(query_pairs),
                        )
                    )
                },
                query_pairs=query_pairs,
            )
            normalized = _normalize_bithumb_order(payload)
            normalized = _apply_order_market_fallback(
                normalized,
                exchange_market=exchange_market,
                exchange_order_id=exchange_order_id,
            )
            return self._ok(normalized, raw_payload=payload)
        except PrivateExchangeApiError as exc:
            return self._handle_api_error(exc)

    def list_open_orders(self, *, market: str | None = None) -> PrivateExchangeResult:
        try:
            query_pairs: list[tuple[str, str]] = []
            if market:
                query_pairs.append(("market", _normalize_market(self.exchange, market).exchange_symbol))
            query_pairs.append(("state", "wait"))
            frozen_pairs = tuple(query_pairs)
            payload = self._request(
                operation_name="list_open_orders",
                method="GET",
                path="/v1/orders",
                headers={
                    "Authorization": build_bearer_authorization(
                        create_bithumb_jwt_token(
                            self._credentials.access_key,
                            self._credentials.secret_key,
                            query_string=build_query_string(frozen_pairs),
                        )
                    )
                },
                query_pairs=frozen_pairs,
            )
            items = payload if isinstance(payload, list) else []
            normalized = [_normalize_bithumb_order(item) for item in items if isinstance(item, dict)]
            return self._ok({"items": normalized, "count": len(normalized)}, raw_payload=payload)
        except PrivateExchangeApiError as exc:
            return self._handle_api_error(exc)


class CoinonePrivateExchangeConnector(RestPrivateExchangeConnector):
    def get_balances(self) -> PrivateExchangeResult:
        try:
            headers, body, _encoded = build_coinone_private_headers(
                {},
                access_key=self._credentials.access_key,
                secret_key=self._credentials.secret_key,
            )
            payload = self._request(
                operation_name="get_balances",
                method="POST",
                path="/v2.1/account/balance/all",
                headers=headers,
                json_body=body,
            )
            items = []
            if isinstance(payload, dict):
                balances = payload.get("balances")
                if isinstance(balances, list):
                    items = [_normalize_coinone_balance(item) for item in balances if isinstance(item, dict)]
            return self._ok({"items": items, "count": len(items)}, raw_payload=payload)
        except PrivateExchangeApiError as exc:
            return self._handle_api_error(exc)

    def place_order(self, request_payload: dict[str, object]) -> PrivateExchangeResult:
        try:
            body = _build_coinone_order_payload(request_payload)
            headers, signed_body, _encoded = build_coinone_private_headers(
                body,
                access_key=self._credentials.access_key,
                secret_key=self._credentials.secret_key,
            )
            payload = self._request(
                operation_name="place_order",
                method="POST",
                path="/v2.1/order",
                headers=headers,
                json_body=signed_body,
            )
            market = _normalize_market(self.exchange, str(request_payload.get("market") or ""))
            return self._ok(
                _normalize_coinone_place_order(payload, market=market, request_payload=request_payload),
                raw_payload=payload,
            )
        except PrivateExchangeApiError as exc:
            return self._handle_api_error(exc)

    def get_order_status(
        self, *, exchange_order_id: str, market: str
    ) -> PrivateExchangeResult:
        try:
            exchange_market = _normalize_market(self.exchange, market)
            headers, body, _encoded = build_coinone_private_headers(
                {
                    "order_id": exchange_order_id,
                    "quote_currency": exchange_market.quote_currency,
                    "target_currency": exchange_market.target_currency,
                },
                access_key=self._credentials.access_key,
                secret_key=self._credentials.secret_key,
            )
            payload = self._request(
                operation_name="get_order_status",
                method="POST",
                path="/v2.1/order/detail",
                headers=headers,
                json_body=body,
            )
            return self._ok(_normalize_coinone_order(payload), raw_payload=payload)
        except PrivateExchangeApiError as exc:
            return self._handle_api_error(exc)

    def cancel_order(
        self, *, exchange_order_id: str, market: str
    ) -> PrivateExchangeResult:
        try:
            exchange_market = _normalize_market(self.exchange, market)
            headers, body, _encoded = build_coinone_private_headers(
                {
                    "order_id": exchange_order_id,
                    "quote_currency": exchange_market.quote_currency,
                    "target_currency": exchange_market.target_currency,
                },
                access_key=self._credentials.access_key,
                secret_key=self._credentials.secret_key,
            )
            payload = self._request(
                operation_name="cancel_order",
                method="POST",
                path="/v2.1/order/cancel",
                headers=headers,
                json_body=body,
            )
            normalized = _normalize_coinone_order(payload)
            normalized = _apply_order_market_fallback(
                normalized,
                exchange_market=exchange_market,
                exchange_order_id=exchange_order_id,
            )
            return self._ok(normalized, raw_payload=payload)
        except PrivateExchangeApiError as exc:
            return self._handle_api_error(exc)

    def list_open_orders(self, *, market: str | None = None) -> PrivateExchangeResult:
        try:
            body: dict[str, object] = {}
            if market:
                exchange_market = _normalize_market(self.exchange, market)
                body["quote_currency"] = exchange_market.quote_currency
                body["target_currency"] = exchange_market.target_currency
            headers, signed_body, _encoded = build_coinone_private_headers(
                body,
                access_key=self._credentials.access_key,
                secret_key=self._credentials.secret_key,
            )
            payload = self._request(
                operation_name="list_open_orders",
                method="POST",
                path="/v2.1/order/active_orders",
                headers=headers,
                json_body=signed_body,
            )
            items: list[dict[str, object]] = []
            if isinstance(payload, dict):
                raw_items = payload.get("active_orders") or payload.get("open_orders")
                if isinstance(raw_items, list):
                    items = [_normalize_coinone_order(item) for item in raw_items if isinstance(item, dict)]
            return self._ok({"items": items, "count": len(items)}, raw_payload=payload)
        except PrivateExchangeApiError as exc:
            return self._handle_api_error(exc)


def build_private_exchange_connector(
    exchange: str,
    *,
    config: AppConfig,
) -> PrivateExchangeConnectorProtocol:
    status = inspect_exchange_trading_credentials_from_config(config, exchange)
    if not status.ready:
        return MissingCredentialsPrivateExchangeConnector(exchange=exchange, status=status)
    credentials = load_exchange_trading_credentials_from_config(config, exchange)
    if credentials is None:
        return MissingCredentialsPrivateExchangeConnector(exchange=exchange, status=status)
    base_url_by_exchange = {
        "upbit": config.upbit_quotation_base_url,
        "bithumb": config.bithumb_public_base_url,
        "coinone": config.coinone_public_base_url,
    }
    connector_class_by_exchange = {
        "upbit": UpbitPrivateExchangeConnector,
        "bithumb": BithumbPrivateExchangeConnector,
        "coinone": CoinonePrivateExchangeConnector,
    }
    connector_class = connector_class_by_exchange[exchange]
    return connector_class(
        exchange=exchange,
        credentials=credentials,
        base_url=base_url_by_exchange[exchange],
        timeout_ms=config.market_data_timeout_ms,
    )


def build_private_exchange_connectors(
    *,
    config: AppConfig,
    exchanges: tuple[str, ...] = ("upbit", "bithumb", "coinone"),
) -> dict[str, PrivateExchangeConnectorProtocol]:
    return {
        exchange: build_private_exchange_connector(exchange, config=config)
        for exchange in exchanges
    }


def build_private_exchange_ws_monitor(
    *,
    exchange: str,
    configured: bool,
    auth_ready: bool,
) -> PrivateExchangeWebsocketMonitorInfo:
    endpoint_by_exchange = {
        "upbit": "wss://api.upbit.com/websocket/v1/private",
        "bithumb": None,
        "coinone": "wss://stream.coinone.co.kr/v1/private",
    }
    ping_interval_by_exchange = {
        "upbit": None,
        "bithumb": None,
        "coinone": 900,
    }
    idle_timeout_by_exchange = {
        "upbit": None,
        "bithumb": None,
        "coinone": 1800,
    }
    connection_limit_by_exchange = {
        "upbit": None,
        "bithumb": None,
        "coinone": 20,
    }
    return PrivateExchangeWebsocketMonitorInfo(
        exchange=exchange,
        configured=configured,
        auth_ready=auth_ready,
        connection_state="not_connected" if auth_ready else "not_configured",
        disconnect_count=0,
        last_connected_at=None,
        last_failed_at=None,
        last_close_code=None,
        last_close_category=None,
        endpoint=endpoint_by_exchange.get(exchange),
        ping_interval_seconds=ping_interval_by_exchange.get(exchange),
        idle_timeout_seconds=idle_timeout_by_exchange.get(exchange),
        connection_limit=connection_limit_by_exchange.get(exchange),
    )


def _decode_json_payload(raw_text: str) -> object:
    stripped = raw_text.strip()
    if not stripped:
        return {}
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return {"raw_text": stripped}


def _normalize_market(exchange: str, market: str) -> ExchangeMarket:
    raw = market.strip().upper()
    if not raw:
        raise PrivateExchangeApiError(
            exchange=exchange,
            operation_name="normalize_market",
            internal_code="INVALID_REQUEST",
            reason="market is required",
            retryable=False,
        )
    if "/" in raw:
        target_currency, quote_currency = raw.split("/", 1)
    elif "-" in raw:
        quote_currency, target_currency = raw.split("-", 1)
    else:
        raise PrivateExchangeApiError(
            exchange=exchange,
            operation_name="normalize_market",
            internal_code="INVALID_REQUEST",
            reason=f"unsupported market format: {market}",
            retryable=False,
        )
    canonical_symbol = f"{target_currency}/{quote_currency}"
    exchange_symbol = f"{quote_currency}-{target_currency}"
    return ExchangeMarket(
        canonical_symbol=canonical_symbol,
        exchange_symbol=exchange_symbol,
        quote_currency=quote_currency,
        target_currency=target_currency,
    )


def _normalize_side(side: object) -> str:
    normalized = str(side or "").strip().lower()
    if normalized in {"buy", "bid"}:
        return "buy"
    if normalized in {"sell", "ask"}:
        return "sell"
    raise PrivateExchangeApiError(
        exchange="common",
        operation_name="normalize_side",
        internal_code="INVALID_REQUEST",
        reason=f"unsupported side: {side}",
        retryable=False,
    )


def _build_upbit_order_payload(request_payload: dict[str, object]) -> dict[str, object]:
    market = _normalize_market("upbit", str(request_payload.get("market") or ""))
    side = _normalize_side(request_payload.get("side"))
    order_type = str(request_payload.get("order_type") or "limit").strip().lower()
    client_order_id = str(request_payload.get("client_order_id") or "").strip()
    if order_type == "limit":
        price = _require_text(request_payload, "price")
        qty = _require_text_any(request_payload, "qty", "volume")
        body: dict[str, object] = {
            "market": market.exchange_symbol,
            "side": "bid" if side == "buy" else "ask",
            "ord_type": "limit",
            "price": price,
            "volume": qty,
        }
    elif order_type == "market" and side == "buy":
        body = {
            "market": market.exchange_symbol,
            "side": "bid",
            "ord_type": "price",
            "price": _require_text_any(request_payload, "amount", "quote_qty", "price"),
        }
    elif order_type == "market" and side == "sell":
        body = {
            "market": market.exchange_symbol,
            "side": "ask",
            "ord_type": "market",
            "volume": _require_text_any(request_payload, "qty", "volume"),
        }
    else:
        raise PrivateExchangeApiError(
            exchange="upbit",
            operation_name="place_order",
            internal_code="INVALID_REQUEST",
            reason=f"unsupported order_type for upbit: {order_type}",
            retryable=False,
        )
    if client_order_id:
        body["identifier"] = client_order_id
    return body


def _build_bithumb_order_payload(request_payload: dict[str, object]) -> dict[str, object]:
    market = _normalize_market("bithumb", str(request_payload.get("market") or ""))
    side = _normalize_side(request_payload.get("side"))
    order_type = str(request_payload.get("order_type") or "limit").strip().lower()
    if order_type != "limit":
        raise PrivateExchangeApiError(
            exchange="bithumb",
            operation_name="place_order",
            internal_code="INVALID_REQUEST",
            reason="bithumb connector currently supports limit orders only",
            retryable=False,
        )
    body: dict[str, object] = {
        "market": market.exchange_symbol,
        "side": "bid" if side == "buy" else "ask",
        "ord_type": "limit",
        "price": _require_text(request_payload, "price"),
        "volume": _require_text_any(request_payload, "qty", "volume"),
    }
    client_order_id = str(request_payload.get("client_order_id") or "").strip()
    if client_order_id:
        body["client_order_id"] = client_order_id
    return body


def _build_coinone_order_payload(request_payload: dict[str, object]) -> dict[str, object]:
    market = _normalize_market("coinone", str(request_payload.get("market") or ""))
    side = _normalize_side(request_payload.get("side"))
    order_type = str(request_payload.get("order_type") or "limit").strip().lower()
    body: dict[str, object] = {
        "quote_currency": market.quote_currency,
        "target_currency": market.target_currency,
        "side": "BUY" if side == "buy" else "SELL",
    }
    if order_type == "limit":
        body.update(
            {
                "type": "LIMIT",
                "price": _require_text(request_payload, "price"),
                "qty": _require_text_any(request_payload, "qty", "volume"),
            }
        )
        if "post_only" in request_payload:
            body["post_only"] = bool(request_payload.get("post_only"))
    elif order_type == "market" and side == "buy":
        body.update(
            {
                "type": "MARKET",
                "amount": _require_text_any(request_payload, "amount", "quote_qty", "price"),
            }
        )
    elif order_type == "market" and side == "sell":
        body.update(
            {
                "type": "MARKET",
                "qty": _require_text_any(request_payload, "qty", "volume"),
            }
        )
    else:
        raise PrivateExchangeApiError(
            exchange="coinone",
            operation_name="place_order",
            internal_code="INVALID_REQUEST",
            reason=f"unsupported order_type for coinone: {order_type}",
            retryable=False,
        )
    client_order_id = str(request_payload.get("client_order_id") or "").strip()
    if client_order_id:
        body["user_order_id"] = client_order_id
    if request_payload.get("limit_price") is not None:
        body["limit_price"] = str(request_payload.get("limit_price"))
    return body


def _apply_order_market_fallback(
    payload: dict[str, object],
    *,
    exchange_market: ExchangeMarket,
    exchange_order_id: str,
) -> dict[str, object]:
    updated = dict(payload)
    if not updated.get("exchange_order_id"):
        updated["exchange_order_id"] = exchange_order_id
    if not updated.get("market"):
        updated["market"] = exchange_market.canonical_symbol
    if not updated.get("exchange_market"):
        updated["exchange_market"] = exchange_market.exchange_symbol
    return updated


def _normalize_upbit_balance(item: dict[str, object]) -> dict[str, object]:
    currency = str(item.get("currency") or "")
    unit_currency = str(item.get("unit_currency") or "")
    return {
        "currency": currency,
        "market": f"{currency}/{unit_currency}" if unit_currency else currency,
        "available": str(item.get("balance") or "0"),
        "locked": str(item.get("locked") or "0"),
        "avg_buy_price": str(item.get("avg_buy_price") or "0"),
    }


def _normalize_bithumb_balance(item: dict[str, object]) -> dict[str, object]:
    currency = str(item.get("currency") or item.get("unit_currency") or "")
    return {
        "currency": currency,
        "market": None,
        "available": str(item.get("balance") or item.get("available") or "0"),
        "locked": str(item.get("locked") or item.get("in_use") or item.get("limit") or "0"),
        "avg_buy_price": str(item.get("avg_buy_price") or "0"),
    }


def _normalize_coinone_balance(item: dict[str, object]) -> dict[str, object]:
    return {
        "currency": str(item.get("currency") or ""),
        "market": None,
        "available": str(item.get("available") or "0"),
        "locked": str(item.get("limit") or "0"),
        "avg_buy_price": str(item.get("average_price") or "0"),
    }


def _normalize_upbit_order(payload: object) -> dict[str, object]:
    item = payload if isinstance(payload, dict) else {}
    market = str(item.get("market") or "")
    exchange_market = _normalize_market("upbit", market) if market else None
    raw_state = str(item.get("state") or "")
    return {
        "exchange_order_id": str(item.get("uuid") or ""),
        "client_order_id": item.get("identifier"),
        "market": None if exchange_market is None else exchange_market.canonical_symbol,
        "exchange_market": market or None,
        "side": "buy" if str(item.get("side") or "") == "bid" else "sell",
        "order_type": _normalize_upbit_order_type(item),
        "status": _normalize_upbit_order_status(raw_state),
        "raw_status": raw_state,
        "requested_price": item.get("price"),
        "requested_qty": item.get("volume"),
        "remaining_qty": item.get("remaining_volume"),
        "filled_qty": item.get("executed_volume"),
        "avg_fill_price": None,
        "fee_amount": item.get("paid_fee"),
        "fee_rate": None,
        "created_at": item.get("created_at"),
        "updated_at": item.get("created_at"),
    }


def _normalize_bithumb_order(payload: object) -> dict[str, object]:
    item = payload if isinstance(payload, dict) else {}
    market = str(item.get("market") or "")
    exchange_market = _normalize_market("bithumb", market) if market else None
    raw_state = str(item.get("state") or item.get("order_state") or item.get("status") or "")
    return {
        "exchange_order_id": str(item.get("uuid") or item.get("order_id") or ""),
        "client_order_id": item.get("client_order_id"),
        "market": None if exchange_market is None else exchange_market.canonical_symbol,
        "exchange_market": market or None,
        "side": "buy" if str(item.get("side") or "") == "bid" else "sell",
        "order_type": str(item.get("ord_type") or item.get("type") or "limit").lower(),
        "status": _normalize_bithumb_order_status(raw_state),
        "raw_status": raw_state,
        "requested_price": item.get("price"),
        "requested_qty": item.get("volume") or item.get("original_volume") or item.get("qty"),
        "remaining_qty": item.get("remaining_volume") or item.get("remain_qty"),
        "filled_qty": item.get("executed_volume") or item.get("executed_qty"),
        "avg_fill_price": item.get("avg_price") or item.get("average_executed_price"),
        "fee_amount": item.get("paid_fee") or item.get("fee"),
        "fee_rate": item.get("fee_rate"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("created_at") or item.get("updated_at"),
    }


def _normalize_coinone_place_order(
    payload: object,
    *,
    market: ExchangeMarket,
    request_payload: dict[str, object],
) -> dict[str, object]:
    item = payload if isinstance(payload, dict) else {}
    return {
        "exchange_order_id": str(item.get("order_id") or ""),
        "client_order_id": request_payload.get("client_order_id"),
        "market": market.canonical_symbol,
        "exchange_market": f"{market.quote_currency}-{market.target_currency}",
        "side": _normalize_side(request_payload.get("side")),
        "order_type": str(request_payload.get("order_type") or "limit").strip().lower(),
        "status": "submitted",
        "raw_status": None,
        "requested_price": request_payload.get("price"),
        "requested_qty": request_payload.get("qty") or request_payload.get("volume"),
        "remaining_qty": None,
        "filled_qty": None,
        "avg_fill_price": None,
        "fee_amount": None,
        "fee_rate": None,
        "created_at": None,
        "updated_at": None,
    }


def _normalize_coinone_order(payload: object) -> dict[str, object]:
    root = payload if isinstance(payload, dict) else {}
    item = root.get("order") if isinstance(root.get("order"), dict) else root
    quote_currency = str(item.get("quote_currency") or "")
    target_currency = str(item.get("target_currency") or "")
    market = f"{target_currency}/{quote_currency}" if quote_currency and target_currency else None
    raw_status = str(item.get("status") or "")
    return {
        "exchange_order_id": str(item.get("order_id") or ""),
        "client_order_id": item.get("user_order_id"),
        "market": market,
        "exchange_market": f"{quote_currency}-{target_currency}" if market else None,
        "side": "buy" if str(item.get("side") or "").upper() == "BUY" else "sell",
        "order_type": str(item.get("type") or "").lower(),
        "status": _normalize_coinone_order_status(raw_status),
        "raw_status": raw_status,
        "requested_price": item.get("price"),
        "requested_qty": item.get("original_qty"),
        "remaining_qty": item.get("remain_qty"),
        "filled_qty": item.get("executed_qty"),
        "avg_fill_price": item.get("average_executed_price"),
        "fee_amount": item.get("fee"),
        "fee_rate": item.get("fee_rate"),
        "created_at": item.get("created_at") or item.get("ordered_at"),
        "updated_at": item.get("updated_at") or item.get("ordered_at"),
    }


def _normalize_upbit_order_type(item: dict[str, object]) -> str:
    ord_type = str(item.get("ord_type") or "").strip().lower()
    side = str(item.get("side") or "").strip().lower()
    if ord_type == "price" and side == "bid":
        return "market_buy"
    if ord_type == "market" and side == "ask":
        return "market_sell"
    return ord_type or "limit"


def _normalize_upbit_order_status(raw_state: str) -> str:
    normalized = raw_state.strip().lower()
    if normalized in {"wait", "watch"}:
        return "open"
    if normalized == "done":
        return "filled"
    if normalized == "cancel":
        return "cancelled"
    return normalized or "unknown"


def _normalize_bithumb_order_status(raw_state: str) -> str:
    normalized = raw_state.strip().lower()
    if normalized in {"wait", "watch", "pending"}:
        return "open"
    if normalized == "done":
        return "filled"
    if normalized in {"cancel", "cancelled"}:
        return "cancelled"
    return normalized or "unknown"


def _normalize_coinone_order_status(raw_state: str) -> str:
    normalized = raw_state.strip().upper()
    mapping = {
        "LIVE": "open",
        "PARTIALLY_FILLED": "partially_filled",
        "PARTIALLY_CANCELED": "partially_cancelled",
        "FILLED": "filled",
        "CANCELED": "cancelled",
        "CANCEL": "cancelled",
    }
    return mapping.get(normalized, normalized.lower() or "unknown")


def _query_pairs_from_payload(payload: dict[str, object]) -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            for item in value:
                pairs.append((key, str(item)))
            continue
        if isinstance(value, bool):
            pairs.append((key, "true" if value else "false"))
            continue
        pairs.append((key, str(value)))
    return tuple(pairs)


def _require_text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if value is None or str(value).strip() == "":
        raise PrivateExchangeApiError(
            exchange="common",
            operation_name="validate_payload",
            internal_code="INVALID_REQUEST",
            reason=f"{key} is required",
            retryable=False,
        )
    return str(value)


def _require_text_any(payload: dict[str, object], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip() != "":
            return str(value)
    joined = ", ".join(keys)
    raise PrivateExchangeApiError(
        exchange="common",
        operation_name="validate_payload",
        internal_code="INVALID_REQUEST",
        reason=f"one of {joined} is required",
        retryable=False,
    )


def _map_error(
    *,
    exchange: str,
    operation_name: str,
    http_status: int | None,
    payload: object,
) -> PrivateExchangeApiError:
    raw_message = _payload_error_message(payload)
    message = raw_message.lower()
    if http_status == 401 or "auth" in message or "jwt" in message or "signature" in message:
        return PrivateExchangeApiError(exchange, operation_name, "AUTH_FAILED", raw_message, False, http_status, payload)
    if http_status == 404 or "not found" in message or "존재하지" in message:
        return PrivateExchangeApiError(exchange, operation_name, "ORDER_NOT_FOUND", raw_message, False, http_status, payload)
    if http_status == 429 or "too many" in message or "rate" in message:
        return PrivateExchangeApiError(exchange, operation_name, "RATE_LIMITED", raw_message, True, http_status, payload)
    if "insufficient" in message or "잔고" in message:
        return PrivateExchangeApiError(exchange, operation_name, "INSUFFICIENT_BALANCE", raw_message, False, http_status, payload)
    if http_status is not None and http_status >= 500:
        return PrivateExchangeApiError(exchange, operation_name, "SERVER_ERROR", raw_message, True, http_status, payload)
    if http_status is not None and http_status >= 400:
        return PrivateExchangeApiError(exchange, operation_name, "INVALID_REQUEST", raw_message, False, http_status, payload)
    return PrivateExchangeApiError(exchange, operation_name, "INVALID_REQUEST", raw_message, False, http_status, payload)


def _payload_error_message(payload: object) -> str:
    if isinstance(payload, dict):
        error_obj = payload.get("error")
        if isinstance(error_obj, dict):
            name = str(error_obj.get("name") or "").strip()
            message = str(error_obj.get("message") or "").strip()
            return ": ".join(part for part in (name, message) if part) or "request failed"
        for key in ("message", "error_msg", "error_message"):
            value = payload.get(key)
            if value:
                return str(value)
        for key in ("error_code", "errorCode"):
            value = payload.get(key)
            if value and str(value) != "0":
                return f"error_code={value}"
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return str(payload)
