import {
  tracesSchema,
  type TraceEvent,
  type TraceFlag,
} from "../features/control/trace-model.ts"

// Fictional runs for the local preview; artifact links use the existing mock drawer.
export function demoTraces(artifactId: string) {
  const variants: TraceFlag[][] = [
    ["recalled_and_injected", "recalled_but_withheld", "fallback_used"],
    ["not_recalled"],
    ["recalled_but_withheld"],
    ["recalled_and_injected"],
  ]
  const events: TraceEvent[] = []
  const runs = variants.map((flags, index) => {
    const id = String(index + 1).repeat(32)
    const injected = flags.includes("recalled_and_injected")
    const withheld = flags.includes("recalled_but_withheld")
    const names: TraceEvent["event"][] = [
      "agent_begin",
      "llm_request",
      "tool_call",
      "tool_result",
      "llm_response",
      "agent_done",
    ]
    if (index === 0) names.push("message_sent")
    const stepStatus = (event: TraceEvent["event"]): TraceEvent["status"] => {
      if (event === "tool_result") return "unknown"
      if (event === "agent_done" && index === 3) return "error"
      if (event === "agent_begin" || event === "tool_call") return "running"
      return "ok"
    }
    const steps = names.map((event, sequence): TraceEvent => ({
      run_id: id,
      sequence: sequence + 1,
      at: new Date(Date.UTC(2026, 9, 23, 8 - index, 0, sequence)).toISOString(),
      event,
      request_index: sequence ? 1 : 0,
      status: stepStatus(event),
      duration_ms: event === "tool_result" ? 120 : null,
      tool: event.startsWith("tool_") ? "lookup_weather" : "",
      recall:
        event === "llm_request"
          ? {
              mode: "strict",
              candidates: index === 1 ? 0 : 3,
              picked_ids: injected ? [artifactId] : [],
              pinned_ids: [],
              artifact_ids: injected ? [artifactId] : [],
              dropped_ids: [],
              withheld_ids: withheld ? ["mock_memory_family_2"] : [],
              disclosure: withheld ? { mock_memory_family_2: "silence" } : {},
              fallback: flags.includes("fallback_used") ? "recent_topic" : "",
              chars: injected ? 80 : 0,
              gate: {
                evaluated: index !== 1,
                passed: index === 1 ? 0 : 1,
                rejected: index === 1 ? 0 : 2,
                threshold: 0.7,
              },
            }
          : null,
    }))
    events.push(...steps)
    return {
      id,
      started_at: steps[0]?.at,
      updated_at: steps.at(-1)?.at,
      status: index === 3 ? "error" : "completed",
      delivered: index === 0,
      flags,
      artifact_ids: injected ? [artifactId] : [],
      event_count: steps.length,
      partial: false,
    }
  })
  return tracesSchema.parse({
    runs,
    events,
    capacity: 5000,
    retention_days: 7,
    persistence_error: false,
  })
}
