"""Entry point for the Perfetto MCP server."""

import logging
import signal
import sys
import os
from src.perfetto_mcp.server import create_server

logger = logging.getLogger(__name__)


def setup_signal_handlers():
    """Setup signal handlers for immediate exit."""
    def signal_handler(signum, frame):
        logger.info("Received shutdown signal, exiting immediately...")
        # Cleanup will be handled by atexit handlers
        os._exit(0)  # Force immediate exit without cleanup of threads
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Termination signal


if __name__ == "__main__":
    # Setup signal handling before starting server
    setup_signal_handlers()
    
    try:
        # Create and run the server
        mcp = create_server()
        mcp.run(transport="stdio")
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down gracefully...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Server error: {e}")
        sys.exit(1)