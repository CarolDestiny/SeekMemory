import { useState } from "react"
import type { OperationEvent } from "./model.ts"

export function useLogs(events: readonly OperationEvent[]) {
  const [kind, setKind] = useState("all")
  const [state, setState] = useState("all")
  const [level, setLevel] = useState("all")
  const [module, setModule] = useState("all")
  const [query, setQuery] = useState("")
  const needle = query.trim().toLowerCase()
  const filtered = events.filter((event) => {
    if (kind !== "all" && event.kind !== kind) return false
    if (state !== "all" && event.status !== state) return false
    if (level !== "all" && event.level !== level) return false
    if (module !== "all" && event.source?.module !== module) return false
    const searchText = [
      event.message,
      event.taskId,
      event.stage,
      event.source?.module,
      event.source?.file,
      event.source?.function,
      event.source?.line,
      JSON.stringify(event.context),
      event.error?.type,
    ]
      .join(" ")
      .toLowerCase()
    return searchText.includes(needle)
  })
  return {
    kind,
    setKind,
    state,
    setState,
    level,
    setLevel,
    module,
    setModule,
    query,
    setQuery,
    filtered,
    kinds: Array.from(new Set(events.map((event) => event.kind))).sort(),
    modules: Array.from(
      new Set(
        events.flatMap((event) => (event.source ? [event.source.module] : []))
      )
    ).sort(),
  }
}
