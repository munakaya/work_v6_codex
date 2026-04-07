from __future__ import annotations

import os
from pathlib import Path
import tempfile

from trading_platform.config import load_config
from trading_platform.private_exchange_connector import (
    build_private_exchange_connector,
    build_private_exchange_connectors,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
TMP_ROOT = ROOT_DIR / ".tmp"


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    with tempfile.TemporaryDirectory(dir=TMP_ROOT) as primary_tmp, tempfile.TemporaryDirectory(
        dir=TMP_ROOT
    ) as fallback_tmp:
        primary_dir = Path(primary_tmp)
        fallback_dir = Path(fallback_tmp)
        _write(
            primary_dir / "upbit_trading.json",
            '{"access_key":"upbit-access","secret_key":"upbit-secret"}',
        )
        _write(
            fallback_dir / "bithumb.json",
            '{"api_key":"bithumb-access","secret_key":"bithumb-secret"}',
        )

        previous_primary = os.environ.get("TP_EXCHANGE_KEY_PRIMARY_DIR")
        previous_fallback = os.environ.get("TP_EXCHANGE_KEY_FALLBACK_DIR")
        try:
            os.environ["TP_EXCHANGE_KEY_PRIMARY_DIR"] = str(primary_dir)
            os.environ["TP_EXCHANGE_KEY_FALLBACK_DIR"] = str(fallback_dir)
            config = load_config()

            upbit = build_private_exchange_connector("upbit", config=config)
            _assert(upbit.info.ready is True, "upbit connector should be ready")
            _assert(
                upbit.info.state == "ready_not_implemented",
                "upbit placeholder state mismatch",
            )
            _assert(
                upbit.get_balances().outcome == "not_implemented",
                "upbit placeholder result mismatch",
            )

            bithumb = build_private_exchange_connector("bithumb", config=config)
            _assert(bithumb.info.ready is True, "bithumb connector should be ready")
            _assert(
                "bithumb.json" in str(bithumb.info.credential_source_path),
                "bithumb fallback path mismatch",
            )

            coinone = build_private_exchange_connector("coinone", config=config)
            _assert(coinone.info.ready is False, "coinone connector should be unavailable")
            _assert(coinone.get_balances().outcome == "unavailable", "coinone outcome mismatch")

            bundle = build_private_exchange_connectors(config=config)
            _assert(set(bundle) == {"upbit", "bithumb", "coinone"}, "bundle keys mismatch")
            print("PASS private exchange connector placeholder readiness")
        finally:
            if previous_primary is None:
                os.environ.pop("TP_EXCHANGE_KEY_PRIMARY_DIR", None)
            else:
                os.environ["TP_EXCHANGE_KEY_PRIMARY_DIR"] = previous_primary
            if previous_fallback is None:
                os.environ.pop("TP_EXCHANGE_KEY_FALLBACK_DIR", None)
            else:
                os.environ["TP_EXCHANGE_KEY_FALLBACK_DIR"] = previous_fallback


if __name__ == "__main__":
    main()
