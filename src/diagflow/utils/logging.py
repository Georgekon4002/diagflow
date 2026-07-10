"""
DiagFlow — Structured Logging Setup

Configures structlog for consistent, machine-readable logging.
In development: pretty-printed colored output.
In production: JSON lines for log aggregation.
"""

import logging
import sys

import structlog


def setup_logging(log_level: str = "DEBUG") -> None:
    """
    Configure structlog and stdlib logging.

    Args:
        log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR)
    """
    # Determine if we're in development
    is_dev = log_level.upper() == "DEBUG"

    # Choose renderer based on environment
    if is_dev:
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer(ensure_ascii=False)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            renderer,
        ],
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.DEBUG)
        ),
        cache_logger_on_first_use=True,
    )

    # Also configure stdlib logging for libraries
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.DEBUG),
    )
