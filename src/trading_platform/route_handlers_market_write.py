from __future__ import annotations

from http import HTTPStatus

from .request_utils import json_string


class ControlPlaneMarketWriteRouteMixin:
    MAX_MARKET_POLL_ITEMS = 20

    def _market_data_poll_response(self) -> tuple[HTTPStatus, dict[str, object]]:
        body, error = self._read_json_body()
        if error is not None:
            return error

        exchange = json_string(body.get("exchange"))
        markets_raw = body.get("markets")
        invalid_fields: list[str] = []
        if "exchange" in body and exchange is None:
            invalid_fields.append("exchange")
        if not isinstance(markets_raw, list):
            invalid_fields.append("markets")
        markets: list[str] = []
        if isinstance(markets_raw, list):
            for item in markets_raw:
                market = json_string(item)
                if market is None:
                    invalid_fields.append("markets")
                    break
                normalized = market.strip().upper()
                if not normalized:
                    invalid_fields.append("markets")
                    break
                markets.append(normalized)
        if invalid_fields:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "invalid fields: " + ", ".join(sorted(set(invalid_fields))),
                    }
                ),
            )
        if not exchange or not markets:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": "exchange and markets are required",
                    }
                ),
            )
        if len(markets) > self.MAX_MARKET_POLL_ITEMS:
            return (
                HTTPStatus.BAD_REQUEST,
                self._response(
                    error={
                        "code": "INVALID_REQUEST",
                        "message": (
                            f"markets may contain at most {self.MAX_MARKET_POLL_ITEMS} items"
                        ),
                    }
                ),
            )

        snapshots, errors = self.server.market_data_runtime.refresh(
            exchange=exchange,
            markets=markets,
        )
        status = HTTPStatus.OK if not errors else HTTPStatus.MULTI_STATUS
        return status, self._response(
            data={
                "exchange": exchange.strip().lower(),
                "requested_markets": markets,
                "items": snapshots,
                "count": len(snapshots),
                "errors": errors,
                "error_count": len(errors),
            }
        )
