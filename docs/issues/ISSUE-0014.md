# ISSUE-0014 反思模块没接线：signals 只有测试在调，冷处理、错误留档、负权重、情绪闭环都没有

> 一句话：`maintain/reflect.py` 的 `signals()` / `should_reflect()` 写得很完整，
> 但 `main.py` 从未 import；`enable_reflect` 配置没有被读。没有 24 小时挂起表、
> 没有 mistake 写入、没有 `weight=-0.3` 的负权重记忆，也没有“连续两天情绪低”
> 的褪色逻辑。

| 项 | 值 |
|---|---|
| 编号 | ISSUE-0014 |
| 级别 | P2（能力缺失：自我纠错链路没有入口） |
| 状态 | open |
| 报告人 | 审计记录（agent） |
| 日期 | 2026-10-21 |
| 关联 PR | 待开（建议分支 `feat/issue-0014-reflect`） |
| 影响版本 | `main` @ `1be8baa` |
| GitHub | 待同步 |

## 症状

- 用户说“不是这个意思”“我没这么说”，bot 不会意识到自己上一轮理解错了；
  不会挂起、不会在 24 小时后确认、不会写 mistake。
- 没有 `weight < 0` 的羞愧记忆；同类判断不会“下次收着点”。
- 用户连续追问/接梗时，没有 +1 的正向强化；错分/对分阈值只存在于测试里。
- “情绪低持续 2 天 → 反思 → 细节褪色、情绪标签保留、新增 self 记忆”
  完全没有实现。

## 现状（代码证据）

规则函数存在：

```text
maintain/reflect.py:77    def signals(prev_user: str, cur_user: str) -> dict:
maintain/reflect.py:85        negation = _find_negation(cur)
maintain/reflect.py:86        if negation:
maintain/reflect.py:87            wrong += 2
maintain/reflect.py:90        overlap = _overlap(prev, cur)
maintain/reflect.py:91        if overlap > 0.6:
maintain/reflect.py:92            wrong += 1
maintain/reflect.py:94        followup = _find_followup(cur)
maintain/reflect.py:95        if followup:
maintain/reflect.py:96            right += 1
maintain/reflect.py:99        if prev and len(cur) < len(prev) * 0.5:
maintain/reflect.py:100           wrong += 1
maintain/reflect.py:103       return {"wrong": wrong, "right": right, "reasons": reasons}

maintain/reflect.py:106   def should_reflect(result: dict) -> bool:
maintain/reflect.py:109       return int(result.get("wrong", 0)) >= 2
```

调用方只有测试：

```bash
cd SeekMemory
grep -rn "from .maintain.reflect\|from maintain.reflect\|should_reflect\|signals(" --include="*.py" .
# 只命中 maintain/reflect.py 自身和 tests/test_maintain.py
grep -n "enable_reflect" _conf_schema.json main.py
# 只命中 _conf_schema.json:49，main.py 没有读
```

`main.py` 的缓冲只有用户侧文本（`main.py:171` 固定 `"user"`），没有 bot 回复，
所以“回复骤短（< 上轮 50%）”连比较对象都没有；也没有按用户保存的
`prev_user` 状态。

没有挂起/确认/留档表：

```text
store/schema.sql:1-69   # blobs/ledger/nodes/edges/sources/evidence，没有 pending/mistake
```

没有负权重写入路径：

```bash
grep -rn --include="*.py" "weight.*-0.3\|mistake" .
# 无命中；-0.3 只在 core/strength.py:50 作为 valence 阈值出现
```

## 设计期望

- DESIGN §8 信号（`docs/DESIGN.md:358-368`）：
  「不是这个意思/我没这么说」错 +2；重复解释同一件事错 +1；
  回复骤短（< 上轮 50%）错 +1；追问/展开/接梗对 +1；
  错分 ≥2 反思，对分 ≥2 强化。
- DESIGN §8 冷处理（`:371-377`）：发现可能错 → 挂起 24h；再出现 → 确认，
  写 mistake；没出现 → 撤案。
- DESIGN §8 错误留档（`:379-386`）：`about=self, shape=point`，
  `weight=-0.3`；**负权重 = 羞愧，下次会收着点**。
- DESIGN §4.7 情绪闭环（`:198-206`）：情绪低持续 2 天 → 触发反思 →
  那段 episode 细节衰减 ×1.5（褪色）→ 情绪标签保留 → 新增 self 记忆。
- DESIGN §7.2（`:329-336`）：反思权限分 owner 深度 / trusted 仅“没人接” / guest 无。

## 差距

1. **没有调用方**：`main.py` 不在每轮/下一轮调用 `signals()`；`enable_reflect`
   配置是死配置。
2. **没有按用户的前一轮状态**：`_pending` 只有当前用户的文本流，没有
   `prev_user` / `prev_bot`；群聊多用户会混。
3. **没有挂起表**：24h 冷处理需要一个 `pending_reflection` 表（话题、证据、
   due_at、状态），schema 没有。
4. **没有 mistake 写入**：没有 `make("memory", {level:"detail"/"scene",
   about:"self", ...}, strength={"weight": -0.3})` 的路径。
5. **没有负权重处理**：`score` 的 `weight` 项可以接受负值，但没有任何地方
   产生负权重；`decay` 也会把负权重按比例淡化（`core/strength.py:85-87`），
   语义需要确认。
6. **没有确认/强化闭环**：对分 ≥2 时没有 `reinforce("confirmed")`；
   追问/接梗也没有回写。
7. **情绪闭环缺失**：没有连续两天低情绪的检测，没有细节褪色 ×1.5，
   没有 self 情绪记忆。
8. **权限没分**：反思深度/“仅没人接”没有实现（ISSUE-0005）。

## 影响

- **用户可感知**：bot 会一错再错；用户纠正后没有“记住我错了”的痕迹，
  下次还会犯。
- **人格**：错误留档是“羞愧”的来源，没有负权重，人格只会正向沉淀，
  不像人。
- **关系**：情绪闭环缺失，用户低落时 bot 不会“收着点”，也不会把那段细节
  淡化，可能反复提伤心事。
- **成本**：设计说反思“只在出错时 1 次”，当前是 0 次；不是成本问题，
  是能力没接。

## 建议方案

| 方案 | 做法 | 代价 | 风险 | 能否解决 |
|---|---|---|---|---|
| A. 完整反思闭环 | 每轮保存 `prev_user/prev_bot`（按 umo）；下一轮调 `signals()`；wrong≥2 写 `pending_reflection`（due_at=+24h）；同话题再出现→确认→写 mistake（weight=-0.3）；right≥2→`reinforce("confirmed")`；夜间扫描到期 pending，撤案/确认；情绪闭环单独规则 | 2~3 人日；新表 + 每轮规则；要定义“同话题” | 误判（否定词/短回复）会写错 mistake；挂起表要防重复；群聊多用户 | 能 |
| B. 只做即时留档 | 不做 24h 挂起；wrong≥2 直接写 mistake；right≥2 直接强化 | 1 人日；简单 | 一次情绪就留档，容易误伤；不符合 DESIGN 冷处理 | 部分解决 |
| C. 只记录信号日志 | 每轮算 signals 写 debug 日志，不写记忆 | 0.3 人日；零风险 | 不产生任何行为变化 | 不能 |

### 推荐

**A，先做“按用户保存上一轮 + signals 日志”，再做挂起/留档。**

1. 在 buffer/内存里按 `umo` 保存 `prev_user`、`prev_bot`；没有 bot 回复时，
   至少能算否定/重复解释/追问三类，回复骤短先跳过（等 ISSUE-0002 存 bot 回复）。
2. `wrong >= 2` 时写一条 pending（话题用 bigram + 时间窗），`due_at = now+24h`；
   `right >= 2` 时对上一轮注入的 top1 `reinforce("confirmed")`。
3. 夜间扫描 pending：同话题再次出现 → 确认，写 mistake；到期未出现 → 撤案。
   mistake 的 payload 用 `level=detail/scene`、`about=self`、`weight=-0.3`，
   `lineage.sources` 指向对话 source（ISSUE-0013）。
4. 情绪闭环：先用 `strength.valence < -0.3` 且连续 2 天的记忆判断；
   命中后把那段 episode 的细节 `weight *= 0.67`（≈ 衰减 ×1.5），
   新增一条 `about=self` 的情绪记忆；不要改动原始事实。
5. 权限：owner 才做深度反思；trusted 只处理“没人接”的冷场；guest 不做
   （ISSUE-0005）。

## 验收标准

- [ ] 用户说“不是这个意思”后，24h 内挂起一条 pending；同话题再出现时
      写出 mistake，`weight=-0.3`，可追溯到原对话。
- [ ] 24h 内没再出现，pending 自动撤案，不产生 mistake。
- [ ] 用户追问/接梗时，上一轮记忆的 weight 增加（confirmed），有 ledger。
- [ ] “回复骤短”在 bot 回复被缓冲后能参与评分；当前阶段有明确跳过日志。
- [ ] 连续两天低情绪能触发一次细节褪色，情绪标签保留，新增 self 记忆。
- [ ] 反思只对 owner 深度执行；trusted/guest 行为符合 RBAC 表。
- [ ] 新增测试：否定、重复解释、短回复、追问、挂起/确认/撤案、负权重。

## 决策记录

- 2026-10-21：开 issue，只记录现状，不改代码。
- 待定：pending 的“同话题”判定；mistake 的 level；负权重参与衰减的语义；
  情绪闭环是否依赖关系曲线（ISSUE-0008）。

## 参考

- `maintain/reflect.py:77-111`
- `main.py:164-174`、`:213-249`
- `_conf_schema.json:49-53`
- `store/schema.sql:1-69`（无 pending/mistake 表）
- `core/strength.py:85-96`
- `docs/DESIGN.md:198-206`、`:329-336`、`:358-386`
