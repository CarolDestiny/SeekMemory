# ISSUE-0011 强化与命中计数没接线：hits 永远不涨、hot 永远不设、同一段记忆会反复注入

> 一句话：`core/strength.py` 里的 `reinforce()` 和 `hit_cooldown_ok()` 只有测试在调；
> `main._recall_block()` 选出记忆后不回写 hits / last_used / hot_until，
> `score._recently_used()` 读的三个字段没有任何代码写入。于是“被想起会变强”
> 和“防复读”两条设计都不成立。

| 项 | 值 |
|---|---|
| 编号 | ISSUE-0011 |
| 级别 | P2（能力缺失：强化/防复读/晋升的数据来源断了） |
| 状态 | open |
| 报告人 | 审计记录（agent） |
| 日期 | 2026-10-21 |
| 关联 PR | 待开（建议分支 `feat/issue-0011-reinforce`） |
| 影响版本 | `main` @ `1be8baa` |
| GitHub | 待同步 |

## 症状

- 同一段对话里，同一条记忆可能被连续多轮注入；`hot_until` 和会话缓存都没有。
- `hits` 永远是 0（除非模型在 JSON 里主动写 `hits`，而提示词没要求）。
- `weight` 不会因为“被检索命中”而 +0.1，也不会因为“她主动说出/对方确认”而增长。
- `promote_candidates()` 要求 `hits > 10`，但 hits 不增长，所以晋升永远选不出人。
- `decay.retention()` 里的 `(1 + 0.5 × hits)` 项实际上只靠 weight 折算，
  “越常想起越难忘”没有真实数据。

## 现状（代码证据）

强化函数只被测试调用：

```text
core/strength.py:90    def reinforce(s: Strength, source: str) -> Strength:
core/strength.py:92        if source not in REINFORCE_DELTAS:
core/strength.py:95        delta = REINFORCE_DELTAS[source]
core/strength.py:96        return replace(s, weight=round(s.weight + delta, 4))

core/strength.py:115   def hit_cooldown_ok(last_window: str | None, now: str) -> bool:
```

`grep -rn "reinforce(\|hit_cooldown_ok" --include="*.py" .` 只命中
`core/strength.py` 和 `tests/`，生产路径没有调用。

读路径选出记忆后只组装，不回写：

```text
main.py:151       seed_ids = seeds(text, pool)
main.py:152       activation = activate(seed_ids, self.graph, self.cache)
main.py:153       candidates = [(a, float(activation.get(a.header.id, 0.0))) for a in pool]
main.py:154       picked = select(candidates, text, 0.0, k=..., explore=...)
main.py:161       return assemble_text(picked, budget=...)
```

`select()` 也不写回：

```text
recall/score.py:179   def select(candidates, text, now_days, k=8, explore=0.1, seed=None):
recall/score.py:238       append((-value, art.header.id, order, art))
recall/score.py:239       scored.sort()
recall/score.py:240       top = [item[3] for item in scored[:k]]
recall/score.py:246       return top
```

`_recently_used()` 读的字段没有写入方：

```text
recall/score.py:129   def _recently_used(art: Artifact) -> float:
recall/score.py:132       hits = int(art.header.strength.hits)
recall/score.py:136       last = payload.get("last_used") or payload.get("hot_until") or payload.get("used_at")
recall/score.py:137       return 1.0 if hits > 0 and last else 0.0
```

全仓库没有 `last_used`/`hot_until`/`used_at` 的赋值（`grep -rn "last_used\|hot_until\|used_at"` 只命中
`recall/score.py:136`）。`main.py:55-60` 只是把模型输出里可能带的 `hits` 塞进
strength，而 `perceive/extract.py:22-29` 的字段清单没有 `hits`。

## 设计期望

- DESIGN §4.6（`docs/DESIGN.md:189-197`）四来源强化：
  被检索命中 `weight +0.1`；她主动说出 `+0.3`；对方确认 `+0.2`；
  共同经历（shared）基础 `×1.5`。
- DESIGN §4.3（`:162`）命中计数规则：30 分钟内多次命中只计 1 次；
  跨天一天最多 1 次。
- DESIGN §5.1（`:220-230`）：打分里 `−2.0 × 最近刚用过`、`−3.0 × hot`；
  “会话缓存：同会话内已注入的不再重复注入”。
- DESIGN §4.4 第 4 级（`:171`）：`hits > 10` → 晋升人格候选。

## 差距

1. **命中不回写**：`_recall_block` 拿到 `picked` 后没有 `revise(strength=hits+1)`
   或 `reinforce(..., "recall")`。
2. **没有 last_used/hot_until**：三个字段只读不写，`−2.0` 惩罚永远是 0。
3. **没有会话缓存**：同一会话内重复注入没有拦截；`_recall_block` 不持有
   会话级 `seen` 集合。
4. **没有命中冷却**：`hit_cooldown_ok` 没有调用方；即使回写 hits，也会被
   同一轮/连续几轮刷高。
5. **没有确认/主动说出的检测**：没有把“对/是的”或她主动复述识别成
   `confirmed`/`spoken` 的路径。
6. **shared ×1.5 没实现**：`make()` 时没有按 scope=shared 放大基础权重；
   `merge` 只在合并时乘 1.2（`maintain/merge.py:169`），不是强化。
7. **session 缓存与 scope 无关**：未来加缓存时要注意同一条记忆对不同 viewer
   的可见性（ISSUE-0003）。

## 影响

- **用户可感知**：她会反复提同一件事，显得“卡带”；不会因为被想起而更牢，
  也不会因为被冷落而变淡（衰减仍按 created 走）。
- **人格**：hits 不涨，晋升阈值永远达不到，persona 为空（ISSUE-0006）。
- **衰减**：`retention` 的 hits 项只能靠 weight 折算；权重不涨，长期记忆的
  稳定性不会随使用变化。
- **成本**：重复注入浪费预算，挤掉真正相关的新记忆。
- **不涉及**：不会导致崩溃/数据损坏；是“行为不像人”的体验缺陷。

## 建议方案

| 方案 | 做法 | 代价 | 风险 | 能否解决 |
|---|---|---|---|---|
| A. 选后回写 + 冷却 + 会话缓存 | `_recall_block` 选出 `picked` 后，对每条：若 `hit_cooldown_ok(last_used, now)` 则 `hits+1`、`weight+0.1`、`last_used=now`、`hot_until=now+2h`；`revise` 落库 + cache.put；会话级 `seen` 集合拦截重复；确认词触发 `confirmed`；shared 写入时 ×1.5 | 1~2 人日；每轮多几次 DB 写（可批量/延迟） | 写放大；冷却窗口要调；hot 太长会影响召回 | 能 |
| B. 只做防复读 | 只维护会话 `seen` + hot_until，不回写 hits/weight | 0.5 人日；写少 | 晋升/衰减仍不工作 | 只能解决重复 |
| C. 批量回写 | 夜间把当天注入记录聚合成 hits/weight，再统一写 | 1 人日；写少 | 当天内仍会重复；要额外日志表 | 能，但防复读要另做 |

### 推荐

**A，先做“会话内不重复 + hot”，再做 hits/weight 落库。**

1. `_recall_block` 增加 `seen: set[str]`（按会话/umo 存，进程内即可），
   过滤已注入的 id；`select` 的候选池先扣掉 seen。
2. 对 `picked` 逐条：`hit_cooldown_ok(payload.get("last_used"), now)` →
   `hits + 1`、`weight + 0.1`、`last_used=now`、`hot_until=now+2h`；
   `revise` 后 `db.upsert` + `cache.put`。
3. `confirmed`：用户下一轮出现“对/是的/没错”且上一轮有注入 → 对上一轮
   picked 的 top1 执行 `reinforce("confirmed")`；`spoken` 暂不做自动检测，
   留给反思/抽取链路（ISSUE-0014）。
4. `shared`：写入时 `strength.weight *= 1.5`（或基础分乘），并在 payload 标记
   `shared_boost=true`，避免重复乘。
5. 落库频率：每轮最多写 3 条，失败 fail-open；不要因为记忆写失败影响聊天。

## 验收标准

- [ ] 同一会话连续两轮问相似问题，第二轮不再注入第一轮已注入的记忆
      （或按配置只保留 1 条）。
- [ ] 被注入的记忆 `hits` 增加；30 分钟内重复注入不重复计数。
- [ ] `hot_until` 被写入，`_recently_used()` 能返回 1.0，打分里出现 −2.0 惩罚。
- [ ] `hits > 10` 的记忆能被 `promote_candidates()` 选中（配合 ISSUE-0006）。
- [ ] `scope=shared` 的写入权重是普通记忆的 1.5 倍，且不会重复放大。
- [ ] 新增测试：冷却窗口、会话去重、hits/weight 回写、shared 放大。

## 决策记录

- 2026-10-21：开 issue，只记录现状，不改代码。
- 待定：hot 窗口多长；会话 seen 的过期；是否每轮落库还是批量；
  `spoken` 如何识别；`shared ×1.5` 是乘 weight 还是乘 retention。

## 参考

- `core/strength.py:27-31`、`:58-62`、`:90-96`、`:115-124`
- `main.py:55-60`、`:145-161`
- `recall/score.py:129-137`、`:179-247`
- `maintain/promote.py:24-32`
- `perceive/extract.py:22-29`
- `docs/DESIGN.md:162`、`:171`、`:189-197`、`:220-230`
