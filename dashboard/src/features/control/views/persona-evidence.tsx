import { useState } from "react"
import { Button } from "@/ui"
import type { ManagementClient, RuntimeStatus } from "../model"
import {
  usePersonaEvidence,
  useImpressionEvidence,
  type PersonaEvidenceView,
} from "../use-persona-evidence"

type Persona = NonNullable<RuntimeStatus["persona"]>

const roleLabels: Record<string, string> = {
  user: "用户",
  assistant: "助手",
}

export function PersonaEvidence({
  client,
  persona,
}: {
  client: ManagementClient
  persona: Persona
}) {
  const revisions = [...persona.revisions].sort(
    (left, right) => right.revision - left.revision
  )
  const [requested, setSelected] = useState(persona.revision)
  const selected = revisions.some((item) => item.revision === requested)
    ? requested
    : (revisions[0]?.revision ?? persona.revision)

  const { state, reload } = usePersonaEvidence(client, persona.id, selected)

  return (
    <section className="space-y-4 rounded-lg border bg-muted/20 p-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h3 className="font-semibold">版本证据</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            查看人格从哪些经历中形成。
          </p>
        </div>
        <label className="flex items-center gap-2 text-xs">
          <span className="text-muted-foreground">选择人格版本</span>
          <select
            aria-label="选择人格版本"
            className="rounded-md border bg-background px-2 py-1"
            value={selected}
            onChange={(event) => {
              setSelected(Number(event.target.value))
            }}
          >
            {revisions.map((item) => (
              <option key={item.revision} value={item.revision}>
                第 {item.revision} 版 · {item.at || "时间未记录"}
              </option>
            ))}
          </select>
        </label>
      </div>

      {state.status === "loading" && (
        <p role="status" className="text-sm text-muted-foreground">
          正在读取该版本的证据…
        </p>
      )}
      {state.status === "error" && (
        <div role="alert" className="space-y-2 text-sm text-destructive">
          <p>证据读取失败：{state.message}</p>
          <Button variant="outline" onClick={reload}>
            重试
          </Button>
        </div>
      )}
      {state.status === "idle" && (
        <p className="text-sm text-muted-foreground">尚未选择人格版本。</p>
      )}
      {state.status === "ready" && (
        <EvidenceBody
          key={`${persona.id}:${selected}`}
          client={client}
          view={state.view}
        />
      )}
    </section>
  )
}

function EvidenceBody({
  view,
  client,
}: {
  view: PersonaEvidenceView
  client: ManagementClient
}) {
  const version = view.version
  if (!version) {
    return (
      <p className="text-sm text-muted-foreground">
        没有找到所选版本的证据记录。
      </p>
    )
  }
  const empty = view.derivedFrom.length === 0 && version.sourceIds.length === 0
  return (
    <div className="space-y-5">
      <div>
        <h4 className="text-sm font-medium">支持的自我印象</h4>
        {view.derivedFrom.length === 0 ? (
          <p className="mt-1 text-xs text-muted-foreground">
            该版本未记录自我印象链接。
          </p>
        ) : (
          <>
            <ul className="mt-2 flex flex-wrap gap-2">
              {view.derivedFrom.map((id) => (
                <li key={id}>
                  <ImpressionEvidence
                    client={client}
                    id={id}
                    revision={version.revision}
                    sources={version.sourceIds}
                  />
                </li>
              ))}
            </ul>
          </>
        )}
      </div>

      <div>
        <h4 className="text-sm font-medium">原始对话证据</h4>
        {view.sources.length === 0 && view.missingSourceIds.length === 0 ? (
          <p className="mt-1 text-xs text-muted-foreground">
            {empty ? "该版本未记录证据来源。" : "该版本记录的证据均未返回。"}
          </p>
        ) : (
          <ul className="mt-2 space-y-3">
            {view.sources.map((source) => (
              <li
                key={source.id}
                className="rounded-md border bg-background p-3"
              >
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                  <span>
                    {roleLabels[source.role] ?? "其他角色"} ·{" "}
                    {source.at || "时间未记录"}
                  </span>
                  <code className="wrap-anywhere">{source.id}</code>
                </div>
                <p className="mt-2 text-sm leading-6 wrap-anywhere whitespace-pre-wrap">
                  {source.text || "未返回正文"}
                </p>
                {source.umo && (
                  <p className="mt-1 text-xs wrap-anywhere text-muted-foreground">
                    来源会话：{source.umo}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
        {view.missingSourceIds.length > 0 && (
          <p role="status" className="mt-2 text-xs text-destructive">
            未返回的原始对话证据：
            {view.missingSourceIds.join("、")}
          </p>
        )}
      </div>
    </div>
  )
}

function ImpressionEvidence({
  client,
  id,
  revision,
  sources,
}: {
  client: ManagementClient
  id: string
  revision: number
  sources: readonly string[]
}) {
  const [open, setOpen] = useState(false)
  const state = useImpressionEvidence(
    client,
    open ? id : null,
    revision,
    sources
  )
  return (
    <div className="space-y-2">
      <Button
        variant="outline"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        自我印象 <code className="text-xs">{id}</code>
      </Button>
      {open && state.status === "loading" && (
        <p role="status">正在读取自我印象…</p>
      )}
      {open && state.status === "error" && (
        <p role="alert">自我印象暂时无法读取。</p>
      )}
      {open && state.status === "ready" && (
        <p className="text-sm">
          {state.text ?? "没有保存与该人格版本对应的印象正文。"}
        </p>
      )}
    </div>
  )
}
