import { useReducer } from "react"
import type { MemoryRecord, MemorySource } from "./model.ts"
import {
  initialLibraryState,
  libraryReducer,
  selectLibrary,
  type CategoryFilter,
  type StateFilter,
} from "./library-state.ts"

export function useMemoryLibrary(source: MemorySource) {
  const [filters, dispatch] = useReducer(libraryReducer, initialLibraryState)
  const records: readonly MemoryRecord[] =
    source.status === "ready" ? source.records : []
  const selection = selectLibrary(records, filters)

  return {
    ...selection,
    filters,
    source,
    setCategory: (value: CategoryFilter) =>
      dispatch({ type: "category", value }),
    setState: (value: StateFilter) => dispatch({ type: "state", value }),
    setQuery: (value: string) => dispatch({ type: "query", value }),
    setPage: (value: number) => dispatch({ type: "page", value }),
    resetFilters: () => dispatch({ type: "reset" }),
    selectMemory: (id: string) => {
      if (selection.pageRecords.some((record) => record.id === id))
        dispatch({ type: "select", id })
    },
    navigateToMemory: (id: string) => {
      const index = selection.orderedRecords.findIndex(
        (record) => record.id === id
      )
      if (index >= 0) dispatch({ type: "navigate", id, index })
    },
  }
}

export type MemoryLibraryViewModel = ReturnType<typeof useMemoryLibrary>
