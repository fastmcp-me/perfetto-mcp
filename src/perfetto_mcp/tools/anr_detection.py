"""ANR detection tool for analyzing Application Not Responding events."""

import json
import logging
from typing import Optional, Dict, Any
from .base import BaseTool
from ..utils.query_helpers import format_query_result_row

logger = logging.getLogger(__name__)


class AnrDetectionTool(BaseTool):
    """Tool for detecting and analyzing ANR events in Perfetto traces."""
    
    def detect_anrs(
        self, 
        trace_path: str, 
        process_name: Optional[str] = None,
        min_duration_ms: int = 5000,
        time_range: Optional[Dict[str, int]] = None
    ) -> str:
        """
        Detect ANR events in a Perfetto trace with contextual analysis.
        
        Args:
            trace_path: Path to the Perfetto trace file
            process_name: Optional process name to filter (supports glob patterns)
            min_duration_ms: Minimum ANR duration threshold (default: 5000ms)
            time_range: Optional dict with 'start_ms' and 'end_ms' keys
            
        Returns:
            str: JSON string with ANR detection results
        """
        
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
            qr_it = tp.query(sql_query)
            
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
                    row_dict['timestamp_ms'] = int(row_dict['ts'] / 1e6)
                
                # Add severity analysis
                severity = self._analyze_anr_severity(row_dict)
                row_dict['severity'] = severity
                
                anrs.append(row_dict)
            
            # Create structured result
            result = {
                "success": True,
                "total_anr_count": len(anrs),
                "anrs": anrs,
                "filters_applied": {
                    "process_name": process_name,
                    "min_duration_ms": min_duration_ms,
                    "time_range": time_range
                }
            }
            
            return json.dumps(result, indent=2)
        
        try:
            return self.execute_with_connection(trace_path, _execute_anr_detection)
        except FileNotFoundError as fnf:
            error_result = {
                "success": False,
                "error": "File not found",
                "message": f"Failed to open the trace file. Please double-check the trace_path. Error: {str(fnf)}",
                "total_anr_count": 0,
                "anrs": []
            }
            return json.dumps(error_result, indent=2)
        except Exception as e:
            # Check if it's an ANR module availability issue
            error_msg = str(e).lower()
            if 'android.anrs' in error_msg or 'no such table' in error_msg:
                error_result = {
                    "success": False,
                    "error": "ANR data not available",
                    "message": "This trace does not contain ANR data. ANR events are typically only available in Android system traces that include the 'android.anrs' data source.",
                    "suggestion": "Ensure the trace was captured with Android system tracing enabled and includes ANR detection.",
                    "total_anr_count": 0,
                    "anrs": []
                }
            else:
                error_result = {
                    "success": False,
                    "error": type(e).__name__,
                    "message": f"ANR detection failed: {str(e)}",
                    "total_anr_count": 0,
                    "anrs": []
                }
            return json.dumps(error_result, indent=2)
    
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