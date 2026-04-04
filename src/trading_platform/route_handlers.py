from __future__ import annotations

from http import HTTPStatus
from uuid import uuid4

from .request_utils import read_json_body, response_payload, write_json, write_text
from .route_handlers_market_read import ControlPlaneMarketReadRouteMixin
from .route_handlers_market_write import ControlPlaneMarketWriteRouteMixin
from .route_handlers_order_write import ControlPlaneOrderWriteRouteMixin
from .route_handlers_redis import ControlPlaneRedisRouteMixin
from .route_handlers_read import ControlPlaneReadRouteMixin
from .route_handlers_runtime_read import ControlPlaneRuntimeReadRouteMixin
from .route_handlers_strategy_write import ControlPlaneStrategyWriteRouteMixin
from .route_handlers_stream_read import ControlPlaneStreamReadRouteMixin
from .route_handlers_write import ControlPlaneWriteRouteMixin


class ControlPlaneRouteMixin(
    ControlPlaneRedisRouteMixin,
    ControlPlaneMarketReadRouteMixin,
    ControlPlaneRuntimeReadRouteMixin,
    ControlPlaneStreamReadRouteMixin,
    ControlPlaneReadRouteMixin,
    ControlPlaneMarketWriteRouteMixin,
    ControlPlaneWriteRouteMixin,
    ControlPlaneOrderWriteRouteMixin,
    ControlPlaneStrategyWriteRouteMixin,
):
    def _response(
        self,
        data: dict[str, object] | None = None,
        error: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return response_payload(
            request_id_factory=lambda: str(uuid4()),
            data=data,
            error=error,
        )

    def _write_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        write_json(self, status, payload)

    def _write_text(
        self,
        status: HTTPStatus,
        payload: str,
        content_type: str = "text/plain; version=0.0.4; charset=utf-8",
    ) -> None:
        write_text(self, status, payload, content_type)

    def _read_json_body(
        self,
    ) -> tuple[dict[str, object], tuple[HTTPStatus, dict[str, object]] | None]:
        return read_json_body(self)
