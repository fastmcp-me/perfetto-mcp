# Perfetto Trace Analysis Reference for MCP

## Architecture & Data Model

**Core Data Types**:
- **Slices**: Time-bounded events with start/end timestamps, can be nested to show call stacks. Depth parameter indicates nesting level.
- **Counters**: Time-series numeric values (CPU freq, memory, battery) sampled at timestamps
- **Thread States**: Scheduling information with state transitions
- **Flows/Links**: Arrows connecting cause->effect across threads/processes

**Track Hierarchy**:
- CPU core tracks: Per-core runnable thread slices
- Process tracks: High-level events affecting entire process
- Thread tracks: Detailed execution including function calls
- Counter tracks: Time-series graphs
- Frame timeline: Expected vs Actual frame slices

## Essential SQL Tables & Queries

**Core Tables**:
- `slice`: Duration events (ts, dur, name, depth, track_id)
- `thread_state`: Thread scheduling states and durations
- `sched_slice`: CPU scheduling with nanosecond precision
- `android_anrs`: Detected ANR events with timestamps
- `counter/counter_track`: Time-series metrics
- `process/thread`: Metadata (names, PIDs, TIDs)
- `android_startup`: App launch metrics

## Mental model

Perfetto gives a unified, system-wide timeline joining kernel, framework/services, and app events so you can answer: what ran, where, and for how long. Core primitives the LLM should use: Tracks (CPU cores, processes, threads, counters), Slices (bounded work like Choreographer#doFrame or Binder transact), Counters (CPU freq/util, heap size, battery/GPU), and Flows (cause->effect across threads/processes).

**Key Analysis Queries**:
```sql
-- Thread state distribution for main thread
SELECT state, SUM(dur)/1e9 AS total_sec, 
       100.0 * SUM(dur)/(SELECT MAX(ts)-MIN(ts) FROM thread_state) AS percentage
FROM thread_state JOIN thread USING(utid)
WHERE thread.name = 'main' GROUP BY state ORDER BY total_sec DESC;

-- Find scheduling gaps indicating jank
SELECT ts, dur, cpu, end_state, thread.name, process.name
FROM sched_slice LEFT JOIN thread USING(utid) LEFT JOIN process USING(upid)
WHERE thread.is_main_thread = 1 AND dur > 16000000 -- 16ms+ gaps
ORDER BY dur DESC;

-- Binder transaction latency analysis
SELECT slice.name, dur/1e6 as latency_ms, ts/1e9 as timestamp_sec
FROM slice WHERE name LIKE 'binder%' AND dur > 10e6
ORDER BY dur DESC LIMIT 20;

-- GC frequency and impact
SELECT ts/1e9 AS time_sec, dur/1e6 AS gc_duration_ms,
       LEAD(ts) OVER (ORDER BY ts) - ts AS time_to_next_gc
FROM slice WHERE name LIKE 'GC_%';
```

## ANR Deep Dive

**Detection & Analysis Workflow**:
1. **Locate ANR**: Find `am_anr` event in system_server for exact timestamp
2. **Identify window**: Examine 100ms-1s before ANR detection (critical period)
3. **Main thread analysis**:
   - Last responsive moment
   - State transitions: Running (R) -> Sleeping (S) or Uninterruptible Sleep (D)
   - Check for: I/O operations, binder transactions, lock waits, GC pauses
4. **Trace dependencies**:
   - Wake-up chains between threads
   - Binder transaction flows (client -> server spans)
   - Shared resource access patterns
5. **System factors**:
   - CPU saturation (many runnable threads)
   - System_server lock contention
   - Binder thread pool exhaustion

**Thread States Explained**:
- **Running (R)**: Currently executing on CPU
- **Runnable (R)**: Ready but waiting for CPU (CPU contention indicator)
- **Sleeping (S)**: Voluntary wait (locks, conditions)
- **Uninterruptible Sleep (D)**: I/O wait, cannot be interrupted (disk/network)
- **Stopped (T)**: Suspended by signal
- **Zombie (Z)**: Terminated but not reaped

**Common ANR Patterns**:
- **Deadlocks**: Circular wait patterns, multiple threads in Sleep state with lock wait reasons
- **Main thread I/O**: Operations >100ms (file system, database queries, SharedPreferences commits)
- **Binder bottlenecks**: Transactions >1-2 seconds, incomplete at ANR time, thread pool saturation
- **GC pressure**: Multiple consecutive GC events blocking execution

## Performance Analysis Patterns

**Frame Production Pipeline**:
1. Input processing
2. Animation updates  
3. Measure/layout passes (check for multiple per frame)
4. Draw operations (watch for overdraw)
5. RenderThread GPU commands
6. SurfaceFlinger composition

**Jank Detection Metrics**:
- Single frame >25ms = visible stuttering
- Frame >32ms = multiple dropped frames
- Irregular frame intervals = pipeline problems
- Check: Choreographer#doFrame duration, VSYNC-app vs VSYNC-sf alignment
- App Jank Types: Key app-related janks include "AppDeadlineMissed" (app took longer than expected) and "BufferStuffing" (app sends frames faster than they can be presented, creating a queue backlog that increases input latency).
- SurfaceFlinger Jank Categories: System-level janks include "SurfaceFlingerCpuDeadlineMissed" (main thread overrun), "SurfaceFlingerGpuDeadlineMissed" (GPU composition delays), "DisplayHAL" (hardware abstraction layer delays), and "PredictionError" (scheduler timing drift).
- SQL Data Access: Frame data is accessible through SQL queries via two main tables (`expected_frame_timeline_slice` and `actual_frame_timeline_slice`) that provide detailed timing, token information, jank types, and process details for comprehensive performance analysis.

**Memory Pressure Indicators**:
- **App level**: GC frequency >1/sec, GC duration >10ms, heap growth approaching limit
- **System level**: kswapd activation, direct reclaim events, lmkd process kills, PSI metrics
- **Allocation patterns**: Spikes >10MB/sec during animations, monotonic growth (leaks), rapid alloc/free cycles (churn)

**Cascading Failure Recognition**:
- Memory pressure -> GC storms -> frame drops
- CPU saturation -> scheduling delays -> ANR
- Thermal rise -> frequency throttling -> system-wide slowdown
- Lock contention -> priority inversions -> RenderThread delays

## System Components Analysis

**system_server Critical Services**:
- **ActivityManagerService**: Process lifecycle, ANR detection (`am_anr` events), memory trimming
- **WindowManagerService**: Focus changes, visibility updates, input routing, animation coordination
- **InputDispatcher**: 5-second timeout enforcement, input queue management, touch/key event processing
- **PowerManagerService**: Wake locks, power state transitions, battery optimization impacts

**SurfaceFlinger**:
- Vsync signal generation (60/90/120Hz targets)
- Buffer queue management (depth indicates pressure)
- Layer composition (count and complexity)
- GPU composition fallback (performance impact)

**Binder IPC Analysis**:
- Transaction components: `binder_transaction` (outgoing), `binder_transaction_received` (incoming)
- Thread pool: Binder_1, Binder_2, etc. (exhaustion causes queuing)
- Performance red flags: Latency >10ms, queue depth growth, transactions >1MB, failed transactions

## Systematic Analysis Methodology

### Initial Assessment Checklist:
- Trace validity: Sufficient duration, necessary categories enabled
- Baseline establishment: Normal frame durations, memory patterns, thread utilization
- Symptom window identified: Exact timeframe of issue
- Critical threads identified: Main, RenderThread, relevant Binder threads

### Investigation Workflows:

### ANR investigation workflow:
1. **Locate ANR event**: Find `am_anr` in system_server
2. **Identify frozen thread**: Usually main/UI thread
3. **Analyze pre-ANR window**: 5-10 seconds before event
4. **Check thread state**: 
   - Last responsive moment
   - Transition to blocked state
   - Blocking reason/wait channel
5. **Trace dependencies**:
   - Binder calls in progress
   - Lock holders
   - I/O operations
6. **Identify root cause**:
   - Direct blocker
   - Cascade effects
   - System conditions

### Common ANR root causes:
- **Deadlocks**:
  - Circular wait patterns in lock acquisition
  - Multiple threads waiting on each other
  - Visible as threads in Sleep state with lock wait reasons
- **Main thread I/O**:
  - File system operations exceeding 100ms
  - Database queries without async handling
  - SharedPreferences commits on main thread
- **Infinite loops**:
  - CPU consumption without yielding
  - Missing break conditions
  - Continuous Running state without progress
- **GC pressure**:
  - Excessive garbage collection blocking execution
  - Multiple consecutive GC events
  - Memory allocation failures

### Jank investigation workflow:
1. **Quantify problem**: SQL query for frames >16.67ms
2. **Identify worst frames**: Sort by duration
3. **Per-frame analysis**:
   - Main thread operations
   - RenderThread completion
   - SurfaceFlinger composition
4. **Pattern recognition**:
   - Consistent problems vs. spikes
   - Correlation with user actions
   - System event alignment
5. **Root cause analysis**:
   - App code issues
   - System resource contention
   - Environmental factors

### Memory investigation workflow:
1. **Characterize usage**: Growth rate, peaks, baseline
2. **GC pattern analysis**:
   - Frequency and duration
   - Types of collection
   - Memory freed per GC
3. **Allocation tracking**:
   - Hot allocation sites
   - Large allocations
   - Allocation storms
4. **System memory correlation**:
   - Available memory trends
   - Memory pressure events
   - Process terminations
5. **Leak detection**:
   - Monotonic growth
   - Unreleased references
   - Native vs. Java heap

### Practical Triage Questions:
- Which thread is on critical path? Running vs waiting? Why?
- Is device CPU-bound, I/O-bound, lock-bound, or remote-service-bound?
- Any GC, frequency limits, or thermal events?
- Single root cause or multiple compounding factors?

## Repeatable analysis workflow

1. Isolate the symptom window (user action, jank cluster, stall, power spike).
2.	Check frame health (if UI): find over‑budget frames; record timestamps.
3.	Inspect critical threads in that window:
	- UI/Main (measure/layout/draw), check GC pauses and lock waits.
	- RenderThread/GPU for heavy rasterization or driver waits.
	- Binder pool for long remote calls or queue buildup.
4.	Correlate with CPUs: were cores busy? Was the thread runnable but unscheduled? What frequencies were set?
5.	Identify waits: I/O (disk/net), mutex, scheduler wait, Binder reply latency.
6.	Scan counters: RAM spikes -> GC; pinned low CPU freq -> latency/thermal; current spikes -> power regressions.
7.	Validate causality: follow flows or Binder chains request->work->response.
8.	Summarize the root cause in one sentence with evidence.

## Common Anti-patterns & Solutions

**Main Thread Violations**:
- Synchronous file I/O -> Use background threads
- Network calls -> AsyncTask/Coroutines
- Database queries -> Room with LiveData
- Bitmap decoding -> Background + caching
- SharedPreferences commit() -> Use apply()

**Layout Inefficiencies**:
- Nested LinearLayouts with weights -> ConstraintLayout
- Complex RelativeLayout chains -> Flatten hierarchy
- Multiple onLayout per frame -> Optimize invalidation
- Deep view hierarchies -> Merge/ViewStub

**Object Allocation Hot Paths**:
- Allocations in onDraw() -> Pre-allocate
- String concatenation in loops -> StringBuilder
- Creating objects in tight loops -> Object pools
- Autoboxing in performance code -> Primitive arrays

## Environmental & Cross-Process Factors

**Thermal Management**:
- CPU/GPU frequency scaling visible in traces
- Thermal zone temperature readings
- Throttling patterns: Periodic drops, sustained limitations

**Cross-Process Dependencies**:
- PackageManager queries during startup
- System service contention (ActivityManager, WindowManager)
- Shared resources: File locks, databases, hardware (camera, sensors)
- Multi-hop binder chains: Cumulative latency, timeout propagation

## Building Analytical Intuition

**Pattern Recognition Signatures**:
- **Lock contention**: Multiple threads waiting, same wait channel, priority inversions
- **Memory pressure cascade**: GC storms -> allocation failures -> lmkd kills
- **Thermal throttling**: Periodic performance drops aligned with freq changes
- **Binder exhaustion**: All Binder_N threads busy, growing transaction queue

**Key Principles**:
- Never analyze single track in isolation - correlate across layers
- Distinguish symptoms from root causes - visible problems have hidden origins
- Use SQL for quantitative analysis
- Consider device state and environmental factors
- Focus on critical path - what's actually blocking user experience

**Progressive Analysis**:
1. Broad metrics: Overall frame rate, memory trends, CPU usage
2. Anomaly identification: Statistical outliers, pattern breaks
3. Focused analysis: Specific timeframes, affected components
4. Root cause tracing: Dependencies, causality chains
5. Verification: Consistency across multiple occurrences

## ANR Timeout Reference

| ANR Type | Timeout | Focus Areas |
|----------|---------|-------------|
| Input dispatch | 5 seconds | Touch/key events, UI thread blocking |
| Broadcast (foreground) | 10 seconds | onReceive() execution, synchronous operations |
| Service (foreground) | 20 seconds | onCreate/onStartCommand, initialization |
| Broadcast (background) | 60 seconds | Background processing, resource contention |

## Frame Timing Targets

| Display Refresh Rate | Frame Budget | Jank Threshold |
|---------------------|--------------|----------------|
| 60Hz | 16.67ms | >25ms |
| 90Hz | 11.11ms | >17ms |
| 120Hz | 8.33ms | >13ms |

## Diagnostic patterns & fast cues
- UI jank (missed vsync): over-long doFrame on UI, heavy raster on RenderThread, or delayed CPU service due to contention.
- Binder bottlenecks: client main thread awaiting reply; confirm server thread-pool saturation and long handlers.
- I/O stalls: main thread touches disk/network; long syscalls; CPU cores idle while waiting.
- GC pauses: recognizable runtime slices; correlate with heap counters & allocation bursts.
- Thermal/CPU scaling: low frequencies under demand -> latency; sustained high freq with little work -> power waste.
- Lock contention: many short run slices with waits on a mutex; long critical section on the owner thread.

Thread state sanity
When a thread is slow, classify it as Running (consuming CPU), Runnable (ready but not scheduled -> CPU contention or priority issue), or Waiting/Blocked (I/O, lock, Binder reply). Breakdowns across sched/thread_state plus per-core activity quickly reveal the limiting factor.

## Quick triage checklist (for the LLM)
- Have we found the symptom window?
- Which thread is on the critical path and is it running, runnable, or waiting-and why?
- Are we CPU-bound, I/O-bound, lock-bound, or remote-service-bound?
- Any GC, frequency limits, or thermal events?
- Single root cause or multiple compounding factors?
- Do we have ranked, actionable fixes?
