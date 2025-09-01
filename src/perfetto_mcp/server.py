"""Main MCP server setup with lifecycle management."""

import atexit
import logging
from mcp.server.fastmcp import FastMCP
from .connection_manager import ConnectionManager
from .tools.trace_data import TraceDataTool
from .tools.slice_info import SliceInfoTool
from .tools.sql_query import SqlQueryTool
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
    trace_data_tool = TraceDataTool(connection_manager)
    slice_info_tool = SliceInfoTool(connection_manager)
    sql_query_tool = SqlQueryTool(connection_manager)
    
    # Register tools with MCP server
    @mcp.tool()
    def get_trace_data(trace_path: str) -> str:
        """
        Get overview and sample data from a Perfetto trace file to understand what's available.
        
        WHEN TO USE: Always use this tool first when analyzing a new trace file. This gives you essential 
        context about the trace contents, total data volume, and examples of what types of events/slices 
        are recorded. This information helps you decide what specific queries to run next.
        
        WHAT YOU GET: Total slice count, sample slice names with timestamps and durations. Use the sample 
        slice names you see in the output for subsequent get_slice_info() calls or SQL queries.
        
        TRACE FILE CONTEXT: Perfetto traces contain performance data from Android, Chrome, or custom 
        applications. Slices represent time spans of operations like function calls, GPU work, system 
        calls, or user-defined events. Timestamps (ts) are in nanoseconds, durations (dur) in nanoseconds.

        Parameters
        ----------
        trace_path : str
            Path to Perfetto trace file (.pftrace, .pb, or other Perfetto formats). Can be absolute 
            or relative path. The trace should be from Android systrace, Chrome tracing, or custom 
            Perfetto instrumentation.

        Returns
        -------
        str
            Human-readable summary with:
            - Connection confirmation 
            - Total slice count (indicates trace size/complexity)
            - 5 sample slices with: ts (timestamp in ns), dur (duration in ns), name (event/function name)
            - Error details if trace cannot be opened
            
            Use slice names from samples in follow-up queries.

        AI Agent Usage Notes
        -------------------
        - Call this FIRST for any new trace analysis task
        - Extract slice names from the sample output for targeted analysis  
        - Use slice count to gauge trace complexity (>1M slices = large trace)
        - If trace won't open, suggest checking file path and format
        """
        return trace_data_tool.get_trace_data(trace_path)
    
    @mcp.tool()
    def get_slice_info(trace_path: str, slice_name: str) -> str:
        """
        Filter and analyze all occurrences of a specific named event/operation in the trace.
        
        WHEN TO USE: After get_trace_data() shows you available slice names, use this to analyze all instances 
        of a specific operation. Perfect for understanding patterns like: How often does X function run? 
        What's the timing distribution? Are there performance outliers?
        
        SEARCH BEHAVIOR: Performs EXACT case-sensitive string matching. "main" != "Main" != "MAIN". 
        The slice_name must match exactly what appears in the trace data.
        
        ANALYSIS WORKFLOW:
        1. Use get_trace_data() to see sample slice names
        2. Pick interesting slice name from samples  
        3. Use this tool to get count + detailed samples of that specific slice
        4. For complex analysis, use execute_sql_query() with WHERE name = 'slice_name'

        Parameters
        ----------
        trace_path : str
            Path to the same Perfetto trace file used in get_trace_data()
        slice_name : str
            EXACT name of slice to analyze. Must match case and spelling exactly as shown 
            in get_trace_data() output. Common patterns: function names (e.g. "main", "malloc"), 
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
        - Use slice names exactly as shown in get_trace_data() output
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
    
    # Setup cleanup using atexit - the simplest and most reliable approach
    atexit.register(connection_manager.cleanup)

    # Register MCP resources in dedicated module
    register_resources(mcp)

    logger.info("Perfetto MCP server created with connection management")

    return mcp
