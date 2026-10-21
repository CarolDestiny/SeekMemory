import { Badge, Button, JsonView } from "@/ui"
import type { RuntimeStatus } from "../model"

export function RuntimePanel({
  status,
  busy,
  onAction,
}: {
  status: RuntimeStatus | null
  busy: boolean
  onAction: (action: "extract" | "weekly" | "cancel") => void
}) {
  const task = status?.activeTask
  return (
    <section className="mx-auto w-full max-w-6xl space-y-6 p-5 sm:p-8">
      <div>
        <h1 className="text-2xl font-semibold">运行检测与任务</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          检查引擎、账本、模型配置与持久化状态，查看待处理会话。
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        {[
          ["定时任务", String(status?.schedulerCount ?? "—")],
          [
            "待抽取消息",
            String(
              status?.pending.reduce((total, item) => total + item.count, 0) ??
                "—"
            ),
          ],
          ["当前操作", task?.kind ?? "空闲"],
        ].map(([label, value]) => (
          <div key={label} className="rounded-xl border bg-card p-6">
            <p className="text-xs text-muted-foreground">{label}</p>
            <p className="mt-3 text-2xl font-semibold">{value}</p>
          </div>
        ))}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {status?.checks.map((check) => (
          <div
            key={check.name}
            className="flex items-center justify-between rounded-xl border bg-card p-5"
          >
            <div>
              <p className="font-medium">
                {{
                  engine: "记忆引擎",
                  journal: "生命周期日志",
                  ledger: "账本哈希链",
                  provider: "模型配置",
                }[check.name] ?? check.name}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {check.detail}
              </p>
            </div>
            <Badge
              variant="outline"
              className={check.ok ? "text-primary" : "text-destructive"}
            >
              {check.ok ? "正常" : "需检查"}
            </Badge>
          </div>
        ))}
      </div>
      <div className="space-y-4 rounded-xl border bg-card p-6">
        <h2 className="text-lg font-semibold">维护操作</h2>
        <p className="text-sm leading-6 text-muted-foreground">
          立即抽取会调用配置的模型并写入记忆；每周整理会遗忘、合并并提炼人格。操作共用后台任务锁，运行期间暂停人工编辑。
        </p>
        <div className="flex flex-wrap gap-3">
          <Button
            disabled={busy || !!task || !status?.ready}
            onClick={() => {
              onAction("extract")
            }}
          >
            立即抽取
          </Button>
          <Button
            variant="outline"
            disabled={busy || !!task || !status?.ready}
            onClick={() => {
              onAction("weekly")
            }}
          >
            运行每周整理
          </Button>
          {task && (
            <Button
              variant="destructive"
              onClick={() => {
                onAction("cancel")
              }}
            >
              取消当前任务
            </Button>
          )}
        </div>
        {task && (
          <p className="font-mono text-xs wrap-anywhere">
            任务 ID：{task.id} · 每 2 秒刷新
          </p>
        )}
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="space-y-3">
          <h2 className="font-semibold">待处理会话</h2>
          <JsonView value={status?.pending ?? []} />
        </section>
        <section className="space-y-3">
          <h2 className="font-semibold">当前配置</h2>
          <p className="text-xs text-muted-foreground">
            配置编辑使用 AstrBot
            插件配置页。此处展示实际配置，不代表所有历史配置项均已接入执行路径。
          </p>
          <JsonView value={status?.config ?? {}} />
        </section>
      </div>
    </section>
  )
}
