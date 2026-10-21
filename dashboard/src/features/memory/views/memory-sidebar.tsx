import { Layers3, Library } from "lucide-react"
import { Button } from "@/ui"
import { cn } from "@/lib/utils"
import type { MemoryLibraryViewModel } from "../use-memory-library"
import { memoryCategories } from "../model"
import { categoryIcons, categoryLabels } from "./presentation"

export function MemorySidebar({ vm }: { vm: MemoryLibraryViewModel }) {
  const {
    filters: { category },
    setCategory,
    stats,
    categoryCounts,
  } = vm
  return (
    <aside className="hidden w-56 shrink-0 flex-col border-r bg-sidebar lg:flex">
      <div className="flex items-center gap-3 px-6 py-7">
        <div className="brand-mark">
          <Layers3 className="size-5" />
        </div>
        <div>
          <p className="text-sm font-semibold tracking-tight">SeekMemory</p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">记忆工作台</p>
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
              "bg-primary text-primary-foreground shadow-sm hover:bg-primary-hover hover:text-primary-foreground"
          )}
          onClick={() => {
            setCategory("all")
          }}
        >
          <Library className="size-4" />
          全部记忆
          <span className="ml-auto font-mono text-xs">{stats.total}</span>
        </Button>
        <p className="px-3 pt-7 pb-2 text-[11px] tracking-widest text-muted-foreground">
          按类型查看
        </p>
        {memoryCategories.map((key) => {
          const label = categoryLabels[key]
          const Icon = categoryIcons[key]
          return (
            <Button
              key={key}
              variant="ghost"
              aria-pressed={category === key}
              className={cn(
                "h-10 w-full justify-start gap-3 px-3 font-normal text-muted-foreground",
                category === key &&
                  "bg-primary font-medium text-primary-foreground shadow-sm hover:bg-primary-hover hover:text-primary-foreground"
              )}
              onClick={() => {
                setCategory(key)
              }}
            >
              <Icon className="size-4" />
              {label}
              <span className="ml-auto font-mono text-xs">
                {categoryCounts[key]}
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
  )
}
