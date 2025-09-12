"""Binder transaction profiler using android.binder module."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from .base import BaseTool, ToolError
from ..utils.query_helpers import format_query_result_row

logger = logging.getLogger(__name__)


class BinderTransactionProfilerTool(BaseTool):
    """Analyze binder transaction performance and identify bottlenecks.

    Uses the android.binder module to compute client/server latencies, overhead,
    and optionally includes a breakdown of thread states during the transaction.
    """

    def binder_transaction_profiler(
        self,
        trace_path: str,
        process_filter: str,
        min_latency_ms: float = 10.0,
        include_thread_states: bool = True,
    ) -> str:
        """Profile binder transactions for a process as client or server.

        Parameters
        ----------
        trace_path : str
            Path to the Perfetto trace file.
        process_filter : str
            Process name to match either as client or server process in binder txns.
        min_latency_ms : float, optional
            Minimum client latency to include (ms). Default: 10.0.
        include_thread_states : bool, optional
            If true, includes top thread states per transaction (aggregated). Default: True.

        Returns
        -------
        str
            JSON envelope with fields: processName, tracePath, success, error, result.
            Result shape:
              {
                totalCount: number,
                transactions: [
                  {
                    client_process, server_process, aidl_name, method_name,
                    client_latency_ms, server_latency_ms, overhead_ms,
                    is_main_thread, is_sync, top_thread_states, latency_severity
                  }
                ],
                filters: { process_filter, min_latency_ms, include_thread_states }
              }
        """

        def _op(tp):
            if not process_filter or not isinstance(process_filter, str):
                raise ToolError("INVALID_PARAMETERS", "process_filter must be a non-empty string")
            try:
                _ = float(min_latency_ms)
            except Exception:
                raise ToolError("INVALID_PARAMETERS", "min_latency_ms must be numeric")

            safe_proc = process_filter.replace("'", "''")

            # Build the conditional projection for thread states
            if include_thread_states:
                top_states_sql = (
                    "(SELECT GROUP_CONCAT(thread_state || ':' || CAST(state_duration_ms AS TEXT) || 'ms', ', ') "
                    "FROM thread_state_breakdown tsb "
                    "WHERE tsb.binder_txn_id = ba.binder_txn_id "
                    "ORDER BY state_duration_ms DESC LIMIT 3) AS top_thread_states"
                )
            else:
                top_states_sql = "NULL AS top_thread_states"

            sql_query = f"""
            INCLUDE PERFETTO MODULE android.binder;

            WITH binder_analysis AS (
              SELECT 
                binder_txn_id,
                client_process,
                server_process,
                aidl_name,
                method_name,
                client_ts,
                client_dur,
                server_ts,
                server_dur,
                is_main_thread,
                is_sync,
                client_tid,
                server_tid
              FROM android_binder_txns
              WHERE (client_process = '{safe_proc}' OR server_process = '{safe_proc}')
                AND client_dur >= {float(min_latency_ms)} * 1e6
            ),
            thread_state_breakdown AS (
              SELECT 
                binder_txn_id,
                thread_state_type,
                thread_state,
                SUM(thread_state_dur) / 1e6 as state_duration_ms
              FROM android_sync_binder_thread_state_by_txn
              WHERE binder_txn_id IN (SELECT binder_txn_id FROM binder_analysis)
              GROUP BY binder_txn_id, thread_state_type, thread_state
            )
            SELECT 
              ba.client_process,
              ba.server_process,
              ba.aidl_name,
              ba.method_name,
              CAST(ba.client_dur / 1e6 AS REAL) as client_latency_ms,
              CAST(ba.server_dur / 1e6 AS REAL) as server_latency_ms,
              CAST((ba.client_dur - ba.server_dur) / 1e6 AS REAL) as overhead_ms,
              ba.is_main_thread,
              ba.is_sync,
              {top_states_sql},
              CASE
                WHEN ba.client_dur > 100e6 AND ba.is_main_thread THEN 'CRITICAL'
                WHEN ba.client_dur > 50e6 THEN 'HIGH'
                WHEN ba.client_dur > 20e6 THEN 'MEDIUM'
                ELSE 'LOW'
              END as latency_severity
            FROM binder_analysis ba
            ORDER BY ba.client_dur DESC;
            """

            try:
                rows = list(tp.query(sql_query))
            except Exception as e:
                msg = str(e)
                # Common failures when binder module/views are unavailable
                if (
                    "android_binder_txns" in msg
                    or "android.binder" in msg
                    or "android_sync_binder_thread_state_by_txn" in msg
                    or "no such" in msg.lower()
                ):
                    raise ToolError(
                        "BINDER_DATA_UNAVAILABLE",
                        "Binder analysis data not available in this trace (module/views missing).",
                        details=msg,
                    )
                raise

            transactions: List[Dict[str, Any]] = []
            columns = None
            for r in rows:
                if columns is None:
                    columns = list(r.__dict__.keys())
                transactions.append(format_query_result_row(r, columns))

            return {
                "totalCount": len(transactions),
                "transactions": transactions,
                "filters": {
                    "process_filter": process_filter,
                    "min_latency_ms": min_latency_ms,
                    "include_thread_states": include_thread_states,
                },
            }

        return self.run_formatted(trace_path, process_filter, _op)

