import assert from "node:assert/strict"
import test from "node:test"
import {
  detailSchema,
  statusSchema,
  updateSchema,
} from "../src/features/control/model.ts"

void test("editor commands require confirmation, a revision and an audit reason", () => {
  const command = {
    id: "memory-1",
    expectedRevision: 3,
    payload: { text: "A corrected fact", level: "fact" },
    scope: "private",
    state: "active",
    reason: "Correction",
    confirmed: true,
  }
  assert.equal(updateSchema.safeParse(command).success, true)
  for (const invalid of [
    { ...command, confirmed: false },
    { ...command, reason: "  " },
    { ...command, expectedRevision: 0 },
    { ...command, payload: [] },
    { ...command, scope: "public" },
    { ...command, extra: "untrusted" },
  ])
    assert.equal(updateSchema.safeParse(invalid).success, false)
})

void test("detail keeps raw evidence and additional header fields without trusting malformed identities", () => {
  const value = {
    artifact: {
      header: {
        id: "memory-1",
        family: "secret",
        revision: 2,
        state: "forgotten",
        scope: "shadow",
        lineage: { sources: ["source-1"] },
      },
      payload: { ref: "vault", shadow_text: "A promise" },
    },
    versions: [],
    sources: [],
    ledger: [],
  }
  assert.equal(
    detailSchema.parse(value).artifact.header["lineage"] !== undefined,
    true
  )
  assert.equal(
    detailSchema.safeParse({
      ...value,
      artifact: {
        ...value.artifact,
        header: { ...value.artifact.header, revision: "2" },
      },
    }).success,
    false
  )
})

void test("runtime status supports an unavailable engine while retaining diagnostics", () => {
  const value = {
    ready: false,
    checks: [{ name: "engine", ok: false, detail: "Unavailable" }],
    activeTask: null,
    pending: [],
    schedulerCount: 0,
    config: {},
  }
  assert.equal(statusSchema.parse(value).ready, false)
  assert.equal(
    statusSchema.safeParse({ ...value, schedulerCount: -1 }).success,
    false
  )
})
