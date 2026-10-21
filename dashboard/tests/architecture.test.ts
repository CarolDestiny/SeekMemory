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
    name: "架构与可读性规则拒绝跨层依赖和嵌套三元表达式",
    rejected: true,
    files: {
      "features/control/nested.ts":
        'export const label = (a: boolean, b: boolean) => a ? "a" : b ? "b" : "c"',
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
    name: "架构与可读性规则允许依赖注入、公共组件适配和顺序分支",
    rejected: false,
    files: {
      "features/control/flat.ts":
        'export function label(a: boolean, b: boolean) { if (a) return "a"; if (b) return "b"; return "c" }',
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
      // 导入边界测试样例无需类型服务或已安装的运行时依赖。
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
                  item.code === "eslint(no-restricted-globals)" ||
                  item.code === "eslint(no-nested-ternary)")
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
