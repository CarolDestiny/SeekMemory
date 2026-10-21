import { BookOpen, CircleDot, Fingerprint, Sparkles, Users } from "lucide-react"
import { memoryCategories, type MemoryCategory } from "../model"
import type { CategoryFilter, StateFilter } from "../library-state"
import type { SelectOption } from "@/ui"

export const categoryLabels = {
  fact: "事实",
  scene: "场景",
  detail: "细节",
  impression: "印象",
  persona: "人格",
  example: "语料",
  media: "媒体",
  secret: "秘密影子",
  designated: "指定交付",
} satisfies Record<MemoryCategory, string>

export const categoryIcons = {
  fact: CircleDot,
  scene: BookOpen,
  detail: Fingerprint,
  impression: Sparkles,
  persona: Users,
  example: BookOpen,
  media: CircleDot,
  secret: Fingerprint,
  designated: Sparkles,
}

export const categoryFilterOptions: readonly SelectOption<CategoryFilter>[] = [
  { value: "all", label: "全部类型" },
  ...memoryCategories.map((value) => ({ value, label: categoryLabels[value] })),
]

export const stateFilterOptions: readonly SelectOption<StateFilter>[] = [
  { value: "all", label: "全部状态" },
  { value: "active", label: "有效记忆" },
  { value: "forgotten", label: "已遗忘" },
  { value: "merged", label: "已合并" },
]

export const memoryDateFormat = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "Asia/Shanghai",
})
