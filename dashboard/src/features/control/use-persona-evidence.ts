import { useCallback, useEffect, useRef, useState } from "react"
import { z } from "zod"
import type { ArtifactDetail, ManagementClient } from "./model.ts"

/**
 * 人格版本证据的只读投影。
 *
 * 历史 header 在数据库中可能是 JSON 字符串，lineage 也可能再嵌套一层
 * JSON 字符串。这里只解码所选版本自己的 header；缺失或损坏时返回空数组，
 * 绝不把当前版本或其他版本的证据补到旧版本上。
 */

export interface PersonaEvidenceVersion {
  readonly revision: number
  readonly at: string
  readonly op: string
  readonly text: string
  readonly derivedFrom: readonly string[]
  readonly sourceIds: readonly string[]
}

export interface PersonaEvidenceSource {
  readonly id: string
  readonly text: string
  readonly role: string
  readonly at: string
  readonly umo: string
}

export interface PersonaEvidenceView {
  readonly version: PersonaEvidenceVersion | null
  readonly derivedFrom: readonly string[]
  readonly sources: readonly PersonaEvidenceSource[]
  readonly missingSourceIds: readonly string[]
}

export interface PersonaEvidenceDetail {
  readonly versions: readonly Record<string, unknown>[]
  readonly sources: readonly Record<string, unknown>[]
}

function objectValue(value: unknown, depth = 0): Record<string, unknown> {
  if (depth > 3) return {}
  if (typeof value === "string") {
    if (!value.trim()) return {}
    try {
      return objectValue(JSON.parse(value) as unknown, depth + 1)
    } catch {
      return {}
    }
  }
  const parsed = z.record(z.string(), z.unknown()).safeParse(value)
  return parsed.success ? parsed.data : {}
}

function stringList(value: unknown): string[] {
  let candidate = value
  if (typeof candidate === "string") {
    try {
      candidate = JSON.parse(candidate) as unknown
    } catch {
      return []
    }
  }
  if (!Array.isArray(candidate)) return []
  const out: string[] = []
  for (const item of candidate) {
    if (typeof item !== "string") continue
    const text = item.trim()
    if (text && !out.includes(text)) out.push(text)
  }
  return out
}

function payloadText(row: Record<string, unknown>): string {
  if (typeof row["text"] === "string") return row["text"]
  for (const candidate of [row["payload"], row["content"]]) {
    const payload = objectValue(candidate)
    if (typeof payload["text"] === "string") return payload["text"]
  }
  return ""
}

function versionFrom(
  row: Record<string, unknown>
): PersonaEvidenceVersion | null {
  const revision = row["revision"]
  if (
    typeof revision !== "number" ||
    !Number.isInteger(revision) ||
    revision < 0
  )
    return null
  const header = objectValue(row["header"])
  const lineage = objectValue(header["lineage"])
  return {
    revision,
    at: typeof row["at"] === "string" ? row["at"] : "",
    op: typeof row["op"] === "string" ? row["op"] : "",
    text: payloadText(row),
    derivedFrom: stringList(lineage["derived_from"] ?? lineage["derivedFrom"]),
    sourceIds: stringList(lineage["sources"] ?? lineage["sourceIds"]),
  }
}

function sourceFrom(
  row: Record<string, unknown>
): PersonaEvidenceSource | null {
  if (typeof row["id"] !== "string" || !row["id"]) return null
  return {
    id: row["id"],
    text: typeof row["text"] === "string" ? row["text"] : "",
    role: typeof row["role"] === "string" ? row["role"] : "",
    at: typeof row["at"] === "string" ? row["at"] : "",
    umo: typeof row["umo"] === "string" ? row["umo"] : "",
  }
}

export function projectEvidence(
  detail: PersonaEvidenceDetail,
  revision: number
): PersonaEvidenceView {
  let version: PersonaEvidenceVersion | null = null
  for (const row of detail.versions) {
    const parsed = versionFrom(row)
    if (parsed?.revision === revision) {
      version = parsed
      break
    }
  }
  if (version === null)
    return { version: null, derivedFrom: [], sources: [], missingSourceIds: [] }

  const byId = new Map<string, PersonaEvidenceSource>()
  for (const row of detail.sources) {
    const source = sourceFrom(row)
    if (source && !byId.has(source.id)) byId.set(source.id, source)
  }
  const sources: PersonaEvidenceSource[] = []
  const missingSourceIds: string[] = []
  for (const id of version.sourceIds) {
    const source = byId.get(id)
    if (source) sources.push(source)
    else missingSourceIds.push(id)
  }
  return {
    version,
    derivedFrom: version.derivedFrom,
    sources,
    missingSourceIds,
  }
}

type DetailState =
  | { readonly status: "idle" }
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly detail: ArtifactDetail }
  | { readonly status: "error"; readonly message: string }

/**
 * 读取一个人格版本自己的证据。
 *
 * 版本、人格 ID、客户端或重试次数变化都会使旧请求失效；组件卸载后
 * 迟到的响应也不会写入状态。详情接口已经过宿主管理员认证。
 */
function useEvidenceDetail(
  client: ManagementClient,
  personaId: string | null,
  revision: number | null
) {
  const [snapshot, setSnapshot] = useState<{
    client: ManagementClient | null
    id: string | null
    revision: number | null
    state: DetailState
  }>({ client: null, id: null, revision: null, state: { status: "idle" } })
  const [attempt, setAttempt] = useState(0)
  const token = useRef(0)

  useEffect(() => {
    const current = ++token.current
    const setState = (state: DetailState) => {
      setSnapshot({ client, id: personaId, revision, state })
    }
    if (!personaId || revision === null) {
      setState({ status: "idle" })
      return
    }
    setState({ status: "loading" })
    Promise.resolve()
      .then(() => client.detail(personaId))
      .then(
        (detail) => {
          if (current !== token.current) return
          setState({ status: "ready", detail })
        },
        (failure: unknown) => {
          if (current !== token.current) return
          setState({
            status: "error",
            message:
              failure instanceof Error ? failure.message : "证据读取失败",
          })
        }
      )
    return () => {
      token.current += 1
    }
  }, [attempt, client, personaId, revision])

  const reload = useCallback(() => {
    setAttempt((value) => value + 1)
  }, [])

  const matches =
    snapshot.client === client &&
    snapshot.id === personaId &&
    snapshot.revision === revision
  const state: DetailState = matches
    ? snapshot.state
    : { status: personaId && revision !== null ? "loading" : "idle" }
  return { state, reload }
}

export function usePersonaEvidence(
  client: ManagementClient,
  id: string | null,
  revision: number | null
) {
  const { state, reload } = useEvidenceDetail(client, id, revision)
  if (state.status === "ready") {
    if (revision === null) return { state: { status: "idle" as const }, reload }
    return {
      state: {
        status: "ready" as const,
        view: projectEvidence(state.detail, revision),
      },
      reload,
    }
  }
  return { state, reload }
}

export function projectImpression(
  detail: PersonaEvidenceDetail,
  allowedSourceIds: readonly string[]
): string | null {
  const allowed = new Set(allowedSourceIds)
  const versions = [...detail.versions].sort(
    (a, b) => Number(b["revision"]) - Number(a["revision"])
  )
  for (const row of versions) {
    const version = versionFrom(row)
    if (
      version &&
      version.sourceIds.length > 0 &&
      version.sourceIds.every((id) => allowed.has(id))
    )
      return version.text || null
  }
  return null
}

export function useImpressionEvidence(
  client: ManagementClient,
  id: string | null,
  revision: number,
  sources: readonly string[]
) {
  const { state } = useEvidenceDetail(client, id, revision)
  if (state.status === "ready")
    return {
      status: "ready" as const,
      text: projectImpression(state.detail, sources),
    }
  return state
}
