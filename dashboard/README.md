# SeekMemory dashboard

React, TypeScript, Vite, Tailwind CSS and shadcn/ui (Base UI / Nova).
The standalone mock workspace supports layout development without running AstrBot,
Python, a database, or a model provider. Real memory APIs are not connected yet.

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

Use the toolbar at the top to switch scenarios and themes. In the error scenario,
the retry button returns to normal data. Resize the browser to inspect responsive
layouts; below 1280 CSS pixels, select a memory to open its detail drawer.

`pnpm dev:host` starts without mocks and currently shows the API integration
placeholder. Mock code is loaded only when both `import.meta.env.DEV` is true
and the Vite mode is `mock`; production builds exclude the fixture JavaScript.
Even `vite build --mode mock` does not enable demo data.

## Validation and packaging

Type checking uses TypeScript 7.0.2. App, build, and test configurations inherit
strict settings from `tsconfig.base.json`, including unchecked indexed access
and exact optional properties. Oxlint replaces ESLint and runs type-aware rules
through `oxlint-tsgolint`. Explicit `any`, unsafe use of propagated `any`, unsafe
type assertions, non-null assertions, and unhandled promises are errors.
Warnings also fail the lint command. Third-party declarations are not linted.

```bash
pnpm typecheck
pnpm lint
pnpm test
pnpm check
pnpm build
```

The build replaces `../views/memory/` with generated assets. AstrBot discovers
`views/memory/index.html` after the plugin is reloaded. Release packages must
include these generated files; users should not need Node.js to use the plugin.

Assets use relative URLs. AstrBot injects its plugin view SDK, which sets
`html[data-theme]`; the stylesheet follows that attribute without browser storage.
Future API calls should use `window.AstrBotPluginView` and plugin routes registered
through `Context.register_web_api`.

Tests run with Node's built-in TypeScript support and test runner. They cover
schema failures, immutable inputs, combined filters, page resets, empty and
shrinking datasets, cross-page navigation, and deterministic ordering.

## Architecture and component replacement

The memory feature uses a small MVVM-style split:

```text
src/dev/                         Development source and preview controls
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
mock source uses this same boundary. The future AstrBot source should adapt the
wire format here, without adding demo fallbacks to the real client.

Pure models and state do not import React or access browser globals. React hooks
own application state and derived data; views own presentation concerns such as
the mobile drawer. The UI adapter cannot import memory features or mock data.
Oxlint enforces these directions and blocks direct vendor imports from views.
Models and hooks have no dependency on shadcn, Base UI, CSS, or Lucide.

To replace the component library:

1. Reimplement `src/ui/index.tsx` against the new library, preserving its own
   React/DOM contracts. Compound controls expose `DetailDrawer` and `Tabs` rather
   than exporting Base UI's composition API or vendor prop types.
2. Update `src/ui/styles.css`, retaining the semantic tokens used by the views
   and the host's `html[data-theme]` behavior. Remove `src/ui/shadcn/`,
   `components.json`, and unused vendor dependencies when no longer needed.
3. Run `pnpm check`, `pnpm build`, and the mock preview. Check keyboard focus,
   drawer dismissal, tab selection, themes, and narrow layouts with the new library.

The model, reducer, and hooks require no changes for a component-library swap.
Views still intentionally use React, Tailwind layout utilities, and Lucide icons.
Replacing those technologies involves their presentation files too; the UI
adapter is not a promise of framework-independent rendering. There is no
repository/DI framework while only one development source exists.

Authentication, bridge behavior, and real memory operations still require
integration testing inside AstrBot.

## Components

```bash
pnpm exec shadcn add button
```

Generated components live in `src/ui/shadcn`. Add components as needed and expose
application-owned contracts through `src/ui/index.tsx`; feature views import only
`@/ui`. Keep vendor-specific selectors and styling in the adapter.
See the [AstrBot plugin view guide](https://docs.astrbot.app/dev/star/guides/plugin-pages.html)
and [shadcn/ui documentation](https://ui.shadcn.com/docs/installation/vite).
