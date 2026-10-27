# Agent Runtime：会话注意力与运行时动作

## 职责

app/runtime 定义不依赖 AstrBot 的会话状态、注意力决策和运行时动作生命周期。它处理“何时观察、何时回复或等待”及延迟回复的协调，不取代 SeekMemory 的 Extraction、Recall 或普通 AstrBot 工具循环。

## 对象与策略

- RuntimeInput 是从宿主事件裁剪出的输入；RunContext 是一项待执行任务的上下文。
- SessionState 保存 wait、retry、quiet、cooldown、unread/read-through、dispatch 尝试等会话运行状态。它不是 Source 或 Artifact。
- WakePolicy 对输入给出 ignore、observe、wait、reply 之一。私聊和 @/直接提及是强注意力；明确问题可直接回复；quiet/cooldown 影响 ambient 流量。
- TimingPolicy 是纯 wait/retry 截止时间策略。Scheduler 只读持久化状态并返回 due runs；RuntimeWorker 轮询、去重并分发，不拥有记忆规则。
- MemoryContextPort 将运行时输入交给既有 RecallService；Runtime 本身不实现第二套记忆检索。

## 两条运行路径

**普通 AstrBot 回复**：hook 将用户消息交给 AgentRuntime.accept_user；RunRecorder 写用户 Source/队列；请求 hook 由 runtime.build_context 取得记忆；模型与宿主发送完成后，capture/delivery hooks 经 AgentRuntime/RunRecorder 记录助手 Source、召回强化和 EpisodeRecord。

accept_user 返回的 UserRunReceipt 包含本轮接收时的消息确认序号 read_through_seq。宿主只在事件上携带该序号，并在发送完成时传回 record_delivery；运行时只确认该序号及以前的消息，保留此后到达的未读消息和等待任务。重复或乱序确认不能使已读位置、最近发言时间和冷却期限倒退。缺少序号的旧调用、过期事件只更新交付时间，不清空未读。待抽取队列不是未读计数；宿主不从队列长度推算会话未读数。

**延迟 ambient 回复**：开启 runtime_gate_enabled 后，worker 根据已到期 wait/retry 选择会话；Runtime 领取 dispatch、构建记忆上下文、调用 ModelGateway、通过 MessageSender 发送，再记录助手 Source 与 EpisodeRecord。失败会按每会话上限和指数退避重试。该路径直接调用 provider，不运行完整 AstrBot agent/tool 循环。

等待和重试期限在模型与发送执行期间保留，尝试次数在调用前持久化。取消会安排有限重试并继续抛出取消信号；进程中断后，原有 Scheduler 可从同一状态恢复。重试次数跨重启保留，新 Source 使用自己的次数预算。只有成功确认对应消息或旧任务耗尽时才清理相应任务，不能覆盖期间新消息安排的期限。运行时保存领取时的状态快照以区分旧标记与新任务，不增加数据库字段、表或第二套调度循环。

成功发送后重新读取注入时钟，作为交付审计、最近发言和冷却的起点；失败或取消后也重新读时钟，从失败时刻开始退避。显式传入的 now 是该次运行的时间下界。RuntimeWorker.dispatch 统一管理并发名额与会话去重；轮询、直接调用共用此入口。排队也占用会话去重标记，取得名额后复查开关、时钟和到期状态，取消会释放名额与标记。这只保证单个 worker 进程中的协调，不保证跨进程严格单次发送。

runtime_gate_enabled 默认 false。关闭时，等待和后台 deferred dispatch 不活跃；普通事件捕获、记忆注入和审计仍由插件 hook 承担。

## 写回与诊断

RunRecorder 是 Source、pending projection、checkpoint 和 episode 的唯一运行时写回协调者，以 run_id 和确定性 Source ID 防止重复回调重复写入。runtime_episodes 是追加式业务审计元数据；RunTracer/TraceStore 是受字段白名单约束的诊断时间线。二者不保存对话正文，不互相替代。

ToolPolicy 在模型请求前可从 req.func_tool 移除不允许的工具；观察工具调用的 hook 只是诊断信号，不能单独阻止执行。实际过滤由 runtime_tool_filter_enabled 控制，默认关闭。
