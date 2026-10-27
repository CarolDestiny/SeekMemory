# adapters：AstrBot 宿主适配

## 职责

adapters 把 AstrBot 事件、provider 和消息发送映射到应用端口。宿主对象不进入 core、recall 或 app/runtime 的领域策略中。

## 组合根

AstrBotPlugin 在 start 时建立 Store、Cache、Tree、Graph、HybridRetriever、Source-backed Buffer、CheckpointManager、各应用服务、AgentRuntime、Jobs、WebRoutes 与后台服务；stop 时依次停止后台任务与管理任务、注销本实例路由、保存缓冲、flush checkpoint，最后关闭 Store。

main.py 定义插件入口并委托 lifecycle；组合和 wiring 位于 adapters/astrbot_plugin.py。AstrBotHooks 在 adapters/astrbot_hooks.py 把宿主 hook 映射为服务调用：访问策略、输入接收、记忆注入、助手回复捕获、实际发送后的交付记录、运行时/工具观测。它不实现抽取、容量或维护算法。

## 端口适配

- AstrBotRuntimeAdapter 将消息转成 RuntimeInput，并管理宿主 event extra 中的 user/reply Source ID、turn ID、final recall IDs 和 episode 去重标记。
- AstrBotModelGateway 提供延迟回复使用的 ModelGateway。
- AstrBotActionPort 提供 MessageSender。
- ProviderChatModel 将宿主 extraction/persona provider 包装为 ChatModel。
- SeekMemoryContextAdapter 将 Runtime 的 MemoryContextPort 接到现有 RecallService。

AstrBot 的时间入口统一使用 UTC+8：astrbot_time.py 在既有 RunRecorder 写入前转换用户、助手和运行审计时间，保留内核原有的无时区 ISO 字符串格式。AstrBotBuffer 复用 Buffer 的入队与话题算法，只在宿主投影中统一时间，并按 UTC+8 计算队列年龄；AstrBotSourceView 为抽取提供相同时间格式的原文读取视图，覆盖已处理父消息的读回。历史 Source 不改写。无时区的宿主时间按 UTC+8 解释，带偏移的时间先换算。运行时决策仍使用 epoch 时间戳，不依赖操作系统时区，不修改 core、Buffer 或抽取原型。

AccessService 基于完整 session UMO、sender ID、owner/trusted 配置和 observe_groups 决定观察/召回；宿主事件信息只在边界处转换。配置和 database path 仍由插件组合根读取。

## 当前边界

宿主 hook 注册必须绑定真实插件模块路径，避免热重载后回调无法识别。Runtime 的工具过滤在模型请求前运行；工具调用完成后的观测 hook 不能作为强制拦截。插件初始化/宿主 API 不可用时，由上层状态和 fail-open 处理，不应把 AstrBot 依赖泄漏到业务模块。
