"""Main MCP server setup with lifecycle management."""

import atexit
import logging
from mcp.server.fastmcp import FastMCP
from .connection_manager import ConnectionManager
from .tools.trace_data import TraceDataTool
from .tools.slice_info import SliceInfoTool
from .tools.sql_query import SqlQueryTool

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
        """Get trace data from a trace file"""
        return trace_data_tool.get_trace_data(trace_path)
    
    @mcp.tool()
    def get_slice_info(trace_path: str, slice_name: str) -> str:
        """
        Retrieve information about slices with a given name from a Perfetto trace.

        Parameters
        ----------
        trace_path : str
            Path to the Perfetto trace file.
        slice_name : str
            Name of the slice you want to inspect.

        Returns
        -------
        str
            Summary including the total number of matching slices and a few example rows.
        """
        return slice_info_tool.get_slice_info(trace_path, slice_name)
    
    @mcp.tool()
    def execute_sql_query(trace_path: str, sql_query: str) -> str:
        """
        Execute any SQL query on a Perfetto trace and return results in JSON format.
        Results are limited to a maximum of 50 rows for performance.

        Parameters
        ----------
        trace_path : str
            Path to the Perfetto trace file.
        sql_query : str
            The SQL query to execute against the trace database.

        Returns
        -------
        str
            JSON string containing the query results with columns and rows,
            or an error message if the query fails.
        """
        return sql_query_tool.execute_sql_query(trace_path, sql_query)
    
    # Setup cleanup using atexit - the simplest and most reliable approach
    atexit.register(connection_manager.cleanup)
    
    logger.info("Perfetto MCP server created with connection management")
    
    return mcp
