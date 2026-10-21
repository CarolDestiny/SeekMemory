import { useEffect, useState } from "react"
import { FlaskConical, Moon, Sun } from "lucide-react"

import { MemoryLibrary } from "@/components/memory-library"
import { Button } from "@/components/ui/button"
import { mockMemories } from "@/dev/mock-data"
import type { PreviewState } from "@/lib/memory"

export default function MockApp() {
  const [scenario, setScenario] = useState<PreviewState | "long">("ready")
  const [dark, setDark] = useState(false)

  useEffect(() => {
    document.documentElement.dataset["theme"] = dark ? "dark" : "light"
    return () => {
      delete document.documentElement.dataset["theme"]
    }
  }, [dark])

  const records =
    scenario === "empty" || scenario === "error" || scenario === "loading"
      ? []
      : scenario === "long"
        ? mockMemories.filter((record) => record.id === "mock_memory_010")
        : mockMemories

  return (
    <>
      <div className="flex min-h-12 flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-primary/15 bg-primary/5 px-4 py-2 sm:px-6">
        <div className="flex items-center gap-2.5 text-xs">
          <FlaskConical className="size-3.5 text-primary" />
          <span className="font-semibold text-primary">MOCK · 独立预览</span>
          <span className="hidden text-muted-foreground sm:inline">
            虚构示例数据 · 未连接 AstrBot
          </span>
        </div>
        <div className="flex items-center gap-2">
          <label
            htmlFor="preview-scenario"
            className="text-xs text-muted-foreground"
          >
            预览状态
          </label>
          <select
            id="preview-scenario"
            className="filter-select h-7 min-w-24 bg-card text-xs"
            value={scenario}
            onChange={(event) => {
              const value = event.target.value
              if (
                value === "ready" ||
                value === "loading" ||
                value === "empty" ||
                value === "error" ||
                value === "long"
              )
                setScenario(value)
            }}
          >
            <option value="ready">正常数据</option>
            <option value="loading">加载中</option>
            <option value="empty">空数据</option>
            <option value="error">加载失败</option>
            <option value="long">长内容</option>
          </select>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={dark ? "切换到浅色" : "切换到深色"}
            onClick={() => setDark(!dark)}
          >
            {dark ? <Sun /> : <Moon />}
          </Button>
        </div>
      </div>
      <MemoryLibrary
        key={scenario}
        records={records}
        status={scenario === "long" ? "ready" : scenario}
        onRetry={() => setScenario("ready")}
      />
    </>
  )
}
