"""Frame performance summary tool using per-frame metrics."""

from __future__ import annotations

import logging
from typing import Any, Dict

from .base import BaseTool, ToolError

logger = logging.getLogger(__name__)


class FramePerformanceSummaryTool(BaseTool):
    """Aggregated frame performance summary with jank statistics.

    Uses Android per-frame metrics to compute jank counts, jank rate, and CPU time
    statistics (avg, max, p95, p99). Requires frame timeline + per-frame metrics
    to be present in the trace.
    """

    def frame_performance_summary(self, trace_path: str, process_name: str) -> str:
        """Summarize frame performance for a given process.

        Parameters
        ----------
        trace_path : str
            Path to the Perfetto trace file.
        process_name : str
            Exact process name to analyze (as stored in the trace).

        Returns
        -------
        str
            JSON envelope with fields:
            - processName, tracePath, success, error, result
            - result: {
                total_frames, jank_frames, jank_rate_percent,
                slow_frames, big_jank_frames, huge_jank_frames,
                avg_cpu_time_ms, max_cpu_time_ms, p95_cpu_time_ms, p99_cpu_time_ms,
                performance_rating
              }
        """

        def _op(tp):
            if not process_name or not isinstance(process_name, str):
                raise ToolError("INVALID_PARAMETERS", "process_name must be a non-empty string")

            safe_proc = process_name.replace("'", "''")

            # Use SUM over CASE to avoid dialect-dependent boolean count semantics.
            # Guard division by zero for empty traces.
            sql = f"""
            INCLUDE PERFETTO MODULE android.frames.per_frame_metrics;

            WITH frame_metrics AS (
              SELECT 
                COUNT(*) AS total_frames,
                SUM(CASE WHEN afs.was_jank THEN 1 ELSE 0 END) AS jank_frames,
                SUM(CASE WHEN afs.was_slow_frame THEN 1 ELSE 0 END) AS slow_frames,
                SUM(CASE WHEN afs.was_big_jank THEN 1 ELSE 0 END) AS big_jank_frames,
                SUM(CASE WHEN afs.was_huge_jank THEN 1 ELSE 0 END) AS huge_jank_frames,
                AVG(afs.cpu_time) / 1e6 AS avg_cpu_time_ms,
                MAX(afs.cpu_time) / 1e6 AS max_cpu_time_ms,
                PERCENTILE(afs.cpu_time, 0.95) / 1e6 AS p95_cpu_time_ms,
                PERCENTILE(afs.cpu_time, 0.99) / 1e6 AS p99_cpu_time_ms
              FROM android_frame_stats afs
              JOIN android_frames af USING(frame_id)
              WHERE af.process_name = '{safe_proc}'
            )
            SELECT 
              total_frames,
              jank_frames,
              CAST(CASE WHEN total_frames > 0 THEN 100.0 * jank_frames / total_frames ELSE 0 END AS REAL) AS jank_rate_percent,
              slow_frames,
              big_jank_frames,
              huge_jank_frames,
              CAST(avg_cpu_time_ms AS REAL) AS avg_cpu_time_ms,
              CAST(max_cpu_time_ms AS REAL) AS max_cpu_time_ms,
              CAST(p95_cpu_time_ms AS REAL) AS p95_cpu_time_ms,
              CAST(p99_cpu_time_ms AS REAL) AS p99_cpu_time_ms,
              CASE
                WHEN (CASE WHEN total_frames > 0 THEN 100.0 * jank_frames / total_frames ELSE 0 END) < 1 THEN 'EXCELLENT'
                WHEN (CASE WHEN total_frames > 0 THEN 100.0 * jank_frames / total_frames ELSE 0 END) < 5 THEN 'GOOD'
                WHEN (CASE WHEN total_frames > 0 THEN 100.0 * jank_frames / total_frames ELSE 0 END) < 10 THEN 'ACCEPTABLE'
                ELSE 'POOR'
              END AS performance_rating
            FROM frame_metrics;
            """

            try:
                qr_it = tp.query(sql)
                # Expect exactly one row summary; default to zeros if none
                summary: Dict[str, Any] = {
                    "total_frames": 0,
                    "jank_frames": 0,
                    "jank_rate_percent": 0.0,
                    "slow_frames": 0,
                    "big_jank_frames": 0,
                    "huge_jank_frames": 0,
                    "avg_cpu_time_ms": None,
                    "max_cpu_time_ms": None,
                    "p95_cpu_time_ms": None,
                    "p99_cpu_time_ms": None,
                    "performance_rating": "UNKNOWN",
                }

                for row in qr_it:
                    # Pull attributes safely; Perfetto rows expose columns as attributes
                    summary = {
                        "total_frames": getattr(row, "total_frames", 0) or 0,
                        "jank_frames": getattr(row, "jank_frames", 0) or 0,
                        "jank_rate_percent": getattr(row, "jank_rate_percent", 0.0) or 0.0,
                        "slow_frames": getattr(row, "slow_frames", 0) or 0,
                        "big_jank_frames": getattr(row, "big_jank_frames", 0) or 0,
                        "huge_jank_frames": getattr(row, "huge_jank_frames", 0) or 0,
                        "avg_cpu_time_ms": getattr(row, "avg_cpu_time_ms", None),
                        "max_cpu_time_ms": getattr(row, "max_cpu_time_ms", None),
                        "p95_cpu_time_ms": getattr(row, "p95_cpu_time_ms", None),
                        "p99_cpu_time_ms": getattr(row, "p99_cpu_time_ms", None),
                        "performance_rating": getattr(row, "performance_rating", "UNKNOWN") or "UNKNOWN",
                    }
                    break

                return summary

            except Exception as e:
                raise ToolError(
                    "FRAME_METRICS_UNAVAILABLE",
                    "Per-frame metrics not available in this trace or query failed.",
                    details=str(e),
                )

        return self.run_formatted(trace_path, process_name, _op)

