# SeekMemory dashboard

React, TypeScript, Vite, Tailwind CSS and shadcn/ui (Base UI / Nova).
This scaffold currently shows a setup placeholder; memory APIs are not connected.

## Development

The local setup was verified with Node.js 26.7 and pnpm 10.13. From this directory:

```bash
pnpm install --frozen-lockfile
pnpm dev
```

The development server binds to `http://127.0.0.1:5176`. Standalone development
does not connect to AstrBot or change memory data.

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

## Components

```bash
pnpm exec shadcn add button
```

Generated components live in `src/components/ui`. Add components as needed.
See the [AstrBot plugin view guide](https://docs.astrbot.app/dev/star/guides/plugin-pages.html)
and [shadcn/ui documentation](https://ui.shadcn.com/docs/installation/vite).
