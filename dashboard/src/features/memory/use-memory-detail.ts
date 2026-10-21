import { useState } from "react"
import type { MemoryRecord } from "./model.ts"

export function useMemoryDetail(
  memory: MemoryRecord,
  records: readonly MemoryRecord[]
) {
  const currentVersion = memory.versions[0]
  const [revision, setRevision] = useState(currentVersion.revision)
  const versionIndex = Math.max(
    0,
    memory.versions.findIndex((item) => item.revision === revision)
  )
  const version = memory.versions[versionIndex] ?? currentVersion
  const previous = memory.versions[versionIndex + 1]
  const related = memory.relatedIds.flatMap((id) => {
    const record = records.find((item) => item.id === id)
    return record ? [record] : []
  })

  return { currentVersion, version, previous, related, setRevision }
}
