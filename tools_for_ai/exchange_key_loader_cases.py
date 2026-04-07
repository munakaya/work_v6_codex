from __future__ import annotations

from pathlib import Path
import tempfile

from trading_platform.config import load_config
from trading_platform.strategy.exchange_key_loader import (
    load_exchange_trading_credentials,
    load_exchange_trading_credentials_from_config,
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

        _assert(
            load_exchange_trading_credentials(
                "upbit",
                primary_dir=primary_dir,
                fallback_dir=fallback_dir,
            )
            is None,
            "missing files should return None",
        )
        print("PASS exchange key loader missing file")

        _write(
            primary_dir / "upbit_trading.json",
            '{"access_key":"ram-upbit-access","secret_key":"ram-upbit-secret"}',
        )
        _write(
            fallback_dir / "upbit.json",
            '{"access_key":"fallback-upbit-access","secret_key":"fallback-upbit-secret"}',
        )
        credentials = load_exchange_trading_credentials(
            "upbit",
            primary_dir=primary_dir,
            fallback_dir=fallback_dir,
        )
        _assert(credentials is not None, "primary credentials missing")
        _assert(credentials.access_key == "ram-upbit-access", "primary dir should win")
        _assert(
            credentials.source_path == primary_dir / "upbit_trading.json",
            "primary path mismatch",
        )
        print("PASS exchange key loader prefers /dev/shm-style primary path")

        _write(
            fallback_dir / "bithumb.json",
            '{"access_key":"fallback-bithumb-access","secret_key":"fallback-bithumb-secret"}',
        )
        credentials = load_exchange_trading_credentials(
            "bithumb",
            primary_dir=primary_dir,
            fallback_dir=fallback_dir,
        )
        _assert(credentials is not None, "fallback credentials missing")
        _assert(credentials.access_key == "fallback-bithumb-access", "fallback access mismatch")
        _assert(
            credentials.source_path == fallback_dir / "bithumb.json",
            "fallback path mismatch",
        )
        print("PASS exchange key loader uses ~/.key-style fallback path")

        _write(
            fallback_dir / "coinone.json",
            '{"access_token":"legacy-coinone-access","secret_key":"legacy-coinone-secret"}',
        )
        credentials = load_exchange_trading_credentials(
            "coinone",
            primary_dir=primary_dir,
            fallback_dir=fallback_dir,
        )
        _assert(credentials is not None, "legacy coinone credentials missing")
        _assert(
            credentials.access_key == "legacy-coinone-access",
            "legacy field normalization mismatch",
        )
        print("PASS exchange key loader normalizes legacy access key aliases")

        _write(
            fallback_dir / "bithumb.json",
            '{"api_key":"legacy-bithumb-access","secret_key":"legacy-bithumb-secret"}',
        )
        credentials = load_exchange_trading_credentials(
            "bithumb",
            primary_dir=primary_dir,
            fallback_dir=fallback_dir,
        )
        _assert(credentials is not None, "legacy bithumb credentials missing")
        _assert(
            credentials.access_key == "legacy-bithumb-access",
            "legacy bithumb alias mismatch",
        )

        _write(
            fallback_dir / "upbit.json",
            '{"access_key":"config-upbit-access","secret_key":"config-upbit-secret"}',
        )
        previous_primary = None
        previous_fallback = None
        try:
            import os

            previous_primary = os.environ.get("TP_EXCHANGE_KEY_PRIMARY_DIR")
            previous_fallback = os.environ.get("TP_EXCHANGE_KEY_FALLBACK_DIR")
            os.environ["TP_EXCHANGE_KEY_PRIMARY_DIR"] = str(primary_dir / "missing")
            os.environ["TP_EXCHANGE_KEY_FALLBACK_DIR"] = str(fallback_dir)
            config = load_config()
            credentials = load_exchange_trading_credentials_from_config(config, "upbit")
            _assert(credentials is not None, "config helper credentials missing")
            _assert(credentials.access_key == "config-upbit-access", "config helper mismatch")
        finally:
            import os

            if previous_primary is None:
                os.environ.pop("TP_EXCHANGE_KEY_PRIMARY_DIR", None)
            else:
                os.environ["TP_EXCHANGE_KEY_PRIMARY_DIR"] = previous_primary
            if previous_fallback is None:
                os.environ.pop("TP_EXCHANGE_KEY_FALLBACK_DIR", None)
            else:
                os.environ["TP_EXCHANGE_KEY_FALLBACK_DIR"] = previous_fallback
        print("PASS exchange key loader config helper")

        _write(
            fallback_dir / "coinone.json",
            '{"access_key":"broken-only"}',
        )
        try:
            load_exchange_trading_credentials(
                "coinone",
                primary_dir=primary_dir,
                fallback_dir=fallback_dir,
            )
        except ValueError as exc:
            _assert("secret_key" in str(exc), "invalid file should mention missing secret_key")
        else:
            raise AssertionError("invalid credential file should raise ValueError")
        print("PASS exchange key loader invalid payload")


if __name__ == "__main__":
    main()
