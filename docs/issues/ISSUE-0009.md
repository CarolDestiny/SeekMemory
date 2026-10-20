# ISSUE-0009 写入从不建联想边：激活扩散永远只返回种子，扩散贡献为 0

> 一句话：`Graph.link()` / `DB.add_edge()` 都写好了，但生产写入路径
> （`main._nightly`）只 `db.upsert()`，从不建边；抽取提示词里也没有 `links` 字段。
> 所以 `activate()` 的返回值就是种子本身，`ANALYSIS.md` 实测扩散新增候选为 0。

| 项 | 值 |
|---|---|
| 编号 | ISSUE-0009 |
| 级别 | P2（能力缺失：联想检索没有数据基础） |
| 状态 | open |
| 报告人 | 审计记录（agent） |
| 日期 | 2026-10-21 |
| 关联 PR | 待开（建议分支 `feat/issue-0009-link-writer`） |
| 影响版本 | `main` @ `1be8baa` |
| GitHub | 待同步 |

## 症状

- “命中 A → 沿 links 扩 1 跳，最多 2 条”的联想效果不存在；检索结果永远只来自
  字面命中的种子。
- 新写入的记忆之间没有 `similar/causal/temporal` 边；`edges` 表在生产库里为空。
- `scale.py` 的 6/6 里，激活扩散没有贡献；`e2e.py` 的图边是脚本手工
  `graph.link()` 造的（`benchmarks/e2e.py:109`），不代表生产。

## 现状（代码证据）

边的写入 API 存在：

```text
core/graph.py:21   def link(self, src: str, dst: str, kind: str, weight: float) -> None:
core/graph.py:23       if kind not in KINDS:
core/graph.py:29       self.db.add_edge(src, dst, kind, float(weight))

store/db.py:137    def add_edge(self, src, dst, kind, weight):
store/db.py:141        "INSERT INTO edges(src, dst, kind, weight) VALUES(?, ?, ?, ?) ..."
```

生产写入路径没有调用：

```text
main.py:230       written = 0
main.py:231       for it in items[:3]:
main.py:233           art = make("memory", it, strength=_strength_of(it))
main.py:242           self.db.upsert(art)
main.py:243           if self.cache:
main.py:244               self.cache.put(art)
main.py:245           written += 1
```

`grep -rn "graph.link\|add_edge" --include="*.py" .` 只命中：

```text
core/tree.py:84      self.db.add_edge(parent_id, child.header.id, kind, 1.0)
core/graph.py:29     self.db.add_edge(src, dst, kind, float(weight))
tests/test_smoke.py:61
tests/test_store.py:142-143
benchmarks/e2e.py:109
```

`core/tree.py:84` 是抽象树的 `tree_child:<parent>` 边，不是联想边；`Graph.link`
在生产路径没有调用方。抽取提示词也没有要求模型输出 links：

```text
perceive/extract.py:22   每条输出一个对象，字段固定：
perceive/extract.py:23   - level: ...
perceive/extract.py:24   - text: ...
perceive/extract.py:25   - about: ...
perceive/extract.py:26   - arousal: ...
perceive/extract.py:27   - valence: ...
perceive/extract.py:28   - funny: ...
perceive/extract.py:29   - first: ...
```

扩散模块本身是好的，但只能从种子出发：

```text
recall/spread.py:56    scores = {sid: MAX_ACTIVATION for sid in seed_ids if sid}
recall/spread.py:57    frontier = dict(scores)
recall/spread.py:61        for nid, weight in _neighbours(graph, node_id):
recall/spread.py:64            contribution = value * DECAY * _weight(weight)
```

种子为空时 `scores = {}`，循环不执行，返回空激活（ISSUE-0001 的复现场景）。

## 设计期望

- DESIGN §5.1（`docs/DESIGN.md:228`）：命中 A → 沿 `links` 扩 1 跳，最多 2 条。
- DESIGN 统一模型（`:52`）：`links: []` 是记忆的一部分。
- DESIGN v3 关系边（`:543-549`）：`similar A ↔ B`、`causal A → B`、
  `temporal A ~ B`。
- DESIGN v3 激活扩散（`:551-555`）：
  `种子提取 → 激活种子 → 沿边扩散（衰减）→ 按层裁剪 → 取 top-k`。
- DESIGN §12（`:454-462`）：检索每轮 0 次模型调用，边应在写入/整理时建好。

## 差距

1. **没有建边策略**：写入时没有“相似/因果/同期”判断，也没有“先查最近 N 条
   再连边”的逻辑。
2. **抽取不产出 links**：模型没有机会指出“这条和那条有关”；`payload.links`
   即使被模型写上，也没有代码消费成 `edges`。
3. **整理不建边**：`merge_similar()` 只写 `lineage.derived_from`，
   不写 graph 边；`Tree.add_under()` 只写树边。
4. **没有出度上限/清理**：即使以后建边，也需要防止每个新节点连所有旧节点；
   DESIGN 没有给出出度策略，需要补。
5. **benchmark 没验证**：`scale.py` 不建边，`e2e.py` 手工建边；
   没有“有边 vs 无边”的对照，扩散价值无法证明。

## 影响

- **用户可感知**：她不会“由一件事想起另一件事”；只有字面重合才能召回。
- **ISSUE-0001 无解**：零字面重合时 seeds=0，扩散也救不回来；建边是跨过
  字面鸿沟的最低成本路径之一（另一条是向量，见 ISSUE-0001）。
- **基准失真**：`scale.md` 的 6/6 不能归功于激活扩散；`benchmarks/results/ANALYSIS.md:109`
  已明确“0 个新增候选”。对外引用时必须说明。
- **成本**：写入时建边是纯本地规则，零模型；现在等于把设计里最便宜的联想能力
  闲置。

## 建议方案

| 方案 | 做法 | 代价 | 风险 | 能否解决 |
|---|---|---|---|---|
| A. 写入时规则建边 | 新记忆写入后，取同 scope 最近 N 条（如 20），按 bigram 相似度 >0.3 建 `similar`；同一天/相邻天建 `temporal`；标签/因果词（因为/所以/后来）建 `causal`；每节点出度 ≤5，权重按相似度 | 1~2 人日；纯本地；需要调阈值 | 误连边会扩散噪声；出度控制不好会放大热门节点 | 能，覆盖大部分联想 |
| B. 抽取时让模型给 links | prompt 增加 `links: [{"to": "记忆原文/序号", "kind": "..."}]`；写入时解析成边 | 1~2 人日；增加输出长度/解析失败 | 模型可能编造目标；需要稳定 id 映射 | 能，语义更好 |
| C. 夜间批量相似度 | 每周对新写入的一批做两两相似，过阈值建边 | 0.5~1 人日；实现简单 | O(n²)；只能补相似边，没有因果/时序 | 只能解决相似 |

### 推荐

**A 先落地，B 作为增强。**

1. `main._nightly` 写入每条新记忆后，调一个 `link_new(art, cache, graph)`：
   取同 scope 最近 20 条，算 bigram Dice；>0.35 建 `similar`，权重 = 相似度；
   同一天或相邻天建 `temporal`，权重 0.5；命中因果连接词建 `causal`。
2. 每节点出度 ≤5，按权重保留；`Graph.link` 已有 upsert 语义，重复连边只更新权重。
3. 增加 `benchmarks/e2e.py` 不再手工建边，改为调用生产 `link_new`；
   `scale.py` 增加“无边/有边”两列，证明扩散增量。
4. 如果后续要语义边，再在抽取 prompt 里加 `links`，不要让模型直接写 DB。

不建议只做 C：相似边只能解决“说法相近”，解决不了“因为/后来”的时序与因果；
而且 O(n²) 在 800 条稳态下每周都要跑。

## 验收标准

- [ ] 新写入的记忆在同一 scope 内能自动产生 `similar/temporal` 边；
      `edges` 表非空。
- [ ] 单节点出度不超过配置上限；重复写入不产生重复边。
- [ ] 构造“只在 B 中出现关键词、A 与 B 有边”的用例：查询 A 能通过 1 跳召回 B。
- [ ] `scale.py` 的“有边/无边”对照里，扩散新增候选 >0；`e2e.py` 不再手工建边。
- [ ] 误连边可清理：提供按权重/时间删除边的维护函数（或在下一次整理时重建）。
- [ ] 新增测试：相似/时序/因果三类边、出度上限、跨 scope 不连边。

## 决策记录

- 2026-10-21：开 issue，只记录现状，不改代码。
- 待定：相似阈值；出度上限；边权衰减；是否允许跨 scope 建边（默认不）；
  `links` 是 payload 字段还是只存 edges 表。

## 参考

- `core/graph.py:21-53`
- `store/db.py:137-151`
- `main.py:230-245`
- `perceive/extract.py:22-29`
- `recall/spread.py:44-75`
- `benchmarks/e2e.py:109`
- `benchmarks/results/ANALYSIS.md:109`、`:116`
- `docs/DESIGN.md:52`、`:228`、`:543-555`
