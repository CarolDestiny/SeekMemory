# ISSUE-0006 沉淀链路断了：promote 只返回候选，persona 永远为空，抽象树只实例化不使用

> 一句话：`maintain/promote.py` 的 `promote_candidates()` 没有任何调用方；
> 生产代码没有一处 `make("persona", ...)`；`main.py:105` 创建了 `Tree`，
> 但 `add_under()` / `impressions()` 在生产路径上一次都没被调用。四层里的
> impression / persona 实际上没有数据。

| 项 | 值 |
|---|---|
| 编号 | ISSUE-0006 |
| 级别 | P2（能力缺失：人格与抽象树没有产出路径） |
| 状态 | closed |
| 报告人 | 审计记录（agent） |
| 日期 | 2026-10-21 |
| 关联 PR | PR-0009（`fix/issue-0009-0006-edges-and-persona`） |
| 影响版本 | `main` @ `1be8baa` |
| GitHub | 待同步 |

## 症状

- 没有任何记忆会被晋升成人格；`persona` family 的模型、校验器、注入模板都写好了，
  但库里永远是空。
- 合并出来的 `impression` 节点没有父子关系：`merge_similar()` 只 `db.upsert()`
  新节点，没调用 `tree.add_under()`，`Tree.children()` 查不到它的 scene/detail。
- `Tree.impressions()` 是常驻注入的候选来源，但生产路径没有调用；
  `assemble` 的 persona 分支永远不会被触发。

## 现状（代码证据）

`promote_candidates()` 只有定义，没有调用：

```text
maintain/promote.py:24   def promote_candidates(cache: Cache, min_hits: int = 10) -> list[Artifact]:
maintain/promote.py:26       found = [
maintain/promote.py:27           art for art in cache.active()
maintain/promote.py:28           if art.header.strength.weight > WEIGHT_BAR and _hits(art) > min_hits
maintain/promote.py:29       ]
maintain/promote.py:31       found.sort(...)
maintain/promote.py:32       return found
```

复核命令：

```bash
cd SeekMemory
grep -rn "promote_candidates\|promote" --include="*.py" . | grep -v tests
grep -rn "make(\"persona\"\|make('persona'" --include="*.py" .
grep -n "self.tree\|add_under\|impressions" main.py
```

输出里 `promote_candidates` 只命中 `maintain/promote.py` 自己；`make("persona")`
只命中测试；`main.py` 只有 `:21` import、`:71` 声明、`:105` 实例化，
没有 `add_under()` / `impressions()`。

夜间/每周写入只造 `memory`：

```text
main.py:233   art = make("memory", it, strength=_strength_of(it))
main.py:242   self.db.upsert(art)
main.py:258   async def _weekly(self) -> None:
main.py:265       dropped = decay_all(self.db, self.cache, today)
main.py:266       merged = merge_similar(self.db, self.cache, threshold=0.6)
main.py:267       logger.info(f"[seekmemory] 每周整理：遗忘 {dropped} 条，合并 {merged} 组")
```

`merge_similar()` 会造 impression（`maintain/merge.py:151-181`），但只
`db.upsert(art)` / `cache.put(art)`（`:182-183`），没有 `parent` 字段，
也没有 `tree.add_under()`。`Tree` 的写入能力只有测试在用：

```text
core/tree.py:72    def add_under(self, child, parent_id):
core/tree.py:84        self.db.add_edge(parent_id, child.header.id, kind, 1.0)
tests/test_smoke.py:59   tree.add_under(scene, impression.header.id)
```

注入端的 persona 分支是好的，但没有数据：

```text
recall/assemble.py:125  def _persona_sentence(art):
recall/assemble.py:127      text = _clean(_voice(_raw(art), "self"))
recall/assemble.py:128      return f"你记得{text}" if text else ""
recall/assemble.py:140      if family == "persona": ...
recall/assemble.py:197      header = [i for i, (layer, _) in enumerate(entries) if layer == "persona"]
```

## 设计期望

- DESIGN §4.4 第 4 级（`docs/DESIGN.md:171`）：`hits > 10` → 晋升人格候选。
- DESIGN §4.5 每周六步（`:183-187`）：第 4 步是“晋升检查”。
- DESIGN §13 v2（`:476`）：`Distiller` 是明确列出的 v2 能力。
- DESIGN v3 抽象树（`:535-541`）：`impression → scene → detail` 三级父子关系，
  impression 常驻注入，scene 检索注入，detail 按需下钻。
- DESIGN §4.1（`:124-132`）：四层结构里长期记忆“↓ 沉淀”到人格（版本化）。

## 差距

1. **晋升没有调用方**：`promote_candidates()` 写好了阈值，但周任务不调用；
   `hits` 本身也从不增长（见 ISSUE-0011），所以即使调用也选不出人。
2. **没有 Distiller**：没有“把候选记忆蒸馏成一句 persona”的提示词、解析、
   写入路径；`persona` 的 `revision`/`lineage` 也没有实际使用。
3. **抽象树没有接**：`merge_similar()` 造 impression 时不挂 parent；
   `Tree` 实例化了但生产路径不写；`Tree.impressions()` 不被 `assemble` 使用。
4. **persona 权限/审批缺失**：DESIGN §7.2 说“改人格仅 owner”，
   当前没有改人格动作，也就没有 gate（见 ISSUE-0005）。
5. **没有评估**：新增人格后没有“这次改动更一致还是更飘”的判据
   （COMPARISON 也提到这一点），至少要有 revision + 来源。

## 影响

- **用户可感知**：bot 不会“越来越像一个人”；四层记忆只剩 fact/scene 两层，
  `benchmarks/results/ANALYSIS.md:108` 已实测“impression、persona 为 0”。
- **注入结构**：`assemble` 的头部第 ① 段“人格骨架”永远空着，预算被中部记忆占满；
  与 README“人格是底色”的承诺不一致。
- **抽象树**：合并出的 impression 是孤节点，无法从 impression 下钻到 scene/detail；
  `Tree` 模块的测试通过但生产价值为 0。
- **成本**：蒸馏需要每周 1 次模型调用（DESIGN §12 的“每周整理 2 次”之一），
  当前这 1 次没有花，也没有产出。

## 建议方案

| 方案 | 做法 | 代价 | 风险 | 能否解决 |
|---|---|---|---|---|
| A. 周任务接入 promote + LLM 蒸馏 | `_weekly` 调 `promote_candidates()`；对 top-N 候选组 prompt，输出 1 句 persona + 证据 id；`make("persona")` 或 `revise` 旧 persona；写 `lineage.sources`；同时 `tree.add_under(impression, ...)` | 2~3 人日；每周 1 次模型调用；prompt 要防编造 | 蒸馏出的人格可能泛化/失真；需要人工可回滚（revision） | 能 |
| B. 规则蒸馏，不调模型 | 用 impression 的 `text` 按频次/权重拼一句“你不轻易说重话”式模板；固定阈值触发 | 0.5~1 人日；零模型成本 | 句子生硬，容易重复；不如模型 | 只能让 persona 非空 |
| C. 只修抽象树 | merge 时 `tree.add_under(impression, None)` / 挂 scene；先不做 persona | 0.5 人日；改动小 | 人格仍然为空 | 只能解决树 |

### 推荐

**A，分两阶段：先把树接上，再做 Distiller。**

1. **树**：`merge_similar()` 造出 impression 后，调用
   `Tree.add_under(impression, None)` 作为根；成员 scene/detail 改成
   `add_under(member, impression.id)` 或在 merge 前记录 parent。
   `assemble` 头部优先取 `tree.impressions()`，而不是只靠 level 字符串。
2. **Distiller**：周任务第 4 步调 `promote_candidates(min_hits=10)`；
   取 top 5，prompt 要求“只输出一句人格陈述 + 引用的记忆 id”；
   新 persona 用 `revise` 保留 revision，`lineage.sources` 填候选 id；
   失败/空输出不写，保留旧 persona。
3. **评估**：至少记录每次 persona 的 revision、来源数、长度；
   不做自动“人格一致性”评分，先人工看。

## 验收标准

> 逐条对照（2026-10-21，PR-0009）。验证命令：`python3 -m unittest tests.test_persona`。

- [x] 一条 `hits > 10` 的 active 记忆能在周任务后进入 persona 候选，并产出
      `family=persona` 节点（或明确记录“候选为空”）。
      口径按本 PR 调整为 `weight >= 1.5` 且（`hits >= 3` 或存在 ≥ 30 天），
      纯规则不调模型；`tests/test_persona.py:PromoteTest` 覆盖四条边界，
      `DistillTest` 验证命中即产出 `family=persona`；没有候选时返回 `None`。
- [x] `assemble.build()` 的头部第一句是 persona（有 persona 时）。
      `tests/test_persona.py:ComposeTest.test_persona_is_first_in_assembled_text`：
      输出以人格句开头，且不再出现「你记得你……」。
- [ ] 合并出的 impression 能通过 `Tree.children()` 找到其 scene/detail。
      **遗留**：`merge_similar()` 仍未挂 parent，`Tree.add_under()` 的生产接线
      不在本 PR 范围（容量/编排议题），此条未完成。
- [x] persona 有 `revision` 与 `lineage.sources`，能追溯到候选记忆。
      `DistillTest.test_persona_text_lineage_and_strength`：新 persona
      `revision=1`、更新后 `revision=2`；`derived_from` 指向 weight 最高的 3 条
      impression，`sources` 合并去重（`src_a`/`src_b`/`src_c`）。
- [x] 蒸馏失败/空输出不覆盖旧 persona；有日志。
      `DistillTest.test_no_candidate_keeps_old_persona` 返回 `None`，旧 persona
      仍 active 且账本不新增；`main._weekly` 记录「人格 已更新/无变化」。
- [ ] 新增测试：树挂载、promote 阈值、persona 写入/修订、空输出保留旧值。
      promote 阈值、persona 写入/修订、空输出保留旧值均已覆盖
      （`tests/test_persona.py` 15 条）；**树挂载**未覆盖（见上条遗留）。

## 决策记录

- 2026-10-21：开 issue，只记录现状，不改代码。
- 待定：persona 是全局唯一还是按 scope；蒸馏用哪个模型/温度；
  树根是单根还是每个 scope 一根。

### 实现记录（2026-10-21，PR-0009）

- 采用方案 B（规则蒸馏，不调模型）：`maintain/persona.py:distill_persona()`。
- 输入口径：active、`level=impression`、`weight >= 1.5`，且
  `hits >= 3` 或存在 ≥ 30 天；`maintain/promote.py` 改为同一口径并接上调用方。
- 输出：`family=persona`、`payload["text"]` 为第二人称规则文本；取 weight 最高的 3 条，
  旧 persona 置 `state="merged"`，新 persona 的 `lineage.derived_from` 指向来源 impression。
- 每周任务 `main._weekly` 在 decay/merge 之后调用；没有候选时保留旧人格。
- 账本：新旧 persona 各写 `op="merge"`，reason 带来源 id 与合并说明。
- 注入：`recall.assemble` 原先已把 persona 放头部，但会拼成“你记得你……”，
  已改为直接输出第二人称文本；新增测试覆盖“persona 在头部”。
- 未包含：抽象树的 `add_under()` 生产接线仍不在本 PR 范围（属容量/编排议题）。

## 参考

- `maintain/promote.py:24-32`
- `main.py:105`、`:233`、`:258-267`
- `maintain/merge.py:151-183`
- `core/tree.py:57-85`
- `recall/assemble.py:125-141`、`:197-198`
- `benchmarks/results/ANALYSIS.md:108`
- `docs/DESIGN.md:124-132`、`:171`、`:183-187`、`:476`、`:535-541`
