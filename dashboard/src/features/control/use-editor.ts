import { useEffect, useState } from "react"
import {
  updateSchema,
  type ArtifactDetail,
  type ManagementClient,
  type UpdateCommand,
} from "./model"

export function useEditor(
  client: ManagementClient,
  id: string | null,
  onSaved: () => Promise<void>
) {
  const [detail, setDetail] = useState<ArtifactDetail | null>(null)
  const [payload, setPayload] = useState("")
  const [scope, setScope] = useState<UpdateCommand["scope"]>("private")
  const [state, setState] = useState<UpdateCommand["state"]>("active")
  const [reason, setReason] = useState("")
  const [confirmed, setConfirmed] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [saving, setSaving] = useState(false)
  const [reload, setReload] = useState(0)
  useEffect(() => {
    let active = true
    if (id)
      void client
        .detail(id)
        .then((data) => {
          if (!active) return
          setError("")
          setConfirmed(false)
          setReason("")
          setDetail(data)
          setPayload(JSON.stringify(data.artifact.payload, null, 2))
          setScope(data.artifact.header.scope)
          setState(data.artifact.header.state)
        })
        .catch((failure: unknown) => {
          if (active)
            setError(
              failure instanceof Error ? failure.message : "详情读取失败"
            )
        })
    return () => {
      active = false
    }
  }, [client, id, reload])
  const save = async () => {
    if (!detail || !id || !confirmed) return
    setSaving(true)
    setError("")
    setNotice("")
    try {
      const value: unknown = JSON.parse(payload)
      const command = updateSchema.parse({
        id,
        expectedRevision: detail.artifact.header.revision,
        payload: value,
        scope,
        state,
        reason,
        confirmed,
      })
      await client.update(command)
      await onSaved()
      setNotice("已保存为新修订，旧版本保留在历史中。")
      setReload((value) => value + 1)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "保存失败")
    } finally {
      setSaving(false)
    }
  }
  return {
    detail,
    payload,
    setPayload,
    scope,
    setScope,
    state,
    setState,
    reason,
    setReason,
    confirmed,
    setConfirmed,
    error,
    notice,
    saving,
    save,
    reload: () => {
      setDetail(null)
      setError("")
      setReload((value) => value + 1)
    },
  }
}
