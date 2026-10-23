import assert from "node:assert/strict"
import { test } from "node:test"
import { Window } from "happy-dom"
import { act, createElement, useEffect } from "react"
import { createRoot } from "react-dom/client"
import { mockClient } from "../src/dev/mock-client.ts"
import {
  detailSchema,
  personaRevisionSchema,
  type ArtifactDetail,
  type ManagementClient,
} from "../src/features/control/model.ts"
import {
  projectEvidence,
  projectImpression,
  usePersonaEvidence,
} from "../src/features/control/use-persona-evidence.ts"

function version(
  revision: number,
  ids: string[],
  text = `version-${revision}`
) {
  return {
    revision,
    at: "2026-10-23T10:00:00Z",
    op: "promote",
    content: JSON.stringify({ text }),
    header: JSON.stringify({
      lineage: JSON.stringify({ sources: ids, derived_from: [`i${revision}`] }),
    }),
  }
}
const detail = detailSchema.parse({
  artifact: {
    header: {
      id: "p",
      family: "persona",
      revision: 2,
      state: "active",
      scope: "shared",
    },
    payload: { text: "new" },
  },
  versions: [version(2, ["s1", "s2", "missing"]), version(1, ["s1"])],
  sources: [
    { id: "s1", text: "OLD_ONLY", role: "user" },
    { id: "s2", text: "NEW_ONLY", role: "assistant" },
  ],
  ledger: [],
})

void test("older persona versions show only their own evidence and report missing sources", () => {
  const old = projectEvidence(detail, 1)
  assert.deepEqual(
    old.sources.map((s) => s.id),
    ["s1"]
  )
  assert.equal(JSON.stringify(old).includes("NEW_ONLY"), false)
  assert.deepEqual(old.derivedFrom, ["i1"])
  assert.deepEqual(projectEvidence(detail, 2).missingSourceIds, ["missing"])
  assert.equal(projectEvidence(detail, 999).version, null)
})

void test("historical missing lineage is not filled from the head or another version", () => {
  const legacy = {
    ...detail,
    versions: [{ revision: 1, header: "broken" }, version(2, ["s2"])],
  }
  assert.deepEqual(projectEvidence(legacy, 1).sources, [])
  assert.deepEqual(
    personaRevisionSchema.parse({
      revision: 1,
      at: "",
      op: "promote",
      text: "old",
    }).sourceIds,
    []
  )
  assert.equal(projectImpression(detail, ["s1"]), "version-1")
  assert.equal(projectImpression(detail, []), null)
})

function deferred<T>() {
  let resolve: (value: T) => void = () => {
    throw new Error("not initialized")
  }
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

void test("changing revision, client or persona invalidates late evidence replies", async () => {
  const dom = new Window()
  const globals = {
    window: dom,
    document: dom.document,
    IS_REACT_ACT_ENVIRONMENT: true,
  }
  const previous = Object.getOwnPropertyDescriptors(globalThis)
  for (const [key, value] of Object.entries(globals))
    Object.defineProperty(globalThis, key, {
      configurable: true,
      writable: true,
      value,
    })
  const first = deferred<ArtifactDetail>()
  const client: ManagementClient = {
    ...mockClient,
    detail: () => first.promise,
  }
  const next: ManagementClient = {
    ...mockClient,
    detail: () => Promise.resolve(detail),
  }
  let current: ReturnType<typeof usePersonaEvidence> | undefined
  function snapshot() {
    assert.ok(current)
    return current
  }
  function Probe({
    source,
    revision,
    id,
  }: {
    source: ManagementClient
    revision: number
    id: string
  }) {
    const vm = usePersonaEvidence(source, id, revision)
    useEffect(() => {
      current = vm
    }, [vm])
    return null
  }
  const root = createRoot(document.createElement("div"))
  try {
    await act(async () => {
      root.render(
        createElement(Probe, { source: client, revision: 1, id: "p" })
      )
    })
    assert.equal(snapshot().state.status, "loading")
    await act(async () => {
      root.render(
        createElement(Probe, { source: next, revision: 2, id: "new-p" })
      )
    })
    const changed = snapshot().state
    assert.ok(changed.status === "ready")
    assert.equal(changed.view.version?.revision, 2)
    await act(async () => {
      first.resolve(detail)
    })
    const late = snapshot().state
    assert.ok(late.status === "ready")
    assert.equal(late.view.version?.revision, 2)
    await act(async () => {
      root.unmount()
    })
  } finally {
    await dom.happyDOM.close()
    for (const key of Object.keys(globals)) {
      const descriptor = previous[key]
      if (descriptor) Object.defineProperty(globalThis, key, descriptor)
      else Reflect.deleteProperty(globalThis, key)
    }
  }
})
