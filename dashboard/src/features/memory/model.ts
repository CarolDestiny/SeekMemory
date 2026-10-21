import { z } from "zod"
import type { ApiSchemas, DeepReadonly } from "../../contracts/api.ts"

export const memoryCategorySchema = z.enum([
  "fact",
  "scene",
  "detail",
  "impression",
  "persona",
  "example",
  "media",
  "secret",
  "designated",
])
export const memoryCategories = memoryCategorySchema.options
export const memoryStateSchema = z.enum(["active", "forgotten", "merged"])

const memoryVersionSchema = z
  .strictObject({
    revision: z.number().int().positive(),
    at: z.iso.datetime({ offset: true }),
    text: z.string().min(1),
  })
  .readonly()

// 宿主适配器与 Mock 共用经过校验的记忆库数据结构。
export const memoryRecordSchema = z
  .strictObject({
    id: z.string().min(1),
    title: z.string().min(1),
    text: z.string().min(1),
    category: memoryCategorySchema,
    state: memoryStateSchema,
    scope: z.enum(["private", "shared", "shadow"]),
    subject: z.string().min(1),
    session: z.string().min(1),
    tags: z.array(z.string().min(1)).readonly(),
    confidence: z.number().min(0).max(1),
    hits: z.number().int().nonnegative(),
    updatedAt: z.iso.datetime({ offset: true }),
    versions: z.tuple([memoryVersionSchema], memoryVersionSchema).readonly(),
    relatedIds: z.array(z.string().min(1)).readonly(),
  })
  .superRefine((memory, context) => {
    if (memory.versions[0].text !== memory.text) {
      context.addIssue({
        code: "custom",
        path: ["versions", 0, "text"],
        message: "最新版本必须与当前内容一致。",
      })
    }
    for (let index = 1; index < memory.versions.length; index += 1) {
      const previous = memory.versions[index - 1]
      const current = memory.versions[index]
      if (previous && current && previous.revision <= current.revision) {
        context.addIssue({
          code: "custom",
          path: ["versions", index],
          message: "版本号必须唯一，并按降序排列。",
        })
      }
    }
  })
  .readonly() satisfies z.ZodType<DeepReadonly<ApiSchemas["MemoryRecord"]>>

export const memoryCollectionSchema = z
  .array(memoryRecordSchema)
  .superRefine((records, context) => {
    const ids = new Set<string>()
    records.forEach((record, index) => {
      if (ids.has(record.id)) {
        context.addIssue({
          code: "custom",
          path: [index, "id"],
          message: "记忆 ID 必须唯一。",
        })
      }
      ids.add(record.id)
    })
  })
  .readonly()

export type MemoryCategory = z.infer<typeof memoryCategorySchema>
export type MemoryState = z.infer<typeof memoryStateSchema>
export type MemoryRecord = z.infer<typeof memoryRecordSchema>

export type MemorySource =
  | { readonly status: "loading" }
  | { readonly status: "error"; readonly message: string }
  | { readonly status: "ready"; readonly records: readonly MemoryRecord[] }
