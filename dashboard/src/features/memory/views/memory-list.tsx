import {
  ArrowDownWideNarrow,
  ChevronLeft,
  ChevronRight,
  Search,
  TriangleAlert,
  X,
} from "lucide-react"
import { Badge, Button, Input, Select, Skeleton } from "@/ui"
import { cn } from "@/lib/utils"
import type { MemoryLibraryViewModel } from "../use-memory-library"
import {
  categoryFilterOptions,
  categoryIcons,
  categoryLabels,
  memoryDateFormat,
  stateFilterOptions,
} from "./presentation"

interface MemoryListProps {
  vm: MemoryLibraryViewModel
  onSelect: (id: string) => void
  onRetry: () => void
}

export function MemoryList({ vm, onSelect, onRetry }: MemoryListProps) {
  const {
    filters: { category, state, query },
    source,
    setCategory,
    setState,
    setQuery,
    setPage,
    resetFilters,
    hasFilters,
    pageRecords,
    selected,
    currentPage,
    pageCount,
    resultCount,
  } = vm
  const status = source.status
  return (
    <section
      aria-label="记忆列表"
      className="min-w-0 flex-1 overflow-hidden rounded-xl border bg-card"
    >
      <div className="space-y-3 border-b p-4">
        <div className="relative">
          <Search className="pointer-events-none absolute top-2.5 left-3 size-4 text-muted-foreground" />
          <Input
            aria-label="搜索记忆"
            placeholder="搜索内容、标签或相关对象…"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
            }}
            className="h-9 bg-background pr-9 pl-9"
          />
          {query && (
            <Button
              aria-label="清空搜索"
              variant="ghost"
              size="icon-xs"
              className="absolute top-1.5 right-1.5"
              onClick={() => {
                setQuery("")
              }}
            >
              <X />
            </Button>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            label="记忆类型"
            value={category}
            options={categoryFilterOptions}
            onValueChange={setCategory}
            className="max-w-32 lg:hidden"
          />
          <Select
            label="记忆状态"
            value={state}
            options={stateFilterOptions}
            onValueChange={setState}
          />
          {hasFilters && (
            <Button variant="ghost" size="xs" onClick={resetFilters}>
              重置筛选
            </Button>
          )}
          <span className="ml-auto flex items-center gap-1 text-[11px] text-muted-foreground">
            <ArrowDownWideNarrow className="size-3" />
            最近更新
          </span>
        </div>
      </div>

      {status === "loading" ? (
        <div role="status" aria-label="正在加载记忆" className="divide-y">
          {Array.from({ length: 4 }, (_, index) => (
            <div key={index} className="space-y-3 p-5">
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-1/3" />
            </div>
          ))}
        </div>
      ) : status === "error" ? (
        <div role="alert" className="px-6 py-20 text-center">
          <TriangleAlert className="mx-auto mb-4 size-8 text-amber-500" />
          <h2 className="font-medium">暂时无法加载记忆</h2>
          <p className="mt-2 mb-5 text-sm text-muted-foreground">
            {source.status === "error" ? source.message : ""}
          </p>
          <Button variant="outline" onClick={onRetry}>
            重试加载
          </Button>
        </div>
      ) : pageRecords.length === 0 ? (
        <div role="status" className="px-6 py-20 text-center">
          <Search className="mx-auto mb-4 size-8 text-muted-foreground/40" />
          <h2 className="font-medium">
            {hasFilters ? "没有找到匹配的记忆" : "这里还没有记忆"}
          </h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            {hasFilters
              ? "试试其他关键词，或调整筛选条件。"
              : "新的记忆形成后，会出现在这个位置。"}
          </p>
        </div>
      ) : (
        <ul className="divide-y">
          {pageRecords.map((record) => {
            const Icon = categoryIcons[record.category]
            return (
              <li key={record.id}>
                <button
                  aria-pressed={selected?.id === record.id}
                  onClick={() => onSelect(record.id)}
                  className={cn(
                    "group relative flex w-full gap-3 p-5 text-left transition-colors hover:bg-muted/40 focus-visible:z-10 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none focus-visible:ring-inset",
                    selected?.id === record.id &&
                      "bg-primary/5 before:absolute before:inset-y-4 before:left-0 before:w-0.5 before:rounded-r before:bg-primary"
                  )}
                >
                  <div
                    className={cn(
                      "mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border bg-background text-muted-foreground",
                      selected?.id === record.id &&
                        "border-primary/15 text-primary"
                    )}
                  >
                    <Icon className="size-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start gap-2">
                      <h2 className="line-clamp-2 flex-1 text-sm leading-6 font-medium">
                        {record.title}
                      </h2>
                      {record.state !== "active" && (
                        <Badge
                          variant="outline"
                          className="mt-0.5 text-[10px] text-muted-foreground"
                        >
                          {record.state === "forgotten" ? "已遗忘" : "已合并"}
                        </Badge>
                      )}
                    </div>
                    <p className="mt-1 line-clamp-2 text-xs leading-6 text-muted-foreground">
                      {record.text}
                    </p>
                    <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1.5 text-[10px] text-muted-foreground">
                      <Badge
                        variant="secondary"
                        className="h-4 rounded px-1.5 text-[10px] font-normal"
                      >
                        {categoryLabels[record.category]}
                      </Badge>
                      <span>{record.subject}</span>
                      <span className="opacity-40">·</span>
                      <span>
                        {memoryDateFormat.format(new Date(record.updatedAt))}
                      </span>
                      <span className="ml-auto font-mono opacity-70">
                        v{record.versions[0].revision}
                      </span>
                    </div>
                  </div>
                </button>
              </li>
            )
          })}
        </ul>
      )}
      <footer className="flex items-center justify-between gap-3 border-t px-4 py-3">
        <p aria-live="polite" className="text-[11px] text-muted-foreground">
          {status === "loading"
            ? "加载中…"
            : status === "error"
              ? "加载失败"
              : "共 " + resultCount + " 条记忆"}
        </p>
        <div className="flex items-center gap-2">
          <Button
            aria-label="上一页"
            variant="ghost"
            size="icon-xs"
            disabled={currentPage === 0 || status !== "ready"}
            onClick={() => setPage(currentPage - 1)}
          >
            <ChevronLeft />
          </Button>
          <span className="text-[11px] text-muted-foreground tabular-nums">
            {currentPage + 1} / {pageCount}
          </span>
          <Button
            aria-label="下一页"
            variant="ghost"
            size="icon-xs"
            disabled={currentPage + 1 >= pageCount || status !== "ready"}
            onClick={() => setPage(currentPage + 1)}
          >
            <ChevronRight />
          </Button>
        </div>
      </footer>
    </section>
  )
}
