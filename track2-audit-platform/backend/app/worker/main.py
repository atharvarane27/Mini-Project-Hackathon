import logging
import signal
import sys
import time
from types import FrameType

from app.config import get_settings
from app.core.logging import setup_logging

settings = get_settings()
logger = logging.getLogger("app.worker")

running = True


def signal_handler(signum: int, frame: FrameType | None) -> None:
    """Handle graceful termination signals."""
    global running
    sig_name = signal.Signals(signum).name
    logger.info("Termination signal received in worker", extra={"signal": sig_name})
    running = False


def main() -> None:
    """Worker entry point - future sole owner of in-memory heap and background dispatcher."""
    setup_logging(settings.LOG_LEVEL)
    logger.info(
        "AuditForge Worker starting up (single heap owner process)",
        extra={
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "db_backend": settings.DB_BACKEND,
        },
    )

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        while running:
            # Active idle polling loop until Phase P06/P07 queue & outbox logic is attached
            time.sleep(1)
    except Exception as exc:
        logger.error(
            "Worker encountered unexpected failure",
            extra={"error": str(exc)},
            exc_info=True,
        )
        sys.exit(1)
    finally:
        logger.info("AuditForge Worker gracefully terminated")


if __name__ == "__main__":
    main()
