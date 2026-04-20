from __future__ import annotations

from http import HTTPStatus
from uuid import uuid4

from trading_platform.route_handlers_write import ControlPlaneWriteRouteMixin
from trading_platform.request_utils import response_payload


CONFIG_JSON = {
    "arbitrage_runtime": {
        "enabled": True,
        "market": "KRW-XRP",
        "base_exchange": "upbit",
        "hedge_exchange": "bithumb",
    }
}


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class _FakeReadStore:
    supports_mutation = True
    backend_name = "memory"

    def __init__(self) -> None:
        self.running = True
        self.assigned = {
            "config_scope": "default",
            "version_no": 7,
            "apply_status": "pending",
        }
        self.config_versions = [
            {
                "config_scope": "default",
                "version_no": 7,
                "config_json": CONFIG_JSON,
            }
        ]
        self.bot_detail = {
            "bot_id": "bot-1",
            "assigned_config_version": dict(self.assigned),
        }
        self.run = {
            "run_id": "run-1",
            "bot_id": "bot-1",
            "strategy_name": "arbitrage",
            "mode": "shadow",
            "status": "running",
        }
        self.created_run = {
            "run_id": "run-created-1",
            "bot_id": "bot-1",
            "strategy_name": "arbitrage",
            "mode": "shadow",
            "status": "created",
        }

    def list_config_versions(self, config_scope: str) -> list[dict[str, object]]:
        return [item for item in self.config_versions if item["config_scope"] == config_scope]

    def assign_config(self, *, bot_id: str, config_scope: str, version_no: int) -> dict[str, object] | None:
        if bot_id != "bot-1":
            return None
        self.assigned = {
            "config_scope": config_scope,
            "version_no": version_no,
            "apply_status": "pending",
        }
        self.bot_detail["assigned_config_version"] = dict(self.assigned)
        return dict(self.assigned)

    def get_bot_detail(self, bot_id: str) -> dict[str, object] | None:
        if bot_id != "bot-1":
            return None
        return dict(self.bot_detail)

    def list_strategy_runs(
        self,
        *,
        bot_id: str | None = None,
        status: str | None = None,
        mode: str | None = None,
    ) -> list[dict[str, object]]:
        if bot_id not in {None, "bot-1"}:
            return []
        if status not in {None, "running"} or not self.running:
            return []
        return [dict(self.run)]

    def create_strategy_run(
        self, *, bot_id: str, strategy_name: str, mode: str
    ) -> tuple[str, dict[str, object] | None]:
        if bot_id != "bot-1":
            return "not_found", None
        created = dict(self.created_run)
        created["strategy_name"] = strategy_name
        created["mode"] = mode
        return "created", created

    def start_strategy_run(self, run_id: str) -> tuple[str, dict[str, object] | None]:
        if run_id != "run-1":
            return "not_found", None
        self.run["status"] = "running"
        return "started", dict(self.run)


class _FakeMetrics:
    def observe_alert_emitted(self, level: str) -> None:
        return None


class _FakeUnavailableMarketDataRuntime:
    pass


class _FakeMarketDataRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def refresh(self, *, exchange: str, markets: tuple[str, ...], trace_id: str | None = None):
        self.calls.append((exchange, tuple(markets)))
        if exchange == "bithumb":
            return [], [
                {
                    "market": markets[0],
                    "code": "UPSTREAM_TIMEOUT",
                    "message": "timed out",
                    "status": 504,
                }
            ]
        return [
            {
                "exchange": exchange,
                "market": markets[0],
                "source_type": "public_ws",
                "collector_fallback_used": False,
            }
        ], []


class _FakeServer:
    def __init__(self) -> None:
        self.read_store = _FakeReadStore()
        self.metrics = _FakeMetrics()
        self.market_data_runtime = _FakeMarketDataRuntime()


class _DummyHandler(ControlPlaneWriteRouteMixin):
    def __init__(self, server: _FakeServer, body: dict[str, object] | None = None) -> None:
        self.server = server
        self._body = body or {}

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

    def _read_json_body(self):
        return dict(self._body), None

    def _sync_bot_state(self, bot_id: str) -> None:
        return None

    def _sync_strategy_run_state(self, payload: dict[str, object]) -> None:
        return None


def _assert_no_prewarm(payload: dict[str, object]) -> None:
    _assert("collector_prewarm" not in payload["data"], f"unexpected prewarm payload: {payload}")


def _assert_prewarm_skipped(prewarm: dict[str, object]) -> None:
    _assert(prewarm["status"] == "skipped", f"skip status mismatch: {prewarm}")
    _assert(prewarm["reason"] == "no_targets", f"skip reason mismatch: {prewarm}")
    _assert(prewarm["requested_target_count"] == 0, f"skip target count mismatch: {prewarm}")
    _assert(prewarm["success_count"] == 0, f"skip success count mismatch: {prewarm}")
    _assert(prewarm["failure_count"] == 0, f"skip failure count mismatch: {prewarm}")
    _assert(prewarm["items"] == [], f"skip items mismatch: {prewarm}")


def _assert_prewarm_unavailable(prewarm: dict[str, object], *, target_count: int) -> None:
    _assert(prewarm["status"] == "unavailable", f"unavailable status mismatch: {prewarm}")
    _assert(prewarm["requested_target_count"] == target_count, f"unavailable target count mismatch: {prewarm}")
    _assert(prewarm["success_count"] == 0, f"unavailable success count mismatch: {prewarm}")
    _assert(prewarm["failure_count"] == 0, f"unavailable failure count mismatch: {prewarm}")
    _assert(prewarm["items"] == [], f"unavailable items mismatch: {prewarm}")
    _assert(prewarm["reason"] == "market_data_runtime.refresh is unavailable", f"unavailable reason mismatch: {prewarm}")


def _assert_prewarm(payload: dict[str, object]) -> None:
    prewarm = payload["data"]["collector_prewarm"]
    _assert(prewarm["requested_target_count"] == 2, f"prewarm target count mismatch: {prewarm}")
    _assert(prewarm["success_count"] == 1, f"prewarm success count mismatch: {prewarm}")
    _assert(prewarm["failure_count"] == 1, f"prewarm failure count mismatch: {prewarm}")
    _assert(prewarm["status"] == "partial", f"prewarm status mismatch: {prewarm}")
    items = {(item["exchange"], item["status"]): item for item in prewarm["items"]}
    _assert(("upbit", "fetched") in items, f"upbit fetched item missing: {prewarm}")
    _assert(("bithumb", "failed") in items, f"bithumb failed item missing: {prewarm}")


def _case_prewarm_skips_without_targets() -> None:
    server = _FakeServer()
    handler = _DummyHandler(server)
    prewarm = handler._prewarm_market_data_for_config(config_json={"arbitrage_runtime": {"enabled": False}})
    _assert_prewarm_skipped(prewarm)


def _case_assign_config_prewarms_targets() -> None:
    server = _FakeServer()
    handler = _DummyHandler(server, {"config_scope": "default", "version_no": 7})
    status, payload = handler._assign_config_response("/api/v1/bots/bot-1/assign-config")
    _assert(status == HTTPStatus.ACCEPTED, f"assign-config status mismatch: {status} {payload}")
    _assert(
        server.market_data_runtime.calls == [
            ("bithumb", ("KRW-XRP",)),
            ("upbit", ("KRW-XRP",)),
        ],
        f"assign-config prewarm calls mismatch: {server.market_data_runtime.calls}",
    )
    _assert_prewarm(payload)


def _case_prewarm_marks_runtime_unavailable() -> None:
    server = _FakeServer()
    server.market_data_runtime = _FakeUnavailableMarketDataRuntime()
    handler = _DummyHandler(server)
    prewarm = handler._prewarm_market_data_for_config(config_json=CONFIG_JSON)
    _assert_prewarm_unavailable(prewarm, target_count=2)


def _case_assign_config_skips_without_running_run() -> None:
    server = _FakeServer()
    server.read_store.running = False
    handler = _DummyHandler(server, {"config_scope": "default", "version_no": 7})
    status, payload = handler._assign_config_response("/api/v1/bots/bot-1/assign-config")
    _assert(status == HTTPStatus.ACCEPTED, f"assign-config skip status mismatch: {status} {payload}")
    _assert(server.market_data_runtime.calls == [], f"unexpected skip prewarm calls: {server.market_data_runtime.calls}")
    _assert("collector_prewarm" not in payload["data"], f"skip payload should omit prewarm: {payload}")


def _case_assign_config_skips_for_non_arbitrage_run() -> None:
    server = _FakeServer()
    server.read_store.run["strategy_name"] = "rebalance"
    handler = _DummyHandler(server, {"config_scope": "default", "version_no": 7})
    status, payload = handler._assign_config_response("/api/v1/bots/bot-1/assign-config")
    _assert(status == HTTPStatus.ACCEPTED, f"assign-config non-arbitrage status mismatch: {status} {payload}")
    _assert(server.market_data_runtime.calls == [], f"unexpected non-arbitrage prewarm calls: {server.market_data_runtime.calls}")
    _assert_no_prewarm(payload)


def _case_start_strategy_run_prewarms_targets() -> None:
    server = _FakeServer()
    handler = _DummyHandler(server)
    status, payload = handler._start_strategy_run_response("run-1")
    _assert(status == HTTPStatus.ACCEPTED, f"start status mismatch: {status} {payload}")
    _assert(
        server.market_data_runtime.calls == [
            ("bithumb", ("KRW-XRP",)),
            ("upbit", ("KRW-XRP",)),
        ],
        f"start prewarm calls mismatch: {server.market_data_runtime.calls}",
    )
    _assert_prewarm(payload)


def _case_start_strategy_run_skips_without_assigned_config() -> None:
    server = _FakeServer()
    server.read_store.bot_detail = {"bot_id": "bot-1", "assigned_config_version": None}
    handler = _DummyHandler(server)
    status, payload = handler._start_strategy_run_response("run-1")
    _assert(status == HTTPStatus.ACCEPTED, f"start without config status mismatch: {status} {payload}")
    _assert(server.market_data_runtime.calls == [], f"unexpected start-without-config prewarm calls: {server.market_data_runtime.calls}")
    _assert_no_prewarm(payload)



def _case_create_strategy_run_does_not_prewarm() -> None:
    server = _FakeServer()
    handler = _DummyHandler(server, {"bot_id": "bot-1", "strategy_name": "arbitrage", "mode": "shadow"})
    status, payload = handler._create_strategy_run_response()
    _assert(status == HTTPStatus.CREATED, f"create run status mismatch: {status} {payload}")
    _assert(server.market_data_runtime.calls == [], f"create run should not prewarm: {server.market_data_runtime.calls}")
    _assert_no_prewarm(payload)


def main() -> None:
    _case_prewarm_skips_without_targets()
    _case_prewarm_marks_runtime_unavailable()
    _case_assign_config_prewarms_targets()
    _case_assign_config_skips_without_running_run()
    _case_assign_config_skips_for_non_arbitrage_run()
    _case_start_strategy_run_prewarms_targets()
    _case_start_strategy_run_skips_without_assigned_config()
    _case_create_strategy_run_does_not_prewarm()
    print("PASS prewarm skips cleanly when config has no collector targets")
    print("PASS prewarm reports unavailable when runtime refresh hook is missing")
    print("PASS assign-config prewarms market data targets from arbitrage config")
    print("PASS assign-config skips prewarm when no running arbitrage run exists")
    print("PASS assign-config skips prewarm for non-arbitrage running runs")
    print("PASS strategy run start prewarms market data targets from assigned config")
    print("PASS strategy run start skips prewarm without assigned config")
    print("PASS strategy run create does not prewarm collector targets")


if __name__ == "__main__":
    main()
