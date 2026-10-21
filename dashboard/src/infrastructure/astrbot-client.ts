import { z } from "zod"
import type { ApiRequest, ApiResponse } from "../contracts/api.ts"
import { memoryCollectionSchema } from "../features/memory/model.ts"
import {
  detailSchema,
  diagnosticSchema,
  eventsSchema,
  statusSchema,
  updateSchema,
  type ManagementClient,
} from "../features/control/model.ts"

interface PluginBridge {
  ready(): Promise<unknown>
  apiGet(endpoint: string, query?: Record<string, string>): Promise<unknown>
  apiPost(endpoint: string, body: unknown): Promise<unknown>
}
declare global {
  interface Window {
    AstrBotPluginPage?: PluginBridge
  }
}

async function bridge(): Promise<PluginBridge> {
  const current = window.AstrBotPluginPage
  if (!current)
    throw new Error("请从 AstrBot 的 SeekMemory 插件视图打开此页面。")
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    await Promise.race([
      current.ready(),
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(
          () => reject(new Error("宿主连接超时，请重新打开插件视图。")),
          10000
        )
      }),
    ])
  } finally {
    if (timer !== undefined) clearTimeout(timer)
  }
  return current
}

const idResponseSchema = z.object({ id: z.string() }) satisfies z.ZodType<
  ApiResponse<"task">
>

export const astrbotClient: ManagementClient = {
  async records() {
    const host = await bridge()
    const data = await host.apiGet("manage/records")
    return z.object({ records: memoryCollectionSchema }).parse(data).records
  },
  async status() {
    const host = await bridge()
    const data = await host.apiGet("manage/status")
    return statusSchema.parse(data)
  },
  async detail(id) {
    const host = await bridge()
    const data = await host.apiGet("manage/detail", { id })
    return detailSchema.parse(data)
  },
  async events() {
    const host = await bridge()
    const data = await host.apiGet("manage/events")
    return eventsSchema.parse(data).events
  },
  async update(command) {
    const body = updateSchema.parse(command) satisfies ApiRequest<"update">
    const host = await bridge()
    const data = await host.apiPost("manage/update", body)
    idResponseSchema.parse(data)
  },
  async diagnose(query) {
    const body: ApiRequest<"diagnose"> = query
    const host = await bridge()
    const data = await host.apiPost("manage/diagnose", body)
    return diagnosticSchema.parse(data)
  },
  async task(kind) {
    const body = { kind, confirmed: true } satisfies ApiRequest<"task">
    const host = await bridge()
    const data = await host.apiPost("manage/task", body)
    return idResponseSchema.parse(data).id
  },
  async cancel(id) {
    const body = { id, confirmed: true } satisfies ApiRequest<"cancel">
    const host = await bridge()
    const data = await host.apiPost("manage/cancel", body)
    idResponseSchema.parse(data)
  },
}
