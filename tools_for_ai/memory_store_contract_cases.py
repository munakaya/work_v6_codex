from __future__ import annotations

from datetime import UTC, datetime

from trading_platform.storage.store_factory import sample_read_store


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _verify_read_contracts() -> None:
    store = sample_read_store()

    bots = store.list_bots()
    bot_id = str(bots[0]["bot_id"])
    original_bot_status = str(store.bot_details[bot_id]["status"])
    bots[0]["status"] = "corrupted"
    _assert(
        str(store.bot_details[bot_id]["status"]) == original_bot_status,
        "list_bots returned live bot reference",
    )

    detail = store.get_bot_detail(bot_id)
    _assert(detail is not None, "bot detail missing")
    original_recent_alert_count = len(store.bot_details[bot_id]["recent_alerts"])
    detail["recent_alerts"].append(  # type: ignore[index]
        {
            "alert_id": "fake-alert",
            "level": "error",
            "code": "FAKE",
            "message": "should not persist",
        }
    )
    _assert(
        len(store.bot_details[bot_id]["recent_alerts"]) == original_recent_alert_count,
        "get_bot_detail returned live nested recent_alerts reference",
    )

    latest_config = store.latest_config("default")
    _assert(latest_config is not None, "latest config missing")
    latest_config["config_json"]["arbitrage_runtime"]["base_balance"]["available_quote"] = "1"  # type: ignore[index]
    _assert(
        str(
            store.config_versions["default"][0]["config_json"]["arbitrage_runtime"]["base_balance"][
                "available_quote"
            ]
        )
        != "1",
        "latest_config returned live config_json reference",
    )

    config_versions = store.list_config_versions("default")
    config_versions[0]["config_json"]["arbitrage_runtime"]["hedge_balance"]["available_base"] = "0"  # type: ignore[index]
    _assert(
        str(
            store.config_versions["default"][0]["config_json"]["arbitrage_runtime"]["hedge_balance"][
                "available_base"
            ]
        )
        != "0",
        "list_config_versions returned live config_json reference",
    )

    alerts = store.list_alerts()
    _assert(alerts, "sample alerts missing")
    alert_id = str(alerts[0]["alert_id"])
    alerts[0]["message"] = "corrupted"
    _assert(
        str(store.alerts[0]["message"]) != "corrupted",
        "list_alerts returned live alert reference",
    )

    alert_detail = store.get_alert_detail(alert_id)
    _assert(alert_detail is not None, "alert detail missing")
    alert_detail["message"] = "corrupted-detail"
    _assert(
        str(store.alerts[0]["message"]) != "corrupted-detail",
        "get_alert_detail returned live alert reference",
    )


def _verify_mutation_contracts() -> None:
    store = sample_read_store()

    registered = store.register_bot(
        bot_key="memory-contract-bot",
        strategy_name="arbitrage",
        mode="shadow",
        hostname="memory-store-contract",
    )
    bot_id = str(registered["bot_id"])
    registered["assigned_config_version"]["version_no"] = 999  # type: ignore[index]
    _assert(
        int(store.bot_details[bot_id]["assigned_config_version"]["version_no"]) != 999,
        "register_bot returned live assigned_config_version reference",
    )

    run_outcome, run = store.create_strategy_run(
        bot_id=bot_id,
        strategy_name="arbitrage",
        mode="shadow",
    )
    _assert(run_outcome == "created" and run is not None, "create_strategy_run failed")
    run_id = str(run["run_id"])
    run["status"] = "corrupted"
    _assert(
        str(store.strategy_runs[run_id]["status"]) == "created",
        "create_strategy_run returned live run reference",
    )

    conflict_outcome, conflict_run = store.create_strategy_run(
        bot_id=bot_id,
        strategy_name="arbitrage",
        mode="shadow",
    )
    _assert(conflict_outcome == "conflict" and conflict_run is not None, "conflict path missing")
    conflict_run["status"] = "conflict-corrupted"
    _assert(
        str(store.strategy_runs[run_id]["status"]) == "created",
        "create_strategy_run conflict returned live run reference",
    )

    started_outcome, started_run = store.start_strategy_run(run_id)
    _assert(started_outcome == "started" and started_run is not None, "start_strategy_run failed")
    started_run["status"] = "stopped"
    _assert(
        str(store.strategy_runs[run_id]["status"]) == "running",
        "start_strategy_run returned live run reference",
    )

    intent_outcome, intent = store.create_order_intent(
        strategy_run_id=run_id,
        market="KRW-BTC",
        buy_exchange="sample",
        sell_exchange="upbit",
        side_pair="buy_then_sell",
        target_qty="0.01",
        expected_profit="1000",
        expected_profit_ratio="0.01",
        status="created",
        decision_context={"risk": {"spread_bps": "50"}},
    )
    _assert(intent_outcome == "created" and intent is not None, "create_order_intent failed")
    intent_id = str(intent["intent_id"])
    intent["decision_context"]["risk"]["spread_bps"] = "999"  # type: ignore[index]
    _assert(
        str(store.order_intents[intent_id]["decision_context"]["risk"]["spread_bps"]) == "50",
        "create_order_intent returned live decision_context reference",
    )

    order_outcome, order = store.create_order(
        order_intent_id=intent_id,
        exchange_name="sample",
        exchange_order_id="memory-contract-order-001",
        market="KRW-BTC",
        side="buy",
        requested_price="100000",
        requested_qty="0.01",
        status="submitted",
        raw_payload={"remote": {"status": "submitted"}},
    )
    _assert(order_outcome == "created" and order is not None, "create_order failed")
    order_id = str(order["order_id"])
    order["raw_payload"]["remote"]["status"] = "corrupted"  # type: ignore[index]
    _assert(
        str(store.orders[order_id]["raw_payload"]["remote"]["status"]) == "submitted",
        "create_order returned live raw_payload reference",
    )

    fill_outcome, fill = store.create_fill(
        order_id=order_id,
        exchange_trade_id="memory-contract-fill-001",
        fill_price="100000",
        fill_qty="0.01",
        fee_asset="KRW",
        fee_amount="10",
        filled_at=_iso_now(),
    )
    _assert(fill_outcome == "created" and fill is not None, "create_fill failed")
    fill_id = str(fill["fill_id"])
    fill["fee_amount"] = "999"
    persisted_fill = next(item for item in store.fills if str(item["fill_id"]) == fill_id)
    _assert(
        str(persisted_fill["fee_amount"]) == "10",
        "create_fill returned live fill reference",
    )

    alert = store.emit_alert(
        bot_id=bot_id,
        level="warning",
        code="MEMORY_CONTRACT",
        message="alert copy regression",
    )
    alert["message"] = "corrupted-alert"
    _assert(
        str(store.alerts[0]["message"]) == "alert copy regression",
        "emit_alert returned live alert reference",
    )

    config_version = store.create_config_version(
        config_scope="default",
        config_json={"risk": {"max_quote_notional": "5000000"}},
        checksum="memory-contract-checksum",
        created_by="tools_for_ai",
    )
    config_version["config_json"]["risk"]["max_quote_notional"] = "1"  # type: ignore[index]
    _assert(
        str(store.config_versions["default"][0]["config_json"]["risk"]["max_quote_notional"])
        == "5000000",
        "create_config_version returned live config_json reference",
    )


def main() -> None:
    _verify_read_contracts()
    print("PASS memory store contract read paths")
    _verify_mutation_contracts()
    print("PASS memory store contract mutation paths")


if __name__ == "__main__":
    main()
