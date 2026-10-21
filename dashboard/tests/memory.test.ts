import assert from "node:assert/strict"
import test from "node:test"
import { mockMemories } from "../src/dev/mock-data.ts"
import {
  memoryCategories,
  memoryCollectionSchema,
  memoryRecordSchema,
} from "../src/features/memory/model.ts"
import {
  initialLibraryState,
  libraryReducer,
  selectLibrary,
} from "../src/features/memory/library-state.ts"

const records = memoryCollectionSchema.parse(mockMemories)
const first = records[0]
assert.ok(first)

await test("fixtures satisfy the same immutable data contract as an external source", () => {
  assert.equal(records.length, 12)
  assert.ok(Object.isFrozen(records))
  assert.ok(Object.isFrozen(first))
  assert.ok(Object.isFrozen(first.versions))
  assert.ok(Object.isFrozen(first.versions[0]))
})

await test("unknown inputs must pass structural and scalar validation", () => {
  const invalidInputs: unknown[] = [
    null,
    { ...first, confidence: 2 },
    { ...first, confidence: "0.9" },
    { ...first, hits: -1 },
    { ...first, category: "unsupported" },
    { ...first, updatedAt: "not-a-date" },
    { ...first, versions: [] },
    { ...first, unexpected: true },
  ]
  for (const input of invalidInputs)
    assert.equal(memoryRecordSchema.safeParse(input).success, false)
})

await test("version history cannot disagree with the current content or revision order", () => {
  assert.equal(
    memoryRecordSchema.safeParse({
      ...first,
      text: "Changed without a revision",
    }).success,
    false
  )
  assert.equal(
    memoryRecordSchema.safeParse({
      ...first,
      versions: [first.versions[0], first.versions[0]],
    }).success,
    false
  )
  assert.equal(
    memoryRecordSchema.safeParse({
      ...first,
      versions: [
        first.versions[0],
        { ...first.versions[0], revision: first.versions[0].revision + 1 },
      ],
    }).success,
    false
  )
})

await test("duplicate memory identities are rejected at the collection boundary", () => {
  assert.equal(memoryCollectionSchema.safeParse([first, first]).success, false)
})

await test("category, state, and search filters compose instead of replacing one another", () => {
  const result = selectLibrary(records, {
    ...initialLibraryState,
    category: "fact",
    state: "forgotten",
    query: "  小夏  ",
  })
  assert.equal(result.resultCount, 1)
  assert.equal(result.selected?.id, "mock_memory_011")
  assert.equal(result.stats.total, 12)
  assert.equal(result.stats.active, 10)
  assert.equal(result.stats.forgotten, 2)
  assert.equal(result.stats.versionCount, 17)
  assert.equal(result.categoryCounts.fact, 4)
})

await test("search includes tags and sessions, with case and whitespace normalization", () => {
  assert.equal(
    selectLibrary(records, {
      ...initialLibraryState,
      query: "  DEMO:FRIENDMESSAGE:10003 ",
    }).resultCount,
    2
  )
  assert.equal(
    selectLibrary(records, { ...initialLibraryState, query: "共同经历" })
      .resultCount,
    1
  )
  assert.equal(
    selectLibrary(records, { ...initialLibraryState, query: "   " }).hasFilters,
    false
  )
})

await test("changing a filter resets pagination and selection while retaining other filters", () => {
  const dirty = {
    ...initialLibraryState,
    query: "coffee",
    page: 1,
    selectedId: first.id,
  }
  for (const next of [
    libraryReducer(dirty, { type: "query", value: "new" }),
    libraryReducer(dirty, { type: "category", value: "scene" }),
    libraryReducer(dirty, { type: "state", value: "forgotten" }),
  ]) {
    assert.equal(next.page, 0)
    assert.equal(next.selectedId, null)
  }
  assert.equal(
    libraryReducer(dirty, { type: "category", value: "scene" }).query,
    "coffee"
  )
  assert.deepEqual(
    libraryReducer(dirty, { type: "reset" }),
    initialLibraryState
  )
})

await test("empty results and a shrinking source never leave a stale page or detail selection", () => {
  const state = { ...initialLibraryState, page: 8, selectedId: "removed-id" }
  const empty = selectLibrary([], state)
  assert.equal(empty.currentPage, 0)
  assert.equal(empty.pageCount, 1)
  assert.equal(empty.selected, null)
  const reduced = selectLibrary([first], state)
  assert.equal(reduced.currentPage, 0)
  assert.equal(reduced.selected?.id, first.id)
  const noMatch = selectLibrary(records, { ...state, query: "no-such-memory" })
  assert.equal(noMatch.resultCount, 0)
  assert.equal(noMatch.selected, null)
})

await test("navigation clears filters and reveals a related record on its actual page", () => {
  const ordered = selectLibrary(records, initialLibraryState).orderedRecords
  const index = ordered.findIndex((record) => record.id === "mock_memory_008")
  assert.ok(index >= 6)
  const state = libraryReducer(
    {
      ...initialLibraryState,
      category: "fact",
      state: "forgotten",
      query: "unrelated",
    },
    { type: "navigate", id: "mock_memory_008", index }
  )
  const result = selectLibrary(records, state)
  assert.equal(result.currentPage, 1)
  assert.equal(result.selected?.id, "mock_memory_008")
  assert.equal(result.hasFilters, false)
})

await test("page selection is local to the current page and invalid page input is normalized", () => {
  const result = selectLibrary(records, {
    ...initialLibraryState,
    page: 1,
    selectedId: first.id,
  })
  assert.equal(result.selected?.id, "mock_memory_007")
  for (const value of [-1, Number.NaN, Number.POSITIVE_INFINITY]) {
    assert.equal(
      libraryReducer(initialLibraryState, { type: "page", value }).page,
      0
    )
  }
  const selected = libraryReducer(initialLibraryState, {
    type: "select",
    id: first.id,
  })
  assert.equal(selected.selectedId, first.id)
})

await test("recent-first ordering is deterministic and never mutates the source", () => {
  const reversed = records.toReversed()
  const originalIds = reversed.map((record) => record.id)
  const result = selectLibrary(reversed, initialLibraryState)
  assert.equal(result.selected?.id, first.id)
  assert.deepEqual(
    reversed.map((record) => record.id),
    originalIds
  )
})

await test("all nine category entries filter only their own family or memory level", () => {
  const matrix = memoryCollectionSchema.parse(
    memoryCategories.map((category) => ({ ...first, id: category, category }))
  )
  for (const category of memoryCategories) {
    const result = selectLibrary(matrix, { ...initialLibraryState, category })
    assert.equal(result.resultCount, 1)
    assert.equal(result.selected?.category, category)
    assert.equal(result.categoryCounts[category], 1)
  }
})
