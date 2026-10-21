import { useState } from "react"
import {
  Archive,
  ChevronRight,
  CircleDot,
  GitBranch,
  Layers3,
  Library,
} from "lucide-react"
import { Badge, DetailDrawer, Skeleton } from "@/ui"
import type { MemorySource } from "../model"
import { useMemoryLibrary } from "../use-memory-library"
import { MemoryDetail } from "./memory-detail"
import { MemorySidebar } from "./memory-sidebar"
import { MemoryList } from "./memory-list"

interface MemoryWorkspaceProps {
  source: MemorySource
  onRetry: () => void
  onInspect?: ((id: string) => void) | undefined
}

export function MemoryWorkspace({
  source,
  onRetry,
  onInspect,
}: MemoryWorkspaceProps) {
  const vm = useMemoryLibrary(source)
  const { selected, orderedRecords, navigateToMemory } = vm
  const status = source.status
  const [detailOpen, setDetailOpen] = useState(false)
  const stats = [
    { label: "全部记忆", value: vm.stats.total, icon: Library },
    { label: "有效记忆", value: vm.stats.active, icon: CircleDot },
    { label: "历史版本", value: vm.stats.versionCount, icon: GitBranch },
    { label: "已遗忘", value: vm.stats.forgotten, icon: Archive },
  ]
  const onSelect = (id: string) => {
    vm.selectMemory(id)
    if (!window.matchMedia("(min-width: 1280px)").matches) setDetailOpen(true)
  }
  return (
    <div className="flex min-h-0 flex-1">
      <MemorySidebar vm={vm} />

      <main className="min-w-0 flex-1">
        <header className="flex h-16 items-center justify-between border-b bg-card/80 px-5 sm:px-8">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Layers3 className="mr-1 size-4 lg:hidden" />
            <span>工作空间</span>
            <ChevronRight className="size-3" />
            <span className="font-medium text-foreground">记忆库</span>
          </div>
          <Badge
            variant="outline"
            className="font-normal text-muted-foreground"
          >
            {onInspect ? "管理员工作空间" : "只读预览"}
          </Badge>
        </header>
        <div className="mx-auto max-w-[1600px] space-y-6 p-4 sm:p-8">
          <div className="workspace-intro">
            <Layers3
              aria-hidden="true"
              className="pointer-events-none absolute top-1/2 right-8 hidden size-24 -translate-y-1/2 text-primary/25 sm:block"
              strokeWidth={1}
            />
            <p className="section-kicker">MEMORY LIBRARY</p>
            <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
              记忆库
            </h1>
            <p className="mt-2 text-sm text-muted-foreground sm:pr-32">
              查看记住了什么，以及它如何变化。
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {stats.map(({ label, value, icon: Icon }, index) => (
              <div
                key={label}
                className={`surface-panel px-4 py-4 sm:px-5 ${index === 0 ? "metric-feature" : ""}`}
              >
                <div className="mb-3 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                  <span>{label}</span>
                  <span className="metric-icon">
                    <Icon className="size-4" />
                  </span>
                </div>
                {status === "loading" ? (
                  <Skeleton className="h-7 w-12" />
                ) : (
                  <p className="text-2xl font-semibold tabular-nums">
                    {status === "error" ? "—" : value}
                    <span className="ml-2 text-xs font-normal text-muted-foreground">
                      {label === "历史版本" ? "个" : "条"}
                    </span>
                  </p>
                )}
              </div>
            ))}
          </div>

          <div className="flex min-w-0 items-start gap-5">
            <MemoryList vm={vm} onSelect={onSelect} onRetry={onRetry} />
            <aside
              aria-label="选中的记忆"
              className="surface-panel hidden w-[350px] shrink-0 overflow-hidden xl:block 2xl:w-[380px]"
            >
              {status === "ready" && selected ? (
                <MemoryDetail
                  key={selected.id}
                  memory={selected}
                  records={orderedRecords}
                  onNavigate={navigateToMemory}
                  onInspect={onInspect}
                />
              ) : (
                <div className="px-6 py-24 text-center text-sm text-muted-foreground">
                  <Layers3 className="mx-auto mb-4 size-7 opacity-30" />
                  {status === "loading"
                    ? "正在加载记忆…"
                    : "选择一条记忆查看详情"}
                </div>
              )}
            </aside>
          </div>
          <p className="pb-2 text-center text-[11px] text-muted-foreground/70">
            时间显示为北京时间
          </p>
        </div>
      </main>
      <DetailDrawer
        open={detailOpen && status === "ready" && !!selected}
        onOpenChange={setDetailOpen}
        title="记忆详情"
        description="查看内容、版本历史和关联记忆"
      >
        {selected && (
          <MemoryDetail
            key={selected.id}
            memory={selected}
            records={orderedRecords}
            onNavigate={navigateToMemory}
            onInspect={
              onInspect
                ? (id) => {
                    setDetailOpen(false)
                    onInspect(id)
                  }
                : undefined
            }
          />
        )}
      </DetailDrawer>
    </div>
  )
}
