import { z } from "zod"
import type { MemoryRecord } from "../memory/model.ts"

export const detailSchema = z.object({
  artifact: z.object({
    header: z
      .object({
        id: z.string(),
        family: z.string(),
        revision: z.number().int().positive(),
        state: z.enum(["active", "forgotten", "merged"]),
        scope: z.enum(["private", "shared", "shadow"]),
      })
      .passthrough(),
    payload: z.record(z.string(), z.json()),
  }),
  versions: z.array(z.record(z.string(), z.json())),
  sources: z.array(z.record(z.string(), z.json())),
  ledger: z.array(z.record(z.string(), z.json())),
})
export const statusSchema = z.object({
  ready: z.boolean(),
  checks: z.array(
    z.object({ name: z.string(), ok: z.boolean(), detail: z.string() })
  ),
  activeTask: z.object({ id: z.string(), kind: z.string() }).nullable(),
  pending: z.array(
    z.object({ session: z.string(), count: z.number().int().nonnegative() })
  ),
  schedulerCount: z.number().int().nonnegative(),
  config: z.record(z.string(), z.json()),
})
const logSourceSchema = z.object({
  module: z.string(),
  file: z.string(),
  function: z.string(),
  line: z.number().int().positive(),
})
export const eventSchema = z.object({
  id: z.string(),
  at: z.string(),
  kind: z.string(),
  status: z.string(),
  message: z.string(),
  taskId: z.string(),
  level: z.enum(["DEBUG", "INFO", "WARNING", "ERROR"]).default("INFO"),
  stage: z.string().default(""),
  source: logSourceSchema.nullable().default(null),
  context: z
    .record(
      z.string(),
      z.union([z.string(), z.number(), z.boolean(), z.null()])
    )
    .default({}),
  durationMs: z.number().nonnegative().nullable().default(null),
  error: z
    .object({ type: z.string(), frames: z.array(logSourceSchema) })
    .nullable()
    .default(null),
})
export const eventsSchema = z.object({
  events: z.array(eventSchema),
  capacity: z.number(),
})
export const diagnosticSchema = z.object({
  block: z.string(),
  info: z.record(z.string(), z.json()),
  visible: z.array(z.string()),
  excluded: z.array(z.string()),
})
export const updateSchema = z.strictObject({
  id: z.string().min(1),
  expectedRevision: z.number().int().positive(),
  payload: z.record(z.string(), z.json()),
  scope: z.enum(["private", "shared", "shadow"]),
  state: z.enum(["active", "forgotten", "merged"]),
  reason: z.string().trim().min(1).max(300),
  confirmed: z.literal(true),
})
export type ArtifactDetail = z.infer<typeof detailSchema>
export type RuntimeStatus = z.infer<typeof statusSchema>
export type OperationEvent = z.infer<typeof eventSchema>
export type Diagnostic = z.infer<typeof diagnosticSchema>
export type UpdateCommand = z.infer<typeof updateSchema>
export interface DiagnosticQuery {
  query: string
  umo: string
  speaker: string
}

export interface ManagementClient {
  records(): Promise<readonly MemoryRecord[]>
  status(): Promise<RuntimeStatus>
  detail(id: string): Promise<ArtifactDetail>
  events(): Promise<OperationEvent[]>
  update(command: UpdateCommand): Promise<void>
  diagnose(query: DiagnosticQuery): Promise<Diagnostic>
  task(kind: "extract" | "weekly"): Promise<string>
  cancel(id: string): Promise<void>
}
