import { useState } from "react"
import {
  Archive,
  ArrowDownWideNarrow,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  CircleDot,
  Fingerprint,
  GitBranch,
  Layers3,
  Library,
  Search,
  Sparkles,
  TriangleAlert,
  Users,
  X,
} from "lucide-react"

import { MemoryDetail } from "@/components/memory-detail"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import {
  categoryLabels,
  memoryDateFormat,
  type MemoryCategory,
  type MemoryRecord,
  type PreviewState,
} from "@/lib/memory"
import { cn } from "@/lib/utils"

interface MemoryLibraryProps {
  records: MemoryRecord[]
  status: PreviewState
  onRetry: () => void
}

const categoryIcons = {
  fact: CircleDot,
  scene: BookOpen,
  detail: Fingerprint,
  impression: Sparkles,
  persona: Users,
}
const pageSize = 6

export function MemoryLibrary({
  records,
  status,
  onRetry,
}: MemoryLibraryProps) {
  const [category, setCategory] = useState<MemoryCategory | "all">("all")
  const [state, setState] = useState("all")
  const [query, setQuery] = useState("")
  const [page, setPage] = useState(0)
  const [selectedId, setSelectedId] = useState<string>()
  const [detailOpen, setDetailOpen] = useState(false)
  const visibleRecords = records.filter(
    (record) =>
      (category === "all" || record.category === category) &&
      (state === "all" || record.state === state) &&
      [
        record.title,
        record.text,
        record.subject,
        record.session,
        ...record.tags,
      ]
        .join(" ")
        .toLowerCase()
        .includes(query.trim().toLowerCase())
  )
  const pageCount = Math.max(1, Math.ceil(visibleRecords.length / pageSize))
  const currentPage = Math.min(page, pageCount - 1)
  const pageRecords = visibleRecords.slice(
    currentPage * pageSize,
    (currentPage + 1) * pageSize
  )
  const selected =
    pageRecords.find((record) => record.id === selectedId) ?? pageRecords[0]
  const hasFilters = category !== "all" || state !== "all" || query !== ""
  const stats = [
    { label: "全部记忆", value: records.length, icon: Library },
    {
      label: "有效记忆",
      value: records.filter((item) => item.state === "active").length,
      icon: CircleDot,
    },
    {
      label: "历史版本",
      value: records.reduce((count, item) => count + item.versions.length, 0),
      icon: GitBranch,
    },
    {
      label: "已遗忘",
      value: records.filter((item) => item.state === "forgotten").length,
      icon: Archive,
    },
  ]
  // Related records may be outside the current filter or page.
  const navigateToMemory = (id: string) => {
    setCategory("all")
    setState("all")
    setQuery("")
    setPage(
      Math.max(
        0,
        Math.floor(records.findIndex((record) => record.id === id) / pageSize)
      )
    )
    setSelectedId(id)
  }

  return (
    <div className="flex min-h-[calc(100svh-3rem)]">
      <aside className="hidden w-56 shrink-0 flex-col border-r bg-card lg:flex">
        <div className="flex items-center gap-3 px-6 py-7">
          <div className="flex size-9 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <Layers3 className="size-5" />
          </div>
          <div>
            <p className="text-sm font-semibold tracking-tight">SeekMemory</p>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              记忆工作台
            </p>
          </div>
        </div>
        <nav aria-label="记忆分类" className="space-y-1 px-3">
          <p className="px-3 pt-4 pb-3 text-[11px] tracking-widest text-muted-foreground">
            记忆空间
          </p>
          <Button
            variant="ghost"
            aria-pressed={category === "all"}
            className={cn(
              "h-10 w-full justify-start gap-3 px-3",
              category === "all" &&
                "bg-primary/8 text-primary hover:bg-primary/12 hover:text-primary"
            )}
            onClick={() => {
              setCategory("all")
              setPage(0)
            }}
          >
            <Library className="size-4" />
            全部记忆
            <span className="ml-auto font-mono text-xs opacity-60">
              {records.length}
            </span>
          </Button>
          <p className="px-3 pt-7 pb-2 text-[11px] tracking-widest text-muted-foreground">
            按类型查看
          </p>
          {Object.entries(categoryLabels).map(([value, label]) => {
            const key = value as MemoryCategory
            const Icon = categoryIcons[key]
            return (
              <Button
                key={key}
                variant="ghost"
                aria-pressed={category === key}
                className={cn(
                  "h-10 w-full justify-start gap-3 px-3 font-normal text-muted-foreground",
                  category === key &&
                    "bg-primary/8 font-medium text-primary hover:text-primary"
                )}
                onClick={() => {
                  setCategory(key)
                  setPage(0)
                }}
              >
                <Icon className="size-4" />
                {label}
                <span className="ml-auto font-mono text-xs opacity-60">
                  {records.filter((item) => item.category === key).length}
                </span>
              </Button>
            )
          })}
        </nav>
        <div className="mx-5 mt-auto mb-6 border-t pt-5">
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="size-1.5 rounded-full bg-primary" />
            SeekMemory WebUI
          </p>
          <p className="mt-2 text-[11px] leading-5 text-muted-foreground/70">
            每一条记忆，都有迹可循。
          </p>
        </div>
      </aside>

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
            只读预览
          </Badge>
        </header>
        <div className="mx-auto max-w-[1600px] space-y-6 p-4 sm:p-8">
          <div>
            <p className="mb-2 text-[10px] font-semibold tracking-[0.24em] text-primary">
              MEMORY LIBRARY
            </p>
            <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
              记忆库
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              查看记住了什么，以及它如何变化。
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {stats.map(({ label, value, icon: Icon }) => (
              <div
                key={label}
                className="rounded-xl border bg-card px-4 py-4 sm:px-5"
              >
                <div className="mb-3 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                  <span>{label}</span>
                  <Icon className="size-3.5 opacity-70" />
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
                      setPage(0)
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
                        setPage(0)
                      }}
                    >
                      <X />
                    </Button>
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <select
                    aria-label="记忆类型"
                    value={category}
                    onChange={(event) => {
                      setCategory(event.target.value as MemoryCategory | "all")
                      setPage(0)
                    }}
                    className="filter-select max-w-32 lg:hidden"
                  >
                    <option value="all">全部类型</option>
                    {Object.entries(categoryLabels).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                  <select
                    aria-label="记忆状态"
                    value={state}
                    onChange={(event) => {
                      setState(event.target.value)
                      setPage(0)
                    }}
                    className="filter-select"
                  >
                    <option value="all">全部状态</option>
                    <option value="active">有效记忆</option>
                    <option value="forgotten">已遗忘</option>
                  </select>
                  {hasFilters && (
                    <Button
                      variant="ghost"
                      size="xs"
                      onClick={() => {
                        setCategory("all")
                        setState("all")
                        setQuery("")
                        setPage(0)
                      }}
                    >
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
                <div
                  role="status"
                  aria-label="正在加载记忆"
                  className="divide-y"
                >
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
                    这是模拟错误，可以重试返回正常预览。
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
                          onClick={() => {
                            setSelectedId(record.id)
                            if (
                              !window.matchMedia("(min-width: 1280px)").matches
                            )
                              setDetailOpen(true)
                          }}
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
                              {record.state === "forgotten" && (
                                <Badge
                                  variant="outline"
                                  className="mt-0.5 text-[10px] text-muted-foreground"
                                >
                                  已遗忘
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
                                {memoryDateFormat.format(
                                  new Date(record.updatedAt)
                                )}
                              </span>
                              <span className="ml-auto font-mono opacity-70">
                                v{record.versions[0]?.revision ?? 1}
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
                <p
                  aria-live="polite"
                  className="text-[11px] text-muted-foreground"
                >
                  {status === "loading"
                    ? "加载中…"
                    : status === "error"
                      ? "加载失败"
                      : "共 " + visibleRecords.length + " 条记忆"}
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
                    disabled={
                      currentPage + 1 >= pageCount || status !== "ready"
                    }
                    onClick={() => setPage(currentPage + 1)}
                  >
                    <ChevronRight />
                  </Button>
                </div>
              </footer>
            </section>
            <aside
              aria-label="选中的记忆"
              className="hidden w-[350px] shrink-0 overflow-hidden rounded-xl border bg-card xl:block 2xl:w-[380px]"
            >
              {status === "ready" && selected ? (
                <MemoryDetail
                  key={selected.id}
                  memory={selected}
                  records={records}
                  onNavigate={navigateToMemory}
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
            示例内容仅用于界面预览 · 时间显示为北京时间
          </p>
        </div>
      </main>
      <Sheet
        open={detailOpen && status === "ready" && !!selected}
        onOpenChange={setDetailOpen}
      >
        <SheetContent className="gap-0 overflow-y-auto data-[side=right]:w-full data-[side=right]:sm:max-w-lg">
          <SheetHeader className="sr-only">
            <SheetTitle>记忆详情</SheetTitle>
            <SheetDescription>查看内容、版本历史和关联记忆</SheetDescription>
          </SheetHeader>
          {selected && (
            <div className="pt-8">
              <MemoryDetail
                key={selected.id}
                memory={selected}
                records={records}
                onNavigate={navigateToMemory}
              />
            </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  )
}
