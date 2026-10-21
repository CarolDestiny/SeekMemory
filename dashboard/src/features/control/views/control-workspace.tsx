import { useState } from "react"
import {
  Activity,
  BookOpen,
  FlaskConical,
  RefreshCw,
  ScrollText,
} from "lucide-react"
import { Badge, Button, DetailDrawer, Select } from "@/ui"
import { MemoryWorkspace } from "@/features/memory/views/memory-workspace"
import type { ManagementClient } from "../model"
import { useControl } from "../use-control"
import { ArtifactEditor } from "./artifact-editor"
import { Diagnostics } from "./diagnostics"
import { LogView } from "./log-view"
import { RuntimePanel } from "./runtime-panel"

const sections = [
  { id: "memory", label: "记忆库", icon: BookOpen },
  { id: "runtime", label: "运行与任务", icon: Activity },
  { id: "diagnose", label: "召回诊断", icon: FlaskConical },
  { id: "logs", label: "生命周期日志", icon: ScrollText },
] as const

export function ControlWorkspace({ client }: { client: ManagementClient }) {
  const vm = useControl(client)
  const [section, setSection] =
    useState<(typeof sections)[number]["id"]>("memory")
  const [scope, setScope] = useState("all")
  const [session, setSession] = useState("all")
  const [editorId, setEditorId] = useState<string | null>(null)
  const [action, setAction] = useState<"extract" | "weekly" | "cancel" | null>(
    null
  )
  const [confirmed, setConfirmed] = useState(false)
  const [cancelId, setCancelId] = useState("")
  const source =
    vm.source.status === "ready"
      ? {
          ...vm.source,
          records: vm.source.records.filter(
            (record) =>
              (scope === "all" || record.scope === scope) &&
              (session === "all" || record.session === session)
          ),
        }
      : vm.source
  const sessions =
    vm.source.status === "ready"
      ? Array.from(
          new Set(vm.source.records.map((record) => record.session))
        ).sort()
      : []
  const task = vm.status?.activeTask
  return (
    <div className="flex min-h-svh flex-col bg-background">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b bg-card px-4 py-3 sm:px-6">
        <nav aria-label="工作台导航" className="flex flex-wrap gap-1">
          {sections.map(({ id, label, icon: Icon }) => (
            <Button
              key={id}
              variant={section === id ? "secondary" : "ghost"}
              aria-pressed={section === id}
              onClick={() => setSection(id)}
            >
              <Icon className="size-4" />
              {label}
            </Button>
          ))}
        </nav>
        <div className="flex items-center gap-3">
          <Badge variant="outline">
            {vm.status?.ready ? "引擎就绪" : "等待连接"}
          </Badge>
          <Button
            variant="ghost"
            aria-label="刷新工作台"
            onClick={() => {
              void vm.refresh()
            }}
          >
            <RefreshCw className="size-4" />
            刷新
          </Button>
        </div>
      </header>
      {vm.error && (
        <p
          role="alert"
          className="border-b border-destructive/20 bg-destructive/5 px-6 py-3 text-sm text-destructive"
        >
          {vm.error}
        </p>
      )}
      {section === "memory" && (
        <>
          <div className="flex flex-wrap items-center gap-3 border-b px-5 py-3 text-xs">
            <span className="text-muted-foreground">管理范围</span>
            <Select
              label="筛选 scope"
              value={scope}
              onValueChange={setScope}
              options={[
                { value: "all", label: "全部 scope" },
                { value: "private", label: "私有" },
                { value: "shared", label: "共享" },
                { value: "shadow", label: "影子" },
              ]}
            />
            <Select
              label="筛选来源会话"
              className="max-w-80"
              value={session}
              onValueChange={setSession}
              options={[
                { value: "all", label: "全部来源会话" },
                ...sessions.map((value) => ({ value, label: value })),
              ]}
            />
            <span className="text-muted-foreground">
              管理员可查看所有家族；筛选不改变机器人访问权限。
            </span>
          </div>
          <MemoryWorkspace
            source={source}
            onRetry={() => {
              void vm.refresh()
            }}
            onInspect={setEditorId}
          />
        </>
      )}
      {section === "runtime" && (
        <RuntimePanel
          status={vm.status}
          busy={vm.busy}
          onAction={(next) => {
            setAction(next)
            setCancelId(task?.id ?? "")
            setConfirmed(false)
          }}
        />
      )}
      {section === "diagnose" && <Diagnostics client={client} />}
      {section === "logs" && <LogView events={vm.events} />}
      <ArtifactEditor
        key={editorId}
        client={client}
        id={editorId}
        close={() => setEditorId(null)}
        onSaved={vm.refresh}
      />
      <DetailDrawer
        open={action !== null}
        onOpenChange={(open) => {
          if (!open) setAction(null)
        }}
        title="确认维护操作"
        description="确认任务影响后执行"
      >
        <div className="space-y-5 p-6">
          <h2 className="text-xl font-semibold">
            确认
            {action === "extract"
              ? "立即抽取"
              : action === "weekly"
                ? "每周整理"
                : "取消任务"}
          </h2>
          <p className="text-sm leading-7 text-muted-foreground">
            {action === "cancel"
              ? "取消会保留尚未处理的抽取消息；已经完成的写入不会撤销。同步整理开始后可能已完成，取消并不保证回滚。"
              : "此操作会修改真实记忆数据。旧版本和已写入的账本会保留；抽取还可能产生模型调用费用。"}
          </p>
          <label className="flex gap-2 text-sm">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            我已确认本次操作及其影响
          </label>
          <Button
            disabled={!confirmed || vm.busy}
            onClick={() => {
              const selected = action
              if (!selected) return
              setAction(null)
              void vm.run(() =>
                selected === "cancel"
                  ? client.cancel(cancelId)
                  : client.task(selected)
              )
            }}
          >
            确认执行
          </Button>
        </div>
      </DetailDrawer>
    </div>
  )
}
