"""Main MCP server setup with lifecycle management."""

import atexit
import logging
from mcp.server.fastmcp import FastMCP
from .connection_manager import ConnectionManager
from .tools.slice_info import SliceInfoTool
from .tools.sql_query import SqlQueryTool
from .tools.anr_detection import AnrDetectionTool
from .resource import register_resources

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_server() -> FastMCP:
    """Create and configure the Perfetto MCP server.
    
    Returns:
        FastMCP: Configured MCP server instance
    """
    # Create MCP server
    mcp = FastMCP("Perfetto MCP")
    
    # Initialize connection manager
    connection_manager = ConnectionManager()
    
    # Create tool instances
    slice_info_tool = SliceInfoTool(connection_manager)
    sql_query_tool = SqlQueryTool(connection_manager)
    anr_detection_tool = AnrDetectionTool(connection_manager)


    @mcp.tool()
    def get_slice_info(trace_path: str, slice_name: str, package_name: str | None = None) -> str:
        """
        Filter and summarize all occurrences of a specific slice (exact name).

        WHEN TO USE: Quickly understand how often a slice appears, its timing
        distribution at a glance, and see a few worst-case examples with context
        (process/thread/track).

        SEARCH BEHAVIOR: Performs EXACT case-sensitive string matching. "main" !=
        "Main" != "MAIN". The `slice_name` must match exactly what appears in the
        trace data.

        OUTPUT FIELDS (result):
        - sliceName: Input name
        - totalCount: Total number of matching slices
        - durationSummary: { minMs, avgMs, maxMs }
        - timeBounds: { earliestTsMs, latestTsMs, spanMs }
        - examples: Up to 50 longest instances with fields:
          { sliceId, tsMs, endTsMs, durMs, depth, category, trackName,
            process_name, pid, thread_name, tid, is_main_thread }

        Parameters
        ----------
        trace_path : str
            Path to the Perfetto trace file
        slice_name : str
            EXACT name of slice to analyze.

        Returns
        -------
        str
            JSON envelope with fields:
            - packageName, tracePath, success, error, result
            - result: see OUTPUT FIELDS above

        Notes
        -----
        - For complex filtering (duration > X, time ranges, process filters),
          use execute_sql_query() with WHERE clauses.
        """
        return slice_info_tool.get_slice_info(trace_path, slice_name, package_name)


    @mcp.tool()
    def execute_sql_query(trace_path: str, sql_query: str, package_name: str | None = None) -> str:
        """
        Execute arbitrary SQL queries against a Perfetto trace database.
        
        This is the most powerful tool for trace analysis, allowing you to write custom
        SQL queries against the trace database. The Perfetto trace database contains
        multiple tables (slice, thread, process, counter, etc.) that you can query
        using standard SQL syntax. Results return all matching rows (no automatic LIMIT is applied).

        Parameters
        ----------
        trace_path : str
            Absolute or relative path to the Perfetto trace file (.pftrace, .pb files).
            The file must be a valid Perfetto trace that can be opened by TraceProcessor.
        sql_query : str
            SQL query to execute against the trace database. Only SELECT statements are
            allowed for security reasons. Available tables include: slice, thread,
            process, counter, args, track, and many others.

        Returns
        -------
        str
            JSON envelope with fields:
            - packageName, tracePath, success, error, result
            - result: { query, columns, rows, rowCount }

        Security Notes
        -------------
        - Only SELECT queries are permitted
        - SQL injection protection through query validation

        Examples
        --------
        execute_sql_query("trace.pftrace", "SELECT name, COUNT(*) FROM slice GROUP BY name ORDER BY COUNT(*) DESC")
        execute_sql_query("trace.pb", "SELECT ts, dur, tid FROM slice WHERE dur > 1000000")
        execute_sql_query("trace.pftrace", "SELECT DISTINCT name FROM thread")
        execute_sql_query("trace.pb", "SELECT * FROM process WHERE name LIKE '%chrome%'")
        """
        return sql_query_tool.execute_sql_query(trace_path, sql_query, package_name)


    @mcp.tool()
    def detect_anrs(trace_path: str, process_name: str | None = None, min_duration_ms: int = 5000, time_range: dict | None = None, package_name: str | None = None) -> str:
        """
        Detect ANR (Application Not Responding) events in a Perfetto trace with contextual analysis.
        
        WHEN TO USE: Use this tool to identify ANR events in Android application traces. ANRs occur 
        when the main thread is blocked for more than 5 seconds (by default), causing the system 
        to show "App Not Responding" dialogs. This tool provides comprehensive analysis including 
        main thread state, GC pressure, and severity assessment.
        
        WHAT YOU GET: Structured JSON output with detailed ANR information including timestamps, 
        process details, main thread states, concurrent GC events, and severity analysis. Each 
        ANR includes contextual data to help understand root causes.
        
        ANR ANALYSIS CONTEXT: ANRs are critical performance issues that directly impact user 
        experience. They typically occur due to:
        - Main thread blocking operations (I/O, network, database)
        - Lock contention and synchronization issues
        - Memory pressure causing excessive GC
        - Binder transaction delays
        - CPU-intensive operations on the main thread
        
        SEVERITY LEVELS: Results include severity analysis:
        - CRITICAL: High GC pressure (>10 events) or system process ANRs
        - HIGH: Main thread in disk/interruptible sleep or moderate GC pressure
        - MEDIUM: Main thread running (CPU bound) or normal conditions
        - LOW: Minimal impact ANRs

        Parameters
        ----------
        trace_path : str
            Path to Perfetto trace file (.pftrace, .pb, or other Perfetto formats). The trace 
            must be from Android system tracing with ANR detection enabled. Typical sources 
            include systrace, perfetto system traces, or custom Android instrumentation.
        process_name : str, optional
            Filter ANRs by process name. Supports glob patterns (*, ?, [abc]). Examples:
            - "com.example.app" (exact match)
            - "com.example.*" (all processes starting with com.example.)
            - "*browser*" (any process containing 'browser')
            If None, returns ANRs from all processes.
        min_duration_ms : int, optional
            Minimum ANR duration threshold in milliseconds. Default is 5000ms (5 seconds),
            which is the standard Android ANR threshold. Lower values may include shorter
            blocking events that don't trigger system ANR dialogs.
        time_range : dict, optional
            Filter ANRs by time range with keys:
            - 'start_ms': Start time in milliseconds from trace beginning
            - 'end_ms': End time in milliseconds from trace beginning
            If None, analyzes the entire trace duration.

        Returns
        -------
        str
            JSON envelope with fields:
            - packageName, tracePath, success, error, result
            - result: {
                totalCount,
                anrs: [{ process_name, pid, upid, ts, timestampMs, subject, main_thread_state, gc_events_near_anr, severity }...],
                filters: { process_name, min_duration_ms, time_range }
              }

        AI Agent Usage Notes
        -------------------
        - ANR data requires Android system traces with 'android.anrs' data source enabled
        - Ensure the trace contains Android performance data
        - High ANR counts indicate systemic performance issues requiring investigation
        - Correlate ANR timestamps with other performance metrics (frame drops, memory pressure)
        - For detailed root cause analysis, use execute_sql_query() with ANR timestamps
        - Zero ANRs doesn't mean good performance - check trace coverage and data sources
        
        Common Follow-up Queries
        -----------------------
        - Thread state analysis around ANR timestamps
        - Binder transaction analysis during ANR periods  
        - Memory allocation patterns before ANRs
        - CPU utilization and scheduling data during ANRs
        """
        return anr_detection_tool.detect_anrs(trace_path, process_name, min_duration_ms, time_range, package_name)
    
    # Setup cleanup using atexit
    atexit.register(connection_manager.cleanup)

    # Register MCP resources in dedicated module
    register_resources(mcp)

    logger.info("Perfetto MCP server created with connection management")

    return mcp
