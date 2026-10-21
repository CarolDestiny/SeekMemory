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
        // Vite 的许可证报告仅覆盖 JS 依赖，CSS 和字体声明需另行补充。
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
    outDir: "../pages/memory",
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
