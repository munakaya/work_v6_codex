from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .config import AppConfig
from .strategy.exchange_key_loader import (
    ExchangeTradingCredentials,
    ExchangeTradingCredentialsStatus,
    inspect_exchange_trading_credentials_from_config,
    load_exchange_trading_credentials_from_config,
)


@dataclass(frozen=True)
class PrivateExchangeResult:
    outcome: str
    reason: str | None = None
    data: object | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "outcome": self.outcome,
            "reason": self.reason,
            "data": self.data,
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

    def list_open_orders(self, *, market: str | None = None) -> PrivateExchangeResult:
        return self._unavailable_result()

    def _unavailable_result(self) -> PrivateExchangeResult:
        return PrivateExchangeResult(
            outcome="unavailable",
            reason=(
                "trading credentials are missing or invalid "
                f"(exchange={self.exchange}, state={self._status.state})"
            ),
        )


class PlaceholderPrivateExchangeConnector:
    def __init__(self, *, exchange: str, credentials: ExchangeTradingCredentials) -> None:
        self.exchange = exchange
        self.name = f"{exchange}:private_placeholder"
        self._credentials = credentials

    @property
    def info(self) -> PrivateExchangeConnectorInfo:
        return PrivateExchangeConnectorInfo(
            exchange=self.exchange,
            name=self.name,
            configured=True,
            ready=True,
            state="ready_not_implemented",
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
        return self._not_implemented_result("get_balances")

    def place_order(self, request_payload: dict[str, object]) -> PrivateExchangeResult:
        return self._not_implemented_result("place_order")

    def get_order_status(
        self, *, exchange_order_id: str, market: str
    ) -> PrivateExchangeResult:
        return self._not_implemented_result("get_order_status")

    def list_open_orders(self, *, market: str | None = None) -> PrivateExchangeResult:
        return self._not_implemented_result("list_open_orders")

    def _not_implemented_result(self, operation_name: str) -> PrivateExchangeResult:
        return PrivateExchangeResult(
            outcome="not_implemented",
            reason=f"{self.exchange} private connector operation not implemented: {operation_name}",
        )


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
    return PlaceholderPrivateExchangeConnector(exchange=exchange, credentials=credentials)


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
