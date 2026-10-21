# SeekMemory 管理界面

使用 React、TypeScript、Vite、Tailwind CSS 和 shadcn/ui（Base UI / Nova）。
独立 Mock 工作台支持在不启动 AstrBot、Python、数据库或模型服务的情况下开发排版。
生产环境通过 AstrBot 已认证的插件视图桥接器访问运行中的记忆引擎。

## 本地开发

本地环境已使用 Node.js 26.7 和 pnpm 10.13 验证。在本目录执行：

```bash
pnpm install --frozen-lockfile
pnpm dev
```

开发服务器监听 `http://127.0.0.1:5176`。`pnpm dev` 和 `pnpm dev:mock` 都启用 Mock 模式。
所有人物、会话和记忆均为虚构数据；预览不会连接 AstrBot、读取其配置或修改真实记忆。
Mock 数据只保存在内存中，刷新页面后恢复初始状态。

预览覆盖：

- 按内容、标签、相关对象和会话搜索，类型与状态筛选，以及分页。
- 记忆详情、历史版本选择、与上一版本的内容对比、关联记忆跳转。
- 桌面详情面板和窄屏详情抽屉。
- 深浅主题，以及正常、加载中、空数据、错误和长内容场景。
- 全部六个 Artifact 家族、scope/会话筛选、JSON 修订、运行检测、任务确认、召回诊断和生命周期日志。
  Mock 修改在刷新后重置；Mock 诊断仅使用简化的文本匹配。

顶部工具栏可切换场景和主题。错误场景中的重试按钮会恢复正常数据。
调整浏览器宽度可检查响应式布局；低于 1280 CSS 像素时，选择记忆会打开详情抽屉。

`pnpm dev:host` 不加载 Mock，需要宿主桥接器；直接打开会显示连接错误。
只有 `import.meta.env.DEV` 为真且 Vite 模式为 `mock` 时才加载 Mock 代码。
生产构建排除示例 JavaScript，即使运行 `vite build --mode mock` 也不会启用示例数据。

## 检查与打包

类型检查使用 TypeScript 7.0.2。应用、构建和测试配置继承 `tsconfig.base.json` 的严格设置，
包括索引访问检查和精确可选属性。Oxlint 替代 ESLint，通过 `oxlint-tsgolint` 执行类型感知规则。
显式 `any`、传播而来的 `any` 的不安全使用、不安全类型断言、非空断言和未处理的 Promise 均视为错误。
警告也会导致检查失败；不对第三方类型声明执行 lint。
启用类型感知的 `typescript/no-deprecated`，使用依赖声明中标记弃用的 API 会导致检查失败。
需要保留头部扩展字段时使用 Zod 4 的 `z.looseObject()`。
`no-nested-ternary` 禁止嵌套三元表达式；多状态页面使用独立条件块，有限值到文案/颜色使用映射。
请求、结果校验与状态更新按步骤展开；筛选先排除不匹配项，再处理搜索文本。
保留简单的单层条件表达式，不为消除几行代码而增加小函数。

Oxfmt 使用 `.oxfmtrc.json` 格式化代码，并对 JSX 及 `cn`/`cva` 中的 Tailwind 类名排序。
保持双引号、无分号和 LF 换行；不再需要 Prettier 及其 Tailwind 插件。
`pnpm format` 应用格式化，`pnpm check` 包含格式检查。

```bash
pnpm typecheck
pnpm lint
pnpm test
pnpm format:check
pnpm check
pnpm build
```

构建会用生成资源替换 `../pages/memory/`。插件重载后，AstrBot 发现 `pages/memory/index.html`。
Release 安装包必须包含这些生成文件，使用者无需安装 Node.js。

在插件根目录运行 `python scripts/package_plugin.py`，将已构建视图和 Git 跟踪的后端运行文件
打包为 `dist/astrbot_plugin_seekmemory.zip`，并生成 `dist/SHA256SUMS`。
构建会输出 JavaScript 依赖许可证 `LICENSES.md` 和 CSS/字体声明 `ASSET-LICENSES.txt`。
资源缺失、源码映射、Mock 代码混入或发布标签不匹配都会导致打包失败。
`pages/memory/` 与 `dist/` 保持 Git 忽略；源码下载仅包含源码。
CI 与发布步骤见[发布说明](../CONTRIBUTING.md#release-packaging)。

资源使用相对 URL。AstrBot 注入插件视图 SDK 并设置 `html[data-theme]`，样式跟随该属性，无需浏览器存储。
生产客户端使用 `window.AstrBotPluginPage` 和 `Context.register_web_api` 注册的插件路由。
调用结果按未知输入处理，再由 Zod 校验；无需访问宿主 Cookie、本地存储或父窗口。

测试使用 Node 内置的 TypeScript 支持和测试运行器，覆盖契约失败、输入不可变性、组合筛选、
分页重置、空数据与数据缩减、跨页跳转、稳定排序、管理命令、运行/详情契约、新旧日志、九种类型和宿主桥接边界。
React hook 测试使用 Happy DOM 和注入的客户端，无需渲染组件库代码，验证工作台筛选、写入后刷新竞态、
确认的目标任务身份、重复提交拦截和客户端替换后旧请求失效。
架构测试使用真实 Oxlint 导入规则验证允许与禁止的依赖方向，纳入 `pnpm check` 和 CI。

## 架构与组件替换

记忆功能采用轻量 MVVM 分层：

```text
src/dev/                         开发数据源与预览控制
src/infrastructure/astrbot-client.ts  宿主视图桥接与响应校验
src/features/control/
  model.ts                       管理接口与 Zod 传输契约
  use-control.ts                 scope/会话筛选、任务命令与刷新生命周期
  use-editor.ts                  草稿、修订、确认与冲突错误
  use-diagnostics.ts             只读诊断的操作状态
  use-logs.ts                    日志组合筛选与业务字段搜索
  views/                         工作台、运行检测、编辑、诊断与日志视图
src/features/memory/
  model.ts                       Zod 契约、推导类型与加载状态
  library-state.ts               纯 reducer、选中项与统计派生
  use-memory-library.ts          React 绑定与用户操作
  use-memory-detail.ts           版本选择与关联解析
  views/                         布局、文案、图标与响应式行为
src/ui/
  index.tsx                      应用自有的 UI 契约与适配器
  styles.css                     主题变量与组件库样式
  shadcn/                        生成的组件实现
```

数据源先用 `memoryCollectionSchema` 校验未知输入，再将 `MemorySource` 传给工作台。
领域类型由 Zod 推导，并通过 `satisfies` 与 OpenAPI 生成的传输类型关联。就绪、加载中和错误来源构成可辨识联合类型，
空结果是合法的就绪状态。Mock 数据源使用同一边界。
宿主适配器和开发 Mock 都实现 `ManagementClient`；hook 显式接收客户端，不选择传输方式或示例实现。

纯模型和状态不导入 React，也不访问浏览器全局对象。React hook 管理应用状态及派生数据，
视图负责手机抽屉等呈现状态。UI 适配器不能导入记忆功能或 Mock 数据。
Oxlint 约束上述方向，并阻止视图直接导入组件库。模型和 hook 不依赖 shadcn、Base UI、CSS 或 Lucide。
hook 和视图不能导入具体宿主客户端或 Mock 实现；传输适配器依赖契约而非 hook。
这些规则检查直接导入关系，不是完整的传递依赖分析。

工作台 scope/会话选择、任务确认与派发属于 `use-control.ts`。
当前页签、编辑器显隐和响应式抽屉保留为视图状态。
普通刷新复用进行中的请求；写入后刷新会取代旧请求，防止旧响应覆盖保存结果。
取消任务保留开始确认时显示的任务 ID，即使轮询期间活动任务发生变化，也不会误取消新任务。

替换组件库的步骤：

1. 基于新组件库重写 `src/ui/index.tsx`，保留应用自有的 React/DOM 契约。
   组合控件暴露 `DetailDrawer` 和 `Tabs`，不向业务层导出 Base UI 的组合 API 或属性类型。
2. 更新 `src/ui/styles.css`，保留视图使用的语义变量及宿主 `html[data-theme]` 行为。
   不再使用时移除 `src/ui/shadcn/`、`components.json` 和旧组件库依赖，
   并同步 `vite.config.ts` 的 CSS/字体许可证条目。
3. 运行 `pnpm check`、`pnpm build` 和 Mock 预览，检查新组件库的键盘焦点、
   抽屉关闭、页签选择、主题和窄屏布局。

替换组件库无需修改模型、reducer 和 hook。视图仍使用 React、Tailwind 布局类和 Lucide 图标，
替换这些技术也需要修改相应视图文件；UI 适配器不提供跨框架渲染能力。
当前使用小型注入接口即可，无需仓储层或依赖注入框架。

`tests/test_webui_host.py` 不启动机器人，验证真实 AstrBot 请求/认证上下文、页面发现和生命周期资源归属。
无兼容宿主时跳过；验证页面发现前需先构建。Mock 浏览器检查不覆盖实际部署和真实模型质量。

## 组件维护

```bash
pnpm exec shadcn add button
```

生成组件位于 `src/ui/shadcn`。按需添加组件，并通过 `src/ui/index.tsx` 暴露应用自有契约；
功能视图只导入 `@/ui`。组件库专属选择器和样式保留在适配层。
参考 [AstrBot 插件视图指南](https://docs.astrbot.app/dev/star/guides/plugin-pages.html)
和 [shadcn/ui 文档](https://ui.shadcn.com/docs/installation/vite)。

## 业务日志接入

后端 `Journal.record()` 采集真实调用者的模块、相对文件、函数和行号。
`Journal.span()` 包裹业务阶段，记录耗时及异常帧位置，不采集异常消息或局部变量。
任务执行器通过 ContextVar 传递关联 ID；重启恢复时，单个阶段成功不能被当作整个任务完成。
抽取逻辑接收注入的上下文管理器回调，保持领域代码与日志传输方式独立。

```python
with journal.span("weekly", "merge", threshold=0.6) as metrics:
    metrics["merged"] = merge_similar(db, cache, threshold=0.6)
```

上下文只传入显式的安全 ID 和计数。此封装不自动跟踪每个函数，也不采集全部 AstrBot 日志。
日志视图分别呈现级别、生命周期状态、业务阶段、调用位置、上下文和异常帧；筛选逻辑属于 `use-logs.ts`。
旧事件仍可读取，缺失调用位置时不补造信息。

## 接口契约与类型生成

根目录 `openapi.yaml` 是管理 API 的唯一传输契约来源。修改接口时先更新 YAML，再执行：

```bash
pnpm generate:api
pnpm check
```

生成文件 `src/contracts/generated.ts` 提交到 Git，禁止手工修改。`check:api` 使用生成器的 `--check`
检测漂移，不会自动改写文件；已纳入 `pnpm check`。生成文件保留工具原始格式，Oxfmt 不重排它，
其类型仍受 TS 7 和 Oxlint 检查。`src/contracts/api.ts` 提供操作请求/响应别名，模型只依赖这些纯类型。
Zod 保留运行时校验、旧日志默认值及版本一致性约束；ViewModel 和 UI 不依赖生成器或 OpenAPI 工具。
成功响应直接返回数据；失败使用 `{status, message, data}`。宿主负责 HTTP 前缀、认证与 iframe 通信。
桥接适配器继续调用 `AstrBotPluginPage`，保存和取消的响应也校验返回 ID。

`openapi-typescript` 依赖 TS 5 编译器 API，无法直接使用 TS 7 的原生工具包。
因此 `tools/api-codegen` 是独立开发 workspace，固定生成器 7.13.0 和 TypeScript 5.9.3；
应用、构建和测试仍由根依赖 TypeScript 7.0.2 检查，共用一个 pnpm 锁文件。
无需降级应用，也不把生成器带入生产依赖。

独立 Mock 测试用 Ajv 按 YAML 校验所有家族、日志、诊断和修订后的数据。
实际后端响应的跨语言测试从插件根目录运行：

```bash
python -m pip install -r requirements-dev.txt
python tests/test_api_contract.py --export dashboard/node_modules/.tmp/backend-contract.json
pnpm --dir dashboard test:contract
```

Python 测试使用真实路由、内存 SQLite、管理服务和任务执行器，仅替代宿主的请求/响应传输对象。
导出的实际响应同时接受 YAML 和前端 Zod 校验，覆盖全部八个成功操作和
400/401/404/405/409/413/500/503 错误；文件缺失或覆盖不足会失败，不回退到 Mock。
安装兼容 AstrBot 后，宿主测试也会检查实际响应对象。CI 和发布构建都执行完整校验链。
业务层的 family 校验、版本冲突、状态转换、权限和副作用仍由实现测试覆盖，静态类型不能代替它们。

OpenAPI、生成源码、代码生成器、Ajv、PyYAML、jsonschema、测试及导出样本都不进入运行 ZIP；
生产仍仅包含原有后端运行文件和已构建视图，不新增 Python 运行依赖。

## 冷蓝主题与颜色维护

配色集中在 `src/ui/styles.css`，视图只使用语义变量与公共样式类，不直接写色值。
浅色主色为 `#5168A2`，辅助浅蓝为 `#EAF5FC`，背景为 `#F5F7FD`；淡粉 `#F9EAF0`
仅用于品牌标记的小圆点。深色模式单独配置海军蓝表面与较亮的蓝色交互色。

- `primary` 用于导航选中、按钮和焦点；`secondary` 用于选中列表与详情标题，`accent` 用于辅助内容。
- `workspace-intro` 统一标题背景，`surface-panel` 统一卡片圆角与阴影；`metric-feature` 强调核心统计。
- `Badge` 的 `tone="success|warning|danger|info"` 是应用自有的语义接口；颜色在 UI 适配层映射，视图只决定状态。
- 正常、警告、错误保留独立颜色和文字，不将危险状态改成品牌蓝。hover、focus 与 disabled 沿用组件行为。
- 修改主题不需要更改 model、ViewModel、API 或 Mock 业务数据；替换组件库时可保留语义 token 和 Badge 契约。

已检查浅深主题的正文、辅助文字、主按钮（含 hover）及语义徽章基础配色，对比度均不低于 4.5:1。
这只是明确颜色配对的检查，不等于整站无障碍认证；禁用、透明叠加与实际交互仍需浏览器复核。
桌面 1440px 和手机 390px 已验证导航、详情/编辑抽屉、键盘焦点、诊断及错误重试。
截图保存在独立 [预览分支](https://github.com/SXP-Simon/SeekMemory/tree/webui-previews)，不进入代码 PR 或安装包。
