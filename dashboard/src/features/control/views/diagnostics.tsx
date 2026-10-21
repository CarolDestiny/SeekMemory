import { Badge, Button, Input, JsonView, Textarea } from "@/ui"
import type { ManagementClient } from "../model"
import { useDiagnostics } from "../use-diagnostics"

const disclosureLabels: Record<string, string> = {
  full: "全文",
  paraphrase: "改述",
  hint: "提示",
  silence: "静默",
}

export function Diagnostics({ client }: { client: ManagementClient }) {
  const {
    query,
    setQuery,
    umo,
    setUmo,
    speaker,
    setSpeaker,
    result,
    disclosure,
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
              Mock 匹配与披露示意 · 不代表真实召回规则
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
          <section className="surface-panel space-y-3 p-5">
            <h2 className="text-lg font-semibold">逐条披露结果</h2>
            <p className="text-xs leading-6 text-muted-foreground">
              仅展示检索选中记忆的披露判定，不包含所有常驻或指定交付条目。全文许可仍受最终组装与字数预算限制；静默表示该条未进入披露后的选中集合。
            </p>
            {disclosure.length === 0 && (
              <p className="text-sm text-muted-foreground">
                本次没有逐条披露记录。
              </p>
            )}
            <ul className="divide-y">
              {disclosure.map(({ id, level }) => (
                <li
                  key={id}
                  className="flex items-start justify-between gap-3 py-3"
                >
                  <code className="min-w-0 text-xs wrap-anywhere">{id}</code>
                  <Badge variant="outline">
                    {disclosureLabels[level] ?? `未知级别：${level}`}
                  </Badge>
                </li>
              ))}
            </ul>
          </section>
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
