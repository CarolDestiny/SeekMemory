import { Badge, Input, JsonView, Select, type BadgeProps } from "@/ui"
import type { OperationEvent } from "../model"
import { useLogs } from "../use-logs"

const labels: Record<string, string> = {
  queued: "排队",
  running: "运行中",
  succeeded: "成功",
  failed: "失败",
  cancelled: "已取消",
  interrupted: "异常中断",
  ready: "就绪",
  stopped: "停止",
  debug: "调试",
  info: "信息",
  warning: "警告",
}

const levelTones = {
  ERROR: "danger",
  WARNING: "warning",
  INFO: "info",
  DEBUG: "info",
} satisfies Record<OperationEvent["level"], BadgeProps["tone"]>

export function LogView({ events }: { events: readonly OperationEvent[] }) {
  const vm = useLogs(events)
  return (
    <section className="mx-auto w-full max-w-7xl space-y-6 p-5 sm:p-8">
      <div className="workspace-intro">
        <h1 className="text-2xl font-semibold">生命周期与日志</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          最近 500 条业务记录 · 模块 / 函数 / 行号 · 阶段耗时与任务关联
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          仅显式记录的业务事件；异常展示类型与调用位置，不记录对话正文、模型响应或局部变量。
        </p>
      </div>
      <div className="flex flex-wrap gap-3">
        <Input
          aria-label="搜索日志"
          className="max-w-md"
          value={vm.query}
          onChange={(event) => vm.setQuery(event.target.value)}
          placeholder="搜索模块、函数、阶段、任务 ID 或业务字段"
        />
        <Select
          label="日志类型"
          value={vm.kind}
          onValueChange={vm.setKind}
          options={[
            { value: "all", label: "全部类型" },
            ...vm.kinds.map((value) => ({ value, label: value })),
          ]}
        />
        <Select
          label="日志状态"
          value={vm.state}
          onValueChange={vm.setState}
          options={[
            { value: "all", label: "全部状态" },
            ...Object.entries(labels).map(([value, label]) => ({
              value,
              label,
            })),
          ]}
        />
        <Select
          label="日志级别"
          value={vm.level}
          onValueChange={vm.setLevel}
          options={[
            { value: "all", label: "全部级别" },
            ...["DEBUG", "INFO", "WARNING", "ERROR"].map((value) => ({
              value,
              label: value,
            })),
          ]}
        />
        <Select
          label="日志模块"
          value={vm.module}
          onValueChange={vm.setModule}
          options={[
            { value: "all", label: "全部模块" },
            ...vm.modules.map((value) => ({ value, label: value })),
          ]}
        />
      </div>
      <p className="text-xs text-muted-foreground">
        匹配 {vm.filtered.length} / {events.length} 条
      </p>
      <div className="surface-panel divide-y overflow-hidden">
        {vm.filtered.length === 0 && (
          <p className="p-10 text-center text-muted-foreground">暂无匹配日志</p>
        )}
        {vm.filtered.map((event) => (
          <article key={event.id} className="space-y-3 p-4 sm:px-6">
            <div className="flex flex-wrap items-center gap-3 text-xs">
              <time className="text-muted-foreground">{event.at}</time>
              <Badge variant="outline" tone={levelTones[event.level]}>
                {event.level}
              </Badge>
              <Badge variant="secondary">{event.kind}</Badge>
              <Badge variant="outline">
                {labels[event.status] ?? event.status}
              </Badge>
              {event.stage && (
                <code className="wrap-anywhere">{event.stage}</code>
              )}
              {event.durationMs !== null && (
                <span>{event.durationMs.toLocaleString()} ms</span>
              )}
            </div>
            {event.source ? (
              <p className="font-mono text-xs wrap-anywhere text-muted-foreground">
                {event.source.module} · {event.source.file}:{event.source.line}{" "}
                · {event.source.function}()
              </p>
            ) : (
              <p className="text-xs text-muted-foreground">
                旧记录未采集源码位置
              </p>
            )}
            <p className="text-sm wrap-anywhere">{event.message}</p>
            {event.taskId && (
              <button
                className="text-xs wrap-anywhere text-primary underline"
                onClick={() => vm.setQuery(event.taskId)}
              >
                任务 {event.taskId}
              </button>
            )}
            {(Object.keys(event.context).length > 0 || event.error) && (
              <details className="text-xs">
                <summary className="cursor-pointer text-primary">
                  业务字段与异常位置
                  {event.error ? ` · ${event.error.type}` : ""}
                </summary>
                <div className="mt-3 space-y-3">
                  {Object.keys(event.context).length > 0 && (
                    <JsonView value={event.context} />
                  )}
                  {event.error && (
                    <div className="space-y-2 rounded-lg border border-destructive/20 p-4">
                      <p className="font-semibold text-destructive">
                        {event.error.type}
                      </p>
                      {event.error.frames.map((frame, index) => (
                        <p
                          key={`${frame.file}:${frame.line}:${index}`}
                          className="font-mono wrap-anywhere"
                        >
                          {frame.module} · {frame.file}:{frame.line} ·{" "}
                          {frame.function}()
                        </p>
                      ))}
                    </div>
                  )}
                </div>
              </details>
            )}
          </article>
        ))}
      </div>
    </section>
  )
}
