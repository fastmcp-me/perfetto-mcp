"""Memory leak detector tool using heap growth and heap graph aggregation."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .base import BaseTool, ToolError

logger = logging.getLogger(__name__)


class MemoryLeakDetectorTool(BaseTool):
    """Detect memory leak patterns via heap growth rate and suspicious classes.

    Produces two sections:
    - growth: Average/max growth rate (MB/min) and leak indicator count
    - suspiciousClasses: Top classes by dominated heap size from heap graph aggregation
    """

    def memory_leak_detector(
        self,
        trace_path: str,
        process_name: str,
        growth_threshold_mb_per_min: float = 5.0,
        analysis_duration_ms: int = 60_000,
    ) -> str:
        """Detect memory leak signals for a process.

        Parameters
        ----------
        trace_path : str
            Path to the Perfetto trace file.
        process_name : str
            Exact process name to analyze.
        growth_threshold_mb_per_min : float, optional
            Threshold for average growth rate to flag potential leaks. Default: 5 MB/min.
        analysis_duration_ms : int, optional
            Analyze the first N milliseconds from trace start. Default: 60,000 ms.

        Returns
        -------
        str
            JSON envelope with fields:
            - processName, tracePath, success, error, result
            - result: {
                growth: { avgGrowthRateMbPerMin, maxGrowthRateMbPerMin, sampleCount, leakIndicatorCount },
                suspiciousClasses: [{ type_name, obj_count, size_mb, dominated_obj_count, dominated_size_mb }...],
                filters: { process_name, growth_threshold_mb_per_min, analysis_duration_ms },
                notes: []
              }
        """

        def _op(tp):
            if not process_name or not isinstance(process_name, str):
                raise ToolError("INVALID_PARAMETERS", "process_name must be a non-empty string")
            if analysis_duration_ms is None or int(analysis_duration_ms) <= 0:
                raise ToolError("INVALID_PARAMETERS", "analysis_duration_ms must be > 0")
            try:
                _ = float(growth_threshold_mb_per_min)
            except Exception:
                raise ToolError("INVALID_PARAMETERS", "growth_threshold_mb_per_min must be numeric")

            notes: List[str] = []
            safe_proc = process_name.replace("'", "''")

            # ------------------
            # Growth rate summary
            # ------------------
            growth_summary: Dict[str, Any] = {
                "avgGrowthRateMbPerMin": None,
                "maxGrowthRateMbPerMin": None,
                "sampleCount": 0,
                "leakIndicatorCount": 0,
            }

            growth_sql = f"""
            WITH memory_snapshots AS (
              SELECT 
                c.ts AS ts,
                c.value / 1024.0 / 1024.0 AS heap_size_mb,
                LAG(c.value) OVER (ORDER BY c.ts) AS prev_value,
                LAG(c.ts) OVER (ORDER BY c.ts) AS prev_ts
              FROM counter c
              JOIN process_counter_track pct ON c.track_id = pct.id
              JOIN process p ON pct.upid = p.upid
              WHERE p.name = '{safe_proc}'
                AND pct.name = 'mem.rss'
                AND c.ts <= {int(analysis_duration_ms)} * 1e6
            ),
            growth_analysis AS (
              SELECT 
                ts,
                heap_size_mb,
                (heap_size_mb - prev_value / 1024.0 / 1024.0) AS growth_mb,
                (ts - prev_ts) / 1e9 / 60.0 AS time_interval_min,
                (heap_size_mb - prev_value / 1024.0 / 1024.0) /
                  NULLIF((ts - prev_ts) / 1e9 / 60.0, 0) AS growth_rate_mb_per_min
              FROM memory_snapshots
              WHERE prev_value IS NOT NULL
            )
            SELECT 
              COUNT(*) AS sample_count,
              AVG(growth_rate_mb_per_min) AS avg_growth_rate,
              MAX(growth_rate_mb_per_min) AS max_growth_rate,
              SUM(CASE WHEN growth_rate_mb_per_min > {float(growth_threshold_mb_per_min)} THEN 1 ELSE 0 END) AS leak_indicator_count
            FROM growth_analysis;
            """

            try:
                rows = list(tp.query(growth_sql))
                if rows:
                    r = rows[0]
                    growth_summary = {
                        "avgGrowthRateMbPerMin": (
                            float(getattr(r, "avg_growth_rate", 0.0)) if getattr(r, "avg_growth_rate", None) is not None else None
                        ),
                        "maxGrowthRateMbPerMin": (
                            float(getattr(r, "max_growth_rate", 0.0)) if getattr(r, "max_growth_rate", None) is not None else None
                        ),
                        "sampleCount": int(getattr(r, "sample_count", 0) or 0),
                        "leakIndicatorCount": int(getattr(r, "leak_indicator_count", 0) or 0),
                    }
                else:
                    notes.append("No mem.rss samples found within analysis window")
            except Exception as e:
                logger.warning(f"growth analysis query failed: {e}")
                notes.append(f"growthAnalysis unavailable: {e}")

            # -----------------------
            # Suspicious classes list
            # -----------------------
            suspicious_classes: List[Dict[str, Any]] = []

            classes_sql = f"""
            INCLUDE PERFETTO MODULE android.memory.heap_graph.class_aggregation;
            SELECT 
              type_name,
              obj_count,
              size_bytes / 1024.0 / 1024.0 AS size_mb,
              dominated_obj_count,
              dominated_size_bytes / 1024.0 / 1024.0 AS dominated_size_mb
            FROM android_heap_graph_class_aggregation
            WHERE upid = (SELECT upid FROM process WHERE name = '{safe_proc}' LIMIT 1)
            ORDER BY dominated_size_bytes DESC
            LIMIT 10;
            """

            try:
                rows = list(tp.query(classes_sql))
                for r in rows:
                    suspicious_classes.append(
                        {
                            "type_name": getattr(r, "type_name", None),
                            "obj_count": getattr(r, "obj_count", None),
                            "size_mb": (
                                float(getattr(r, "size_mb", 0.0)) if getattr(r, "size_mb", None) is not None else None
                            ),
                            "dominated_obj_count": getattr(r, "dominated_obj_count", None),
                            "dominated_size_mb": (
                                float(getattr(r, "dominated_size_mb", 0.0)) if getattr(r, "dominated_size_mb", None) is not None else None
                            ),
                        }
                    )
            except Exception as e:
                msg = str(e)
                if (
                    "android_heap_graph_class_aggregation" in msg
                    or "android.memory.heap_graph.class_aggregation" in msg
                    or "no such" in msg.lower()
                ):
                    notes.append("suspiciousClasses unavailable (heap graph module not present in trace)")
                else:
                    logger.warning(f"heap graph aggregation query failed: {e}")
                    notes.append(f"suspiciousClasses error: {e}")

            return {
                "growth": growth_summary,
                "suspiciousClasses": suspicious_classes,
                "filters": {
                    "process_name": process_name,
                    "growth_threshold_mb_per_min": growth_threshold_mb_per_min,
                    "analysis_duration_ms": analysis_duration_ms,
                },
                "notes": notes,
            }

        return self.run_formatted(trace_path, process_name, _op)

