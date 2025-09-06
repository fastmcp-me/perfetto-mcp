"""MCP resource registration package.

Expose a single entrypoint `register_resources(mcp)` that wires up
all MCP resources for the server.
"""

from mcp.server.fastmcp import FastMCP

from .concepts import register_concepts_resource
from .trace_analysis import register_trace_analysis_resource


def register_resources(mcp: FastMCP) -> None:
    """Register all MCP resources on the given server instance."""
    register_concepts_resource(mcp)
    register_trace_analysis_resource(mcp)

