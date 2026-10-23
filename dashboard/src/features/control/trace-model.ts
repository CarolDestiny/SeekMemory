import { z } from "zod"
import type { ApiResponse } from "../../contracts/api.ts"

const ids = z.array(z.string()).max(256)
export const traceFlagSchema = z.enum([
  "not_recalled",
  "recalled_but_withheld",
  "recalled_and_injected",
  "fallback_used",
])
export type TraceFlag = z.infer<typeof traceFlagSchema>
export const traceFlagLabels: Record<TraceFlag, string> = {
  not_recalled: "未召回记忆",
  recalled_but_withheld: "部分记忆被隐藏",
  recalled_and_injected: "记忆已注入",
  fallback_used: "使用兜底",
}
const recallSchema = z.strictObject({
  mode: z.enum(["none", "strict", "loose"]),
  candidates: z.number().int().nonnegative(),
  picked_ids: ids,
  pinned_ids: ids,
  artifact_ids: ids,
  dropped_ids: ids,
  withheld_ids: ids,
  disclosure: z.record(
    z.string(),
    z.enum(["full", "paraphrase", "hint", "silence"])
  ),
  fallback: z.enum(["", "recent_profile", "recent_topic"]),
  chars: z.number().int().nonnegative(),
  gate: z.strictObject({
    evaluated: z.boolean(),
    passed: z.number().int().nonnegative(),
    rejected: z.number().int().nonnegative(),
    threshold: z.number().nonnegative(),
  }),
})
const traceEventSchema = z.strictObject({
  run_id: z.string(),
  sequence: z.number().int().nonnegative(),
  at: z.iso.datetime({ offset: true }),
  event: z.enum([
    "agent_begin",
    "llm_request",
    "llm_response",
    "agent_done",
    "message_sent",
    "tool_call",
    "tool_result",
  ]),
  request_index: z.number().int().nonnegative(),
  status: z.enum(["running", "ok", "error", "unknown"]),
  duration_ms: z.number().nonnegative().nullable(),
  tool: z.string(),
  recall: recallSchema.nullable(),
})
export const tracesSchema = z.strictObject({
  runs: z.array(
    z.strictObject({
      id: z.string(),
      started_at: z.string(),
      updated_at: z.string(),
      status: z.enum(["running", "completed", "error", "interrupted"]),
      delivered: z.boolean(),
      flags: z.array(traceFlagSchema),
      artifact_ids: ids,
      event_count: z.number().int().nonnegative(),
      partial: z.boolean(),
    })
  ),
  events: z.array(traceEventSchema),
  capacity: z.number().int().min(1).max(5000),
  retention_days: z.number().int().min(1).max(365),
  persistence_error: z.boolean(),
}) satisfies z.ZodType<ApiResponse<"traces">>
export type TraceSnapshot = z.infer<typeof tracesSchema>
export type TraceEvent = z.infer<typeof traceEventSchema>

export function filterRuns(snapshot: TraceSnapshot, filter: TraceFlag | "all") {
  return snapshot.runs.filter(
    (run) => filter === "all" || run.flags.includes(filter)
  )
}

export function runTimeline(snapshot: TraceSnapshot, runId: string) {
  return snapshot.events
    .filter((event) => event.run_id === runId)
    .sort((a, b) => a.sequence - b.sequence)
}
