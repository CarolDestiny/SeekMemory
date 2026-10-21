import { Button } from "@/components/ui/button"

export default function App() {
  return (
    <main className="mx-auto flex min-h-svh max-w-4xl flex-col justify-center gap-6 p-8">
      <div className="space-y-3">
        <p className="text-sm font-medium text-muted-foreground">SeekMemory</p>
        <h1 className="text-3xl font-semibold tracking-tight">记忆管理</h1>
        <p className="max-w-xl leading-relaxed text-muted-foreground">
          前端开发环境已就绪。这里将用于浏览记忆、查看版本变化和调试召回结果。
        </p>
      </div>
      <div>
        <Button disabled variant="secondary">
          记忆接口待接入
        </Button>
      </div>
    </main>
  )
}
