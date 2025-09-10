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
    
    # Register tools with MCP server
    # Note: get_trace_data tool has been removed.
    
    @mcp.tool()
    def get_slice_info(trace_path: str, slice_name: str) -> str:
        """
        Filter and analyze all occurrences of a specific named event/operation in the trace.
        
        WHEN TO USE: Use this to analyze all instances of a specific operation by exact name. Perfect for understanding patterns like: How often does X function run? 
        What's the timing distribution? Are there performance outliers?
        
        SEARCH BEHAVIOR: Performs EXACT case-sensitive string matching. "main" != "Main" != "MAIN". 
        The slice_name must match exactly what appears in the trace data.
        
        ANALYSIS WORKFLOW:
        1. Identify an interesting slice name from the trace  
        2. Use this tool to get count + detailed samples of that specific slice
        3. For complex analysis, use execute_sql_query() with WHERE name = 'slice_name'

        Parameters
        ----------
        trace_path : str
            Path to the Perfetto trace file
        slice_name : str
            EXACT name of slice to analyze. Must match case and spelling exactly as it appears in the trace. Common patterns: function names (e.g. "main", "malloc"), 
            Android framework calls (e.g. "binder transaction"), GPU operations (e.g. "GPU Work"),
            web browser events (e.g. "Layout", "Paint").

        Returns
        -------
        str
            Human-readable analysis containing:
            - Connection confirmation + search criteria
            - Total count of matching slices (frequency analysis)
            - 5 sample occurrences with timing data: ts, dur, name
            - Zero results if slice name doesn't exist (check spelling/case)
            - Error details if trace access fails

        AI Agent Usage Notes
        -------------------
        - Use slice names exactly as they appear in the trace
        - Count tells you frequency (high count = hot path, low count = rare event)
        - Compare durations across samples to spot performance issues
        - If count is 0, the name doesn't exist - suggest similar names or SQL query
        - For complex filtering (duration > X, specific time ranges), use execute_sql_query()
        """
        return slice_info_tool.get_slice_info(trace_path, slice_name)
    
    @mcp.tool()
    def execute_sql_query(trace_path: str, sql_query: str) -> str:
        """
        Execute arbitrary SQL queries against a Perfetto trace database.
        
        This is the most powerful tool for trace analysis, allowing you to write custom
        SQL queries against the trace database. The Perfetto trace database contains
        multiple tables (slice, thread, process, counter, etc.) that you can query
        using standard SQL syntax. Results are automatically limited to 50 rows for performance.

        Parameters
        ----------
        trace_path : str
            Absolute or relative path to the Perfetto trace file (.pftrace, .pb files).
            The file must be a valid Perfetto trace that can be opened by TraceProcessor.
        sql_query : str
            SQL query to execute against the trace database. Only SELECT statements are
            allowed for security reasons. The query will automatically have LIMIT 50
            added if no LIMIT clause is present. Available tables include: slice, thread,
            process, counter, args, track, and many others.

        Returns
        -------
        str
            JSON string containing:
            - success: Boolean indicating if query executed successfully
            - query: The actual SQL query that was executed (with any added LIMIT)
            - columns: Array of column names in the result
            - rows: Array of result rows as dictionaries
            - row_count: Number of rows returned
            - limited_to_50: Boolean indicating if results were truncated to 50 rows
            - error/message: Error details if the query failed

        Security Notes
        -------------
        - Only SELECT queries are permitted
        - Results are automatically limited to 50 rows maximum
        - SQL injection protection through query validation

        Examples
        --------
        execute_sql_query("trace.pftrace", "SELECT name, COUNT(*) FROM slice GROUP BY name ORDER BY COUNT(*) DESC")
        execute_sql_query("trace.pb", "SELECT ts, dur, tid FROM slice WHERE dur > 1000000")
        execute_sql_query("trace.pftrace", "SELECT DISTINCT name FROM thread")
        execute_sql_query("trace.pb", "SELECT * FROM process WHERE name LIKE '%chrome%'")
        """
        return sql_query_tool.execute_sql_query(trace_path, sql_query)
    
    @mcp.tool()
    def detect_anrs(trace_path: str, process_name: str = None, min_duration_ms: int = 5000, time_range: dict = None) -> str:
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
            JSON string containing:
            - success: Boolean indicating if detection succeeded
            - total_anr_count: Number of ANR events found
            - anrs: Array of ANR objects with:
              - process_name, pid, upid: Process identification
              - timestamp_ms: ANR time in milliseconds from trace start
              - subject: ANR description/subject line
              - main_thread_state: State of main thread during ANR ('R'=Running, 'S'=Sleep, 'D'=Disk)
              - gc_events_near_anr: Count of GC events within 5 seconds before ANR
              - severity: Analysis-based severity level (CRITICAL/HIGH/MEDIUM/LOW)
            - filters_applied: Summary of filtering criteria used
            - error/message: Error details if detection fails

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
        return anr_detection_tool.detect_anrs(trace_path, process_name, min_duration_ms, time_range)
    
    # Setup cleanup using atexit - the simplest and most reliable approach
    atexit.register(connection_manager.cleanup)

    # Register MCP resources in dedicated module
    register_resources(mcp)

    logger.info("Perfetto MCP server created with connection management")

    return mcp
