import assert from "node:assert/strict"
import { afterEach, test } from "node:test"
import { astrbotClient } from "../src/infrastructure/astrbot-client.ts"

afterEach(() => {
  Reflect.deleteProperty(globalThis, "window")
})

void test("production client requires the host Page bridge and never falls back to fixtures", async () => {
  Object.defineProperty(globalThis, "window", { configurable: true, value: {} })
  await assert.rejects(astrbotClient.records(), /AstrBot/)
})

void test("Page bridge uses relative plugin endpoints and validates unknown responses", async () => {
  const calls: unknown[] = []
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      AstrBotPluginPage: {
        async ready() {
          calls.push("ready")
        },
        async apiGet(endpoint: string) {
          calls.push(endpoint)
          return { records: [] }
        },
        async apiPost(endpoint: string, body: unknown) {
          calls.push({ endpoint, body })
          return { id: "task-1" }
        },
      },
    },
  })
  assert.deepEqual(await astrbotClient.records(), [])
  assert.equal(await astrbotClient.task("weekly"), "task-1")
  assert.deepEqual(calls, [
    "ready",
    "manage/records",
    "ready",
    {
      endpoint: "manage/task",
      body: { kind: "weekly", confirmed: true },
    },
  ])
  await assert.rejects(astrbotClient.status())
})
