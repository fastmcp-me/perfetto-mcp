"""Register Perfetto docs as concrete MCP resources using the decorator API."""

import logging
from importlib.resources import files as resource_files
from pathlib import Path

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def _read_concepts_markdown() -> str:
    """Read the concepts markdown from the installed package or dev repo.

    Priority:
    1) Packaged location: perfetto_mcp/docs/Perfetto-MCP-Concepts.md
    2) Dev fallback: <repo>/docs/Perfetto-MCP-Concepts.md
    """
    # Try packaged file first
    try:
        packaged_concepts = resource_files("perfetto_mcp") / "docs" / "Perfetto-MCP-Concepts.md"
        if packaged_concepts.is_file():
            return packaged_concepts.read_text(encoding="utf-8")
    except Exception as e:
        logger.debug(f"Packaged concepts read failed, will try dev fallback: {e}")

    # Dev fallback
    try:
        repo_root = Path(__file__).resolve().parents[3]
        concepts_file = (repo_root / "docs" / "Perfetto-MCP-Concepts.md").resolve()
        return concepts_file.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to read concepts doc from both packaged and dev paths: {e}")
        raise


def register_concepts_resource(mcp: FastMCP) -> None:
    """Register a concrete resource for the Perfetto concepts doc.

    - Concrete resource for quick discovery via list_resources()
      URI: resource://perfetto-mcp/concepts
    """

    # resource://perfetto-mcp/concepts
    @mcp.resource(
        "resource://perfetto-mcp/concepts",
        name="perfetto-mcp-concepts",
        title="Perfetto MCP Concepts",
        description="Reference guide for Perfetto trace analysis and MCP usage.",
        mime_type="text/markdown",
    )
    def read_concepts() -> str:
        return _read_concepts_markdown()
