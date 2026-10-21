import { lazy, Suspense } from "react"
import { ControlWorkspace } from "@/features/control/views/control-workspace"
import { astrbotClient } from "@/infrastructure/astrbot-client"

// Vite 会从生产构建中移除此分支及其示例数据导入。
const MockApp =
  import.meta.env.DEV && import.meta.env.MODE === "mock"
    ? lazy(() => import("@/dev/MockApp"))
    : null

export default function App() {
  if (MockApp) {
    return (
      <Suspense
        fallback={
          <p role="status" className="p-8 text-sm text-muted-foreground">
            正在加载预览…
          </p>
        }
      >
        <MockApp />
      </Suspense>
    )
  }

  return <ControlWorkspace client={astrbotClient} />
}
