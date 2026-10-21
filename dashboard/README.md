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

```bash
pnpm typecheck
pnpm lint
pnpm build
```

The build replaces `../views/memory/` with generated assets. AstrBot discovers
`views/memory/index.html` after the plugin is reloaded. Release packages must
include these generated files; users should not need Node.js to use the plugin.

Assets use relative URLs. AstrBot injects its plugin view SDK, which sets
`html[data-theme]`; the stylesheet follows that attribute without browser storage.
Future API calls should use `window.AstrBotPluginView` and plugin routes registered
through `Context.register_web_api`.

The presentational components in `src/components/memory-library.tsx` and
`src/components/memory-detail.tsx` receive a view model from `src/lib/memory.ts`.
Development fixtures and preview controls live separately in `src/dev/`.
When the API is implemented, adapt its responses to this model instead of
embedding demo-data fallbacks in the production client. Authentication and
real memory operations still require integration testing inside AstrBot.

## Components

```bash
pnpm exec shadcn add button
```

Generated components live in `src/components/ui`. Add components as needed.
See the [AstrBot plugin view guide](https://docs.astrbot.app/dev/star/guides/plugin-pages.html)
and [shadcn/ui documentation](https://ui.shadcn.com/docs/installation/vite).
