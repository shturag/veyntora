import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog
from veyntora_providers.scrub import scrub


def _scrub_processor(_logger: Any, _method: str, event: MutableMapping[str, Any]) -> Any:
    return scrub(dict(event))


def configure_logging(level: str = "INFO", *, json: bool = True) -> None:
    renderer: Any = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            _scrub_processor,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    # Route stdlib logs (uvicorn, sqlalchemy) through the same scrubber.
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_StdlibScrubFilter())
    logging.basicConfig(level=level, handlers=[handler], force=True)


class _StdlibScrubFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = scrub(record.getMessage())
        record.args = None
        return True
