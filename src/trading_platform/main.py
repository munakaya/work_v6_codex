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

    LOGGER.info(
        "starting %s on %s:%s log=%s",
        config.service_name,
        config.host,
        config.port,
        log_path,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("shutdown requested by keyboard interrupt")
    finally:
        server.server_close()
        LOGGER.info("server stopped")


if __name__ == "__main__":
    main()
