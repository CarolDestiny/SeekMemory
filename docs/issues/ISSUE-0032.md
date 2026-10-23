# ISSUE-0032：运行轨迹（GitHub Issue #11）

- 对应任务：https://github.com/NeverENG/SeekMemory/issues/11
- 本地编号与 GitHub 编号独立；原 ISSUE-0011 是强化计数问题，不能覆盖。
- 状态：本地实现，待 AstrBot 宿主验收和维护者评审。
- 分支：`feat/issue-0011-agent-trace`，基于 PR #40 合并后的 `a16e950`。

## 问题与范围

管理员目前难以还原一次 Agent 运行中，记忆是否被检索、隐藏或注入，以及模型、工具和发送分别走到了哪一步。
新增有界 JSONL 轨迹、管理员查询接口、Run Trace 列表与时间轴，并复用 Artifact 详情抽屉。
不增加模型调用、聊天调试命令或数据库迁移，不改变召回、披露与工具许可策略。

## 验收口径

- 记录 agent_begin / llm_request / llm_response / agent_done，以及 message_sent 和工具开始/返回。
- 每个事件有随机 run_id、递增 sequence 和请求轮次；并发消息不串线。
- 请求只记录模式、候选数、选中/常驻/最终/裁剪记忆 ID、gate、披露、fallback 和字数。
- 不保存会话/用户标识、消息正文、提示词、模型正文、工具参数或返回内容。
- 四类筛选可以重叠：未召回、部分记忆被隐藏、记忆已注入、使用兜底。
- 使用 `recalled_and_injected`，不以 `recalled_and_spoken` 推断模型引用；发送单独展示。
- 默认 7 天、最多 5000 条事件，失效清理发生在启动、写入或读取时。
- JSONL 读取和写入失败不打断 Agent；管理员可见保存失败提示。
- 工具返回仅表示返回，成功状态未知；同一工具重叠调用时不猜测各自耗时。

## 尚待环境验收

在维护者的真实 AstrBot 容器或忠实 staging 副本中运行 host tests，实际触发一次带工具的多轮回复，检查调用顺序、发送回调、权限及插件页面桥接。
本地方法体回归与 mock 页面验证不替代这一项。
