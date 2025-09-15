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
                # Primary path succeeded - add metadata and return
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
                    "analysisSource": "monitor_contention",
                    "primaryDataUnavailable": False,
                }
            except Exception as e:
                msg = str(e)
                if self._is_monitor_contention_unavailable(msg):
                    # Run scheduler fallback
                    fallback_result = self._scheduler_fallback(tp, process_name)
                    if fallback_result["totalCount"] > 0:
                        # Add fallback metadata
                        fallback_result.update({
                            "primaryDataUnavailable": True,
                            "fallbackNotice": "Monitor contention data unavailable; using scheduler-inferred fallback",
                        })
                        return fallback_result
                    else:
                        # No fallback results either - raise original error
                        raise ToolError(
                            "MONITOR_CONTENTION_UNAVAILABLE",
                            "Monitor contention data not available in this trace (module/tables missing).",
                            details=msg,
                        )
                raise

        return self.run_formatted(trace_path, process_name, _op)

    # -------------------------
    # Fallback implementation
    # -------------------------
    def _is_monitor_contention_unavailable(self, error_msg: str) -> bool:
        """Check if the error indicates monitor contention data is unavailable."""
        msg_lower = error_msg.lower()
        return (
            "android_monitor_contention" in error_msg
            or "android.monitor_contention" in error_msg
            or "no such" in msg_lower
        )

    def _scheduler_fallback(self, tp, process_name: str) -> Dict[str, Any]:
        """Run scheduler-based fallback analysis for thread contention."""
        safe_proc = process_name.replace("'", "''")

        # First, try pair-level aggregation with waker linkage
        pairs_sql = f"""
        WITH target AS (
          SELECT upid FROM process WHERE name = '{safe_proc}'
        ), ts AS (
          SELECT ts.ts AS ts, ts.dur AS dur, ts.utid AS utid, ts.state AS state, ts.waker_utid AS waker_utid
          FROM thread_state ts
          JOIN thread t USING(utid)
          JOIN process p USING(upid)
          WHERE p.upid = (SELECT upid FROM target)
            AND ts.state IN ('S','D')
        )
        SELECT
          bt.name AS blocked_thread_name,
          bt.is_main_thread AS blocked_is_main_thread,
          wt.name AS waker_thread_name,
          SUM(ts.dur)/1e6 AS total_blocked_ms,
          AVG(ts.dur)/1e6 AS avg_blocked_ms,
          MAX(ts.dur)/1e6 AS max_blocked_ms,
          SUM(CASE WHEN ts.state IN ('S','D') THEN 1 ELSE 0 END) AS blocked_events
        FROM ts
        JOIN thread bt ON bt.utid = ts.utid
        LEFT JOIN thread wt ON wt.utid = ts.waker_utid
        GROUP BY blocked_thread_name, blocked_is_main_thread, waker_thread_name
        ORDER BY total_blocked_ms DESC
        LIMIT 150;
        """

        try:
            pairs_rows = list(tp.query(pairs_sql))
        except Exception:
            # If even scheduler data is unavailable, return empty result
            return {
                "totalCount": 0,
                "contentions": [],
                "filters": {"process_name": process_name},
                "analysisSource": "scheduler_inferred",
                "usesWakerLinkage": False,
                "usedSchedBlockedReason": False,
            }

        # Check if we have any waker linkage
        has_waker_linkage = any(getattr(r, 'waker_thread_name', None) for r in pairs_rows)

        if not pairs_rows:
            return {
                "totalCount": 0,
                "contentions": [],
                "filters": {"process_name": process_name},
                "analysisSource": "scheduler_inferred",
                "usesWakerLinkage": has_waker_linkage,
                "usedSchedBlockedReason": False,
            }

        # Try to get D-state cause attribution
        top_cause = None
        used_sched_blocked_reason = False
        try:
            causes_sql = f"""
            WITH target AS (
              SELECT upid FROM process WHERE name = '{safe_proc}'
            ), ts AS (
              SELECT ts, dur, utid, state FROM thread_state
              JOIN thread USING(utid)
              JOIN process USING(upid)
              WHERE upid = (SELECT upid FROM target) AND state = 'D'
            )
            SELECT sbr.blocked_function, SUM(ts.dur)/1e6 AS total_blocked_ms
            FROM ts
            JOIN sched_blocked_reason sbr
              ON sbr.utid = ts.utid AND sbr.ts BETWEEN ts.ts AND ts.ts + ts.dur
            GROUP BY sbr.blocked_function
            ORDER BY total_blocked_ms DESC
            LIMIT 150;
            """
            cause_rows = list(tp.query(causes_sql))
            if cause_rows:
                top_cause = getattr(cause_rows[0], 'blocked_function', None)
                used_sched_blocked_reason = True
        except Exception:
            # sched_blocked_reason not available - continue without it
            pass

        # Build contentions from pairs_rows
        contentions = []
        for r in pairs_rows:
            blocked_is_main = bool(getattr(r, 'blocked_is_main_thread', 0) or 0)
            max_blocked_ms = float(getattr(r, 'max_blocked_ms', 0.0) or 0.0)
            avg_blocked_ms = float(getattr(r, 'avg_blocked_ms', 0.0) or 0.0)
            total_blocked_ms = float(getattr(r, 'total_blocked_ms', 0.0) or 0.0)

            severity = self._classify_severity(blocked_is_main, max_blocked_ms, avg_blocked_ms, total_blocked_ms)

            contentions.append({
                'blocked_thread_name': getattr(r, 'blocked_thread_name', None),
                'blocking_thread_name': getattr(r, 'waker_thread_name', None),
                'short_blocking_method_name': top_cause,
                'contention_count': int(getattr(r, 'blocked_events', 0) or 0),
                'total_blocked_ms': total_blocked_ms,
                'avg_blocked_ms': avg_blocked_ms,
                'max_blocked_ms': max_blocked_ms,
                'total_waiters': None,
                'max_concurrent_waiters': None,
                'severity': severity,
            })

        return {
            "totalCount": len(contentions),
            "contentions": contentions,
            "filters": {"process_name": process_name},
            "analysisSource": "scheduler_inferred",
            "usesWakerLinkage": has_waker_linkage,
            "usedSchedBlockedReason": used_sched_blocked_reason,
        }

    def _classify_severity(self, is_main_thread: bool, max_blocked_ms: float, avg_blocked_ms: float, total_blocked_ms: float) -> str:
        """Classify contention severity based on thresholds."""
        if is_main_thread and max_blocked_ms > 100:
            return "CRITICAL"
        elif max_blocked_ms > 500 or total_blocked_ms > 1000:
            return "HIGH"
        elif avg_blocked_ms > 50:
            return "MEDIUM"
        else:
            return "LOW"

