import { useState } from "react"
import { Badge, Input, Select } from "@/ui"
import type { OperationEvent } from "../model"

const labels: Record<string, string> = {
  queued: "排队",
  running: "运行中",
  succeeded: "成功",
  failed: "失败",
  cancelled: "已取消",
  interrupted: "异常中断",
  ready: "就绪",
  stopped: "停止",
  info: "信息",
  warning: "警告",
}

export function LogView({ events }: { events: readonly OperationEvent[] }) {
  const [kind, setKind] = useState("all")
  const [state, setState] = useState("all")
  const [query, setQuery] = useState("")
  const filtered = events.filter(
    (event) =>
      (kind === "all" || event.kind === kind) &&
      (state === "all" || event.status === state) &&
      (event.message + event.taskId).toLowerCase().includes(query.toLowerCase())
  )
  return (
    <section className="mx-auto max-w-6xl space-y-6 p-5 sm:p-8">
      <div>
        <h1 className="text-2xl font-semibold">生命周期与日志</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          最近 500 条结构化记录 · 按任务 ID 追踪 · 不写入对话正文或模型响应
        </p>
      </div>
      <div className="flex flex-wrap gap-3">
        <Input
          aria-label="搜索日志"
          className="max-w-md"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索消息或任务 ID"
        />
        <Select
          label="日志类型"
          value={kind}
          onValueChange={setKind}
          options={[
            { value: "all", label: "全部类型" },
            ...Array.from(new Set(events.map((event) => event.kind))).map(
              (value) => ({ value, label: value })
            ),
          ]}
        />
        <Select
          label="日志状态"
          value={state}
          onValueChange={setState}
          options={[
            { value: "all", label: "全部状态" },
            ...Object.entries(labels).map(([value, label]) => ({
              value,
              label,
            })),
          ]}
        />
      </div>
      <div className="divide-y overflow-hidden rounded-xl border bg-card">
        {filtered.length === 0 && (
          <p className="p-10 text-center text-muted-foreground">暂无匹配日志</p>
        )}
        {filtered.map((event) => (
          <article key={event.id} className="space-y-2 p-4 sm:px-6">
            <div className="flex flex-wrap items-center gap-3 text-xs">
              <time className="text-muted-foreground">{event.at}</time>
              <Badge variant="secondary">{event.kind}</Badge>
              <Badge
                variant="outline"
                className={event.status === "failed" ? "text-destructive" : ""}
              >
                {labels[event.status] ?? event.status}
              </Badge>
            </div>
            <p className="text-sm wrap-anywhere">{event.message}</p>
            {event.taskId && (
              <button
                className="text-xs text-primary underline"
                onClick={() => setQuery(event.taskId)}
              >
                任务 {event.taskId}
              </button>
            )}
          </article>
        ))}
      </div>
    </section>
  )
}
