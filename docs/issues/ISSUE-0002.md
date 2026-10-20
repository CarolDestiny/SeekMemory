# ISSUE-0002 缓冲层只是一个内存列表：没有话题聚合、没有 24h TTL、没有落盘

> 一句话：`main._pending` 是 `list[tuple[role, text]]`，重启即丢；不按话题聚合，
> 也没有 24h 过期，早上说“要辞职”、晚上说“算了”会被同一晚一次性抽走。

| 项 | 值 |
|---|---|
| 编号 | ISSUE-0002 |
| 级别 | P1（功能失效：短期缓冲的核心语义没有实现，且会写错长期记忆） |
| 状态 | open |
| 报告人 | 审计记录（agent） |
| 日期 | 2026-10-21 |
| 关联 PR | 待开（建议分支 `fix/issue-0002-topic-buffer`） |
| 影响版本 | `main` @ `1be8baa` |
| GitHub | 待同步 |

## 症状

- 插件重启后，当天还没到 23:50 的对话全部消失，不会进入长期记忆。
- 缓冲没有时间戳，也没有“话题单元”。夜间把最多 120 条消息拼成一段对话，
  让模型一次性抽 0~3 条；同一天里前后矛盾的两句话没有先后、没有分组，
  模型无法按 DESIGN 的“早上说要辞职，晚上说算了，以晚上为准”处理。
- 缓冲只记用户侧文本，统一标成 `user`，不记 bot 回复、不记群/私聊、不记发送者。
- 超过 200 条时静默丢弃最旧的消息（`main.py:172`）。
- `perceive/compress.py` 写好了三行摘要（情绪/未完成/事实），但 `main.py:22`
  只 import，没有任何调用；夜间不做摘要，组装层也没有“历史摘要”段。

## 现状（代码证据）

```text
main.py:73    self._pending: list[tuple[str, str]] = []  # (role, text) 当天缓冲
main.py:164   @filter.event_message_type(filter.EventMessageType.ALL)
main.py:165   async def buffer_message(...)
main.py:171       self._pending.append(("user", text))
main.py:172       self._pending = self._pending[-200:]
main.py:213   async def _nightly(self)
main.py:214       if not self._pending or self.db is None:
main.py:220       dialogue = "\n".join(f"{r}: {t}" for r, t in self._pending[-120:])
main.py:227           self._pending = []      # 解析为空也清空
main.py:248       self._pending = []          # 写入失败也清空
main.py:22    from .perceive.compress import build_compress_prompt, parse_compress
```

复核命令：

```bash
cd SeekMemory
grep -n "_pending" main.py
grep -n "build_compress_prompt\|parse_compress" main.py
grep -n "CREATE TABLE" store/schema.sql
```

`store/schema.sql` 里没有 buffer / pending / topic 表；`_pending` 没有任何
`datetime`、`umo`、`chat_type`、`topic` 字段。`main.py:227` 和 `main.py:248`
在“模型没抽出东西”和“写库失败”两种情况下都无条件清空缓冲。

## 设计期望

- DESIGN §4.1（`docs/DESIGN.md:122-134`）：短期缓冲是“今天，24h TTL，不注入”，
  **按话题单元存，不按消息**。
- DESIGN §4.2（`:136-147`）：每晚 23:50 读缓冲，**按话题单元聚合**，模型判断
  0~3 条值得沉淀；每条标四维 + strength；去重后写入。
- DESIGN §4.1 的缓冲必要性（`:134`）：早上“要辞职”、晚上“算了”，
  早写进长期就记错了。
- DESIGN §5.3（`:250`）：组装中部第 ④ 段是“历史摘要（情绪优先）”。

## 差距

1. **没有话题单元**：`_pending` 是扁平消息列表，夜间只按条数截断（`main.py:220`），
   没有“同一话题”的聚合键，也没有群/私聊/发送者维度。
2. **没有 TTL**：没有任何代码检查消息年龄；只要进程不重启，前几天的消息也会
   留在列表里直到下一次成功夜间任务。
3. **没有落盘**：缓冲只在内存；`store/schema.sql` 没有对应表，进程退出即丢。
4. **只存用户侧**：`main.py:171` 固定写 `"user"`；bot 的回复不在缓冲里，
   抽取看不到“她当时怎么回”，无法判断“我说陪他躺会儿”这类关系记忆。
5. **失败也清空**：`main.py:227`、`main.py:248` 在解析为空或写库失败后清空，
   这段对话永久丢失，与 DESIGN 的“缓冲是长期记忆的唯一入口”冲突。
6. **摘要模块是死代码**：`perceive/compress.py:10`、`:53` 有完整提示词与解析，
   `main.py:22` import 后从未调用；`assemble.build()` 也没有摘要输入参数。

## 影响

- **用户可感知**：bot 重启一次，当天的记忆就没了；白天说“算了”之后，
  晚上仍可能被记成“他要辞职”，因为两句话在同一个 prompt 里且没有时间/话题结构。
- **数据**：错误沉淀会进入长期库，之后靠衰减慢慢退出；用户无法直接删除。
- **成本**：缓冲无上限（只截 200 条），一次夜间 prompt 可能塞 120 条；
  按话题拆分后可以只对有内容的 topic 调模型。
- **隐私**：`everyone` 模式下不同用户的消息会进同一个列表、同一个 prompt，
  与 scope 隔离问题叠加（见 ISSUE-0003）。

## 建议方案

| 方案 | 做法 | 代价 | 风险 | 能否解决 |
|---|---|---|---|---|
| A. SQLite 缓冲表 + 规则话题聚合 | 新增 `buffer(id, umo, chat_type, role, text, at, topic, consumed)`；每条消息落盘；按“30 分钟时间窗 + bigram 重合”聚 topic；夜间按 topic 组 prompt；24h 未消费的标过期；成功后按 topic 标记 consumed，失败保留 | 1~2 人日；多一张表、一次写入/消息；话题规则要调 | 规则聚合会把无关话题合并；需要迁移/清理策略 | 能覆盖落盘、TTL、话题、失败保留 |
| B. 每日 JSONL + 内存 topic 分组 | 每条消息 append 到 `data/buffer/YYYY-MM-DD.jsonl`；启动时加载当天；按时间窗/关键词分组；夜间读完不立即删，按日清理 | 0.5~1 人日；实现简单，可直接看文件 | 并发写要加锁；JSONL 无索引；跨天边界要处理 | 能解决落盘/TTL，话题仍靠规则 |

### 推荐

先做 A 的最小版：**先落盘、先有 `at` 与 `umo`，再谈聚合**。分三步：

1. 建 `buffer` 表，`buffer_message` 只做 append；`_nightly` 从表里取 24h 内未消费的行。
2. 加规则 topic key：同一 `umo` + 30 分钟窗口 + 与上一话题首条 bigram 重合 ≥ 0.2
   归为同一 topic；无法归类的单独成 topic。
3. 夜间按 topic 组 prompt，每条 topic 最多 1 条沉淀；成功后标记 consumed；
   失败/解析为空保留并记 warning。摘要用 `perceive/compress.py` 的现成函数，
   先写进 buffer 的 summary 字段或单独表，组装层再决定要不要注入。

不建议直接上向量聚类：当前每轮零模型调用是卖点，话题聚合用规则就够；
先把“不丢、不过期、有话题”做对。

## 验收标准

- [ ] 插件在 23:50 前重启，当天消息仍在，夜间仍能抽取（有落盘证据）。
- [ ] 超过 24h 未消费的缓冲不再进入抽取，并有清理/归档记录。
- [ ] 同一话题的“要辞职 / 算了”只沉淀为一条，且以靠后的表述为准；
      不同话题不会被拼进同一条记忆。
- [ ] 抽取失败/写库失败时缓冲保留，不出现“失败即清空”。
- [ ] 群聊与私聊、不同发送者的缓冲可区分，不混进同一个 topic。
- [ ] 新增回归测试：重启恢复、TTL 过期、失败保留、话题分组四类。

## 决策记录

- 2026-10-21：开 issue，只记录现状，不改代码。等确认缓冲表结构与话题规则后再开分支。
- 待定：话题 key 放 DB 还是内存；是否把 bot 回复也写入缓冲；摘要是否单独成 family。

## 参考

- `main.py:22`、`:73`、`:164-174`、`:213-249`
- `store/schema.sql:1-69`（无 buffer 表）
- `perceive/compress.py:10-24`、`:53-71`
- `docs/DESIGN.md` §4.1、§4.2、§5.3
