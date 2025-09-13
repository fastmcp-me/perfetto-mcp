"""ANR detection tool for analyzing Application Not Responding events.

Notes:
- Requires android.anrs data source in the trace; otherwise returns ANR_DATA_UNAVAILABLE.
- Severity heuristic: CRITICAL if GC events near ANR > 10; HIGH if main thread state at ANR
  indicates sleep/IO wait (S/D) or GC > 5; MEDIUM otherwise. System-critical processes are
  escalated to at least HIGH.
- Parameter `min_duration_ms` is currently informational and not used to filter results.
"""

import json
import logging
from typing import Optional, Dict, Any
from .base import BaseTool, ToolError
from ..utils.query_helpers import format_query_result_row

logger = logging.getLogger(__name__)


class AnrDetectionTool(BaseTool):
    """Tool for detecting and analyzing ANR events in Perfetto traces."""

    def detect_anrs(
        self,
        trace_path: str,
        process_name: Optional[str] = None,
        min_duration_ms: int = 5000,
        time_range: Optional[Dict[str, int]] = None,
    ) -> str:
        """Detect ANR events and return a unified JSON envelope."""

        def _execute_anr_detection(tp):
            """Internal operation to execute ANR detection query."""

            # Build the SQL query based on the documentation
            sql_query = """
            INCLUDE PERFETTO MODULE android.anrs;

            SELECT 
              process_name,
              pid,
              upid,
              error_id,
              ts,
              subject,
              -- Find main thread state at ANR time
              (SELECT state FROM thread_state ts
               JOIN thread t USING(utid)
               WHERE t.upid = android_anrs.upid 
                 AND t.is_main_thread = 1
                 AND ts.ts <= android_anrs.ts
               ORDER BY ts.ts DESC LIMIT 1) as main_thread_state,
              -- Check for concurrent GC events
              (SELECT COUNT(*) FROM slice s
               WHERE s.name LIKE '%GC%'
                 AND s.ts BETWEEN android_anrs.ts - 5e9 AND android_anrs.ts) as gc_events_near_anr
            FROM android_anrs
            WHERE 1=1
            """

            # Add process name filter if specified
            if process_name:
                sql_query += f" AND process_name GLOB '{process_name}'"

            # Add time range filters if specified
            if time_range:
                if 'start_ms' in time_range:
                    sql_query += f" AND ts >= {time_range['start_ms']} * 1e6"
                if 'end_ms' in time_range:
                    sql_query += f" AND ts <= {time_range['end_ms']} * 1e6"

            sql_query += " ORDER BY ts"

            # Execute the query
            try:
                qr_it = tp.query(sql_query)
            except Exception as e:
                # Check if it's an ANR module availability issue
                error_msg = str(e).lower()
                if 'android.anrs' in error_msg or 'no such table' in error_msg:
                    raise ToolError(
                        "ANR_DATA_UNAVAILABLE",
                        "This trace does not contain ANR data. ANR events are typically only available in Android system traces that include the 'android.anrs' data source.",
                    )
                raise

            # Collect and format results
            anrs = []
            columns = None

            for row in qr_it:
                # Get column names from the first row
                if columns is None:
                    columns = list(row.__dict__.keys())

                # Convert row to dictionary
                row_dict = format_query_result_row(row, columns)

                # Convert timestamp from nanoseconds to milliseconds
                if 'ts' in row_dict and row_dict['ts'] is not None:
                    row_dict['timestampMs'] = int(row_dict['ts'] / 1e6)

                # Add severity analysis
                severity = self._analyze_anr_severity(row_dict)
                row_dict['severity'] = severity

                anrs.append(row_dict)

            # Result payload only; envelope is added by run_formatted
            return {
                "totalCount": len(anrs),
                "anrs": anrs,
                "filters": {
                    "process_name": process_name,
                    "min_duration_ms": min_duration_ms,
                    "time_range": time_range,
                },
            }

        return self.run_formatted(trace_path, process_name, _execute_anr_detection)

    def _analyze_anr_severity(self, anr_data: Dict[str, Any]) -> str:
        """
        Analyze the severity of an ANR event based on contextual data.
        
        Args:
            anr_data: Dictionary containing ANR event data
            
        Returns:
            str: Severity level ("CRITICAL", "HIGH", "MEDIUM", "LOW")
        """
        # Start with base severity
        severity = "MEDIUM"
        
        # Check main thread state - blocked main thread is more severe
        main_thread_state = anr_data.get('main_thread_state', '')
        if main_thread_state in ['D', 'S']:  # Disk sleep or interruptible sleep
            severity = "HIGH"
        elif main_thread_state == 'R':  # Running - less severe, likely CPU bound
            severity = "MEDIUM"
        
        # Check for GC pressure - high GC activity indicates memory issues
        gc_events = anr_data.get('gc_events_near_anr', 0)
        if gc_events > 10:
            severity = "CRITICAL"
        elif gc_events > 5:
            if severity == "MEDIUM":
                severity = "HIGH"
        
        # Check process name for system critical processes
        process_name = anr_data.get('process_name', '')
        system_critical_processes = [
            'system_server', 'com.android.systemui', 'com.android.launcher'
        ]
        if any(critical in process_name for critical in system_critical_processes):
            if severity in ["LOW", "MEDIUM"]:
                severity = "HIGH"
        
        return severity
