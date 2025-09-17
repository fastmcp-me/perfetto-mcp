"""Main MCP server setup with lifecycle management."""

import atexit
import logging
from mcp.server.fastmcp import FastMCP
from .connection_manager import ConnectionManager
from .tools.find_slices import SliceFinderTool
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
from .tools.binder_transaction_profiler import BinderTransactionProfilerTool
from .tools.main_thread_hotspots import MainThreadHotspotTool

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
    slice_finder_tool = SliceFinderTool(connection_manager)
    sql_query_tool = SqlQueryTool(connection_manager)
    anr_detection_tool = AnrDetectionTool(connection_manager)
    anr_root_cause_tool = AnrRootCauseTool(connection_manager)
    cpu_util_tool = CpuUtilizationProfilerTool(connection_manager)
    jank_frames_tool = JankFramesTool(connection_manager)
    frame_summary_tool = FramePerformanceSummaryTool(connection_manager)
    memory_leak_tool = MemoryLeakDetectorTool(connection_manager)
    heap_dom_tool = HeapDominatorTreeAnalyzerTool(connection_manager)
    thread_contention_tool = ThreadContentionAnalyzerTool(connection_manager)
    binder_txn_tool = BinderTransactionProfilerTool(connection_manager)
    main_thread_hotspot_tool = MainThreadHotspotTool(connection_manager)


    @mcp.tool()
    def find_slices(
        trace_path: str,
        pattern: str,
        process_name: str | None = None,
        match_mode: str = "contains",
        limit: int = 100,
        main_thread_only: bool = False,
        time_range: dict | None = None,
    ) -> str:
        """
        Discover slices by name with flexible matching to quickly survey what's in a trace,
        then get aggregates and linkable examples without writing SQL.

        WHY USE THIS:
        - Explore unknown slice names and hot paths fast (no manual SQL).
        - See frequency and duration stats (min/avg/max and p50/p90/p99 when available) per slice name.
        - Get linkable examples (id, ts, dur, track_id) to jump in UI or correlate with other tools.
        - Filter by process, main thread, and time range to narrow investigations.

        PARAMETERS:
        - pattern: String to match against slice names.
        - match_mode: 'contains' (default), 'exact', or 'glob'.
        - process_name: Optional filter; supports '*' wildcard.
        - main_thread_only: Limit to process main threads.
        - time_range: {'start_ms': X, 'end_ms': Y}.
        - limit: Max example slices to return (default 100).

        OUTPUT:
        - aggregates: Per-slice-name counts and duration stats (min/avg/max, p50/p90/p99 when available).
        - examples: Top slices by duration with thread/process context and track id for linking.
        - notes: Capability or fallback notices.
        """
        return slice_finder_tool.find_slices(
            trace_path,
            pattern,
            process_name,
            match_mode,
            limit,
            main_thread_only,
            time_range,
        )


    @mcp.tool()
    def execute_sql_query(trace_path: str, sql_query: str, process_name: str | None = None) -> str:
        """
        Execute PerfettoSQL scripts (multi-statement) on trace data for advanced analysis.

        USE THIS WHEN: Other tools don't provide what you need, you need complex filtering/joins, 
        or you want to correlate data across multiple tables. This is your power tool for custom 
        analysis - use it when pre-built tools are too limiting.

        CAPABILITIES: Full SQL access to all trace tables including:
        - slice: All trace slices with timing
        - thread/process: Thread and process metadata
        - counter: Performance counters over time
        - android_anrs: ANR events
        - actual_frame_timeline_slice: Frame jank data
        - sched_slice: CPU scheduling information
        - android_binder_txns: Cross-process calls
        - heap_graph_*: Memory heap analysis

        SECURITY: Accepts full PerfettoSQL/SQLite scripts. No automatic LIMIT is applied; large
        queries may return many rows. The script is executed verbatim by TraceProcessor.

        COMMON PATTERNS:
        - Duration analysis: "SELECT name, dur/1e6 as ms FROM slice WHERE dur > 10e6"
        - Aggregation: "SELECT name, COUNT(*), AVG(dur)/1e6 FROM slice GROUP BY name"
        - Time filtering: "SELECT * FROM slice WHERE ts BETWEEN 1e9 AND 2e9"
        - Process filtering: "SELECT * FROM thread WHERE upid IN (SELECT upid FROM process WHERE name LIKE '%chrome%')"

        POWER USER TIP: Use `INCLUDE PERFETTO MODULE ...` statements to load standard library
        modules (supports wildcards like `android.*`). You can also use `CREATE PERFETTO TABLE`/
        `VIEW`/`FUNCTION`/`MACRO`/`INDEX` where supported by TraceProcessor.

        References:
        - PerfettoSQL Syntax: https://perfetto.dev/docs/analysis/perfetto-sql-syntax
        - Standard Library (Prelude): https://perfetto.dev/docs/analysis/stdlib-docs#package-prelude
        """
        return sql_query_tool.execute_sql_query(trace_path, sql_query, process_name)


    @mcp.tool()
    def detect_anrs(trace_path: str, process_name: str | None = None, min_duration_ms: int = 5000, time_range: dict | None = None) -> str:
        """
        USE THIS WHEN: Investigating app freezes, unresponsiveness, "not responding" dialogs, 
        or user complaints about app hangs. ANRs are critical issues where the main thread 
        is blocked for >5 seconds, causing Android to consider killing the app.

        PROVIDES: Complete ANR list with severity assessment based on main thread state and 
        system conditions. Each ANR includes garbage collection pressure analysis to identify 
        memory-related causes.

        FILTERS:
        - process_name: Target app (supports wildcards: "com.example.*", "*browser*")
        - time_range: {'start_ms': X, 'end_ms': Y} to focus on specific periods

        ANR ANALYSIS CONTEXT: ANRs are critical performance issues that directly impact user 
        experience. They typically occur due to:
        - Main thread blocking operations (I/O, network, database)
        - Lock contention and synchronization issues
        - Memory pressure causing excessive GC
        - Binder transaction delays
        - CPU-intensive operations on the main thread

        OUTPUT: 
        - Timestamp and process information for each ANR
        - Main thread state (last known state at ANR ts)
        - GC event count near ANR (>10 events = memory pressure)
        - Severity heuristic: CRITICAL if GC>10; HIGH if main thread in sleep/IO wait or moderate GC; 
          MEDIUM otherwise (system-critical processes escalate severity)

        NEXT STEPS: 
        1. Use anr_root_cause_analyzer with ANR timestamp for deep analysis
        2. Check thread_contention_analyzer for lock-related causes
        3. Run binder_transaction_profiler if ANR involves system services

        INTERPRETATION: Multiple ANRs in short time = systemic issue. Single ANR = investigate 
        specific timestamp. No ANRs doesn't guarantee good performance - check jank metrics too.

        - Requires 'android.anrs' data source in the trace; otherwise returns ANR_DATA_UNAVAILABLE
        - Ensure the trace contains Android performance data
        - High ANR counts indicate systemic performance issues requiring investigation
        - Correlate ANR timestamps with other performance metrics (frame drops, memory pressure)
        - For detailed root cause analysis, use execute_sql_query() with ANR timestamps
        - Zero ANRs doesn't mean good performance - check trace coverage and data sources
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
        Comprehensive root cause analysis for ANR events using multi-signal correlation.

        USE THIS WHEN: After detect_anrs finds an ANR, investigating a known freeze timestamp, 
        or when users report specific times when the app became unresponsive. This tool looks 
        at a ±10 second window around the issue to identify root causes.

        ANALYZES FOUR KEY SIGNALS:
        1. Main thread blocking: Long non-running states (I/O wait, sleeping) preventing UI updates
        2. Binder delays: Slow IPC calls to system services (>100ms transactions)
        3. Memory pressure: Low available memory forcing excessive GC
        4. Lock contention: Java synchronized blocks causing thread waits

        PARAMETERS:
        - process_name: Target process (required for some analyses)
        - anr_timestamp_ms OR time_range: The moment to investigate
        - analysis_window_ms: Context window size (default ±10 seconds)
        - deep_analysis: true for enhanced correlation insights
        - Validation: If both anr_timestamp_ms and time_range are provided, the timestamp must 
          lie within the time_range or the tool returns INVALID_PARAMETERS

        OUTPUT INSIGHTS:
        - "likelyCauses": Ranked list of probable root causes
        - "rationale": Explanation of why each cause was identified
        - Detailed data for each signal type
        - Correlation notes when multiple causes interact

        STRENGTH: Unlike single-signal tools, this correlates multiple data sources to identify 
        the true root cause. For example, it can distinguish between "ANR due to lock contention 
        during GC" vs "ANR due to slow binder call" vs "ANR due to CPU starvation".

        TYPICAL FINDING: Most ANRs are caused by main thread lock contention or synchronous 
        binder calls, not CPU overload. Requires binder and monitor_contention modules in the 
        trace for those signals; missing modules are reported in 'notes'.
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
        Profile CPU usage by thread to identify performance bottlenecks.

        USE THIS WHEN: Investigating high battery drain, thermal throttling, slow performance, 
        or determining if your app is CPU-bound. Essential for understanding whether performance 
        issues are due to excessive CPU usage or other factors (I/O, lock contention, etc.).

        SHOWS PER-THREAD:
        - CPU percentage of trace duration
        - Total runtime and scheduling counts
        - Average/max time slices (long slices = good, many short = thrashing)
        - CPUs used (indicates thread migration)
        - Optional: CPU frequency analysis if trace has DVFS data

        KEY METRICS:
        - Main thread >80% CPU: UI work needs offloading
        - Background thread >90%: Consider chunking work
        - Many threads with low %: Possible over-threading
        - High schedule count with low CPU%: Lock contention likely

        PROCESS PATTERNS:
        - process_name: Supports wildcards ("com.example.*")
        - group_by: Currently "thread" only
        - include_frequency_analysis: Adds CPU frequency correlation

        INTERPRETATION: High CPU doesn't always mean inefficient code - could indicate thermal 
        throttling keeping CPU at low frequencies. Compare with cpu_frequency data. If CPU usage 
        is low but performance is poor, investigate lock contention or I/O blocking instead.

        OUTPUT: Ranked thread list by CPU usage, with main thread flagged. Use this to identify 
        which specific threads need optimization.
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
        Find dropped/janky frames with detailed performance classification.

        USE THIS WHEN: UI feels sluggish, scrolling stutters, animations aren't smooth, or 
        you need to quantify UI performance issues. Jank directly impacts user experience - 
        even a few janky frames can make an app feel unprofessional.

        DETECTS:
        - Frames exceeding deadline (16.67ms for 60fps, 8.33ms for 120fps)
        - Jank source: Application vs SurfaceFlinger (system compositor)
        - Severity: mild, moderate, severe based on deadline overrun
        - CPU/UI thread time per frame

        PARAMETERS:
        - process_name: Exact app name from trace
        - jank_threshold_ms: 16.67 (60fps) or 8.33 (120fps) 
        - severity_filter: ["severe", "moderate"] to focus on worst cases

        OUTPUT INCLUDES:
        - frame_id, timestamp, duration for correlation
        - overrun_ms: How much the frame missed deadline
        - jank_type and source (app vs system)
        - CPU/UI time breakdown
        - Classification: SMOOTH/JANK/BIG_JANK/HUGE_JANK

        INTERPRETATION:
        - Occasional jank (<1% frames): Normal
        - Consistent jank (>5% frames): User-visible problem
        - Jank clusters: Check for GC, I/O, or lock contention at those times
        - SurfaceFlinger jank: System issue, not your app

        FOLLOW-UP: Use frame timestamps to correlate with execute_sql_query for what was 
        happening during janky frames (GC events, binder calls, CPU frequency).
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
        High-level frame performance metrics and overall UI smoothness assessment.

        USE THIS WHEN: Need a quick performance rating, establishing baseline metrics, comparing 
        before/after optimization, or getting an overview before deep-diving into specific frames. 
        This gives you the "forest view" while detect_jank_frames shows individual "trees".

        PROVIDES:
        - Total frame count and jank statistics
        - Jank rate percentage (key metric for UI smoothness)
        - Frame categories: slow, jank, big jank, huge jank
        - CPU time distribution: average, max, P95, P99
        - Performance rating: EXCELLENT/GOOD/ACCEPTABLE/POOR

        PERFORMANCE STANDARDS:
        - EXCELLENT: <1% jank rate (console-quality smoothness)
        - GOOD: 1-5% jank rate (most users won't notice)
        - ACCEPTABLE: 5-10% jank rate (power users will complain)
        - POOR: >10% jank rate (all users affected)

        KEY INSIGHTS:
        - P99 CPU time: Your worst-case frame cost
        - Max CPU time: Spike detection (GC, loading, etc.)
        - Big/huge jank counts: Critical frames that users definitely noticed

        TYPICAL WORKFLOW:
        1. Run this first for overall assessment
        2. If POOR/ACCEPTABLE, use detect_jank_frames for specific bad frames
        3. Correlate bad frame timestamps with other events

        NOTE: Different content types have different standards. Games might accept 5% jank 
        during action scenes, while a reading app should maintain <1% always.
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
        Detect memory leaks through heap growth patterns and suspicious class analysis.

        USE THIS WHEN: Investigating OOM crashes, gradual performance degradation over time, 
        user reports of app becoming sluggish after extended use, or high memory warnings. 
        Memory leaks are often subtle - small leaks can take hours to cause visible problems.

        ANALYZES TWO DIMENSIONS:
        1. Growth pattern: RSS memory trend over time
        2. Heap suspects: Classes with excessive retained memory

        DETECTION CRITERIA:
        - Sustained growth >5MB/min (default threshold)
        - Large dominated heap sizes for specific classes
        - Correlation between growth rate and heap suspects

        PARAMETERS:
        - process_name: Target app
        - growth_threshold_mb_per_min: Leak indicator (default 5.0)
        - analysis_duration_ms: Time window (default 60 seconds)

        OUTPUT:
        - Growth metrics: average/max growth rate, leak indicator count
        - Suspicious classes: Ranked by dominated size with instance counts
        - Memory impact classification per class

        COMMON LEAK PATTERNS:
        - Bitmaps/images not recycled: Large dominated_size_mb
        - Listener registration without unregistration: High instance_count
        - Static collections growing unbounded: Increasing over time
        - Context leaks: Activity/View classes in heap

        LIMITATIONS: Requires heap graph data in trace. Without it, only RSS growth analysis 
        is available. For detailed leak paths, follow up with heap_dominator_tree_analyzer.

        FALSE POSITIVES: Caches and pools may show growth that stabilizes. Check if growth 
        continues indefinitely or plateaus.
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
        Deep-dive into heap memory to identify specific memory-hogging classes.

        USE THIS WHEN: After memory_leak_detector finds issues, investigating high baseline 
        memory usage, or optimizing memory footprint. This shows exactly which classes are 
        retaining the most memory and preventing garbage collection.

        ANALYZES:
        - Latest heap graph snapshot in trace
        - Dominator relationships (what's keeping objects alive)
        - Self vs native memory per class
        - Reachability and GC root distance

        OUTPUT PER CLASS:
        - instance_count: Number of objects
        - self_size_mb: Java heap memory
        - native_size_mb: Native allocations
        - total_size_mb: Combined impact
        - memory_impact: CRITICAL (>50MB), WARNING (>20MB), NORMAL

        KEY INSIGHTS:
        - High instance count + low individual size = collection leak
        - Low instance count + high size = large object problem
        - High native_size: Bitmaps, native buffers
        - Low root_distance: Directly referenced from GC roots

        COMMON FINDINGS:
        - Bitmap/Drawable: Image caching issues
        - Activity/Fragment: Context leaks
        - ArrayList/HashMap: Unbounded collections
        - Custom classes: App-specific retention

        OPTIMIZATION TARGETS: Focus on CRITICAL/WARNING classes first. A single fix can 
        often recover tens of MBs.

        REQUIREMENTS: Requires heap graph data (Debug.dumpHprofData or similar). If extended 
        columns/modules are missing, the tool falls back to a simplified query (omits native_size, 
        reachability, root_distance) and adds a note. If no heap graph exists, returns 
        HEAP_GRAPH_UNAVAILABLE.
        """
        return heap_dom_tool.heap_dominator_tree_analyzer(trace_path, process_name, max_classes)

    @mcp.tool()
    def thread_contention_analyzer(
        trace_path: str,
        process_name: str,
        time_range: dict | None = None,
        min_block_ms: float = 50.0,
        include_per_thread_breakdown: bool = False,
        include_examples: bool = False,
        limit: int = 80,
    ) -> str:
        """
        Find thread synchronization bottlenecks with automatic fallback analysis  - the hidden cause of most ANRs.

        USE THIS WHEN: ANRs with unclear cause, UI freezes despite low CPU usage, deadlock
        suspicion, or whenever performance problems don't correlate with CPU/memory metrics.
        This tool often reveals the true cause when other metrics look normal.

        CRITICAL INSIGHT: Thread contention is the #1 cause of ANRs, more common than CPU
        overload or memory pressure. A single poorly-placed synchronized block can freeze
        an entire app.

        ANALYSIS MODES:
        - PRIMARY: Uses android.monitor_contention data when available for precise Java lock details
        - FALLBACK: Automatically falls back to scheduler-based inference using thread_state,
          sched_waking, and optionally sched_blocked_reason tables when monitor contention is missing

        DETECTS:
        - Which threads are blocked and what's blocking them
        - Specific methods holding locks (when available)
        - Wait duration and frequency
        - Concurrent waiter counts (deadlock risk indicator)
        - D-state blocking attribution via sched_blocked_reason (when available)

        SEVERITY CLASSIFICATION:
        - CRITICAL: Main thread blocked >100ms
        - HIGH: Any thread blocked >500ms or frequent contention
        - MEDIUM: Moderate blocking on worker threads
        - LOW: Minor contention, not user-visible

        OUTPUT METADATA:
        - analysisSource: "monitor_contention" (primary) or "scheduler_inferred" (fallback)
        - usesWakerLinkage: true if waker-thread relationships were available
        - usedSchedBlockedReason: true if D-state function attribution was available
        - primaryDataUnavailable: true when fallback was used
        - fallbackNotice: human-readable explanation when fallback was triggered

        COMMON ANTI-PATTERNS FOUND:
        - Synchronized singleton access on hot paths
        - Database locks held during network I/O
        - SharedPreferences.commit() on main thread
        - Nested synchronized blocks (deadlock risk)
        - UI thread waiting for background thread locks

        RECOMMENDED TRACE CONFIGS:
        - Primary: Include android.monitor_contention data source
        - Fallback: Include linux.ftrace with sched/sched_switch, sched/sched_waking,
          and optionally sched/sched_blocked_reason events

        PARAMETERS:
        - process_name: Target app/process (supports exact name; use find_slices/process metadata tools for discovery)
        - time_range: {'start_ms': X, 'end_ms': Y} to focus analysis on a specific window (e.g., app startup, ANR)
        - min_block_ms: Ignore waits shorter than this threshold (default 50ms)
        - include_per_thread_breakdown: Include per-thread S/D totals and percentages
        - include_examples: Include top example waits for illustration
        - limit: Cap for groups/examples/breakdown rows (default 80)

        FIX PRIORITY: Usually easy fixes with huge impact. Moving work outside synchronized
        blocks or using concurrent structures often solves the problem completely.
        """
        return thread_contention_tool.thread_contention_analyzer(
            trace_path,
            process_name,
            time_range,
            min_block_ms,
            include_per_thread_breakdown,
            include_examples,
            limit,
        )

    @mcp.tool()
    def binder_transaction_profiler(
        trace_path: str,
        process_filter: str,
        min_latency_ms: float = 10.0,
        include_thread_states: bool = True,
        time_range: dict | None = None,
        correlate_with_main_thread: bool = False,
        group_by: str | None = None,
    ) -> str:
        """
        Analyze cross-process (IPC) communication performance and bottlenecks.

        USE THIS WHEN: Slow system UI interactions, input lag, delays in content providers 
        or system services, or when ANRs involve system process communication. Binder is 
        Android's core IPC mechanism - slow binder calls directly cause ANRs.

        MEASURES:
        - Client-side latency (includes waiting + server processing)
        - Server-side processing time
        - Overhead (client latency - server time = IPC overhead)
        - Main thread impact (critical for ANRs)

        PARAMETERS:
        - process_filter: Match as client OR server
        - min_latency_ms: Focus on slow calls (default 10ms)
        - include_thread_states: Show what threads were doing during call
        - time_range: Optional {'start_ms': X, 'end_ms': Y} to scope analysis window
        - correlate_with_main_thread: If true, add best-effort main-thread state summary
        - group_by: One of None, 'aidl', 'server_process' for aggregated views

        KEY METRICS:
        - is_main_thread=true + latency>100ms = ANR risk
        - High overhead = system scheduling issues
        - Synchronous calls on main thread = architecture problem

        COMMON PROBLEMATIC PATTERNS:
        - ContentResolver queries on main thread
        - System service calls during UI drawing
        - Synchronous LocationManager/SensorManager calls
        - PackageManager operations on main thread

        OUTPUT: When group_by is None, returns transaction rows with latencies and overhead_ratio. 
        When grouped, returns aggregates by AIDL method or server process.

        ARCHITECTURE INSIGHT: High binder latency often indicates the need to make calls 
        asynchronous or cache results. Consider using AsyncTask, coroutines, or caching layers.

        NOTE: Some system binder calls are unavoidable. Focus on reducing frequency and moving 
        off main thread where possible.
        """
        return binder_txn_tool.binder_transaction_profiler(
            trace_path,
            process_filter,
            min_latency_ms,
            include_thread_states,
            time_range,
            correlate_with_main_thread,
            group_by,
        )

    @mcp.tool()
    def main_thread_hotspot_slices(
        trace_path: str,
        process_name: str,
        limit: int = 80,
        time_range: dict | None = None,
        min_duration_ms: float | int | None = None,
    ) -> str:
        """
        Identify the heaviest main-thread slices for a process, ordered by duration.

        USE THIS WHEN: You need the fastest view into what the UI thread is spending time on.
        This is ideal for ANR and jank triage, highlighting long-running callbacks and phases.

        PARAMETERS:
        - process_name: Target app/process (supports GLOB like "com.example.*").
        - time_range: {'start_ms': X, 'end_ms': Y} to focus on specific periods.
        - limit: Max number of slices to return (default 80).
        - min_duration_ms: Only include slices >= threshold.

        OUTPUT:
        - hotspots: Top slices with ids, timestamps, durations, and context (thread/process/track).
        - summary: Totals and whether main-thread flag or heuristic was used.
        - notes: Data availability and fallback information.
        """
        return main_thread_hotspot_tool.main_thread_hotspot_slices(
            trace_path,
            process_name,
            limit,
            time_range,
            min_duration_ms,
        )

    # Setup cleanup using atexit
    atexit.register(connection_manager.cleanup)

    # Register MCP resources in dedicated module
    register_resources(mcp)

    logger.info("Perfetto MCP server created with connection management")

    return mcp
