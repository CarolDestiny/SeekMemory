import { useState } from "react"
import type { OperationEvent } from "./model.ts"

export function useLogs(events: readonly OperationEvent[]) {
  const [kind, setKind] = useState("all")
  const [state, setState] = useState("all")
  const [level, setLevel] = useState("all")
  const [module, setModule] = useState("all")
  const [query, setQuery] = useState("")
  const needle = query.trim().toLowerCase()
  const filtered = events.filter(
    (event) =>
      (kind === "all" || event.kind === kind) &&
      (state === "all" || event.status === state) &&
      (level === "all" || event.level === level) &&
      (module === "all" || event.source?.module === module) &&
      [
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
        .includes(needle)
  )
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
