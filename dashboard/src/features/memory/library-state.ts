import type { MemoryCategory, MemoryRecord, MemoryState } from "./model.ts"

export type CategoryFilter = MemoryCategory | "all"
export type StateFilter = MemoryState | "all"
export interface LibraryState {
  readonly category: CategoryFilter
  readonly state: StateFilter
  readonly query: string
  readonly page: number
  readonly selectedId: string | null
}

export const initialLibraryState: LibraryState = {
  category: "all",
  state: "all",
  query: "",
  page: 0,
  selectedId: null,
}
export const pageSize = 6

export type LibraryAction =
  | { type: "category"; value: CategoryFilter }
  | { type: "state"; value: StateFilter }
  | { type: "query"; value: string }
  | { type: "page"; value: number }
  | { type: "select"; id: string }
  | { type: "navigate"; id: string; index: number }
  | { type: "reset" }

export function libraryReducer(
  state: LibraryState,
  action: LibraryAction
): LibraryState {
  switch (action.type) {
    case "category":
      return { ...state, category: action.value, page: 0, selectedId: null }
    case "state":
      return { ...state, state: action.value, page: 0, selectedId: null }
    case "query":
      return { ...state, query: action.value, page: 0, selectedId: null }
    case "page":
      return {
        ...state,
        page: Number.isFinite(action.value)
          ? Math.max(0, Math.trunc(action.value))
          : 0,
        selectedId: null,
      }
    case "select":
      return { ...state, selectedId: action.id }
    case "navigate":
      return {
        ...initialLibraryState,
        page: Math.max(0, Math.floor(action.index / pageSize)),
        selectedId: action.id,
      }
    case "reset":
      return initialLibraryState
  }
}

/** Derive a consistent page and selection without mutating source data. */
export function selectLibrary(
  records: readonly MemoryRecord[],
  state: LibraryState
) {
  const orderedRecords = records.toSorted(
    (left, right) =>
      Date.parse(right.updatedAt) - Date.parse(left.updatedAt) ||
      left.id.localeCompare(right.id)
  )
  const query = state.query.trim().toLowerCase()
  const filtered = orderedRecords.filter(
    (record) =>
      (state.category === "all" || record.category === state.category) &&
      (state.state === "all" || record.state === state.state) &&
      [
        record.title,
        record.text,
        record.subject,
        record.session,
        ...record.tags,
      ]
        .join(" ")
        .toLowerCase()
        .includes(query)
  )
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize))
  const currentPage = Math.max(0, Math.min(state.page, pageCount - 1))
  const pageRecords = filtered.slice(
    currentPage * pageSize,
    (currentPage + 1) * pageSize
  )
  const selected =
    pageRecords.find((record) => record.id === state.selectedId) ??
    pageRecords[0] ??
    null
  const categoryCounts: Record<MemoryCategory, number> = {
    fact: 0,
    scene: 0,
    detail: 0,
    impression: 0,
    persona: 0,
    example: 0,
    media: 0,
    secret: 0,
    designated: 0,
  }
  let active = 0
  let versionCount = 0
  for (const record of records) {
    categoryCounts[record.category] += 1
    if (record.state === "active") active += 1
    versionCount += record.versions.length
  }
  return {
    orderedRecords,
    pageRecords,
    selected,
    currentPage,
    pageCount,
    resultCount: filtered.length,
    hasFilters:
      state.category !== "all" || state.state !== "all" || query !== "",
    categoryCounts,
    stats: {
      total: records.length,
      active,
      forgotten: records.filter((record) => record.state === "forgotten")
        .length,
      versionCount,
    },
  }
}
