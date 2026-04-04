from __future__ import annotations

import logging

from .config import load_config
from .logging_setup import configure_logging
from .server import build_server


LOGGER = logging.getLogger(__name__)


def main() -> None:
    config = load_config()
    log_path = configure_logging(config)
    server = build_server(config)
    server.market_data_runtime.start()

    LOGGER.info(
        "starting %s on %s:%s log=%s store=%s mode=%s redis=%s market_data=%s",
        config.service_name,
        config.host,
        config.port,
        log_path,
        server.store_bootstrap.backend_name,
        server.store_bootstrap.mode,
        server.redis_runtime.info.state,
        server.market_data_runtime.info.state,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("shutdown requested by keyboard interrupt")
    finally:
        server.market_data_runtime.stop()
        server.server_close()
        LOGGER.info("server stopped")


if __name__ == "__main__":
    main()
