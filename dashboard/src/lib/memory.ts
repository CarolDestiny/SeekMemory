export const memoryCategories = [
  "fact",
  "scene",
  "detail",
  "impression",
  "persona",
] as const
export type MemoryCategory = (typeof memoryCategories)[number]

export const categoryLabels = {
  fact: "事实",
  scene: "场景",
  detail: "细节",
  impression: "印象",
  persona: "人格",
} as const satisfies Record<MemoryCategory, string>

export type PreviewState = "ready" | "loading" | "empty" | "error"

export interface MemoryVersion {
  revision: number
  at: string
  text: string
}

// A presentation model, independent of the eventual AstrBot API response.
export interface MemoryRecord {
  id: string
  title: string
  text: string
  category: MemoryCategory
  state: "active" | "forgotten"
  scope: "private" | "shared"
  subject: string
  session: string
  tags: string[]
  confidence: number
  hits: number
  updatedAt: string
  versions: MemoryVersion[]
  relatedIds: string[]
}

export const memoryDateFormat = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "Asia/Shanghai",
})
