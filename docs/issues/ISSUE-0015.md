# ISSUE-0015 措辞没有三档不确定，也没有 metamemory：confidence 不参与表达，分不清“我忘了”和“你没说过”

> 一句话：`assemble._memory_sentence()` 永远用“你记得/你印象里”，
> `Strength.confidence` 只在合并时被取过一次 max；`recall` 只查 active 缓存，
> 不会去查 forgotten 的同话题记忆，所以既不会说“你好像说过”，也不会说
> “我好像忘了，你再说一遍”或“这事你没跟我说过吧”。

| 项 | 值 |
|---|---|
| 编号 | ISSUE-0015 |
| 级别 | P3（增强：表达层的可信度/元记忆精细化） |
| 状态 | open |
| 报告人 | 审计记录（agent） |
| 日期 | 2026-10-21 |
| 关联 PR | 待开（建议分支 `feat/issue-0015-uncertainty`） |
| 影响版本 | `main` @ `1be8baa` |
| GitHub | 待同步 |

## 症状

- 不管记忆是亲口说的（confidence=1.0）、第三方转述（0.7）还是反话检测
  （0.4），注入都用同一种肯定语气“你记得…”。
- 用户问一件她曾经忘记的事，她不会说“我好像忘了”；问一件完全没发生过的事，
  她也不会说“你没跟我说过”，而是可能用无关记忆硬答。
- `confidence` 字段在数据库里有，但读路径没有用它。

## 现状（代码证据）

表达永远肯定：

```text
recall/assemble.py:111   def _memory_sentence(art: Artifact) -> str:
recall/assemble.py:113       text = _clean(_voice(_raw(art), str(art.payload.get("about") or "")))
recall/assemble.py:116       level = str(art.payload.get("level") or "")
recall/assemble.py:117       if level == "impression":
recall/assemble.py:118           return f"你印象里{text}"
recall/assemble.py:119       if level == "detail":
recall/assemble.py:120           return f"你还记得{text}"
recall/assemble.py:121       when = _when(art.header.time.created) if level == "scene" else ""
recall/assemble.py:122       return f"{when}{text}" if when else f"你记得{text}"
```

没有 `confidence` 分支，也没有“好像/是不是”的措辞。

`confidence` 的读取点只有合并：

```text
core/artifact.py:39    confidence: float = 1.0
maintain/merge.py:170         confidence=max(item.confidence for item in strengths),
```

`recall/score.py` 和 `recall/assemble.py` 都没有 `confidence`
（`grep -rn "confidence" --include="*.py" recall` 为空）。

metamemory 也不存在：

```text
store/cache.py:26    def load(self):
store/cache.py:31        for art in self.db.list(state="active"):
store/cache.py:38        if art.header.state != "active":
store/cache.py:39            return
```

缓存只装 active；`_recall_block` 的池子来自 `cache.active()`（`main.py:147`），
所以 forgotten 的记忆连候选都不是，无法判断“同话题有忘掉的记忆”。
`grep -rn "忘了\|没说过\|metamemory" --include="*.py" .` 无命中。

## 设计期望

- DESIGN §6.2（`docs/DESIGN.md:286-292`）三档不确定：

  | confidence | 说法 |
  |---|---|
  | > 0.9 | 「你叫吕宇轩」 |
  | 0.6~0.9 | 「你好像说过你在做量化」 |
  | < 0.6 | 「我是不是听你提过」 |

- DESIGN §6.4（`:301-306`）metamemory：
  有 forgotten 的同话题记忆 → 「我好像忘了，你再说一遍」；
  完全无相关 → 「这事你没跟我说过吧」。
- DESIGN §7.3（`:338-344`）：第三方信息 confidence 低于亲口 1.0，正是为了
  在措辞上体现不确定。

## 差距

1. **confidence 不进表达**：`_memory_sentence()` 没有读
   `art.header.strength.confidence`；三档语气没有实现。
2. **没有“同话题 forgotten”查询**：缓存只装 active，检索池也只 active；
   要做 metamemory 必须额外查 DB 的 forgotten 节点，并按话题/标签匹配。
3. **没有“完全无相关”判定**：`select()` 在没有相关候选时仍会按 weight
   凑满 top-k（ISSUE-0001 已记录），所以“你没说过”永远不会出现。
4. **没有把不确定传给模型**：即使加了措辞，`confidence=0.4` 的反话记忆
   仍要以“我是不是听你提过”出现，而不是直接断言。
5. **没有区分“忘了”和“没有”**：需要一份“同话题但 forgotten”的证据，
   否则两者都只能猜。

## 影响

- **用户可感知**：bot 对不确定的事也说得斩钉截铁，容易编造；对忘掉的事
  不会承认，显得“假装记得”。
- **信任**：三档不确定是 DESIGN 里“像人”的关键细节；没有它，
  confidence 字段等于死数据。
- **与 ISSUE-0001 叠加**：零相关时仍凑 top-k，会让“你没说过”永远无法触发，
  反而用无关记忆硬答。
- **成本**：纯规则/模板，零模型；不做主要是没接线。

## 建议方案

| 方案 | 做法 | 代价 | 风险 | 能否解决 |
|---|---|---|---|---|
| A. 置信度措辞 + forgotten 反查 | `_memory_sentence` 按 confidence 选前缀；`_recall_block` 在无 active 命中时查 `db.list(state="forgotten")`，按 bigram/标签找同话题；有→“我好像忘了”，无→“你没说过”；需要 scope 过滤 | 1~2 人日；多一次 DB 查询（只在无命中时） | forgotten 全表扫描；同话题判定误判；scope 过滤不能漏 | 能 |
| B. 只做三档措辞 | 按 confidence 改前缀，不做 metamemory | 0.3 人日；风险低 | 仍然分不清“忘了/没说过” | 只能解决一半 |
| C. 让模型自己判断 | 把 confidence 和“是否有 forgotten”作为提示词元信息，交给模型措辞 | 0.5 人日；灵活 | 模型可能忽略；不可测试；每轮多 token | 部分解决 |

### 推荐

**B 先做，A 随后。**

1. 在 `_memory_sentence()` 读 `strength.confidence`：
   `>0.9` 用“你记得/你叫…”；`0.6~0.9` 用“你好像说过…”；
   `<0.6` 用“我是不是听你提过…”。同一段里不要每条都加“好像”，
   只对低置信条目加，避免整段变虚。
2. 在 `_recall_block` 里：如果 `seeds`/`select` 的结果全是低相关
   （字面/标签分为 0），先别凑 top-k；查一次 forgotten：
   `db.list(state="forgotten")` + 当前 scope 过滤 + bigram/标签匹配。
   命中→在 block 末尾加“我好像忘了，你再说一遍”；完全没有→
   “这事你没跟我说过吧”。
3. 这一步依赖 ISSUE-0001 的“无相关不硬凑”和 ISSUE-0003 的 scope 过滤；
   在这两个修好前，metamemory 只能做保守版（不主动说“你没说过”）。

## 验收标准

- [ ] 同一句话在 confidence=1.0 / 0.7 / 0.4 下分别出现
      “你记得/你好像说过/我是不是听你提过”三档措辞。
- [ ] 有 forgotten 的同话题记忆时，注入出现“我好像忘了，你再说一遍”。
- [ ] 完全无相关记忆且用户问事实时，出现“这事你没跟我说过吧”，
      而不是用无关高权重记忆硬答。
- [ ] 低置信条目不会污染整段语气（同段高置信仍是肯定句）。
- [ ] forgotten 反查遵守 scope，不把别人的 forgotten 当自己的。
- [ ] 新增测试：三档 confidence、同话题 forgotten、完全无相关、scope 过滤。

## 决策记录

- 2026-10-21：开 issue，只记录现状，不改代码。
- 待定：三档边界是否用 0.9/0.6；同话题判定用 bigram 还是标签；
  “你没说过”是否只在用户明确提问时出现；forgotten 查询的性能。

## 参考

- `recall/assemble.py:111-122`
- `core/artifact.py:36-43`
- `maintain/merge.py:168-174`
- `store/cache.py:26-44`
- `main.py:145-161`
- `recall/score.py:179-247`
- `docs/DESIGN.md:286-306`、`:338-344`
