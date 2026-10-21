import { Badge, Button, Input, JsonView, Textarea } from "@/ui"
import type { ManagementClient } from "../model"
import { useDiagnostics } from "../use-diagnostics"

export function Diagnostics({ client }: { client: ManagementClient }) {
  const {
    query,
    setQuery,
    umo,
    setUmo,
    speaker,
    setSpeaker,
    result,
    error,
    busy,
    diagnose,
  } = useDiagnostics(client)
  return (
    <section className="mx-auto w-full max-w-5xl space-y-6 p-5 sm:p-8">
      <div className="workspace-intro">
        <h1 className="text-2xl font-semibold">召回诊断</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          使用现有 scope 和召回规则，只读预演，不调用模型、不消耗指定交付。
        </p>
      </div>
      <div className="surface-panel space-y-4 p-6">
        <label htmlFor="diagnostic-umo" className="block space-y-2 text-sm">
          <span>会话 UMO</span>
          <Input
            id="diagnostic-umo"
            value={umo}
            maxLength={500}
            onChange={(event) => setUmo(event.target.value)}
            placeholder="napcat:FriendMessage:123456"
          />
        </label>
        <label htmlFor="diagnostic-speaker" className="block space-y-2 text-sm">
          <span>说话人 ID</span>
          <Input
            id="diagnostic-speaker"
            value={speaker}
            maxLength={200}
            onChange={(event) => setSpeaker(event.target.value)}
            placeholder="群聊中请填写实际说话人 ID"
          />
        </label>
        <label htmlFor="diagnostic-query" className="block space-y-2 text-sm">
          <span>查询消息</span>
          <Textarea
            id="diagnostic-query"
            value={query}
            maxLength={4000}
            rows={4}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <Button
          disabled={busy || !query.trim() || !umo.trim() || !speaker.trim()}
          onClick={() => {
            void diagnose()
          }}
        >
          {busy ? "诊断中…" : "运行只读诊断"}
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      )}
      {result && (
        <div className="space-y-5">
          {result.info["mock"] === true && (
            <Badge variant="outline">
              Mock 文本匹配示意 · 不代表真实召回质量
            </Badge>
          )}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {(
              [
                ["召回模式", result.info["mode"] ?? "—"],
                ["检索选中", result.info["picked"] ?? "—"],
                ["常驻条目", result.info["pinned"] ?? "—"],
                ["注入字符", result.info["chars"] ?? result.block.length],
              ] as const
            ).map(([label, value]) => (
              <div key={label} className="surface-panel p-4">
                <p className="text-xs text-muted-foreground">{label}</p>
                <p className="mt-2 text-xl font-semibold">
                  {typeof value === "string" || typeof value === "number"
                    ? value
                    : "—"}
                </p>
              </div>
            ))}
          </div>
          <h2 className="text-lg font-semibold">预计注入内容</h2>
          <p className="rounded-xl border bg-primary/5 p-6 text-sm leading-7 whitespace-pre-wrap">
            {result.block || "本次不会注入记忆"}
          </p>
          <h2 className="text-lg font-semibold">决策指标</h2>
          <JsonView value={result.info} />
          <div className="grid gap-4 md:grid-cols-2">
            <section className="space-y-2">
              <h3>scope 可见候选 · {result.visible.length}</h3>
              <JsonView value={result.visible} />
            </section>
            <section className="space-y-2">
              <h3>scope 排除 · {result.excluded.length}</h3>
              <JsonView value={result.excluded} />
            </section>
          </div>
          <p className="text-xs text-muted-foreground">
            scope
            候选仅表示通过范围过滤，不代表最终被选中或注入；已遗忘与已合并记录不进入此候选池。
          </p>
        </div>
      )}
    </section>
  )
}
