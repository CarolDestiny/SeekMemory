import { z } from "zod"
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

export const astrbotClient: ManagementClient = {
  async records() {
    const data = await (await bridge()).apiGet("manage/records")
    return z.object({ records: memoryCollectionSchema }).parse(data).records
  },
  async status() {
    return statusSchema.parse(await (await bridge()).apiGet("manage/status"))
  },
  async detail(id) {
    return detailSchema.parse(
      await (await bridge()).apiGet("manage/detail", { id })
    )
  },
  async events() {
    return eventsSchema.parse(await (await bridge()).apiGet("manage/events"))
      .events
  },
  async update(command) {
    await (await bridge()).apiPost("manage/update", updateSchema.parse(command))
  },
  async diagnose(query) {
    return diagnosticSchema.parse(
      await (await bridge()).apiPost("manage/diagnose", query)
    )
  },
  async task(kind) {
    return z
      .object({ id: z.string() })
      .parse(
        await (await bridge()).apiPost("manage/task", { kind, confirmed: true })
      ).id
  },
  async cancel(id) {
    await (await bridge()).apiPost("manage/cancel", { id, confirmed: true })
  },
}
