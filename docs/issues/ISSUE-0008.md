# ISSUE-0008 关系曲线不存在：没有日常快照、没有滑动窗口，组装头部也没有“关系结论”

> 一句话：DESIGN 反复要求“关系曲线 / 关系曲线滑窗 / 关系结论（1 句）”，
> 代码里没有任何 relationship/mood 模块，`about=relation` 只被用来把“我们”
> 改成“你们”；`assemble` 的头部第 ② 段永远是空的。

| 项 | 值 |
|---|---|
| 编号 | ISSUE-0008 |
| 级别 | P2（能力缺失：关系建模与关系注入没有实现） |
| 状态 | open |
| 报告人 | 审计记录（agent） |
| 日期 | 2026-10-21 |
| 关联 PR | 待开（建议分支 `feat/issue-0008-relationship`） |
| 影响版本 | `main` @ `1be8baa` |
| GitHub | 待同步 |

## 症状

- 注入里没有“他这三天话越来越少”“你们最近聊得挺多”这类关系结论；
  只有一条条记忆和印象。
- 没有按天/按周聚合的关系快照，无法回答“最近关系怎么样”。
- `about=relation` 的记忆只是人称从“我们”变“你们”，没有关系数值/趋势。

## 现状（代码证据）

全仓库没有 relationship / mood / curve 模块：

```bash
cd SeekMemory
grep -rni "mood\|relationship\|关系曲线\|curve" --include="*.py" .
# 只命中 core/tree.py 的“父子关系”、core/graph.py 的“关系图”等无关词
```

`about=relation` 的唯一处理是人称：

```text
recall/assemble.py:54   def _voice(text: str, about: str) -> str:
recall/assemble.py:55       """把记忆里的第一人称改写成注入时的第二人称。"""
recall/assemble.py:56       if about == "relation":
recall/assemble.py:57           text = text.replace("我们", "你们")
recall/assemble.py:58       return text.replace("我的", "你的").replace("我", "你")
```

`assemble.build()` 的头部只收 persona、impression 和前 3 条：

```text
recall/assemble.py:197   header = [i for i, (layer, _) in enumerate(entries) if layer == "persona"]
recall/assemble.py:198   header += [i for i, (layer, _) in enumerate(entries) if layer == "impression"][:1]
recall/assemble.py:199   header += [
recall/assemble.py:200       i for i, (layer, _) in enumerate(entries)
recall/assemble.py:201       if i not in header and layer != "impression"
recall/assemble.py:202   ][:3]
```

没有“关系状态”这一层，也没有从时间去算趋势的函数。`store/schema.sql` 里没有
relationship/snapshot 表（`:1-69`）。

## 设计期望

- DESIGN §4.1（`docs/DESIGN.md:118`）：每晚流程是
  `缓冲 → 沉淀 → 衰减 → 关系曲线`。
- DESIGN §4.5（`:183-187`）：每周第 5 步是“关系曲线滑窗”。
- DESIGN §5.3（`:242-258`）：组装头部第 ② 段是“关系结论（1 句）”，
  例子是“他这三天话越来越少”。
- **规格缺口**：DESIGN 只写了“关系曲线/滑窗”，没有写窗口长度、指标、存储结构。
  用户口径是“14 天滑动窗口”，但这个数字目前不在 DESIGN 里，实现前必须先补规格，
  否则验收没有依据。

## 差距

1. **没有关系对象**：没有 `relationship`/`relation` family、没有 snapshot 表、
   没有“当前关系状态”的节点。
2. **没有滑窗计算**：没有按 14 天（或任何窗口）聚合消息数、情绪、主动性、
   回复长度的代码。
3. **没有关系结论生成**：没有“一句话总结最近关系”的规则/模型路径。
4. **没有注入位置**：`assemble` 头部只认 persona/impression，不认关系句。
5. **没有版本/回滚**：即使以后生成关系结论，也没有 revision/lineage 方案。
6. **规格未定**：14 天是产品口径，不是 DESIGN 文本；窗口、指标、更新频率、
   是否按 scope 分人都需要先定。

## 影响

- **用户可感知**：她不会“感觉到关系变了”；所有回复都基于单条记忆，
  没有“最近他话少，我收着点”这种整体判断。
- **注入结构**：头部第 ② 段空着，预算给了中部细节，违反
  “越影响她是谁越靠上”的排布原则。
- **与人格混淆**：persona 是“她是谁”，关系是“对你怎么样”；现在两者都没有，
  模型只能从零散记忆里猜。
- **成本**：关系曲线可以纯规则（零模型）计算，不做等于白白丢掉一个低成本能力。

## 建议方案

| 方案 | 做法 | 代价 | 风险 | 能否解决 |
|---|---|---|---|---|
| A. 新增 `relation` family + 每日快照 | 每天/每周把消息数、情绪均值、主动性、回复长度聚成一条 `relation` 节点（`scope` 按人），14 天滑窗算趋势；组装时取最新一条，生成一句“他这三天话越来越少”；revision/lineage 保留 | 2~3 人日；新 family/表；要定义指标与措辞 | 指标噪声大；关系句可能显得武断；需要 scope 隔离（ISSUE-0003） | 能 |
| B. 不落库，查询时从 memory 现算 | 用 `time.created` + `strength` 在 `_recall_block` 里算最近 14 天统计，拼一句 | 0.5~1 人日；零新表 | 每次查询多一次全量扫描；无法保留历史趋势；依赖 created 正确（ISSUE-0012） | 能出句，不能出曲线 |
| C. 只做一句固定模板 | 按最近 3 天消息数分“多/正常/少”，固定文案 | 0.2 人日；最便宜 | 不是曲线，容易重复；用户很快识破 | 只能占位 |

### 推荐

**先补 DESIGN 规格，再做 A。** 建议规格：

1. 窗口 14 天，按自然日聚合；指标至少：消息条数、用户主动发起次数、
   平均回复长度、情绪均值（valence/arousal）、负面词比例。
2. 存储：`relation` family，payload 存 `window_start/window_end/metrics/text`；
   每天一条，或每周一条；`scope` 按对象，`revision` 递增。
3. 生成：纯规则先出“他这三天话越来越少/你们最近聊得挺多”模板；
   需要更自然时再每周 1 次模型改写，但保留指标作为证据。
4. 注入：放在 `assemble` 头部 persona 之后、impression 之前；预算不够时
   关系句优先级高于中部记忆。
5. 如果短期不做，至少把 DESIGN §5.3 的 ② 标注为“未实现”，不要让它看起来
   已经存在。

## 验收标准

- [ ] DESIGN 里补上关系曲线的窗口长度、指标、存储、更新频率。
- [ ] 连续 14 天的消息能生成一条关系快照；窗口滚动后指标随之变化。
- [ ] `assemble.build()` 在有关系快照时，头部出现一句关系结论。
- [ ] 关系快照按 scope/对象隔离，A 的关系不出现在 B 的注入里。
- [ ] 关系句可追溯到指标（payload 里有 metrics），不是模型凭空写。
- [ ] 新增测试：空窗口、单日、14 天、趋势上升/下降四种。

## 决策记录

- 2026-10-21：开 issue，只记录现状，不改代码。确认“14 天”目前不在 DESIGN，
  需要先补规格。
- 待定：日快照还是周快照；是否按群/私聊分别算；关系句用规则还是模型；
  `relation` 是新 family 还是复用 memory。

## 参考

- `recall/assemble.py:54-58`、`:197-203`
- `store/schema.sql:1-69`（无 relationship 表）
- `docs/DESIGN.md:118`、`:183-187`、`:242-258`
- `README.md`“关系的边界”一节（关系状态被描述为头部内容）
