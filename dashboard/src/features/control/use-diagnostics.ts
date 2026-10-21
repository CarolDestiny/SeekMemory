import { useState } from "react"
import {
  selectDisclosure,
  type Diagnostic,
  type ManagementClient,
} from "./model"

export function useDiagnostics(client: ManagementClient) {
  const [query, setQuery] = useState("")
  const [umo, setUmo] = useState("")
  const [speaker, setSpeaker] = useState("")
  const [result, setResult] = useState<Diagnostic | null>(null)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const diagnose = async () => {
    setBusy(true)
    setError("")
    setResult(null)
    try {
      setResult(await client.diagnose({ query, umo, speaker }))
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "诊断失败")
    } finally {
      setBusy(false)
    }
  }
  return {
    disclosure: result ? selectDisclosure(result) : [],
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
  }
}
