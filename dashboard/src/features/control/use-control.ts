import { useCallback, useEffect, useRef, useState } from "react"
import type { MemoryRecord, MemorySource } from "../memory/model.ts"
import type {
  ManagementClient,
  RuntimeStatus,
  OperationEvent,
} from "./model.ts"

type PendingAction =
  | { kind: "extract" | "weekly" }
  | { kind: "cancel"; taskId: string }

export function useControl(client: ManagementClient) {
  const [source, setSource] = useState<MemorySource>({ status: "loading" })
  const [status, setStatus] = useState<RuntimeStatus | null>(null)
  const [events, setEvents] = useState<OperationEvent[]>([])
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const [scope, setScope] = useState<MemoryRecord["scope"] | "all">("all")
  const [session, setSession] = useState("all")
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null)
  const [confirmed, setConfirmed] = useState(false)
  const mounted = useRef(false)
  const loading = useRef<Promise<void> | null>(null)
  const requestVersion = useRef(0)
  const acting = useRef(false)
  const refresh = useCallback(
    (force = false): Promise<void> => {
      if (loading.current && !force) return loading.current
      const version = ++requestVersion.current
      const pending = Promise.allSettled([
        Promise.resolve().then(() => client.records()),
        Promise.resolve().then(() => client.status()),
        Promise.resolve().then(() => client.events()),
      ])
        .then(([records, runtime, log]) => {
          // 写入后的刷新取代先前读取，旧请求的错误也应失效。
          if (!mounted.current || version !== requestVersion.current) return
          if (records.status === "fulfilled")
            setSource({ status: "ready", records: records.value })
          else
            setSource({
              status: "error",
              message:
                records.reason instanceof Error
                  ? records.reason.message
                  : "记忆读取失败",
            })
          if (runtime.status === "fulfilled") setStatus(runtime.value)
          else setStatus(null)
          if (log.status === "fulfilled") setEvents(log.value)
          const messages = new Set<string>()
          for (const result of [records, runtime, log]) {
            if (result.status !== "rejected") continue
            messages.add(
              result.reason instanceof Error
                ? result.reason.message
                : "读取失败"
            )
          }
          setError([...messages].join("；"))
        })
        .finally(() => {
          if (version === requestVersion.current) loading.current = null
        })
      loading.current = pending
      return pending
    },
    [client]
  )
  useEffect(() => {
    mounted.current = true
    void refresh()
    return () => {
      mounted.current = false
      requestVersion.current += 1
      loading.current = null
    }
  }, [refresh])
  const activeTaskId = status?.activeTask?.id
  useEffect(() => {
    if (!activeTaskId) return
    const timer = setInterval(() => {
      void refresh()
    }, 2000)
    return () => clearInterval(timer)
  }, [activeTaskId, refresh])
  const executeAction = async () => {
    if (!pendingAction || !confirmed || acting.current) return
    const selected = pendingAction
    acting.current = true
    setBusy(true)
    setPendingAction(null)
    setConfirmed(false)
    setError("")
    try {
      if (selected.kind === "cancel") await client.cancel(selected.taskId)
      else await client.task(selected.kind)
      if (mounted.current) await refresh(true)
    } catch (failure) {
      if (mounted.current)
        setError(failure instanceof Error ? failure.message : "操作失败")
    } finally {
      acting.current = false
      if (mounted.current) setBusy(false)
    }
  }
  let filteredSource = source
  let sessions: string[] = []
  if (source.status === "ready") {
    filteredSource = {
      ...source,
      records: source.records.filter(
        (record) =>
          (scope === "all" || record.scope === scope) &&
          (session === "all" || record.session === session)
      ),
    }
    sessions = [
      ...new Set(source.records.map((record) => record.session)),
    ].sort()
  }
  return {
    source: filteredSource,
    status,
    events,
    error,
    busy,
    scope,
    setScope,
    session,
    setSession,
    sessions,
    action: pendingAction?.kind ?? null,
    confirmed,
    setConfirmed,
    refresh,
    refreshAfterWrite: () => refresh(true),
    executeAction,
    requestAction: (kind: PendingAction["kind"]) => {
      if (acting.current) return
      if (kind === "cancel") {
        if (!status?.activeTask) return
        setPendingAction({ kind, taskId: status.activeTask.id })
      } else setPendingAction({ kind })
      setConfirmed(false)
    },
    dismissAction: () => {
      setPendingAction(null)
      setConfirmed(false)
    },
  }
}
