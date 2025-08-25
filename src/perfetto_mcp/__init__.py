"""Perfetto MCP Server - A Model Context Protocol server for analyzing Perfetto trace files."""

__version__ = "0.1.0"
__author__ = "Perfetto MCP Team"

from .connection_manager import ConnectionManager
from .server import create_server

__all__ = ["ConnectionManager", "create_server"]
