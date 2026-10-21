import {
  ArrowUpRight,
  Clock3,
  GitBranch,
  Link2,
  LockKeyhole,
  Users,
} from "lucide-react"
import { Badge, Button, Tabs } from "@/ui"
import type { MemoryRecord } from "../model"
import { useMemoryDetail } from "../use-memory-detail"
import { categoryLabels, memoryDateFormat } from "./presentation"

interface MemoryDetailProps {
  memory: MemoryRecord
  records: readonly MemoryRecord[]
  onNavigate: (id: string) => void
}

export function MemoryDetail({
  memory,
  records,
  onNavigate,
}: MemoryDetailProps) {
  const { currentVersion, version, previous, related, setRevision } =
    useMemoryDetail(memory, records)
  return (
    <div className="min-w-0">
      <div className="space-y-4 p-6 pb-5">
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs font-medium tracking-wider text-muted-foreground">
            记忆详情
          </span>
          <Badge variant="outline" className="font-mono">
            v{currentVersion.revision}
          </Badge>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant="secondary" className="category-badge">
            {categoryLabels[memory.category]}
          </Badge>
          <Badge
            variant="outline"
            className={
              memory.state === "active"
                ? "text-primary"
                : "text-muted-foreground"
            }
          >
            <span
              className={
                memory.state === "active"
                  ? "size-1.5 rounded-full bg-primary"
                  : "size-1.5 rounded-full bg-muted-foreground"
              }
            />
            {memory.state === "active" ? "有效" : "已遗忘"}
          </Badge>
        </div>
        <h2 className="text-lg leading-relaxed font-semibold wrap-anywhere">
          {memory.title}
        </h2>
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Clock3 className="size-3.5" />
          更新于 {memoryDateFormat.format(new Date(memory.updatedAt))}
        </p>
      </div>
      <Tabs
        defaultValue="content"
        items={[
          {
            value: "content",
            label: "内容",
            content: (
              <div className="space-y-6 p-6">
                <div className="rounded-xl border border-primary/10 bg-primary/5 p-4">
                  <p className="text-sm leading-7 wrap-anywhere whitespace-pre-wrap">
                    {memory.text}
                  </p>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {memory.tags.map((tag) => (
                    <Badge
                      key={tag}
                      variant="secondary"
                      className="font-normal text-muted-foreground"
                    >
                      #{tag}
                    </Badge>
                  ))}
                </div>
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">可信度</span>
                    <span className="font-mono font-medium">
                      {Math.round(memory.confidence * 100)}%
                    </span>
                  </div>
                  <div
                    role="meter"
                    aria-label="可信度"
                    aria-valuenow={Math.round(memory.confidence * 100)}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    className="h-1.5 overflow-hidden rounded-full bg-muted"
                  >
                    <div
                      className="h-full rounded-full bg-primary"
                      style={{ width: memory.confidence * 100 + "%" }}
                    />
                  </div>
                </div>
                <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-5 gap-y-4 border-t pt-5 text-xs">
                  <dt className="text-muted-foreground">相关对象</dt>
                  <dd className="text-right">{memory.subject}</dd>
                  <dt className="text-muted-foreground">可见范围</dt>
                  <dd className="flex items-center justify-end gap-1.5">
                    {memory.scope === "private" ? (
                      <LockKeyhole className="size-3.5" />
                    ) : (
                      <Users className="size-3.5" />
                    )}
                    {memory.scope === "private" ? "私有" : "共享"}
                  </dd>
                  <dt className="text-muted-foreground">召回次数</dt>
                  <dd className="text-right tabular-nums">{memory.hits} 次</dd>
                  <dt className="text-muted-foreground">来源会话</dt>
                  <dd className="text-right font-mono text-[11px] wrap-anywhere">
                    {memory.session}
                  </dd>
                  <dt className="text-muted-foreground">记忆 ID</dt>
                  <dd className="text-right font-mono text-[11px] wrap-anywhere">
                    {memory.id}
                  </dd>
                </dl>
              </div>
            ),
          },
          {
            value: "history",
            label: (
              <>
                版本历史{" "}
                <span className="text-xs opacity-60">
                  {memory.versions.length}
                </span>
              </>
            ),
            content: (
              <div className="space-y-5 p-6">
                <p className="text-xs leading-5 text-muted-foreground">
                  选择一个版本，查看它与前一版本的完整内容。
                </p>
                <div className="space-y-2">
                  {memory.versions.map((item, index) => (
                    <Button
                      key={item.revision}
                      variant={
                        version.revision === item.revision
                          ? "secondary"
                          : "ghost"
                      }
                      className="h-auto w-full justify-start gap-3 px-3 py-3"
                      aria-pressed={version.revision === item.revision}
                      onClick={() => setRevision(item.revision)}
                    >
                      <GitBranch className="size-4 text-primary" />
                      <span className="font-mono">v{item.revision}</span>
                      <span className="text-xs font-normal text-muted-foreground">
                        {memoryDateFormat.format(new Date(item.at))}
                      </span>
                      {index === 0 && (
                        <span className="ml-auto text-[11px] text-primary">
                          当前
                        </span>
                      )}
                    </Button>
                  ))}
                </div>
                {version && (
                  <div className="space-y-3">
                    {previous && (
                      <section className="rounded-lg border bg-muted/40 p-4">
                        <h3 className="mb-2 text-xs font-medium text-muted-foreground">
                          前一版本 · v{previous.revision}
                        </h3>
                        <p className="text-sm leading-6 wrap-anywhere whitespace-pre-wrap">
                          {previous.text}
                        </p>
                      </section>
                    )}
                    <section className="rounded-lg border border-primary/20 bg-primary/5 p-4">
                      <h3 className="mb-2 text-xs font-medium text-primary">
                        选中版本 · v{version.revision}
                        {!previous && " · 初始记录"}
                      </h3>
                      <p className="text-sm leading-6 wrap-anywhere whitespace-pre-wrap">
                        {version.text}
                      </p>
                    </section>
                  </div>
                )}
              </div>
            ),
          },
          {
            value: "relations",
            label: (
              <>
                关联{" "}
                <span className="text-xs opacity-60">{related.length}</span>
              </>
            ),
            content: (
              <div className="space-y-3 p-6">
                <p className="mb-4 text-xs leading-5 text-muted-foreground">
                  沿着关联查看其他记忆，了解更多上下文。
                </p>
                {related.length === 0 && (
                  <div className="py-10 text-center text-sm text-muted-foreground">
                    <Link2 className="mx-auto mb-3 size-6 opacity-40" />
                    这条记忆暂无关联
                  </div>
                )}
                {related.map((relatedMemory) => (
                  <button
                    key={relatedMemory.id}
                    onClick={() => onNavigate(relatedMemory.id)}
                    className="group flex w-full items-start gap-3 rounded-xl border p-4 text-left transition-colors hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                  >
                    <Link2 className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm leading-6">{relatedMemory.title}</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {categoryLabels[relatedMemory.category]} ·{" "}
                        {relatedMemory.subject}
                      </p>
                    </div>
                    <ArrowUpRight className="mt-1 size-3.5 shrink-0 text-muted-foreground group-hover:text-primary" />
                  </button>
                ))}
              </div>
            ),
          },
        ]}
      />
    </div>
  )
}
