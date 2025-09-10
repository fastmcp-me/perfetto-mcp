# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

**Setup and Dependencies:**
- `uv sync` - Install dependencies and create virtual environment
- `uv add <package>` - Add new dependency

**Running the Server:**
- `uv run mcp dev main.py` - Run MCP server with development tooling
- `uv run python main.py` - Run MCP server directly

**Testing:**
- `uv run pytest -q` - Run test suite (when tests are added)

## Architecture Overview

This is a Model Context Protocol (MCP) server that provides tools for analyzing Perfetto trace files. The server is built using FastMCP with a modular architecture and persistent connection management.

**New Modular Structure:**
```
src/perfetto_mcp/
├── server.py                # Main MCP server with lifecycle management
├── connection_manager.py    # Persistent connection management
├── tools/                   # Individual tool implementations
│   ├── base.py              # Base tool class
│   ├── slice_info.py        # get_slice_info tool
│   └── sql_query.py         # execute_sql_query tool
└── utils/
    └── query_helpers.py     # SQL utilities and validation
```

**Core Components:**
- `ConnectionManager` - Manages persistent TraceProcessor connections with automatic switching and reconnection
- `BaseTool` - Base class providing connection management and error handling for all tools
- `FastMCP Server` - Configured with proper lifecycle management and cleanup handlers

**Available Tools:**
1. `get_slice_info(trace_path, slice_name)` - Filter slices by name with counts and samples  
2. `execute_sql_query(trace_path, sql_query)` - Execute arbitrary SQL queries (limited to 50 rows)

**Connection Management Pattern:**
- Tools use `ConnectionManager` to get persistent connections
- Automatic connection reuse for same trace file
- Automatic connection switching for different trace files
- Reconnection on connection failures
- Proper cleanup on server shutdown

**Error Handling Pattern:**
All tools inherit from `BaseTool` with:
- `FileNotFoundError` - Invalid trace file paths
- `ConnectionError` - TraceProcessor connection issues
- Automatic reconnection attempts on connection failures
- Graceful fallback to error messages when reconnection fails

**Key Improvements:**
- **Performance**: Persistent connections eliminate overhead of opening/closing for each query
- **Reliability**: Automatic reconnection handles connection failures gracefully
- **Maintainability**: Modular structure makes code easier to understand and extend
- **Thread Safety**: Proper locking mechanisms for concurrent tool calls

**Safety Constraints:**
- SQL queries auto-limited to 50 rows for performance
- Only SELECT queries allowed for security (validated in `utils/query_helpers.py`)
- All tools return string responses (JSON for execute_sql_query)
- Thread-safe connection management with proper locking

**Lifecycle Management:**
- Server uses multiple cleanup strategies: atexit, signal handlers
- ConnectionManager handles graceful connection cleanup
- Proper resource management in all shutdown scenarios

**Dependencies:**
- Requires Python >=3.13
- Key packages: `mcp[cli]`, `perfetto`, `protobuf<5`
- Uses `uv` for dependency management and virtual environments

## MCP Resources

The server provides MCP resources for documentation:

- **`resource://perfetto-mcp/concepts`**
  - Text/Markdown reference for Perfetto analysis concepts and workflows
  - Backed by: `docs/Perfetto-MCP-Concepts.md`
  - MIME: `text/markdown`
  - Access via: `list_resources` and `read_resource` tools

- **`resource://perfetto-docs/trace-analysis-getting-started`**
  - URL resource pointing to official Perfetto trace analysis documentation
  - References: `https://perfetto.dev/docs/analysis/getting-started`
  - MIME: `text/markdown`
  - Provides context for using MCP tools with official Perfetto workflow guidance

## Coding Standards & Conventions

**Code Style:**
- Python style: PEP 8, 4-space indentation, line length ~100
- Naming: `snake_case` for functions/vars, `CapWords` for classes, module files in `snake_case`
- Type hints: Use `typing` annotations and docstrings for public tools
- MCP tools: Decorate with `@mcp.tool()` and return concise, user-facing strings or JSON

**Security Guidelines:**
- Never commit trace files; add large traces to `.gitignore` and reference local paths
- SQL safety: Avoid interpolating untrusted input into queries; validate/escape user-provided strings and keep row limits (e.g., `LIMIT 50`)
- Only SELECT queries allowed for security (validated in `utils/query_helpers.py`)

## Key Design Decisions

**Connection Strategy:**
- Single connection per trace file (one active connection at a time)
- Automatic switching when trace_path changes
- No timeouts - reconnection on demand
- Thread-safe operations with locks

**Error Recovery:**
- Automatic reconnection attempts on connection failures
- Preserve original error messages for backward compatibility
- Don't close connections on query errors (only on connection failures)

## Development Workflow

**Adding New Tools:**
- Add tools in individual modules under `src/perfetto_mcp/tools/`
- Inherit from `BaseTool` for connection management and error handling
- Register with `@mcp.tool()` decorator in the server
- Ensure resources are properly managed (connections closed in `finally` blocks)
- Provide clear parameter documentation and predictable return shapes

**Testing Guidelines:**
- Framework: Prefer `pytest` with tests under `tests/` mirroring module names
- Naming: `test_<module>.py` and `test_<behavior>()` function names
- Coverage: Focus on critical path coverage of tool functions and error handling
- Running: `uv run pytest -q` (add `-k <expr>` to filter)

**Module Structure:**
- Entry point: `main.py` - MCP server entrypoint exposing Perfetto tools
- Core server: `src/perfetto_mcp/server.py` - FastMCP server with lifecycle management
- Connection management: `src/perfetto_mcp/connection_manager.py` - Persistent TraceProcessor connections
- Tools: `src/perfetto_mcp/tools/` - Individual tool implementations inheriting from `BaseTool`
- Utilities: `src/perfetto_mcp/utils/` - SQL utilities and validation helpers
- Resources: `src/perfetto_mcp/resource/` - MCP resources registration and management
