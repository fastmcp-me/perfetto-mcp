"""Register Perfetto docs as concrete MCP resources using the decorator API."""

import logging
from pathlib import Path

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register_concepts_resource(mcp: FastMCP) -> None:
    """Register a concrete resource for the Perfetto concepts doc.

    - Concrete resource for quick discovery via list_resources()
      URI: resource://perfetto-mcp/concepts
    """
    repo_root = Path(__file__).resolve().parents[3]
    docs_dir = (repo_root / "docs").resolve()
    concepts_file = (docs_dir / "Perfetto-MCP-Concepts.md").resolve()

    # resource://perfetto-mcp/concepts
    @mcp.resource(
        "resource://perfetto-mcp/concepts",
        name="perfetto-mcp-concepts",
        title="Perfetto MCP Concepts",
        description="Reference guide for Perfetto trace analysis and MCP usage.",
        mime_type="text/markdown",
    )
    def read_concepts() -> str:
        try:
            return concepts_file.read_text()
        except Exception as e:
            logger.warning(f"Failed to read concepts doc: {e}")
            raise
