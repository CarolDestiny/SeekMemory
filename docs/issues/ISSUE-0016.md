# ISSUE-0016 无语境回忆（random_recall）完全没实现：空消息直接 return，10% 探索只在有 query 时发生

> 一句话：DESIGN §5.2 要求“无 query 时按 `funny × weight × 随机扰动` 排序，
> 排除 hot/sensitive，素材来自长期库 + 当天缓冲”；代码里没有 `random_recall`，
> `inject_memory` 在 `message_str` 为空时直接 return，`select()` 的 10% 探索
> 也必须有候选和 query 才会触发。

| 项 | 值 |
|---|---|
| 编号 | ISSUE-0016 |
| 级别 | P3（增强：无语境时的“突然想起”能力缺失） |
| 状态 | open |
| 报告人 | 审计记录（agent） |
| 日期 | 2026-10-21 |
| 关联 PR | 待开（建议分支 `feat/issue-0016-random-recall`） |
| 影响版本 | `main` @ `1be8baa` |
| GitHub | 待同步 |

## 症状

- 用户发一个表情/图片/空白消息，bot 不会“突然想起一件事”，因为
  `inject_memory` 看到空文本就返回。
- 即使消息非空，`select()` 的 10% 探索也只是从当前 query 的候选池里
  随机捞一条，不是 DESIGN 的“无语境回忆”。
- 没有按 `funny × weight × 随机扰动` 的排序，也没有排除 hot/sensitive 的池子。

## 现状（代码证据）

空文本直接跳过：

```text
main.py:126   @filter.on_llm_request()
main.py:127   async def inject_memory(self, event, req):
main.py:133       text = (event.message_str or "").strip()
main.py:134       if not text:
main.py:135           return
main.py:137       block = self._recall_block(text)
```

`_recall_block` 没有“无 query”分支：

```text
main.py:145   def _recall_block(self, text: str) -> str:
main.py:147       pool = self.cache.active()
main.py:148       if not pool:
main.py:149           return ""
main.py:151       seed_ids = seeds(text, pool)
main.py:152       activation = activate(seed_ids, self.graph, self.cache)
main.py:153       candidates = [...]
main.py:154       picked = select(candidates, text, 0.0, k=..., explore=...)
```

`select()` 的探索需要有候选：

```text
recall/score.py:194   if k <= 0 or not candidates:
recall/score.py:195       return []
recall/score.py:241   rest = scored[k:]
recall/score.py:242   if rest and 0.0 < explore <= 1.0:
recall/score.py:243       rng = random.Random(seed if seed is not None else text)
recall/score.py:244       if rng.random() < explore:
recall/score.py:245           pick = rng.choice(rest)[3]
```

没有 `random_recall` 函数：

```bash
cd SeekMemory
grep -rni "random_recall\|无语境\|funny.*weight" --include="*.py" .
# 无命中
```

`_static()` 里已经有 `funny` 素材（`recall/score.py:140-156`），但没有
“无 query 排序”的使用方。

## 设计期望

- DESIGN §5.2（`docs/DESIGN.md:232-240`）：
  ```
  无 query
  按 funny × weight × 随机扰动 排序
  排除 hot / sensitive
  素材两个池：长期库（funny 高的）+ 当天缓冲
  ```
- DESIGN §5.1（`:226`）：90% 按分数取，10% 随机捞一条——这是有 query 的探索，
  不是 §5.2 的无语境回忆。

## 差距

1. **没有入口**：`inject_memory` 空文本 return；没有“无 query 时走另一条路径”。
2. **没有排序函数**：没有 `funny × weight × noise` 的实现；`select()` 的
   打分仍以字面/标签/情绪为主。
3. **没有 hot/sensitive 排除**：`hot_until` 从来没被写入（ISSUE-0011），
   也没有 sensitive 标记；池子无法过滤。
4. **没有“长期 + 当天缓冲”双池**：缓冲还没落盘（ISSUE-0002），
   `_recall_block` 只读 `cache.active()`。
5. **没有“想起”的触发策略**：是空消息触发、低相关触发，还是按概率触发，
   DESIGN 没说；实现前要定。

## 影响

- **用户可感知**：少了一种“她有自己的念头”的体验；只有被问到时才回忆，
  不会主动想起。
- **与探索混淆**：当前 10% 探索会让结果不稳定，但不是无语境回忆；
  用户可能觉得“偶尔答非所问”，而不是“突然想起”。
- **依赖**：要做对，先要有 hot/sensitive 标记（ISSUE-0011）和缓冲（ISSUE-0002）；
  否则只能从长期库里随机捞，效果有限。

## 建议方案

| 方案 | 做法 | 代价 | 风险 | 能否解决 |
|---|---|---|---|---|
| A. 独立 `recall/random.py` | `random_recall(cache, buffer, now, k=1, rng)`：长期库按 `funny*weight*noise` 排序 + 缓冲池；排除 hot/sensitive；在空消息或低相关时调用；结果加“突然想起”措辞 | 1~2 人日；新模块 + 调用条件 | 随机性影响体验；可能想起敏感/不合时宜的事；要 scope 过滤 | 能 |
| B. 复用 select 空 query | `select(candidates, "", now, k=1, explore=0)` 用 weight/freshness 排序；在空消息时调用 | 0.3 人日；改动小 | 没有 funny 权重；没有缓冲池；容易变成“随机旧事” | 只能占位 |
| C. 只在明确冷场时触发 | 连续 N 轮无话题/用户只发表情时，按 A 的排序捞一条 | 1 人日；更可控 | 触发条件复杂；仍依赖 hot/sensitive | 能，体验更稳 |

### 推荐

**A，但先定触发条件。**

1. 触发：`message_str` 为空/只有表情，或连续 2 轮记忆相关度为 0 时，
   以配置概率（默认 0.2）触发；不要每轮都触发。
2. 排序：`score = max(0.1, funny) * max(0.1, weight) * random(0.5, 1.5)`；
   排除 `hot_until > now`、`sensitive=true`、`state != active`。
3. 池子：长期库 + 当天缓冲；缓冲未落盘前先只用长期库，并在 issue 里注明。
4. 措辞：用“她突然想起”的语气，不要伪装成用户刚说过；scope 过滤后再选。
5. 去重：同一会话内不重复“想起”同一条。

不建议直接复用 `select()`：它的打分是 query 相关的，空 query 会退化成
weight/freshness 排序，不是 DESIGN 的 funny 维度。

## 验收标准

- [ ] 空消息/纯表情时，按配置概率触发一次无语境回忆，而不是直接 return。
- [ ] 排序使用 `funny × weight × 随机扰动`，不是字面/标签分。
- [ ] `hot` 与 `sensitive` 记忆不会被“想起”；scope 过滤生效。
- [ ] 同一会话内不重复想起同一条；随机种子可固定用于测试。
- [ ] 有 query 时的 10% 探索与无语境回忆是两条独立路径，互不混淆。
- [ ] 新增测试：空消息触发、hot/sensitive 排除、排序、会话去重。

## 决策记录

- 2026-10-21：开 issue，只记录现状，不改代码。
- 待定：触发条件（空消息/冷场/概率）；是否每轮最多 1 条；
  sensitive 标记怎么来；缓冲池何时接入。

## 参考

- `main.py:126-143`、`:145-161`
- `recall/score.py:140-156`、`:179-247`
- `docs/DESIGN.md:226`、`:232-240`
- `README.md`“检索的联想”一节（无语境回忆被描述为已实现能力）
