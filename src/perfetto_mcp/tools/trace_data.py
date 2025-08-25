"""Trace data tool for getting basic trace information."""

import logging
from .base import BaseTool

logger = logging.getLogger(__name__)


class TraceDataTool(BaseTool):
    """Tool for retrieving basic trace data and statistics."""
    
    def get_trace_data(self, trace_path: str) -> str:
        """Get trace data from a trace file.
        
        Args:
            trace_path: Path to the Perfetto trace file
            
        Returns:
            str: Basic trace information including slice count and sample data
        """
        def _get_trace_data_operation(tp):
            """Internal operation to get trace data."""
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
        
        try:
            return self.execute_with_connection(trace_path, _get_trace_data_operation)
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
