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
├── __init__.py              # Package initialization and stdio entrypoint
├── __main__.py              # Enables `python -m perfetto_mcp`
├── server.py                # MCP server setup with lifecycle management
├── dev.py                   # Dev entry for `mcp dev` (exports `mcp`)
├── connection_manager.py    # Persistent TraceProcessor connection management
├── resource/                # MCP resources registration
│   ├── __init__.py          # register_resources(mcp)
│   ├── concepts.py          # concepts markdown as FileResource
│   └── trace_analysis.py    # trace analysis URL resource
├── tools/
│   ├── __init__.py
│   ├── base.py                             # Base tool with connection mgmt + formatting
│   ├── find_slices.py                      # find_slices tool
│   ├── sql_query.py                        # execute_sql_query tool
│   ├── anr_detection.py                    # detect_anrs tool
│   ├── anr_root_cause.py                   # anr_root_cause_analyzer tool
│   ├── cpu_utilization.py                  # cpu_utilization_profiler tool
│   ├── jank_frames.py                      # detect_jank_frames tool
│   ├── frame_performance_summary.py        # frame_performance_summary tool
│   ├── memory_leak_detector.py             # memory_leak_detector tool
│   ├── heap_dominator_tree_analyzer.py     # heap_dominator_tree_analyzer tool
│   ├── thread_contention_analyzer.py       # thread_contention_analyzer tool
│   ├── binder_transaction_profiler.py      # binder_transaction_profiler tool
│   └── main_thread_hotspots.py             # main_thread_hotspot_slices tool
└── utils/
    ├── __init__.py
    └── query_helpers.py     # SQL script guardrails and formatting helpers
```

### Key Components

- **ConnectionManager**: Manages persistent TraceProcessor connections with automatic switching and reconnection
- **BaseTool**: Base class providing connection management and error handling for all tools
- **Server Lifecycle**: Proper cleanup handlers for graceful shutdown and connection management

## Available Tools

### 1. `find_slices(trace_path, pattern, process_name=None, match_mode='contains', limit=100, main_thread_only=False, time_range=None)`
Discover slices by flexible name matching and return aggregates plus examples without writing SQL.
Returns a JSON envelope with `result = { matchMode, filters, timeRangeMs, aggregates: [...], examples: [...], notes }`.

### 2. `execute_sql_query(trace_path, sql_query, process_name=None)`
Execute PerfettoSQL scripts (multi-statement) against the trace database. The script is executed
verbatim by TraceProcessor. If the final statement is a `SELECT`, rows are returned; otherwise,
the result has `rowCount = 0` and `columns = []`.

Notes:
- Supports full PerfettoSQL, including `INCLUDE PERFETTO MODULE` (wildcards allowed where supported),
  `CREATE PERFETTO TABLE/VIEW/INDEX/MACRO/FUNCTION`, and standard SQLite statements (e.g., `PRAGMA`).
- No automatic `LIMIT` is applied. Consider adding `LIMIT` to avoid large result sets.
- Guardrails: the server enforces basic caps (script size and optional statement count). Scripts are
  otherwise passed through without keyword blocking.

### 3. `detect_anrs(trace_path, process_name=None, min_duration_ms=5000, time_range=None)`
Detect Application Not Responding (ANR) events in Android traces with contextual details and severity analysis.

### 4. `anr_root_cause_analyzer(trace_path, process_name=None, anr_timestamp_ms=None, analysis_window_ms=10000, time_range=None, deep_analysis=False)`
Analyze likely ANR root causes by correlating multiple signals within a time window (main thread blocking, slow Binder transactions, memory pressure, Java monitor contention). Returns a structured envelope with an insights section and per-signal details.

### 5. `cpu_utilization_profiler(trace_path, process_name, group_by='thread', include_frequency_analysis=True)`
Profile CPU utilization for a process with a per-thread breakdown (runtime, scheduling stats, CPU percent). Optionally includes CPU frequency (DVFS) summary when available.

### 6. `detect_jank_frames(trace_path, process_name, jank_threshold_ms=16.67, severity_filter=None)`
Identify janky frames for a process with severity and source classification (Application vs SurfaceFlinger), including overrun, CPU/UI time, and layer name.
Returns a JSON envelope with `result = { totalCount, frames: [...], filters }` where each frame row contains:
`{ frame_id, timestamp_ms, duration_ms, overrun_ms, jank_type, jank_severity_type, jank_source, cpu_time_ms, ui_time_ms, layer_name, jank_classification }`.

Notes for `detect_jank_frames`:
- Requires Android frame timeline data. The tool first uses standard library modules (`android.frames.timeline`, `android.frames.per_frame_metrics`).
- If those are missing, it falls back to raw `actual_frame_timeline_slice`/`expected_frame_timeline_slice` tables and computes `overrun_ms` without CPU/UI time (returned as null) to remain useful on leaner traces.

### 7. `frame_performance_summary(trace_path, process_name)`
Aggregated frame performance metrics and jank statistics for a process.
Returns a JSON envelope with `result = { total_frames, jank_frames, jank_rate_percent, slow_frames, big_jank_frames, huge_jank_frames, avg_cpu_time_ms, max_cpu_time_ms, p95_cpu_time_ms, p99_cpu_time_ms, performance_rating }`.
Requires per-frame metrics; if unavailable, returns a `FRAME_METRICS_UNAVAILABLE` error with details.

### 8. `memory_leak_detector(trace_path, process_name, growth_threshold_mb_per_min=5.0, analysis_duration_ms=60000)`
Detects memory leaks using process RSS growth patterns and heap graph aggregation.
Returns a JSON envelope with `result = { growth: { avgGrowthRateMbPerMin, maxGrowthRateMbPerMin, sampleCount, leakIndicatorCount }, suspiciousClasses: [{ type_name, obj_count, size_mb, dominated_obj_count, dominated_size_mb }], filters, notes }`.
If RSS or heap graph data are unavailable, returns partial results with `notes` explaining what’s missing.

### 9. `heap_dominator_tree_analyzer(trace_path, process_name, max_classes=20)`
Analyzes the latest heap graph snapshot for a process to surface classes dominating heap usage.
Returns a JSON envelope with `result = { totalCount, classes: [{ display_name, instance_count, self_size_mb, native_size_mb, total_size_mb, avg_reachability, min_root_distance, memory_impact }], filters, notes }`.
If extended heap graph columns or modules are missing, falls back to a simplified query (without `native_size_mb`, `avg_reachability`, `min_root_distance`) and adds a `notes` entry. If no heap graph exists in the trace, returns `HEAP_GRAPH_UNAVAILABLE`.

### 10. `thread_contention_analyzer(trace_path, process_name, time_range=None, min_block_ms=50.0, include_per_thread_breakdown=False, include_examples=False, limit=80)`
Identifies thread contention and synchronization bottlenecks with time scoping, minimum-duration filtering, optional per-thread blocked-state breakdown, example waits, and automatic fallback when monitor contention data is unavailable.

Returns a JSON envelope with `result = { totalCount, contentions: [...], filters, analysisSource, usesWakerLinkage?, usedSchedBlockedReason?, primaryDataUnavailable?, fallbackNotice?, timeRangeMs?, thresholds, dataDependencies, notes?, blocked_state_breakdown?, top_dstate_functions?, examples? }` where each contention row contains:
`{ blocked_thread_name, blocking_thread_name, short_blocking_method_name, contention_count, total_blocked_ms, avg_blocked_ms, max_blocked_ms, total_waiters, max_concurrent_waiters, blocked_is_main_thread?, severity }`.

Notes:
- **Primary analysis**: Uses `android.monitor_contention` when available; `min_block_ms` filters out short waits before aggregation; `time_range` restricts to the window.
- **Automatic fallback**: Infers from `thread_state` with waker linkage and optional `sched_blocked_reason` attribution; same `time_range` and thresholding.
- **Breakdown**: If `include_per_thread_breakdown=True`, returns per-thread S/D totals and percentages for the same window.
- **Examples**: If `include_examples=True`, returns the longest waits (from primary or fallback path) capped by `limit`.

### 11. `binder_transaction_profiler(trace_path, process_filter, min_latency_ms=10.0, include_thread_states=True, time_range=None, correlate_with_main_thread=False, group_by=None)`
Analyzes binder transaction performance and identifies bottlenecks using the `android.binder` module.

Returns a JSON envelope with results depending on `group_by`:
- When `group_by=None`: `result = { totalCount, timeRangeMs?, transactions: [...], filters }` where each row contains:
  `{ client_process, server_process, aidl_name, method_name, client_latency_ms, server_latency_ms, overhead_ms, overhead_ratio, is_main_thread, is_sync, top_thread_states, main_thread_top_states?, latency_severity }`.
- When grouped (`'aidl'` or `'server_process'`): `result = { totalCount, timeRangeMs?, aggregates: [...], filters }` with aggregated counts and average latencies/overheads.

Parameters:
- `time_range`: Optional `{'start_ms': X, 'end_ms': Y}` to scope the analysis window by client timestamp.
- `correlate_with_main_thread`: If true, adds a best‑effort summary of client main-thread states for main-thread transactions.
- `group_by`: One of `None`, `'aidl'`, `'server_process'` to switch to aggregated views.

Notes:
- Requires `android.binder` views (`android_binder_txns`, `android_sync_binder_thread_state_by_txn`). If unavailable, returns `BINDER_DATA_UNAVAILABLE`.
- Filters transactions where either client or server matches `process_filter` and client latency >= `min_latency_ms`.
- When `include_thread_states` is true, includes the top thread states by time for each transaction.

### 12. `main_thread_hotspot_slices(trace_path, process_name, limit=80, time_range=None, min_duration_ms=None)`
Identify the longest-running slices on the main thread for a target process. Useful for ANR and jank triage.

Returns a JSON envelope with `result = { filters, timeRangeMs, dataDependencies, hotspots: [...], summary, notes }` where each hotspot row contains:
`{ sliceId, name, category, depth, trackId, trackName, tsMs, endTsMs, durMs, threadName, tid, isMainThread, processName, pid }`.

Notes:
- Filters by `thread.is_main_thread = 1` when available; otherwise falls back to heuristic `tid == pid` and reports this in `notes`.
- Supports `process_name` GLOB (e.g., `com.example.*`), optional `time_range = {start_ms, end_ms}`, and `min_duration_ms` threshold.


## MCP Resources

- `resource://perfetto-mcp/concepts`
  - Text/Markdown reference for Perfetto analysis concepts and workflows
  - Backed by: `docs/Perfetto-MCP-Concepts.md`
  - MIME: `text/markdown`
  - Discover via `list_resources`, read via `read_resource`

- `resource://perfetto-docs/trace-analysis-getting-started`
  - URL resource pointing to official Perfetto trace analysis documentation
  - References: `https://perfetto.dev/docs/analysis/getting-started`
  - MIME: `text/markdown`
  - Provides context for using MCP tools with official Perfetto workflow guidance

## Development Commands

**Setup and Dependencies:**
- `uv sync` - Install dependencies and create virtual environment
- `uv add <package>` - Add new dependency

**Running the Server:**
- `uv run mcp dev src/perfetto_mcp/dev.py` - Run MCP server with development tooling
- `uv run -m perfetto_mcp` - Run MCP server directly (stdio)
- `uvx perfetto-mcp` - Run installed console script

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

- **Permissive PerfettoSQL execution**: Scripts are executed verbatim by TraceProcessor
- **Guardrails**: Script size and statement-count caps (env-configurable); no keyword blocking
- **No automatic LIMIT**: Consider adding `LIMIT` to avoid large result sets

## Tool Output Schema

All tool calls return a consistent JSON envelope:

```
{
  "processName": "not-specified" | "<provided by caller>",
  "tracePath": "./trace.pftrace",
  "success": true,
  "error": null | { "code": "...", "message": "...", "details": "..." },
  "result": { ... tool-specific payload ... }
}
```

Examples:
- find_slices → `result = { matchMode, filters, timeRangeMs, aggregates, examples, notes }`
- execute_sql_query → `result = { query, columns, rows, rowCount, scriptStatementCount?, lastStatementType?, returnsRows }`
- detect_anrs → `result = { totalCount, anrs: [...], filters: { ... } }`
- anr_root_cause_analyzer → `result = { window, filters, mainThreadBlocks, binderDelays, memoryPressure, lockContention, insights, notes }`
- cpu_utilization_profiler → `result = { processName, groupBy, summary, threads, frequency }`
- detect_jank_frames → `result = { totalCount, frames: [...], filters }`
- thread_contention_analyzer → `result = { totalCount, contentions: [...], filters, analysisSource, usesWakerLinkage?, usedSchedBlockedReason?, primaryDataUnavailable?, fallbackNotice? }`

## Dependencies

- Requires Python >=3.10 (3.13+ recommended)
- Key packages: `mcp[cli]`, `perfetto`, `protobuf<5`

## Shutdown Handling

The server implements multiple cleanup strategies:
- Primary: `atexit` handlers for normal shutdown
- Secondary: Signal handlers for SIGTERM/SIGINT
- Graceful: Proper connection cleanup in all scenarios


## Usage Examples

Run the server (stdio):
- `uv run mcp dev src/perfetto_mcp/dev.py` (with dev tooling), or
- `uv run -m perfetto_mcp`, or
- `uvx perfetto-mcp`

Example tool calls (high level):
- `find_slices`: Provide `trace_path` and a `pattern` (default contains) to survey matching slices with stats and top examples.
- `execute_sql_query`: Provide a SELECT query. Dangerous statements are rejected.
- `detect_anrs`: Optionally filter by `process_name`, `min_duration_ms`, and a `{start_ms, end_ms}` window.
- `anr_root_cause_analyzer`: Provide the process and either an `anr_timestamp_ms` with an `analysis_window_ms` or an explicit `time_range`.
- `cpu_utilization_profiler`: Provide `process_name`; returns per-thread CPU usage breakdown. Optionally includes frequency analysis.
- `detect_jank_frames`: Provide `process_name`; optionally tune `jank_threshold_ms` and `severity_filter`.

## Data Prerequisites & Troubleshooting

- `detect_anrs`/`anr_root_cause_analyzer`: Require Android system traces with ANR data. If the ANR module/tables are absent, the tool returns an informative error.
- `detect_jank_frames`: Requires Android frame timeline data (Android S+). If standard library views are missing, the tool falls back to raw frame tables. If even those are absent, you likely didn't enable frame timeline in the trace config.
- `cpu_utilization_profiler`: Requires scheduler data (ftrace sched events) to compute per-thread runtime and scheduling stats.
- `thread_contention_analyzer`: Prefers `android.monitor_contention` data for precise Java lock details, but automatically falls back to scheduler-based inference if unavailable.

If you see a `*_DATA_UNAVAILABLE` error, re-capture with the relevant data sources enabled or provide a different trace.


## Reference Documents

- MCP Server: https://modelcontextprotocol.io/quickstart/server
- Python MCP SDK: https://github.com/modelcontextprotocol/python-sdk
- Perfetto Trace Analysis: https://perfetto.dev/docs/analysis/getting-started
- Perfetto TraceProcessor: https://perfetto.dev/docs/analysis/trace-processor-python

