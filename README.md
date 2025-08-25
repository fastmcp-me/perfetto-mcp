# Perfetto MCP Server

A Model Context Protocol (MCP) server that provides tools for analyzing Perfetto trace files with persistent connection management and automatic reconnection support.

## Features

- **Persistent Connections**: Maintains trace connections across multiple tool calls for improved performance
- **Automatic Reconnection**: Handles connection failures gracefully with automatic retry logic
- **Modular Architecture**: Clean separation of concerns with dedicated modules for different functionalities
- **Thread-Safe**: Safe for concurrent tool calls with proper locking mechanisms

## Architecture

The server is organized into a modular structure:

```
src/perfetto_mcp/
├── __init__.py              # Package initialization
├── server.py                # Main MCP server setup with lifecycle management
├── connection_manager.py    # Persistent TraceProcessor connection management
├── tools/
│   ├── __init__.py
│   ├── base.py              # Base tool class with connection management
│   ├── trace_data.py        # get_trace_data tool
│   ├── slice_info.py        # get_slice_info tool
│   └── sql_query.py         # execute_sql_query tool
└── utils/
    ├── __init__.py
    └── query_helpers.py     # SQL query utilities and validation
```

### Key Components

- **ConnectionManager**: Manages persistent TraceProcessor connections with automatic switching and reconnection
- **BaseTool**: Base class providing connection management and error handling for all tools
- **Server Lifecycle**: Proper cleanup handlers for graceful shutdown and connection management

## Available Tools

### 1. `get_trace_data(trace_path)`
Get basic trace statistics and sample slice data.

### 2. `get_slice_info(trace_path, slice_name)`
Filter slices by name with counts and sample data.

### 3. `execute_sql_query(trace_path, sql_query)`
Execute arbitrary SQL queries against the trace database (limited to 50 rows for performance).

## Development Commands

**Setup and Dependencies:**
- `uv sync` - Install dependencies and create virtual environment
- `uv add <package>` - Add new dependency

**Running the Server:**
- `uv run mcp dev main.py` - Run MCP server with development tooling
- `uv run python main.py` - Run MCP server directly

**Testing:**
- `uv run pytest -q` - Run test suite (when tests are added)

## Connection Management

The server implements intelligent connection management:

- **Persistent Connections**: Connections remain open between tool calls for the same trace file
- **Automatic Switching**: Seamlessly switches connections when a different trace path is provided
- **Reconnection**: Automatically reconnects on connection failures without losing context
- **Cleanup**: Proper connection cleanup on server shutdown via multiple mechanisms

## Error Handling

The server maintains backward compatibility with the original error handling while adding new features:

- **FileNotFoundError**: Invalid trace file paths
- **ConnectionError**: TraceProcessor connection issues
- **Automatic Recovery**: Attempts reconnection on connection failures
- **Graceful Degradation**: Falls back to error messages when reconnection fails

## Safety Features

- **SQL Validation**: Only SELECT queries are allowed for security
- **Row Limiting**: All queries are automatically limited to 50 rows
- **Query Sanitization**: Basic validation to prevent dangerous operations

## Dependencies

- Requires Python >=3.13
- Key packages: `mcp[cli]`, `perfetto`, `protobuf<5`

## Shutdown Handling

The server implements multiple cleanup strategies:
- Primary: `atexit` handlers for normal shutdown
- Secondary: Signal handlers for SIGTERM/SIGINT
- Graceful: Proper connection cleanup in all scenarios
