"""Development entrypoint for MCP dev tooling."""

import os
import sys
from pathlib import Path

# Ensure the project `src` directory is on sys.path when running as a raw file
current_file = Path(__file__).resolve()
src_dir = current_file.parents[1]  # .../repo/src
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from perfetto_mcp.server import create_server  # type: ignore


# Top-level server instance expected by `mcp dev` tooling
mcp = create_server()

__all__ = ["mcp"]
