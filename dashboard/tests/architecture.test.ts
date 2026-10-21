import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs"
import { tmpdir } from "node:os"
import { dirname, join, resolve } from "node:path"
import { test } from "node:test"
import { z } from "zod"

const scenarios = [
  {
    name: "architecture rules reject imports across model, VM, view, UI and transport boundaries",
    rejected: true,
    files: {
      "features/control/model.ts": 'export { useState } from "react"',
      "features/control/use-probe.ts":
        'export { astrbotClient } from "@/infrastructure/astrbot-client"',
      "features/control/views/transport.ts":
        'export { astrbotClient } from "../../../infrastructure/astrbot-client"',
      "features/control/views/vendor.ts":
        'export { Button } from "@/ui/shadcn/button"',
      "features/control/views/network.ts":
        'export const request = fetch("/api")',
      "ui/probe.ts":
        'export { useControl } from "@/features/control/use-control"',
      "infrastructure/probe.ts":
        'export { useControl } from "../features/control/use-control"',
    },
  },
  {
    name: "architecture rules allow injected ports and the public UI adapter",
    rejected: false,
    files: {
      "features/control/use-probe.ts":
        'export type { ManagementClient } from "./model"',
      "features/control/views/probe.ts": 'export { Button } from "@/ui"',
      "infrastructure/probe.ts":
        'export type { ManagementClient } from "../features/control/model"',
      "ui/probe.ts": 'export { Button } from "./shadcn/button"',
    },
  },
] as const

for (const scenario of scenarios) {
  void test(scenario.name, () => {
    const root = mkdtempSync(join(tmpdir(), "seekmemory-architecture-"))
    try {
      // Import-boundary fixtures need no type service or installed runtime imports.
      const config = readFileSync(
        new URL("../.oxlintrc.json", import.meta.url),
        "utf8"
      ).replace(/("typeAware"\s*:\s*)true/, "$1false")
      writeFileSync(join(root, ".oxlintrc.json"), config)
      for (const [file, content] of Object.entries(scenario.files)) {
        const target = join(root, "src", file)
        mkdirSync(dirname(target), { recursive: true })
        writeFileSync(target, content)
      }
      const result = spawnSync(
        process.execPath,
        [resolve("node_modules/oxlint/bin/oxlint"), "src", "--format=json"],
        {
          cwd: root,
          encoding: "utf8",
        }
      )
      assert.equal(
        result.status,
        scenario.rejected ? 1 : 0,
        result.stdout + result.stderr
      )
      const report = z
        .object({
          diagnostics: z.array(
            z.object({ filename: z.string(), code: z.string() })
          ),
        })
        .parse(JSON.parse(result.stdout))
      if (scenario.rejected) {
        for (const file of Object.keys(scenario.files))
          assert.ok(
            report.diagnostics.some(
              (item) =>
                item.filename.replaceAll("\\", "/") === `src/${file}` &&
                (item.code === "eslint(no-restricted-imports)" ||
                  item.code === "eslint(no-restricted-globals)")
            ),
            file
          )
      } else assert.deepEqual(report.diagnostics, [])
    } finally {
      assert.equal(dirname(realpathSync(root)), realpathSync(tmpdir()))
      rmSync(root, { recursive: true, force: true })
    }
  })
}
