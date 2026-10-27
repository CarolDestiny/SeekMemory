# Agent Runtime: Session Attention and Runtime Actions

## Responsibility

app/runtime defines host-agnostic session state, attention decisions, and runtime action lifecycle. It coordinates when to observe, reply, or wait, including deferred replies. It does not replace SeekMemory extraction/recall or AstrBot's ordinary agent/tool loop.

## Objects and policies

- RuntimeInput is a reduced host event; RunContext is one pending action context.
- SessionState stores runtime scheduling state such as wait, retry, quiet, cooldown, unread/read-through, and dispatch attempts. It is not a Source or Artifact.
- WakePolicy returns ignore, observe, wait, or reply. Private messages and direct mentions have high attention; explicit questions may reply directly; quiet/cooldown affects ambient traffic.
- TimingPolicy is a pure wait/retry deadline policy. Scheduler reads persisted state and returns due runs; RuntimeWorker polls, deduplicates in-flight work, and dispatches without owning memory rules.
- MemoryContextPort delegates to the existing RecallService through an adapter; Runtime does not implement a second memory retrieval path.

## Two runtime paths

**Normal AstrBot reply:** a hook gives the user message to AgentRuntime.accept_user; RunRecorder writes a user Source and queue projection; the request hook gets memory through runtime.build_context; after model response and host delivery, capture/delivery hooks use AgentRuntime and RunRecorder to record the assistant Source, recall reinforcement, and EpisodeRecord.

UserRunReceipt from accept_user includes the read_through_seq acknowledgement cursor captured for that run. The host carries it on the event and returns it to record_delivery after sending. Runtime acknowledges only messages through that cursor and preserves later unread input and scheduled work. Duplicate or out-of-order acknowledgements cannot move the read cursor, last delivery time, or cooldown backwards. Legacy calls without a cursor and stale events update delivery timing only. The extraction queue is not an unread counter; the host does not infer session unread counts from its length.

**Deferred ambient reply:** when runtime_gate_enabled is on, the worker selects a session whose wait/retry deadline is due. Runtime claims dispatch, builds memory context, calls ModelGateway, sends through MessageSender, then records the assistant Source and EpisodeRecord. Failure uses bounded per-session retries with exponential backoff. This path calls the provider directly and does not run the full AstrBot agent/tool loop.

Wait/retry deadlines remain persisted during model and send calls, with attempts persisted before the call. Cancellation schedules bounded retry and propagates cancellation. After process loss, the existing Scheduler can recover from that same state. Attempts survive restart, and a new Source has its own attempt budget. Only successful acknowledgement or exhaustion clears the corresponding work; deadlines installed by newer input are preserved. Runtime keeps a claim-time state snapshot to distinguish retained markers from newer work, without adding database fields, tables, or another scheduling loop.

After confirmed send success, runtime refreshes the injected clock for delivery audit, last delivery time, and cooldown. Failure or cancellation also refreshes the clock so backoff starts at failure time. An explicit now is a lower bound for that run. RuntimeWorker.dispatch owns the shared concurrency limit and session deduplication for both scans and direct calls. Queued sessions remain deduplicated; after acquiring a slot, dispatch rechecks the gate, clock, and due state. Cancellation releases both the slot and session marker. Coordination applies to one worker process and does not guarantee exactly-once sends across processes.

runtime_gate_enabled defaults to false. While disabled, wait and background deferred dispatch are inactive; ordinary event capture, memory injection, and audit hooks remain available.

## Write-back and diagnostics

RunRecorder is the single runtime write-back coordinator for Sources, pending projection, checkpoint, and episodes. run_id and deterministic Source IDs prevent repeated callbacks from duplicating writes. runtime_episodes is append-only business audit metadata; RunTracer/TraceStore is a field-whitelisted diagnostic timeline. They are separate and neither stores conversation bodies.

ToolPolicy can remove disallowed tools from req.func_tool before the model request. A post-call tool observation hook is diagnostic and cannot block execution by itself. Actual request filtering is controlled by runtime_tool_filter_enabled and is disabled by default.
