import {
  memoryCollectionSchema,
  type MemoryRecord,
} from "@/features/memory/model"
import {
  detailSchema,
  updateSchema,
  type ArtifactDetail,
  type ManagementClient,
  type OperationEvent,
} from "@/features/control/model"
import { mockMemories } from "./mock-data"

const base = mockMemories[0]
if (!base) throw new Error("Mock fixture requires a base record")
let records = memoryCollectionSchema.parse([
  ...mockMemories,
  ...[
    { category: "example", title: "一起把事情拆成小步骤", scope: "private" },
    { category: "media", title: "一篇关于夜间徒步的文章", scope: "shared" },
    { category: "secret", title: "有件事答应替他保密", scope: "shadow" },
    {
      category: "designated",
      title: "下次问起时，把这份计划还给他",
      scope: "private",
    },
  ].map((item, index) => ({
    ...base,
    ...item,
    id: `mock_memory_family_${index}`,
    text: item.title,
    tags: [],
    versions: [{ revision: 1, at: base.updatedAt, text: item.title }],
    relatedIds: [],
  })),
])
const details = new Map<string, ArtifactDetail>()
for (const record of records) {
  const family = ["fact", "scene", "detail", "impression"].includes(
    record.category
  )
    ? "memory"
    : record.category
  const payload: ArtifactDetail["artifact"]["payload"] = {
    owner_umo: record.session,
    tags: [...record.tags],
    ...(family === "example"
      ? { user: "事情好多，不知道从哪里开始", assistant: record.text }
      : family === "media"
        ? {
            type: "web",
            title: record.title,
            summary: record.text,
            url: "https://example.com/walk",
          }
        : family === "secret"
          ? { ref: "demo-private-reference", shadow_text: record.text }
          : family === "designated"
            ? { text: record.text, trigger: "计划" }
            : family === "memory"
              ? { text: record.text, level: record.category }
              : { text: record.text }),
  }
  details.set(
    record.id,
    detailSchema.parse({
      artifact: {
        header: {
          id: record.id,
          family,
          revision: record.versions[0].revision,
          state: record.state,
          scope: record.scope,
          said_by: record.subject,
        },
        payload,
      },
      versions: record.versions.map((item) => ({
        revision: item.revision,
        at: item.at,
        blob: "demo-content-hash",
        header: "{}",
        content: JSON.stringify({ ...payload, text: item.text }),
      })),
      sources: [],
      ledger: [],
    })
  )
}
let events: OperationEvent[] = [
  {
    id: "boot",
    at: "2026-10-21T08:00:00Z",
    kind: "plugin",
    status: "ready",
    message: "Loaded 14 active artifacts",
    taskId: "",
  },
  {
    id: "run",
    at: "2026-10-21T08:02:00Z",
    kind: "extract",
    status: "running",
    message: "Task started",
    taskId: "demo-extract-01",
  },
  {
    id: "done",
    at: "2026-10-21T08:02:03Z",
    kind: "extract",
    status: "succeeded",
    message: "sessions=2 written=3",
    taskId: "demo-extract-01",
  },
].reverse()

export const mockClient: ManagementClient = {
  async records() {
    return records
  },
  async status() {
    return {
      ready: true,
      checks: ["engine", "ledger", "provider", "journal"].map((name) => ({
        name,
        ok: true,
        detail: "Mock check — no real service connected",
      })),
      activeTask: null,
      pending: [{ session: "napcat:GroupMessage:10001", count: 8 }],
      schedulerCount: 3,
      config: {
        owner_umo: "napcat:FriendMessage:10001",
        observe_groups: true,
        summary_time: "23:50",
        weekly_day: 6,
        budget_chars: 600,
      },
    }
  },
  async events() {
    return events
  },
  async detail(id) {
    const detail = details.get(id)
    if (!detail) throw new Error("记忆不存在")
    return structuredClone(detail)
  },
  async update(input) {
    const command = updateSchema.parse(input)
    const detail = details.get(command.id)
    if (!detail || detail.artifact.header.revision !== command.expectedRevision)
      throw new Error("版本冲突，请重新加载")
    const at = new Date().toISOString()
    const textValue = command.payload["text"]
    const text =
      typeof textValue === "string"
        ? textValue
        : JSON.stringify(command.payload)
    detail.artifact = {
      header: {
        ...detail.artifact.header,
        revision: command.expectedRevision + 1,
        scope: command.scope,
        state: command.state,
      },
      payload: command.payload,
    }
    detail.versions.unshift({
      revision: detail.artifact.header.revision,
      at,
      blob: "demo-new-hash",
      content: JSON.stringify(command.payload),
    })
    detail.ledger.push({ op: "admin_revise", at, reason: command.reason })
    records = memoryCollectionSchema.parse(
      records.map((record): MemoryRecord =>
        record.id !== command.id
          ? record
          : {
              ...record,
              text,
              title: text.slice(0, 60),
              scope: command.scope,
              state: command.state,
              updatedAt: at,
              versions: [
                { revision: command.expectedRevision + 1, at, text },
                ...record.versions,
              ],
            }
      )
    )
  },
  async diagnose({ query, umo }) {
    const visible = records.filter(
      (record) =>
        record.state === "active" &&
        (record.scope !== "private" || record.session === umo)
    )
    const picked = visible.filter((record) => record.text.includes(query))
    return {
      block: picked.map((record) => record.text).join("\n"),
      info: { mock: true, mode: "strict", picked: picked.length },
      visible: visible.map((record) => record.id),
      excluded: records
        .filter((record) => !visible.includes(record))
        .map((record) => record.id),
    }
  },
  async task(kind) {
    const id = "demo-" + crypto.randomUUID()
    events = [
      {
        id,
        at: new Date().toISOString(),
        kind,
        status: "succeeded",
        message: "Mock task completed; no model call or real data change",
        taskId: id,
      },
      ...events,
    ]
    return id
  },
  async cancel() {
    throw new Error("Mock 中没有正在运行的真实任务")
  },
}
