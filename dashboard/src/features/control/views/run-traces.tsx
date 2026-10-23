import { Badge, Button, Select } from "@/ui"
import type { ManagementClient } from "../model"
import { traceFlagLabels, type TraceEvent } from "../trace-model"
import { useRunTraces } from "../use-run-traces"

const eventLabels: Record<TraceEvent["event"], string> = {
  agent_begin: "Agent 开始",
  llm_request: "准备模型请求",
  llm_response: "模型已响应",
  agent_done: "Agent 结束",
  message_sent: "回复已发送",
  tool_call: "开始调用工具",
  tool_result: "工具已返回",
}
const runLabels = {
  running: "进行中",
  completed: "已完成",
  error: "发生错误",
  interrupted: "上次运行未结束",
}
const disclosureLabels = {
  full: "全文",
  paraphrase: "改述",
  hint: "提示",
  silence: "隐藏",
}

function ArtifactLinks({
  ids,
  onInspect,
}: {
  ids: readonly string[]
  onInspect: (id: string) => void
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {ids.map((id) => (
        <button
          key={id}
          className="max-w-full text-left font-mono text-xs break-all text-primary underline"
          onClick={() => onInspect(id)}
        >
          {id}
        </button>
      ))}
    </div>
  )
}

function TraceStep({
  event,
  onInspect,
}: {
  event: TraceEvent
  onInspect: (id: string) => void
}) {
  const recall = event.recall
  return (
    <li className="relative border-l-2 border-primary/20 pb-7 pl-5 last:pb-0">
      <span className="absolute top-1.5 -left-1.5 size-2.5 rounded-full bg-primary" />
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold">{eventLabels[event.event]}</h3>
        {event.status === "error" && <Badge tone="danger">失败</Badge>}
        {event.request_index > 0 && (
          <span className="text-xs text-muted-foreground">
            请求 {event.request_index}
          </span>
        )}
        <time className="text-xs text-muted-foreground">
          {new Date(event.at).toLocaleTimeString()}
        </time>
        {event.duration_ms !== null && (
          <span className="text-xs text-muted-foreground">
            {Math.round(event.duration_ms)} ms
          </span>
        )}
      </div>
      {event.tool && (
        <p className="mt-2 text-sm break-all">
          工具：{event.tool}
          {event.event === "tool_result" && " · 已返回，成功与否未判定"}
        </p>
      )}
      {recall && (
        <div className="mt-3 space-y-3 text-sm">
          <div className="flex flex-wrap gap-2">
            <Badge variant="secondary">候选 {recall.candidates}</Badge>
            <Badge variant="secondary">选中 {recall.picked_ids.length}</Badge>
            <Badge variant="secondary">常驻 {recall.pinned_ids.length}</Badge>
            <Badge tone="success">
              注入 {recall.artifact_ids.length} 条 · {recall.chars} 字
            </Badge>
            {recall.withheld_ids.length > 0 && (
              <Badge tone="warning">隐藏 {recall.withheld_ids.length} 条</Badge>
            )}
            {recall.fallback && <Badge tone="info">使用兜底</Badge>}
          </div>
          <ArtifactLinks ids={recall.artifact_ids} onInspect={onInspect} />
          <details className="rounded-lg border p-3">
            <summary className="cursor-pointer text-muted-foreground">
              筛选与披露详情
            </summary>
            <div className="mt-3 space-y-3">
              <p>
                {recall.gate.evaluated
                  ? `相关性检查：通过 ${recall.gate.passed} 条，过滤 ${recall.gate.rejected} 条，阈值 ${recall.gate.threshold.toFixed(2)}`
                  : "本次未执行相关性检查"}
              </p>
              {recall.dropped_ids.length > 0 && (
                <div>
                  <p className="mb-1">组装时未保留</p>
                  <ArtifactLinks
                    ids={recall.dropped_ids}
                    onInspect={onInspect}
                  />
                </div>
              )}
              {Object.entries(recall.disclosure).map(([id, level]) => (
                <div key={id} className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline">{disclosureLabels[level]}</Badge>
                  <ArtifactLinks ids={[id]} onInspect={onInspect} />
                </div>
              ))}
            </div>
          </details>
        </div>
      )}
    </li>
  )
}

export function RunTraces({
  client,
  onInspect,
}: {
  client: ManagementClient
  onInspect: (id: string) => void
}) {
  const vm = useRunTraces(client)
  return (
    <section className="mx-auto w-full max-w-7xl space-y-5 p-5 sm:p-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">运行轨迹 · Run Trace</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            查看一次回复经过的步骤，以及记忆为什么被使用或隐藏。
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            已注入表示进入模型上下文，不代表回答一定引用。已发送单独记录；不保存对话正文。
          </p>
        </div>
        <Button
          variant="outline"
          disabled={vm.loading}
          onClick={() => {
            void vm.refresh()
          }}
        >
          刷新轨迹
        </Button>
      </div>
      {vm.error && (
        <p role="alert" className="text-sm text-destructive">
          {vm.error}
        </p>
      )}
      {vm.snapshot?.persistence_error && (
        <p role="alert" className="text-sm text-destructive">
          轨迹保存失败，当前记录可能不完整。聊天功能不受影响。
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Select
          label="筛选运行轨迹"
          value={vm.filter}
          onValueChange={vm.setFilter}
          options={[
            { value: "all", label: "全部运行" },
            { value: "not_recalled", label: traceFlagLabels.not_recalled },
            {
              value: "recalled_but_withheld",
              label: traceFlagLabels.recalled_but_withheld,
            },
            {
              value: "recalled_and_injected",
              label: traceFlagLabels.recalled_and_injected,
            },
            { value: "fallback_used", label: traceFlagLabels.fallback_used },
          ]}
        />
        <p className="text-xs text-muted-foreground">
          {vm.total} 次运行
          {vm.snapshot &&
            ` · 保留 ${vm.snapshot.retention_days} 天，最多 ${vm.snapshot.capacity} 条事件`}
        </p>
      </div>
      {vm.loading && (
        <p role="status" className="py-6 text-sm text-muted-foreground">
          正在读取运行轨迹…
        </p>
      )}
      {!vm.loading && !vm.error && vm.total === 0 && (
        <p className="surface-panel p-10 text-center text-sm text-muted-foreground">
          暂无匹配轨迹。机器人处理新消息后，可刷新查看。
        </p>
      )}
      {vm.active && (
        <div className="grid gap-5 lg:grid-cols-[300px_minmax(0,1fr)]">
          <div className="surface-panel max-h-[70vh] space-y-1 overflow-y-auto p-2">
            {vm.runs.map((run) => (
              <button
                key={run.id}
                aria-pressed={run.id === vm.active?.id}
                onClick={() => vm.select(run.id)}
                className="w-full space-y-2 rounded-lg p-3 text-left hover:bg-muted aria-pressed:bg-primary/10"
              >
                <div className="flex items-center justify-between gap-2 text-sm">
                  <time>{new Date(run.started_at).toLocaleString()}</time>
                  <span>{runLabels[run.status]}</span>
                </div>
                <p className="font-mono text-xs text-muted-foreground">
                  {run.id.slice(0, 12)} · {run.event_count} 个步骤
                </p>
                <div className="flex flex-wrap gap-1">
                  {run.flags.map((flag) => (
                    <Badge key={flag} variant="secondary">
                      {traceFlagLabels[flag]}
                    </Badge>
                  ))}
                </div>
              </button>
            ))}
            {vm.total > vm.runs.length && (
              <Button variant="ghost" onClick={vm.showMore}>
                加载更多
              </Button>
            )}
          </div>
          <div className="surface-panel min-w-0 p-5 sm:p-6">
            <div className="mb-6 flex flex-wrap items-center gap-2">
              <h2 className="font-semibold">运行时间轴</h2>
              <Badge tone={vm.active.delivered ? "success" : "info"}>
                {vm.active.delivered ? "回复已发送" : "未记录发送成功"}
              </Badge>
            </div>
            {vm.active.partial && (
              <p className="mb-5 text-xs text-muted-foreground">
                这次运行的部分步骤未保留，时间轴可能不完整。
              </p>
            )}
            <ol className="ml-1">
              {vm.timeline.map((event) => (
                <TraceStep
                  key={`${event.run_id}-${event.sequence}`}
                  event={event}
                  onInspect={onInspect}
                />
              ))}
            </ol>
          </div>
        </div>
      )}
    </section>
  )
}
