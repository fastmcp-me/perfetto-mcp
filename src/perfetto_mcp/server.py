"""Main MCP server setup with lifecycle management."""

import atexit
import logging
from mcp.server.fastmcp import FastMCP
from .connection_manager import ConnectionManager
from .tools.slice_info import SliceInfoTool
from .tools.sql_query import SqlQueryTool
from .tools.anr_detection import AnrDetectionTool
from .resource import register_resources
from .tools.anr_root_cause import AnrRootCauseTool
from .tools.cpu_utilization import CpuUtilizationProfilerTool
from .tools.jank_frames import JankFramesTool
from .tools.frame_performance_summary import FramePerformanceSummaryTool
from .tools.memory_leak_detector import MemoryLeakDetectorTool
from .tools.heap_dominator_tree_analyzer import HeapDominatorTreeAnalyzerTool
from .tools.thread_contention_analyzer import ThreadContentionAnalyzerTool

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_server() -> FastMCP:
    """Create and configure the Perfetto MCP server.
    
    Returns:
        FastMCP: Configured MCP server instance
    """
    # Create MCP server
    mcp = FastMCP("Perfetto MCP")
    
    # Initialize connection manager
    connection_manager = ConnectionManager()
    
    # Create tool instances
    slice_info_tool = SliceInfoTool(connection_manager)
    sql_query_tool = SqlQueryTool(connection_manager)
    anr_detection_tool = AnrDetectionTool(connection_manager)
    anr_root_cause_tool = AnrRootCauseTool(connection_manager)
    cpu_util_tool = CpuUtilizationProfilerTool(connection_manager)
    jank_frames_tool = JankFramesTool(connection_manager)
    frame_summary_tool = FramePerformanceSummaryTool(connection_manager)
    memory_leak_tool = MemoryLeakDetectorTool(connection_manager)
    heap_dom_tool = HeapDominatorTreeAnalyzerTool(connection_manager)
    thread_contention_tool = ThreadContentionAnalyzerTool(connection_manager)


    @mcp.tool()
    def get_slice_info(trace_path: str, slice_name: str, process_name: str | None = None) -> str:
        """
        Filter and summarize all occurrences of a specific slice (exact name).

        WHEN TO USE: Quickly understand how often a slice appears, its timing
        distribution at a glance, and see a few worst-case examples with context
        (process/thread/track).

        SEARCH BEHAVIOR: Performs EXACT case-sensitive string matching. "main" !=
        "Main" != "MAIN". The `slice_name` must match exactly what appears in the
        trace data.

        OUTPUT FIELDS (result):
        - sliceName: Input name
        - totalCount: Total number of matching slices
        - durationSummary: { minMs, avgMs, maxMs }
        - timeBounds: { earliestTsMs, latestTsMs, spanMs }
        - examples: Up to 50 longest instances with fields:
          { sliceId, tsMs, endTsMs, durMs, depth, category, trackName,
            process_name, pid, thread_name, tid, is_main_thread }

        Parameters
        ----------
        trace_path : str
            Path to the Perfetto trace file
        slice_name : str
            EXACT name of slice to analyze.

        Returns
        -------
        str
            JSON envelope with fields:
            - processName, tracePath, success, error, result
            - result: see OUTPUT FIELDS above

        Notes
        -----
        - For complex filtering (duration > X, time ranges, process filters),
          use execute_sql_query() with WHERE clauses.
        """
        return slice_info_tool.get_slice_info(trace_path, slice_name, process_name)


    @mcp.tool()
    def execute_sql_query(trace_path: str, sql_query: str, process_name: str | None = None) -> str:
        """
        Execute arbitrary SQL queries against a Perfetto trace database.
        
        This is the most powerful tool for trace analysis, allowing you to write custom
        SQL queries against the trace database. The Perfetto trace database contains
        multiple tables (slice, thread, process, counter, etc.) that you can query
        using standard SQL syntax. Results return all matching rows (no automatic LIMIT is applied).

        Parameters
        ----------
        trace_path : str
            Absolute or relative path to the Perfetto trace file (.pftrace, .pb files).
            The file must be a valid Perfetto trace that can be opened by TraceProcessor.
        sql_query : str
            SQL query to execute against the trace database. Only SELECT statements are
            allowed for security reasons. Available tables include: slice, thread,
            process, counter, args, track, and many others.

        Returns
        -------
        str
            JSON envelope with fields:
            - processName, tracePath, success, error, result
            - result: { query, columns, rows, rowCount }

        Security Notes
        -------------
        - Only SELECT queries are permitted
        - SQL injection protection through query validation

        Examples
        --------
        execute_sql_query("trace.pftrace", "SELECT name, COUNT(*) FROM slice GROUP BY name ORDER BY COUNT(*) DESC")
        execute_sql_query("trace.pb", "SELECT ts, dur, tid FROM slice WHERE dur > 1000000")
        execute_sql_query("trace.pftrace", "SELECT DISTINCT name FROM thread")
        execute_sql_query("trace.pb", "SELECT * FROM process WHERE name LIKE '%chrome%'")
        """
        return sql_query_tool.execute_sql_query(trace_path, sql_query, process_name)


    @mcp.tool()
    def detect_anrs(trace_path: str, process_name: str | None = None, min_duration_ms: int = 5000, time_range: dict | None = None) -> str:
        """
        Detect ANR (Application Not Responding) events in a Perfetto trace with contextual analysis.
        
        WHEN TO USE: Use this tool to identify ANR events in Android application traces. ANRs occur 
        when the main thread is blocked for more than 5 seconds (by default), causing the system 
        to show "App Not Responding" dialogs. This tool provides comprehensive analysis including 
        main thread state, GC pressure, and severity assessment.
        
        WHAT YOU GET: Structured JSON output with detailed ANR information including timestamps, 
        process details, main thread states, concurrent GC events, and severity analysis. Each 
        ANR includes contextual data to help understand root causes.
        
        ANR ANALYSIS CONTEXT: ANRs are critical performance issues that directly impact user 
        experience. They typically occur due to:
        - Main thread blocking operations (I/O, network, database)
        - Lock contention and synchronization issues
        - Memory pressure causing excessive GC
        - Binder transaction delays
        - CPU-intensive operations on the main thread
        
        SEVERITY LEVELS: Results include severity analysis:
        - CRITICAL: High GC pressure (>10 events) or system process ANRs
        - HIGH: Main thread in disk/interruptible sleep or moderate GC pressure
        - MEDIUM: Main thread running (CPU bound) or normal conditions
        - LOW: Minimal impact ANRs

        Parameters
        ----------
        trace_path : str
            Path to Perfetto trace file (.pftrace, .pb, or other Perfetto formats). The trace 
            must be from Android system tracing with ANR detection enabled. Typical sources 
            include systrace, perfetto system traces, or custom Android instrumentation.
        process_name : str, optional
            Filter ANRs by process name. Supports glob patterns (*, ?, [abc]). Examples:
            - "com.example.app" (exact match)
            - "com.example.*" (all processes starting with com.example.)
            - "*browser*" (any process containing 'browser')
            If None, returns ANRs from all processes.
        min_duration_ms : int, optional
            Minimum ANR duration threshold in milliseconds. Default is 5000ms (5 seconds),
            which is the standard Android ANR threshold. Lower values may include shorter
            blocking events that don't trigger system ANR dialogs.
        time_range : dict, optional
            Filter ANRs by time range with keys:
            - 'start_ms': Start time in milliseconds from trace beginning
            - 'end_ms': End time in milliseconds from trace beginning
            If None, analyzes the entire trace duration.

        Returns
        -------
        str
            JSON envelope with fields:
            - processName, tracePath, success, error, result
            - result: {
                totalCount,
                anrs: [{ process_name, pid, upid, ts, timestampMs, subject, main_thread_state, gc_events_near_anr, severity }...],
                filters: { process_name, min_duration_ms, time_range }
              }

        AI Agent Usage Notes
        -------------------
        - ANR data requires Android system traces with 'android.anrs' data source enabled
        - Ensure the trace contains Android performance data
        - High ANR counts indicate systemic performance issues requiring investigation
        - Correlate ANR timestamps with other performance metrics (frame drops, memory pressure)
        - For detailed root cause analysis, use execute_sql_query() with ANR timestamps
        - Zero ANRs doesn't mean good performance - check trace coverage and data sources
        
        Common Follow-up Queries
        -----------------------
        - Thread state analysis around ANR timestamps
        - Binder transaction analysis during ANR periods  
        - Memory allocation patterns before ANRs
        - CPU utilization and scheduling data during ANRs
        """
        return anr_detection_tool.detect_anrs(trace_path, process_name, min_duration_ms, time_range)


    @mcp.tool()
    def anr_root_cause_analyzer(
        trace_path: str,
        process_name: str | None = None,
        anr_timestamp_ms: int | None = None,
        analysis_window_ms: int = 10_000,
        time_range: dict | None = None,
        deep_analysis: bool = False,
    ) -> str:
        """
        Analyze likely ANR root causes by correlating multiple signals within a time window.

        WHEN TO USE: After detecting an ANR timestamp (via detect_anrs or otherwise), run this tool
        for the affected process to quickly surface likely causes such as slow Binder calls, main
        thread IO/sleep, Java monitor contention, and memory pressure.

        SIGNALS AT A GLANCE
        - Main thread blocking: Long non-running states on the app's main thread (e.g., IO wait or
          sleeping) that directly prevent UI event handling and can trigger ANRs.
        - Binder delays: Slow outbound Binder calls from the app (often the main thread) indicating
          the app is waiting on a remote service/System Server; common in input/provider ANRs.
        - Memory pressure: Low or rapidly dropping MemAvailable around the window suggesting GC/LMK
          pressure contributing to long stalls and poor responsiveness.
        - Java monitor contention: Long waits on synchronized monitors on the main thread showing
          which thread/method is blocking; indicates lock contention or potential deadlocks.

        PARAMETERS
        ----------
        trace_path : str
            Path to the Perfetto trace file.
        process_name : str, optional
            Filter by process name (supports GLOB). Example: "com.example.*". If omitted, runs without
            process filter where possible, but some signals (monitor contention) require a process.
        anr_timestamp_ms : int, optional
            Anchor timestamp in milliseconds from trace start. Used to build a symmetric window when
            time_range is not provided.
        analysis_window_ms : int, optional
            Half-window around the anchor timestamp. Default 10,000 (±10s).
        time_range : dict, optional
            Explicit time window: { 'start_ms': int, 'end_ms': int }. If provided together with
            anr_timestamp_ms, the timestamp must lie within the range; otherwise the tool returns an
            INVALID_PARAMETERS error asking for clarification.
        deep_analysis : bool, optional
            If true, strengthens insights heuristics (e.g., prioritization notes when multiple causes exist).

        RETURNS
        -------
        str
            JSON envelope { processName, tracePath, success, error, result } where result contains:
            - window: { startMs, endMs }
            - filters: { process_name }
            - mainThreadBlocks: [{ tsMs, durMs, state, ioWait, wakerUtid, wakerThreadName, wakerProcessName }]
            - binderDelays: [{ binderTxnId, clientTsMs, clientDurMs, serverProcess, aidlName, methodName, clientMainThread }]
            - memoryPressure: { start: { tsMs, availableMemoryMb }, end: { ... }, deltaMb }
            - lockContention: [{ blockedThreadName, blockingThreadName, blockedMethod, shortBlockingMethod, blockingSrc, waiterCount, blockedThreadWaiterCount, durMs, tsMs }]
            - insights: { likelyCauses, rationale, signalsUsed }
            - notes: [ ... ]
        """
        return anr_root_cause_tool.anr_root_cause_analyzer(
            trace_path,
            process_name,
            anr_timestamp_ms,
            analysis_window_ms,
            time_range,
            deep_analysis,
        )
    
    @mcp.tool()
    def cpu_utilization_profiler(
        trace_path: str,
        process_name: str,
        group_by: str = "thread",
        include_frequency_analysis: bool = True,
    ) -> str:
        """
        Profile CPU utilization for a process with per-thread breakdown.

        WHEN TO USE: Understand which threads consume CPU over the trace duration, how often they're
        scheduled, and whether the main thread is CPU-bound. Optionally correlate with CPU frequency
        (DVFS) when the trace contains frequency counters.

        PARAMETERS
        ----------
        trace_path : str
            Path to the Perfetto trace file.
        process_name : str
            Target process (supports GLOB patterns, e.g. "com.example.*").
        group_by : str, optional
            Currently only "thread" is supported. Default: "thread".
        include_frequency_analysis : bool, optional
            If true, includes avg CPU frequency (kHz) and per-CPU stats when available. Default: True.

        RETURNS
        -------
        str
            JSON envelope with fields:
            - processName, tracePath, success, error, result
            - result: {
                processName, groupBy,
                summary: { runtimeSecondsTotal, cpuPercentOfTrace, threadsCount },
                threads: [ { threadName, isMainThread, runtimeSeconds, cpuPercent, cpusUsed, scheduleCount, avgSliceMs, maxSliceMs }... ],
                frequency: { avgCpuFreqKHz, perCpu: [{ cpu, avgKHz, minKHz, maxKHz }] } | null
              }
        """
        return cpu_util_tool.cpu_utilization_profiler(
            trace_path,
            process_name,
            group_by,
            include_frequency_analysis,
        )

    @mcp.tool()
    def detect_jank_frames(
        trace_path: str,
        process_name: str,
        jank_threshold_ms: float = 16.67,
        severity_filter: list[str] | None = None,
    ) -> str:
        """
        Detect janky frames with severity and source classification.

        WHEN TO USE: Investigate UI performance issues for a specific process.
        Identifies jank type, severity, overrun, CPU/UI time, and whether the
        jank originated in the app vs SurfaceFlinger.

        Parameters
        ----------
        trace_path : str
            Path to the Perfetto trace file.
        process_name : str
            Exact process name to analyze (as stored in the trace).
        jank_threshold_ms : float, optional
            Frame duration threshold (ms) to consider a frame janky. Default: 16.67.
        severity_filter : list[str] | None, optional
            Filter by jank severity types (e.g. ["severe", "moderate"]).

        Returns
        -------
        str
            JSON envelope with fields:
            - processName, tracePath, success, error, result
            - result: {
                totalCount,
                frames: [{ frame_id, timestamp_ms, duration_ms, overrun_ms, jank_type,
                           jank_severity_type, jank_source, cpu_time_ms, ui_time_ms,
                           layer_name, jank_classification }...],
                filters: { process_name, jank_threshold_ms, severity_filter }
              }
        """
        return jank_frames_tool.detect_jank_frames(
            trace_path,
            process_name,
            jank_threshold_ms,
            severity_filter,
        )

    @mcp.tool()
    def frame_performance_summary(trace_path: str, process_name: str) -> str:
        """
        Summarize frame performance with jank and CPU stats.

        WHEN TO USE: High-level overview of a process's frame stability and
        rendering cost. Produces jank counts/rate and CPU time distribution.

        Parameters
        ----------
        trace_path : str
            Path to the Perfetto trace file.
        process_name : str
            Exact process name to analyze.

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
        return frame_summary_tool.frame_performance_summary(trace_path, process_name)

    @mcp.tool()
    def memory_leak_detector(
        trace_path: str,
        process_name: str,
        growth_threshold_mb_per_min: float = 5.0,
        analysis_duration_ms: int = 60_000,
    ) -> str:
        """
        Detect memory leaks through heap growth pattern analysis and heap graph.

        WHEN TO USE: Identify potential memory leaks indicated by sustained RSS growth
        and large retained heap sizes for specific classes.

        Parameters
        ----------
        trace_path : str
            Path to the Perfetto trace file.
        process_name : str
            Exact process name to analyze.
        growth_threshold_mb_per_min : float, optional
            Threshold for growth rate (MB/min) to flag potential leaks. Default: 5.0.
        analysis_duration_ms : int, optional
            Analyze the first N milliseconds from trace start. Default: 60,000 ms.

        Returns
        -------
        str
            JSON envelope with fields:
            - processName, tracePath, success, error, result
            - result: {
                growth: { avgGrowthRateMbPerMin, maxGrowthRateMbPerMin, sampleCount, leakIndicatorCount },
                suspiciousClasses: [{ type_name, obj_count, size_mb, dominated_obj_count, dominated_size_mb }],
                filters: { process_name, growth_threshold_mb_per_min, analysis_duration_ms },
                notes: []
              }

        Notes
        -----
        - Growth analysis uses process RSS samples (process_counter_track 'mem.rss').
        - Suspicious classes require heap graph data (android.memory.heap_graph.class_aggregation).
        - If a dataset is unavailable, the tool returns partial results and notes.
        """
        return memory_leak_tool.memory_leak_detector(
            trace_path,
            process_name,
            growth_threshold_mb_per_min,
            analysis_duration_ms,
        )

    @mcp.tool()
    def heap_dominator_tree_analyzer(
        trace_path: str,
        process_name: str,
        max_classes: int = 20,
    ) -> str:
        """
        Analyze the heap dominator tree to identify memory-hogging classes.

        WHEN TO USE: Understand which classes dominate heap usage in the latest
        heap graph snapshot for a process. Helps pinpoint memory bloat and
        potential leak suspects.

        Parameters
        ----------
        trace_path : str
            Path to the Perfetto trace file.
        process_name : str
            Exact process name to analyze (matches trace data).
        max_classes : int, optional
            Maximum number of classes to return (1–50). Default: 20.

        Returns
        -------
        str
            JSON envelope with fields:
            - processName, tracePath, success, error, result
            - result: {
                totalCount,
                classes: [{ display_name, instance_count, self_size_mb, native_size_mb,
                            total_size_mb, avg_reachability, min_root_distance, memory_impact }...],
                filters: { process_name, max_classes },
                notes: []
              }

        Notes
        -----
        - Uses heap graph tables (heap_graph_object/class). If extended columns
          from the dominator_tree module are unavailable, the tool falls back to
          a simplified query (without native_size/reachability/root_distance)
          and adds a note. If no heap graph exists in the trace, returns a
          HEAP_GRAPH_UNAVAILABLE error.
        """
        return heap_dom_tool.heap_dominator_tree_analyzer(trace_path, process_name, max_classes)

    @mcp.tool()
    def thread_contention_analyzer(
        trace_path: str,
        process_name: str,
    ) -> str:
        """
        Identify thread contention and synchronization bottlenecks for a process.

        WHEN TO USE: Investigate stalls due to Java monitor lock contention, especially
        on the main thread. Highlights which threads/methods are blocking and the
        extent of blocking.

        Parameters
        ----------
        trace_path : str
            Path to the Perfetto trace file.
        process_name : str
            Exact process name to analyze.

        Returns
        -------
        str
            JSON envelope with fields:
            - processName, tracePath, success, error, result
            - result: {
                totalCount,
                contentions: [{ blocked_thread_name, blocking_thread_name,
                                short_blocking_method_name, contention_count,
                                total_blocked_ms, avg_blocked_ms, max_blocked_ms,
                                total_waiters, max_concurrent_waiters, severity }],
                filters: { process_name }
              }

        Notes
        -----
        - Requires android.monitor_contention module in the trace. If unavailable,
          returns MONITOR_CONTENTION_UNAVAILABLE with details.
        """
        return thread_contention_tool.thread_contention_analyzer(
            trace_path,
            process_name,
        )

    # Setup cleanup using atexit
    atexit.register(connection_manager.cleanup)

    # Register MCP resources in dedicated module
    register_resources(mcp)

    logger.info("Perfetto MCP server created with connection management")

    return mcp
