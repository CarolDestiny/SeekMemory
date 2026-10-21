import { useCallback, useEffect, useRef, useState } from "react"
import type { MemorySource } from "../memory/model"
import type { ManagementClient, RuntimeStatus, OperationEvent } from "./model"

export function useControl(client: ManagementClient) {
  const [source, setSource] = useState<MemorySource>({ status: "loading" })
  const [status, setStatus] = useState<RuntimeStatus | null>(null)
  const [events, setEvents] = useState<OperationEvent[]>([])
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const mounted = useRef(false)
  const loading = useRef(false)
  const refresh = useCallback(async () => {
    if (loading.current) return
    loading.current = true
    try {
      const [records, runtime, log] = await Promise.allSettled([
        Promise.resolve().then(() => client.records()),
        Promise.resolve().then(() => client.status()),
        Promise.resolve().then(() => client.events()),
      ])
      if (mounted.current) {
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
        setError(
          Array.from(
            new Set(
              [records, runtime, log]
                .filter((item) => item.status === "rejected")
                .map((item) =>
                  item.reason instanceof Error
                    ? item.reason.message
                    : "读取失败"
                )
            )
          ).join("；")
        )
      }
    } finally {
      loading.current = false
    }
  }, [client])
  useEffect(() => {
    mounted.current = true
    void refresh()
    return () => {
      mounted.current = false
    }
  }, [refresh])
  useEffect(() => {
    if (!status?.activeTask) return
    const timer = setInterval(() => {
      void refresh()
    }, 2000)
    return () => clearInterval(timer)
  }, [status?.activeTask, refresh])
  const run = async (operation: () => Promise<unknown>) => {
    setBusy(true)
    setError("")
    try {
      await operation()
      await refresh()
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "操作失败")
    } finally {
      setBusy(false)
    }
  }
  return { source, status, events, error, busy, refresh, run }
}
