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

This is a Model Context Protocol (MCP) server that provides tools for analyzing Perfetto trace files. The server is built using FastMCP and exposes three main tools:

**Core Components:**
- `main.py` - Single-file MCP server with all tool definitions
- Uses `perfetto.trace_processor.TraceProcessor` for trace analysis
- All tools follow pattern: connect → query → format results → close connection

**Available Tools:**
1. `get_trace_data(trace_path)` - Basic trace statistics and sample slices
2. `get_slice_info(trace_path, slice_name)` - Filter slices by name with counts and samples  
3. `execute_sql_query(trace_path, sql_query)` - Execute arbitrary SQL queries (limited to 50 rows)

**Error Handling Pattern:**
All tools use try/catch with specific handling for:
- `FileNotFoundError` - Invalid trace file paths
- `ConnectionError` - TraceProcessor connection issues
- Always close TraceProcessor in finally block

**Key Constraints:**
- SQL queries auto-limited to 50 rows for performance
- All tools return string responses (JSON for execute_sql_query)
- SQL injection prevention through direct string embedding (consider parameterization for future tools)

**Dependencies:**
- Requires Python >=3.13
- Key packages: `mcp[cli]`, `perfetto`, `protobuf<5`