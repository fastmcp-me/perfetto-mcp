from mcp.server.fastmcp import FastMCP
from perfetto.trace_processor import TraceProcessor
import json
from typing import Optional, List, Any

# Create an MCP server
mcp = FastMCP("Perfetto MCP")


@mcp.tool()
def get_trace_data(trace_path: str) -> str:
    """Get trace data from a trace file"""
    try:
        # Connect to the Perfetto trace
        tp = TraceProcessor(trace=trace_path)
        
        # Get basic information about the trace
        result = []
        result.append(f"Successfully connected to trace: {trace_path}")
        
        # Query basic trace information
        qr_it = tp.query('SELECT COUNT(*) as slice_count FROM slice;')
        for row in qr_it:
            result.append(f"Total slices in trace: {row.slice_count}")
        
        # Get some sample slice data
        qr_it = tp.query('SELECT ts, dur, name FROM slice LIMIT 5;')
        result.append("\nSample slice data:")
        for row in qr_it:
            result.append(f"  ts: {row.ts}, dur: {row.dur}, name: {row.name}")

        return "\n".join(result)

    except FileNotFoundError as fnf:
        return (
            "Failed to open the trace file. Please double‑check the `trace` path "
            f"you supplied. Underlying error: {fnf}"
        )
    except ConnectionError as ce:
        return (
            "Could not connect to the remote trace_processor at the given `addr`. "
            "Ensure it is running and reachable. Underlying error: "
            f"{ce}"
        )
    except Exception as e:
        return f"Error connecting to trace: {str(e)}"
    finally:
        # Close the trace processor
        tp.close()



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
    try:
        # Connect to the Perfetto trace
        tp = TraceProcessor(trace=trace_path)

        result = []
        result.append(f"Successfully connected to trace: {trace_path}")
        result.append(f"Filtering on slice name: '{slice_name}'")

        # Count matching slices – TraceProcessor.query() accepts only the SQL string, so we embed the slice name directly.
        count_query = f"SELECT COUNT(*) AS slice_count FROM slice WHERE name = '{slice_name}'"
        qr_it = tp.query(count_query)
        for row in qr_it:
            result.append(f"Total slices named '{slice_name}': {row.slice_count}")

        # Fetch sample rows for demonstration – embed slice name directly.
        sample_query = f"SELECT ts, dur, name FROM slice WHERE name = '{slice_name}' LIMIT 5"
        qr_it = tp.query(sample_query)
        result.append("\nSample matching slices:")
        for row in qr_it:
            result.append(f"  ts: {row.ts}, dur: {row.dur}, name: {row.name}")

        return "\n".join(result)

    except FileNotFoundError as fnf:
        return (
            "Failed to open the trace file. Please double‑check the `trace` path "
            f"you supplied. Underlying error: {fnf}"
        )
    except ConnectionError as ce:
        return (
            "Could not connect to the remote trace_processor. "
            "Ensure it is running and reachable. Underlying error: "
            f"{ce}"
        )
    except Exception as e:
        return f"Error retrieving slice info: {str(e)}"
    finally:
        # Always close the trace processor
        tp.close()



if __name__ == "__main__":
    mcp.run(transport="stdio")
