import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { afterEach, test } from "node:test"
import { z } from "zod"
import { memoryCollectionSchema } from "../../src/features/memory/model.ts"
import {
  detailSchema,
  diagnosticSchema,
  eventsSchema,
  statusSchema,
} from "../../src/features/control/model.ts"
import { apiOperations, validateApi } from "../contract-schema.ts"
import { astrbotClient } from "../../src/infrastructure/astrbot-client.ts"

afterEach(() => {
  Reflect.deleteProperty(globalThis, "window")
})

// 缺少真实响应样本时直接失败，CI 不允许用 Mock 或跳过来替代实现契约验证。
const samples = z
  .array(
    z.object({
      action: z.string(),
      status: z.number().int(),
      body: z.json(),
    })
  )
  .parse(
    JSON.parse(
      readFileSync(
        new URL(
          "../../node_modules/.tmp/backend-contract.json",
          import.meta.url
        ),
        "utf8"
      )
    )
  )

void test("真实后端响应同时满足 OpenAPI 与前端 Zod，覆盖全部操作及错误状态", () => {
  const parsers: Record<string, z.ZodType> = {
    records: z.object({ records: memoryCollectionSchema }),
    detail: detailSchema,
    status: statusSchema,
    events: eventsSchema,
    diagnose: diagnosticSchema,
    update: z.object({ id: z.string() }),
    task: z.object({ id: z.string() }),
    cancel: z.object({ id: z.string() }),
  }
  const errorSchema = z.object({
    status: z.literal("error"),
    message: z.string(),
    data: z.json(),
  })
  for (const sample of samples) {
    validateApi(sample.action, sample.status, sample.body)
    const parser = sample.status === 200 ? parsers[sample.action] : errorSchema
    assert.ok(parser)
    parser.parse(sample.body)
  }
  assert.deepEqual(
    new Set(
      samples
        .filter((sample) => sample.status === 200)
        .map((sample) => sample.action)
    ),
    new Set(apiOperations.map((operation) => operation.operationId))
  )
  assert.deepEqual(
    new Set(samples.map((sample) => sample.status)),
    new Set([200, 400, 401, 404, 405, 409, 413, 500, 503])
  )
})

void test("生产桥接适配器消费全部成功响应，路径与请求体符合契约", async () => {
  const calls: Record<string, () => Promise<unknown>> = {
    records: () => astrbotClient.records(),
    status: () => astrbotClient.status(),
    detail: () => astrbotClient.detail("fixture"),
    events: () => astrbotClient.events(),
    diagnose: () =>
      astrbotClient.diagnose({
        query: "咖啡",
        umo: "bot:FriendMessage:alice",
        speaker: "alice",
      }),
    update: () =>
      astrbotClient.update({
        id: "fixture",
        expectedRevision: 1,
        payload: { text: "咖啡", level: "fact" },
        state: "active",
        scope: "private",
        reason: "契约验证",
        confirmed: true,
      }),
    task: () => astrbotClient.task("weekly"),
    cancel: () => astrbotClient.cancel("fixture"),
  }
  for (const sample of samples.filter((item) => item.status === 200)) {
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: {
        AstrBotPluginPage: {
          async ready() {},
          async apiGet(endpoint: string) {
            assert.equal(endpoint, `manage/${sample.action}`)
            return sample.body
          },
          async apiPost(endpoint: string, body: unknown) {
            assert.equal(endpoint, `manage/${sample.action}`)
            validateApi(sample.action, 0, body)
            return sample.body
          },
        },
      },
    })
    const call = calls[sample.action]
    assert.ok(call)
    await call()
  }
})
