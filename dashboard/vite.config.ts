import { resolve } from "node:path"
import { readFileSync } from "node:fs"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// https://vite.dev/config/
export default defineConfig({
  base: "./",
  plugins: [
    react(),
    tailwindcss(),
    {
      name: "asset-license-notices",
      generateBundle() {
        // Vite's license report covers JS dependencies, not CSS and font assets.
        const licenses = [
          ["@fontsource-variable/geist", "LICENSE"],
          ["tailwindcss", "LICENSE"],
          ["tw-animate-css", "LICENSE"],
          ["shadcn", "LICENSE.md"],
        ] as const
        this.emitFile({
          type: "asset",
          fileName: "ASSET-LICENSES.txt",
          source: licenses
            .map(
              ([name, file]) =>
                `${name}\n\n${readFileSync(resolve(import.meta.dirname, "node_modules", name, file), "utf8")}`
            )
            .join("\n\n"),
        })
      },
    },
  ],
  build: {
    outDir: "../views/memory",
    emptyOutDir: true,
    license: { fileName: "LICENSES.md" },
  },
  server: {
    host: "127.0.0.1",
    port: 5176,
    strictPort: true,
  },
  resolve: {
    alias: {
      "@": resolve(import.meta.dirname, "./src"),
    },
  },
})
