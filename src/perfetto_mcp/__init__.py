"""Perfetto MCP Server - A Model Context Protocol server for analyzing Perfetto trace files."""

__version__ = "0.1.0"
__author__ = "Antariksh"

import logging
import os
import signal
import sys

from .connection_manager import ConnectionManager
from .server import create_server

__all__ = ["ConnectionManager", "create_server"]


logger = logging.getLogger(__name__)


def _setup_signal_handlers() -> None:
    """Install signal handlers for immediate termination on SIGINT/SIGTERM.

    This mirrors the behavior used during local development to ensure prompt
    shutdown without leaving background threads hanging.
    """

    def _signal_handler(signum, frame):  # type: ignore[unused-argument]
        logger.info("Received shutdown signal, exiting immediately...")
        os._exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)


def main() -> None:
    """Package entrypoint to run the MCP server over stdio.

    Enables both `python -m perfetto_mcp` and the `perfetto-mcp` console script.
    """
    _setup_signal_handlers()

    try:
        mcp = create_server()
        mcp.run(transport="stdio")
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down gracefully...")
        sys.exit(0)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(f"Server error: {exc}")
        sys.exit(1)
