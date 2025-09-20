"""Development entrypoint for MCP dev tooling."""

import os
import sys

try:
    # Prefer absolute import so this works when executed as a standalone file
    from perfetto_mcp.server import create_server  # type: ignore
except ImportError:
    # If imported via raw file path (no package context), add `src` to sys.path
    current_dir = os.path.dirname(__file__)
    src_dir = os.path.dirname(current_dir)
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    from perfetto_mcp.server import create_server  # type: ignore


# Top-level server instance expected by `mcp dev` tooling
mcp = create_server()

__all__ = ["mcp"]
