import { z } from "zod"

export const memoryCategorySchema = z.enum([
  "fact",
  "scene",
  "detail",
  "impression",
  "persona",
])
export const memoryCategories = memoryCategorySchema.options
export const memoryStateSchema = z.enum(["active", "forgotten"])

const memoryVersionSchema = z
  .strictObject({
    revision: z.number().int().positive(),
    at: z.iso.datetime({ offset: true }),
    text: z.string().min(1),
  })
  .readonly()

// This is the validated presentation contract, not a claim about the future wire format.
export const memoryRecordSchema = z
  .strictObject({
    id: z.string().min(1),
    title: z.string().min(1),
    text: z.string().min(1),
    category: memoryCategorySchema,
    state: memoryStateSchema,
    scope: z.enum(["private", "shared"]),
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
        message: "The latest version must match the current content.",
      })
    }
    for (let index = 1; index < memory.versions.length; index += 1) {
      const previous = memory.versions[index - 1]
      const current = memory.versions[index]
      if (previous && current && previous.revision <= current.revision) {
        context.addIssue({
          code: "custom",
          path: ["versions", index],
          message: "Versions must have unique revisions in descending order.",
        })
      }
    }
  })
  .readonly()

export const memoryCollectionSchema = z
  .array(memoryRecordSchema)
  .superRefine((records, context) => {
    const ids = new Set<string>()
    records.forEach((record, index) => {
      if (ids.has(record.id)) {
        context.addIssue({
          code: "custom",
          path: [index, "id"],
          message: "Memory IDs must be unique.",
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
