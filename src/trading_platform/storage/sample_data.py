from __future__ import annotations


def build_sample_state(sample_time):
    bot_1_id = "9d0f9b5d-8f1d-4fe0-bd90-5b7bcb3b4e21"
    bot_2_id = "0ecf5f88-c7d3-4307-b4e7-e54caef0eab3"

    bot_1_heartbeat = {
        "created_at": sample_time(1),
        "is_process_alive": True,
        "is_market_data_alive": True,
        "is_ordering_alive": True,
        "lag_ms": 240,
        "payload": {
            "orderbook_stale_count": 0,
            "balance_refresh_age_ms": 1800,
        },
    }
    bot_2_heartbeat = {
        "created_at": sample_time(3),
        "is_process_alive": True,
        "is_market_data_alive": False,
        "is_ordering_alive": True,
        "lag_ms": 1450,
        "payload": {
            "orderbook_stale_count": 4,
            "balance_refresh_age_ms": 6400,
        },
    }

    bots = [
        {
            "bot_id": bot_1_id,
            "bot_key": "arb-upbit-bithumb-001",
            "strategy_name": "arbitrage",
            "mode": "shadow",
            "status": "running",
            "hostname": "trade-host-01",
            "last_seen_at": bot_1_heartbeat["created_at"],
            "assigned_config_version": {"config_scope": "default", "version_no": 3},
        },
        {
            "bot_id": bot_2_id,
            "bot_key": "arb-upbit-coinone-002",
            "strategy_name": "arbitrage",
            "mode": "dry_run",
            "status": "running",
            "hostname": "trade-host-02",
            "last_seen_at": bot_2_heartbeat["created_at"],
            "assigned_config_version": {"config_scope": "default", "version_no": 2},
        },
    ]

    alerts = [
        {
            "alert_id": "2274470a-1b8d-4bb1-8b60-68ba2f2c17c9",
            "bot_id": bot_2_id,
            "level": "warn",
            "code": "ORDERBOOK_STALE",
            "message": "coinone orderbook freshness exceeded threshold",
            "created_at": sample_time(4),
            "acknowledged_at": None,
        },
        {
            "alert_id": "47083d47-1b3f-43ab-a76a-f967f2e824a8",
            "bot_id": bot_1_id,
            "level": "info",
            "code": "CONFIG_APPLIED",
            "message": "config version 3 applied",
            "created_at": sample_time(9),
            "acknowledged_at": sample_time(8),
        },
    ]

    config_versions = {
        "default": [
            {
                "config_version_id": "5375618a-fd27-430f-a8eb-c5dadfc1d498",
                "config_scope": "default",
                "version_no": 3,
                "config_json": {
                    "strategy_name": "arbitrage",
                    "min_profit": "1000",
                    "max_order_notional": "500000",
                },
                "checksum": "chk-default-v3",
                "created_by": "system",
                "created_at": sample_time(20),
            },
            {
                "config_version_id": "8ea92369-7267-497d-9ac9-47758cc884d2",
                "config_scope": "default",
                "version_no": 2,
                "config_json": {
                    "strategy_name": "arbitrage",
                    "min_profit": "900",
                    "max_order_notional": "450000",
                },
                "checksum": "chk-default-v2",
                "created_by": "system",
                "created_at": sample_time(40),
            },
        ]
    }

    strategy_run_1 = {
        "run_id": "eb8f7c39-d23f-433f-b839-6d2e89d4bbd6",
        "bot_id": bot_1_id,
        "strategy_name": "arbitrage",
        "status": "running",
        "mode": "shadow",
        "created_at": sample_time(12),
        "started_at": sample_time(12),
        "stopped_at": None,
        "decision_count": 184,
    }
    strategy_run_2 = {
        "run_id": "7d9cf351-5b29-44a4-9cb4-ff5d1c4e0a0f",
        "bot_id": bot_2_id,
        "strategy_name": "arbitrage",
        "status": "running",
        "mode": "dry_run",
        "created_at": sample_time(30),
        "started_at": sample_time(30),
        "stopped_at": None,
        "decision_count": 42,
    }

    strategy_runs = {
        strategy_run_1["run_id"]: strategy_run_1,
        strategy_run_2["run_id"]: strategy_run_2,
    }

    order_intent_1 = {
        "intent_id": "dbd43359-4908-4df5-a43a-c19ebec10aa1",
        "bot_id": bot_1_id,
        "strategy_run_id": strategy_run_1["run_id"],
        "market": "BTC-KRW",
        "buy_exchange": "upbit",
        "sell_exchange": "bithumb",
        "side_pair": "buy_sell",
        "target_qty": "0.015",
        "expected_profit": "12500",
        "expected_profit_ratio": "0.0019",
        "status": "created",
        "created_at": sample_time(6),
        "decision_context": {
            "spread_bps": 24,
            "fees_bps": 5,
            "balance_check": "passed",
            "reason": "spread above threshold",
        },
    }
    order_intent_2 = {
        "intent_id": "bd2f6202-86fb-4c6d-8bb1-13b49e681eba",
        "bot_id": bot_2_id,
        "strategy_run_id": strategy_run_2["run_id"],
        "market": "ETH-KRW",
        "buy_exchange": "coinone",
        "sell_exchange": "upbit",
        "side_pair": "buy_sell",
        "target_qty": "0.21",
        "expected_profit": "3400",
        "expected_profit_ratio": "0.0011",
        "status": "submitted",
        "created_at": sample_time(18),
        "decision_context": {
            "spread_bps": 18,
            "fees_bps": 6,
            "balance_check": "passed",
            "reason": "shadow execution sample",
        },
    }

    order_intents = {
        order_intent_1["intent_id"]: order_intent_1,
        order_intent_2["intent_id"]: order_intent_2,
    }

    order_1 = {
        "order_id": "657f0f8d-e7d1-4bd4-b841-85c2d1ed59ca",
        "order_intent_id": order_intent_2["intent_id"],
        "bot_id": bot_2_id,
        "strategy_run_id": strategy_run_2["run_id"],
        "exchange_name": "upbit",
        "exchange_order_id": "UPBIT-20260404-0001",
        "market": "ETH-KRW",
        "side": "sell",
        "requested_price": "4271000",
        "requested_qty": "0.21",
        "filled_qty": "0.17",
        "avg_fill_price": "4272500",
        "fee_amount": "1450",
        "status": "partially_filled",
        "internal_error_code": None,
        "created_at": sample_time(17),
        "submitted_at": sample_time(17),
        "updated_at": sample_time(13),
    }
    order_2 = {
        "order_id": "05438a82-a7bc-4c8b-b7a9-ef9708330878",
        "order_intent_id": None,
        "bot_id": bot_1_id,
        "strategy_run_id": strategy_run_1["run_id"],
        "exchange_name": "bithumb",
        "exchange_order_id": "BITHUMB-20260404-0007",
        "market": "BTC-KRW",
        "side": "buy",
        "requested_price": "98320000",
        "requested_qty": "0.010",
        "filled_qty": "0.010",
        "avg_fill_price": "98318000",
        "fee_amount": "980",
        "status": "filled",
        "internal_error_code": None,
        "created_at": sample_time(11),
        "submitted_at": sample_time(11),
        "updated_at": sample_time(9),
    }

    orders = {
        order_1["order_id"]: order_1,
        order_2["order_id"]: order_2,
    }

    fills = [
        {
            "fill_id": "7d96f709-2d3a-4afd-b2a5-8e63d5ac7d68",
            "order_id": order_1["order_id"],
            "order_intent_id": order_1["order_intent_id"],
            "bot_id": bot_2_id,
            "strategy_run_id": strategy_run_2["run_id"],
            "exchange_name": "upbit",
            "market": "ETH-KRW",
            "side": "sell",
            "fill_price": "4273000",
            "fill_qty": "0.10",
            "fee_asset": "KRW",
            "fee_amount": "860",
            "order_status": "partially_filled",
            "filled_at": sample_time(14),
            "created_at": sample_time(14),
        },
        {
            "fill_id": "4cb0b2f6-d1ef-44bb-8201-b906933514e8",
            "order_id": order_1["order_id"],
            "order_intent_id": order_1["order_intent_id"],
            "bot_id": bot_2_id,
            "strategy_run_id": strategy_run_2["run_id"],
            "exchange_name": "upbit",
            "market": "ETH-KRW",
            "side": "sell",
            "fill_price": "4272000",
            "fill_qty": "0.07",
            "fee_asset": "KRW",
            "fee_amount": "590",
            "order_status": "partially_filled",
            "filled_at": sample_time(13),
            "created_at": sample_time(13),
        },
        {
            "fill_id": "499067ca-4f4c-4dbd-a0fd-ac9164369d96",
            "order_id": order_2["order_id"],
            "order_intent_id": order_2["order_intent_id"],
            "bot_id": bot_1_id,
            "strategy_run_id": strategy_run_1["run_id"],
            "exchange_name": "bithumb",
            "market": "BTC-KRW",
            "side": "buy",
            "fill_price": "98318000",
            "fill_qty": "0.010",
            "fee_asset": "KRW",
            "fee_amount": "980",
            "order_status": "filled",
            "filled_at": sample_time(9),
            "created_at": sample_time(9),
        },
    ]

    bot_details = {
        bot_1_id: {
            **bots[0],
            "latest_heartbeat": bot_1_heartbeat,
            "latest_strategy_run": strategy_run_1,
            "recent_alerts": [alerts[1]],
        },
        bot_2_id: {
            **bots[1],
            "latest_heartbeat": bot_2_heartbeat,
            "latest_strategy_run": strategy_run_2,
            "recent_alerts": [alerts[0]],
        },
    }

    heartbeats = {
        bot_1_id: [
            bot_1_heartbeat,
            {
                "created_at": sample_time(2),
                "is_process_alive": True,
                "is_market_data_alive": True,
                "is_ordering_alive": True,
                "lag_ms": 210,
                "payload": {
                    "orderbook_stale_count": 0,
                    "balance_refresh_age_ms": 1600,
                },
            },
        ],
        bot_2_id: [
            bot_2_heartbeat,
            {
                "created_at": sample_time(5),
                "is_process_alive": True,
                "is_market_data_alive": True,
                "is_ordering_alive": True,
                "lag_ms": 320,
                "payload": {
                    "orderbook_stale_count": 1,
                    "balance_refresh_age_ms": 2200,
                },
            },
        ],
    }

    return {
        "bots": bots,
        "bot_details": bot_details,
        "strategy_runs": strategy_runs,
        "order_intents": order_intents,
        "orders": orders,
        "fills": fills,
        "heartbeats": heartbeats,
        "alerts": alerts,
        "config_versions": config_versions,
    }
