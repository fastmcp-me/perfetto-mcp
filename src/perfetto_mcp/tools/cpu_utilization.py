"""CPU utilization profiler tool with per-thread breakdown and optional DVFS analysis."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .base import BaseTool, ToolError

logger = logging.getLogger(__name__)


class CpuUtilizationProfilerTool(BaseTool):
    """Tool for profiling CPU utilization for a process.

    Provides per-thread CPU runtime, usage percentage over the trace, and scheduling statistics.
    Optionally augments results with CPU frequency (DVFS) summaries when available.
    """

    def cpu_utilization_profiler(
        self,
        trace_path: str,
        process_name: str,
        group_by: str = "thread",
        include_frequency_analysis: bool = True,
    ) -> str:
        """Profile CPU utilization for a given process.

        Parameters
        ----------
        trace_path : str
            Path to the Perfetto trace file.
        process_name : str
            Target process name (supports GLOB patterns, e.g. "com.example.*").
        group_by : str, optional
            Currently only "thread" is supported. Defaults to "thread".
        include_frequency_analysis : bool, optional
            When True, includes average CPU frequency summary (kHz) and per-CPU details
            if DVFS counters are available. Defaults to True.

        Returns
        -------
        str
            JSON envelope with fields: processName, tracePath, success, error, result
            Result shape:
              {
                processName: str,
                groupBy: "thread",
                summary: { runtimeSecondsTotal, cpuPercentOfTrace, threadsCount },
                threads: [
                  { threadName, isMainThread, runtimeSeconds, cpuPercent, cpusUsed,
                    scheduleCount, avgSliceMs, maxSliceMs }
                ],
                frequency: {
                  avgCpuFreqKHz: number | null,
                  perCpu: [{ cpu, avgKHz, minKHz, maxKHz }]
                } | null
              }
        """

        def _op(tp):
            if not process_name or not isinstance(process_name, str):
                raise ToolError("INVALID_PARAMETERS", "process_name must be a non-empty string")

            if group_by != "thread":
                raise ToolError(
                    "INVALID_PARAMETERS",
                    "Only group_by='thread' is supported currently",
                )

            safe_proc = process_name.replace("'", "''")

            # Core per-thread CPU utilization query
            cpu_query = f"""
            INCLUDE PERFETTO MODULE linux.cpu.utilization.process;
            SELECT 
              t.name AS thread_name,
              t.is_main_thread AS is_main_thread,
              SUM(s.dur) AS total_runtime_ns,
              COUNT(DISTINCT s.cpu) AS cpus_used,
              COUNT(*) AS schedule_count,
              AVG(s.dur) AS avg_slice_duration_ns,
              MAX(s.dur) AS max_slice_duration_ns,
              CAST(SUM(s.dur) * 100.0 / trace_dur() AS REAL) AS cpu_percent
            FROM sched_slice s
            JOIN thread t USING(utid)
            JOIN process p USING(upid)
            WHERE p.name GLOB '{safe_proc}'
            GROUP BY t.utid
            ORDER BY total_runtime_ns DESC;
            """

            rows = list(tp.query(cpu_query))

            threads: List[Dict[str, Any]] = []
            total_runtime_ns = 0
            for r in rows:
                total_runtime_ns += int(getattr(r, "total_runtime_ns", 0) or 0)
                threads.append(
                    {
                        "threadName": getattr(r, "thread_name", None),
                        "isMainThread": bool(getattr(r, "is_main_thread", 0) or 0),
                        "runtimeSeconds": float((getattr(r, "total_runtime_ns", 0) or 0) / 1e9),
                        "cpuPercent": float(getattr(r, "cpu_percent", 0.0) or 0.0),
                        "cpusUsed": getattr(r, "cpus_used", None),
                        "scheduleCount": getattr(r, "schedule_count", None),
                        "avgSliceMs": float((getattr(r, "avg_slice_duration_ns", 0) or 0) / 1e6),
                        "maxSliceMs": float((getattr(r, "max_slice_duration_ns", 0) or 0) / 1e6),
                    }
                )

            # Summaries
            runtime_seconds_total = float(total_runtime_ns / 1e9)
            cpu_percent_total = float(sum(t.get("cpuPercent", 0.0) or 0.0 for t in threads))

            frequency: Optional[Dict[str, Any]] = None
            if include_frequency_analysis:
                frequency = self._query_frequency_summary(tp)

            return {
                "processName": process_name,
                "groupBy": group_by,
                "summary": {
                    "runtimeSecondsTotal": runtime_seconds_total,
                    "cpuPercentOfTrace": cpu_percent_total,
                    "threadsCount": len(threads),
                },
                "threads": threads,
                "frequency": frequency,
            }

        return self.run_formatted(trace_path, process_name, _op)

    # -------------------------------
    # Helpers
    # -------------------------------
    def _query_frequency_summary(self, tp) -> Optional[Dict[str, Any]]:
        """Query CPU frequency summary using DVFS counters if present.

        Falls back to cpu_counter_track/counter if android.dvfs is unavailable.
        Returns a dict with avg and per-CPU stats, or None if not available.
        """
        # Try android.dvfs first
        dvfs_sql = """
        INCLUDE PERFETTO MODULE android.dvfs;
        SELECT cpu,
               AVG(value) AS avg_khz,
               MIN(value) AS min_khz,
               MAX(value) AS max_khz
        FROM android_dvfs_counters
        WHERE name LIKE 'cpufreq%'
        GROUP BY cpu
        ORDER BY cpu;
        """
        per_cpu: List[Dict[str, Any]] = []
        try:
            rows = list(tp.query(dvfs_sql))
            for r in rows:
                per_cpu.append(
                    {
                        "cpu": getattr(r, "cpu", None),
                        "avgKHz": float(getattr(r, "avg_khz", 0.0) or 0.0),
                        "minKHz": float(getattr(r, "min_khz", 0.0) or 0.0),
                        "maxKHz": float(getattr(r, "max_khz", 0.0) or 0.0),
                    }
                )
        except Exception as e:
            msg = str(e).lower()
            if "android.dvfs" in msg or "android_dvfs_counters" in msg or "no such" in msg:
                per_cpu = []
            else:
                # Unexpected error; log and return None for frequency
                logger.warning(f"DVFS frequency query failed: {e}")
                return None

        # Fallback to cpu_counter_track if dvfs data unavailable
        if not per_cpu:
            fallback_sql = """
            SELECT ct.cpu AS cpu,
                   AVG(c.value) AS avg_khz,
                   MIN(c.value) AS min_khz,
                   MAX(c.value) AS max_khz
            FROM counter c
            JOIN cpu_counter_track ct ON c.track_id = ct.id
            WHERE ct.name = 'cpufreq'
            GROUP BY ct.cpu
            ORDER BY ct.cpu;
            """
            try:
                rows = list(tp.query(fallback_sql))
                for r in rows:
                    per_cpu.append(
                        {
                            "cpu": getattr(r, "cpu", None),
                            "avgKHz": float(getattr(r, "avg_khz", 0.0) or 0.0),
                            "minKHz": float(getattr(r, "min_khz", 0.0) or 0.0),
                            "maxKHz": float(getattr(r, "max_khz", 0.0) or 0.0),
                        }
                    )
            except Exception as e:
                logger.info(f"CPU freq fallback unavailable: {e}")
                return None

        if not per_cpu:
            return None

        # Average across CPUs
        try:
            avg_all = sum(item["avgKHz"] for item in per_cpu) / max(1, len(per_cpu))
        except Exception:
            avg_all = None

        return {
            "avgCpuFreqKHz": avg_all,
            "perCpu": per_cpu,
        }
