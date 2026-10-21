import { useEffect, useState } from "react"
import { FlaskConical, Moon, Sun } from "lucide-react"

import { MemoryWorkspace } from "@/features/memory/views/memory-workspace"
import { Button, Select, type SelectOption } from "@/ui"
import { mockMemories } from "@/dev/mock-data"
import {
  memoryCollectionSchema,
  type MemorySource,
} from "@/features/memory/model"

type PreviewScenario = "ready" | "loading" | "empty" | "error" | "long"
const scenarioOptions: readonly SelectOption<PreviewScenario>[] = [
  { value: "ready", label: "正常数据" },
  { value: "loading", label: "加载中" },
  { value: "empty", label: "空数据" },
  { value: "error", label: "加载失败" },
  { value: "long", label: "长内容" },
]
const parsedMock = memoryCollectionSchema.safeParse(mockMemories)

export default function MockApp() {
  const [scenario, setScenario] = useState<PreviewScenario>("ready")
  const [dark, setDark] = useState(false)

  useEffect(() => {
    document.documentElement.dataset["theme"] = dark ? "dark" : "light"
    return () => {
      delete document.documentElement.dataset["theme"]
    }
  }, [dark])

  let source: MemorySource
  if (scenario === "loading") source = { status: "loading" }
  else if (scenario === "error")
    source = {
      status: "error",
      message: "这是模拟错误，可以重试返回正常预览。",
    }
  else if (!parsedMock.success)
    source = { status: "error", message: "示例数据校验失败，请检查开发数据。" }
  else
    source = {
      status: "ready",
      records:
        scenario === "empty"
          ? []
          : scenario === "long"
            ? parsedMock.data.filter(
                (record) => record.id === "mock_memory_010"
              )
            : parsedMock.data,
    }

  return (
    <div className="flex min-h-svh flex-col">
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
          <Select
            id="preview-scenario"
            label="预览状态"
            className="filter-select h-7 min-w-24 bg-card text-xs"
            value={scenario}
            options={scenarioOptions}
            onValueChange={setScenario}
          />
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
      <MemoryWorkspace
        key={scenario}
        source={source}
        onRetry={() => setScenario("ready")}
      />
    </div>
  )
}
