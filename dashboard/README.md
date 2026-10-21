# SeekMemory dashboard

React, TypeScript, Vite, Tailwind CSS and shadcn/ui (Base UI / Nova).
The standalone mock workspace supports layout development without running AstrBot,
Python, a database, or a model provider. Production uses AstrBot's authenticated
Plugin Page bridge against the live memory engine.

## Development

The local setup was verified with Node.js 26.7 and pnpm 10.13. From this directory:

```bash
pnpm install --frozen-lockfile
pnpm dev
```

The development server binds to `http://127.0.0.1:5176`. `pnpm dev` and
`pnpm dev:mock` both enable mock mode. All names, sessions, and memories are fictional.
The preview does not connect to AstrBot, read its configuration, or change memory data.
It has no persistence; reloading restores the initial preview.

The preview includes:

- Search by content, tag, subject, or session; category and state filters; pagination.
- Memory details, version selection with previous-version content comparison,
  and navigation between related records.
- Desktop detail panels and a narrow-screen detail drawer.
- Light and dark themes, plus normal, loading, empty, error, and long-content scenarios.
- All six artifact families, scope/session filters, JSON revision editing,
  runtime checks, task confirmations, recall diagnostics and lifecycle logs.
  Mock mutations reset on reload; mock diagnostics use simplified text matching.

Use the toolbar at the top to switch scenarios and themes. In the error scenario,
the retry button returns to normal data. Resize the browser to inspect responsive
layouts; below 1280 CSS pixels, select a memory to open its detail drawer.

`pnpm dev:host` starts without mocks and requires the host bridge; opening it
directly shows a connection error. Mock code is loaded only when both `import.meta.env.DEV` is true
and the Vite mode is `mock`; production builds exclude the fixture JavaScript.
Even `vite build --mode mock` does not enable demo data.

## Validation and packaging

Type checking uses TypeScript 7.0.2. App, build, and test configurations inherit
strict settings from `tsconfig.base.json`, including unchecked indexed access
and exact optional properties. Oxlint replaces ESLint and runs type-aware rules
through `oxlint-tsgolint`. Explicit `any`, unsafe use of propagated `any`, unsafe
type assertions, non-null assertions, and unhandled promises are errors.
Warnings also fail the lint command. Third-party declarations are not linted.

Oxfmt handles formatting through `.oxfmtrc.json`, including Tailwind class sorting
in JSX and `cn`/`cva` calls. It preserves double quotes, no semicolons, and LF
line endings. Prettier and its Tailwind plugin are no longer required.
Use `pnpm format` to apply formatting; `pnpm check` includes a formatting check.

```bash
pnpm typecheck
pnpm lint
pnpm test
pnpm format:check
pnpm check
pnpm build
```

The build replaces `../pages/memory/` with generated assets. AstrBot discovers
`pages/memory/index.html` after the plugin is reloaded. Release packages must
include these generated files; users should not need Node.js to use the plugin.

From the plugin root, `python scripts/package_plugin.py` packages the prebuilt
view and tracked backend runtime into `dist/astrbot_plugin_seekmemory.zip` with
`dist/SHA256SUMS`. The build emits JavaScript dependency licenses as `LICENSES.md`
and CSS/font notices as `ASSET-LICENSES.txt`.
Missing assets, source maps, mock bundles, and mismatched release tags fail packaging.
`pages/memory/` and `dist/` remain ignored; source downloads contain source only.
See [release instructions](../CONTRIBUTING.md#release-packaging) for CI and publishing.

Assets use relative URLs. AstrBot injects its plugin view SDK, which sets
`html[data-theme]`; the stylesheet follows that attribute without browser storage.
The production client uses `window.AstrBotPluginPage` and plugin routes registered
through `Context.register_web_api`. Calls return unknown input validated by Zod.
No host cookies, local storage, or direct parent-window access is required.

Tests run with Node's built-in TypeScript support and test runner. They cover
schema failures, immutable inputs, combined filters, page resets, empty and
shrinking datasets, cross-page navigation, deterministic ordering, administrative
commands, runtime/detail schemas, legacy/structured logs, all nine category filters
and the host bridge boundary. React hook tests
use Happy DOM with an injected client, without rendering component-library code.
They verify workspace filters, post-write refresh races, confirmed task identity,
duplicate-submit prevention, and invalidation of reads from a replaced client.
Architecture fixtures run the real Oxlint import rules against both forbidden
and permitted dependency directions; these checks run in `pnpm check` and CI.

## Architecture and component replacement

The memory feature uses a small MVVM-style split:

```text
src/dev/                         Development source and preview controls
src/infrastructure/astrbot-client.ts  Host Page bridge and response validation
src/features/control/
  model.ts                       Management port and Zod wire contracts
  use-control.ts                 Scope/session filters, task commands and refresh lifecycle
  use-editor.ts                  Drafts, revisions, confirmation and conflict errors
  use-diagnostics.ts             Read-only diagnostic action state
  use-logs.ts                     Combined log filters and searchable business metadata
  views/                         Workspace, runtime, editor, diagnostics and logs
src/features/memory/
  model.ts                       Zod schemas, inferred types, loading state
  library-state.ts               Pure reducer and derived selection/statistics
  use-memory-library.ts          React binding and user actions
  use-memory-detail.ts           Version selection and resolved relationships
  views/                        Layout, labels, icons, responsive behavior
src/ui/
  index.tsx                     Application-owned UI contracts and adapters
  styles.css                    Theme tokens and component-vendor CSS
  shadcn/                       Generated component implementation
```

Data sources validate unknown input with `memoryCollectionSchema` before passing
a `MemorySource` to the workspace. Types are inferred from the Zod schemas;
there is no separate interface to keep in sync. Ready, loading, and error sources
are a discriminated union; empty results are a valid ready source. The current
mock source uses this same boundary. `ManagementClient` is implemented by the
host adapter and the development mock; hooks receive it explicitly and do not
choose transport or fixture implementations.

Pure models and state do not import React or access browser globals. React hooks
own application state and derived data; views own presentation concerns such as
the mobile drawer. The UI adapter cannot import memory features or mock data.
Oxlint enforces these directions and blocks direct vendor imports from views.
Models and hooks have no dependency on shadcn, Base UI, CSS, or Lucide.
Hooks and views cannot import the concrete host client or mock implementation;
transport adapters depend on contracts rather than hooks. These are direct-import
checks, not a complete transitive dependency analysis.

Workspace scope/session selection, task confirmation and dispatch belong to
`use-control.ts`. The selected workspace tab, editor visibility and responsive
drawer remain view state. Ordinary refreshes share an in-flight request; refreshes
after a write supersede it so older responses cannot overwrite the saved result.
Task cancellation retains the ID shown when confirmation began, even if polling
discovers a different active task before confirmation completes.

To replace the component library:

1. Reimplement `src/ui/index.tsx` against the new library, preserving its own
   React/DOM contracts. Compound controls expose `DetailDrawer` and `Tabs` rather
   than exporting Base UI's composition API or vendor prop types.
2. Update `src/ui/styles.css`, retaining the semantic tokens used by the views
   and the host's `html[data-theme]` behavior. Remove `src/ui/shadcn/`,
   `components.json`, and unused vendor dependencies when no longer needed.
   Update the CSS/font license entries in `vite.config.ts` to match dependencies.
3. Run `pnpm check`, `pnpm build`, and the mock preview. Check keyboard focus,
   drawer dismissal, tab selection, themes, and narrow layouts with the new library.

The model, reducer, and hooks require no changes for a component-library swap.
Views still intentionally use React, Tailwind layout utilities, and Lucide icons.
Replacing those technologies involves their presentation files too; the UI
adapter is not a promise of framework-independent rendering. A small injected
port is sufficient; no repository or dependency-injection framework is needed.

`tests/test_webui_host.py` validates real AstrBot request/auth context, page
discovery and lifecycle ownership without starting bots. It skips when a compatible
host is unavailable; build first to include page discovery. Live deployment and
real model quality remain separate from the mock browser checks.

## Components

```bash
pnpm exec shadcn add button
```

Generated components live in `src/ui/shadcn`. Add components as needed and expose
application-owned contracts through `src/ui/index.tsx`; feature views import only
`@/ui`. Keep vendor-specific selectors and styling in the adapter.
See the [AstrBot plugin view guide](https://docs.astrbot.app/dev/star/guides/plugin-pages.html)
and [shadcn/ui documentation](https://ui.shadcn.com/docs/installation/vite).

## Business logging integration

Backend `Journal.record()` captures the real caller's module, relative file,
function and line. `Journal.span()` wraps business stages, measures duration and
records exception frame locations without exception messages or local variables.
The task runner supplies a ContextVar correlation ID; individual stage success
cannot mark a whole task complete during restart recovery. Extraction receives a
context-manager callback, keeping the domain independent of the log transport.

```python
with journal.span("weekly", "merge", threshold=0.6) as metrics:
    metrics["merged"] = merge_similar(db, cache, threshold=0.6)
```

Only pass explicit safe IDs and counters in context. This is not automatic tracing
of every function or a capture of all AstrBot logs. The viewer separates severity,
lifecycle status, business stage, call site, context and exception frames; filtering
belongs to `use-logs.ts`. Old events remain readable without fabricated call sites.
