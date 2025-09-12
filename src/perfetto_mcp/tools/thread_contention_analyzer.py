"""Thread contention analyzer using android.monitor_contention module."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from .base import BaseTool, ToolError
from ..utils.query_helpers import format_query_result_row

logger = logging.getLogger(__name__)


class ThreadContentionAnalyzerTool(BaseTool):
    """Identify thread contention and synchronization bottlenecks.

    Aggregates monitor contention events (Java synchronized blocks/methods) and
    groups contentions by blocked/blocking thread pairs and methods to compute
    contention statistics and severity.
    """

    def thread_contention_analyzer(self, trace_path: str, process_name: str) -> str:
        """Analyze thread contention for a given process.

        Parameters
        ----------
        trace_path : str
            Path to the Perfetto trace file.
        process_name : str
            Exact process name to analyze.

        Returns
        -------
        str
            JSON envelope with fields: processName, tracePath, success, error, result.
            Result shape:
              {
                totalCount: number,
                contentions: [
                  {
                    blocked_thread_name, blocking_thread_name, short_blocking_method_name,
                    contention_count, total_blocked_ms, avg_blocked_ms, max_blocked_ms,
                    total_waiters, max_concurrent_waiters, severity
                  }
                ],
                filters: { process_name }
              }
        """

        def _op(tp):
            if not process_name or not isinstance(process_name, str):
                raise ToolError("INVALID_PARAMETERS", "process_name must be a non-empty string")

            safe_proc = process_name.replace("'", "''")

            sql_query = f"""
            INCLUDE PERFETTO MODULE android.monitor_contention;

            WITH contention_analysis AS (
              SELECT 
                blocked_thread_name,
                blocking_thread_name,
                short_blocking_method_name,
                blocked_method_name,
                blocking_src,
                COUNT(*) as contention_count,
                SUM(dur) / 1e6 as total_blocked_ms,
                AVG(dur) / 1e6 as avg_blocked_ms,
                MAX(dur) / 1e6 as max_blocked_ms,
                SUM(waiter_count) as total_waiters,
                MAX(blocked_thread_waiter_count) as max_concurrent_waiters
              FROM android_monitor_contention
              WHERE upid = (SELECT upid FROM process WHERE name = '{safe_proc}')
              GROUP BY blocked_thread_name, blocking_thread_name, short_blocking_method_name
            ),
            critical_contentions AS (
              SELECT *
              FROM contention_analysis
              WHERE blocked_thread_name LIKE '%main%'
                 OR total_blocked_ms > 1000
                 OR max_blocked_ms > 100
              ORDER BY total_blocked_ms DESC
            )
            SELECT 
              blocked_thread_name,
              blocking_thread_name,
              short_blocking_method_name,
              contention_count,
              CAST(total_blocked_ms AS REAL) as total_blocked_ms,
              CAST(avg_blocked_ms AS REAL) as avg_blocked_ms,
              CAST(max_blocked_ms AS REAL) as max_blocked_ms,
              total_waiters,
              max_concurrent_waiters,
              CASE
                WHEN blocked_thread_name LIKE '%main%' AND max_blocked_ms > 100 THEN 'CRITICAL'
                WHEN max_blocked_ms > 500 THEN 'HIGH'
                WHEN avg_blocked_ms > 50 THEN 'MEDIUM'
                ELSE 'LOW'
              END as severity
            FROM critical_contentions;
            """

            try:
                rows = list(tp.query(sql_query))
            except Exception as e:
                msg = str(e)
                if (
                    "android_monitor_contention" in msg
                    or "android.monitor_contention" in msg
                    or "no such" in msg.lower()
                ):
                    raise ToolError(
                        "MONITOR_CONTENTION_UNAVAILABLE",
                        "Monitor contention data not available in this trace (module/tables missing).",
                        details=msg,
                    )
                raise

            contentions: List[Dict[str, Any]] = []
            columns = None
            for r in rows:
                if columns is None:
                    columns = list(r.__dict__.keys())
                contentions.append(format_query_result_row(r, columns))

            return {
                "totalCount": len(contentions),
                "contentions": contentions,
                "filters": {"process_name": process_name},
            }

        return self.run_formatted(trace_path, process_name, _op)

