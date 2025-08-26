"""Slice info tool for filtering slices by name."""

import logging
from .base import BaseTool

logger = logging.getLogger(__name__)


class SliceInfoTool(BaseTool):
    """Tool for retrieving information about slices with a given name."""
    
    def get_slice_info(self, trace_path: str, slice_name: str) -> str:
        """Implementation for filtering and retrieving slice information by name."""
        def _get_slice_info_operation(tp):
            """Internal operation to get slice info."""
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
        
        try:
            return self.execute_with_connection(trace_path, _get_slice_info_operation)
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
