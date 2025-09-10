"""Slice info tool for filtering slices by name."""

import logging
from typing import Optional
from .base import BaseTool

logger = logging.getLogger(__name__)


class SliceInfoTool(BaseTool):
    """Tool for retrieving information about slices with a given name."""

    def get_slice_info(self, trace_path: str, slice_name: str, package_name: Optional[str] = None) -> str:
        """Implementation for filtering and retrieving slice information by name.

        Returns a unified JSON envelope.
        """

        def _get_slice_info_operation(tp):
            """Internal operation to get slice info and build result payload."""
            # Basic sanitization for embedding into SQL string
            safe_name = slice_name.replace("'", "''")

            # Count matching slices
            count_query = f"SELECT COUNT(*) AS slice_count FROM slice WHERE name = '{safe_name}'"
            count = 0
            qr_it = tp.query(count_query)
            for row in qr_it:
                count = getattr(row, 'slice_count', 0)
                break

            # Fetch sample rows (up to 5)
            sample_query = f"SELECT ts, dur, name FROM slice WHERE name = '{safe_name}' LIMIT 5"
            qr_it = tp.query(sample_query)
            sample_slices = []
            for row in qr_it:
                sample_slices.append({
                    "ts": getattr(row, 'ts', None),
                    "dur": getattr(row, 'dur', None),
                    "name": getattr(row, 'name', None),
                })

            return {
                "sliceName": slice_name,
                "totalCount": int(count),
                "sampleSlices": sample_slices,
            }

        return self.run_formatted(trace_path, package_name, _get_slice_info_operation)
