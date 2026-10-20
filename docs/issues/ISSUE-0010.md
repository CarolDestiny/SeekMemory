# ISSUE-0010 容量治理只实现了第一级：merge 只看 scene/detail、五级淘汰缺两级、没有 blob 清理

> 一句话：DESIGN 的五级淘汰里，代码只稳定实现了第 1 级（`R<0.3` → forgotten）；
> 第 2 级的 `active>500` 被改成“scene+detail>500”，第 3 级要求相似合并、代码却
> 至少 3 条才成簇；第 4 级晋升没有调用方，第 5 级的 180 天物理清理不存在。
> 首因“最早 3 条不衰减”也没实现。

| 项 | 值 |
|---|---|
| 编号 | ISSUE-0010 |
| 级别 | P2（能力缺失：容量不会按设计收敛，稳态 800 无保证） |
| 状态 | open |
| 报告人 | 审计记录（agent） |
| 日期 | 2026-10-21 |
| 关联 PR | 待开（建议分支 `fix/issue-0010-capacity`） |
| 影响版本 | `main` @ `1be8baa` |
| GitHub | 待同步 |

## 症状

- 记忆条数可以长期超过 500/800：merge 只在“scene+detail”超过 500 时触发，
  而且只在周任务里跑；事实、印象、example、media 不计入。
- 两条相似记忆不会合并，必须凑够 3 条才成一个簇。
- `forgotten` 只是 `state` 变了，`blobs` 里的内容永远不会删；数据库只增不减。
- “最早 3 条不衰减”没有实现：`decay_all()` 不看 `first`，只看 `level=fact`。
- `max_episodes` 配置项存在但从未被读。

## 现状（代码证据）

merge 的触发条件：

```text
maintain/merge.py:34    MAX_ACTIVE = 500
maintain/merge.py:128   def merge_similar(db, cache, threshold=0.6, limit=50):
maintain/merge.py:132       pool = [
maintain/merge.py:133           art
maintain/merge.py:134           for art in list(cache.by_level("scene")) + list(cache.by_level("detail"))
maintain/merge.py:135           if art.header.state == "active"
maintain/merge.py:136       ]
maintain/merge.py:137       if len(pool) <= MAX_ACTIVE:
maintain/merge.py:138           return 0
maintain/merge.py:140       pool.sort(key=lambda art: art.header.time.created or art.header.time.updated or "")
maintain/merge.py:141       batch = pool[: max(int(limit), 3)]
```

只对 `scene/detail` 计数，不含 `fact/impression`；`limit` 默认 50；
`_cluster_indices()` 只返回至少 3 条的簇：

```text
maintain/merge.py:95    def _cluster_indices(texts, threshold):
maintain/merge.py:115       return [indices for indices in groups.values() if len(indices) >= 3]
```

decay 只处理 memory，且只按 retention：

```text
maintain/decay.py:43    for art in list(cache.active()):
maintain/decay.py:44        if art.header.family != "memory":
maintain/decay.py:45            continue
maintain/decay.py:50        level = str(art.payload.get("level") or "")
maintain/decay.py:51        if level == "fact":
maintain/decay.py:52            continue
maintain/decay.py:53        shape = str(art.payload.get("shape") or "point")
maintain/decay.py:54        if retention(...) >= FORGET_BELOW:
maintain/decay.py:55            continue
maintain/decay.py:56        db.upsert(revise(art, state="forgotten"))
```

没有 `first` 判断，没有 `valid_to/expires` 判断，没有物理删除。复核：

```bash
cd SeekMemory
grep -rn "first" --include="*.py" maintain core/artifact.py main.py
grep -rn "DELETE\|delete\|GC\|gc" --include="*.py" store maintain
grep -n "max_episodes" _conf_schema.json main.py maintain/*.py
```

`first` 只出现在 `core/families/memory.py:44-46` 的校验和 `maintain/merge.py:157` 的
`"first": False`，衰减路径没有读。`max_episodes` 只出现在
`_conf_schema.json:54-58`，没有调用方。

## 设计期望

- DESIGN §4.4（`docs/DESIGN.md:164-174`）五级淘汰：

  | 级别 | 触发 | 动作 |
  |---|---|---|
  | 1 | `R < 0.3` | `state = forgotten` |
  | 2 | `active > 500` | 取最旧 50 条进整理 |
  | 3 | 整理中相似 > 0.6 | 合并成 `pattern` |
  | 4 | `hits > 10` | 晋升人格候选 |
  | 5 | `forgotten > 180 天` + 无引用 | 物理删 blob |

  稳态 ~800 条，每天进 3~5 出 3~5。
- DESIGN §4.5（`:176-187`）：定期每周日全量六步；紧急 `active > 500`
  只合并最旧 50 条。
- DESIGN §4.3（`:149-162`）：首因“最早 3 条不衰减”。
- DESIGN §4.3（`:158-159`）：形状系数、情绪系数已实现（`core/strength.py:20-25`、
  `:41-55`），这部分不是缺口。

## 差距

1. **计数口径错**：`active > 500` 被实现成 `scene+detail > 500`，`fact`
   和 `impression` 不计入；一个满是 fact 的库永远不会触发合并。
2. **触发频率错**：只在周任务检查；两次周任务之间可以无限增长。
   紧急触发（active>500）没有独立的每日/每轮检查。
3. **合并门槛错**：设计是“相似 >0.6 合并”，代码要求至少 3 条同簇；
   两条高度相似的老记忆会一直留着。
4. **第 4 级缺失**：`promote_candidates` 无调用方（ISSUE-0006）。
5. **第 5 级缺失**：没有按 `forgotten` 时间 + 引用计数删 blob 的代码；
   `blobs` 只增不减。
6. **首因缺失**：`first` 字段没有参与衰减；最早 3 条与普通记忆一样会 forgotten。
7. **配置未接**：`max_episodes` 是空配置；merge 用硬编码 `MAX_ACTIVE=500`。
8. **非 memory 家族没有生命周期**：`example/media/secret/designated` 不衰减、
   不清理；DESIGN 没有规定，但至少要有 TTL/容量策略，否则会无限增长。

## 影响

- **用户可感知**：记忆越多，检索越慢、噪声越多；该忘的没忘，该合的没合。
- **存储**：`blobs` 永不删除，长期运行后 DB 膨胀；WAL 也会变大。
- **人格**：第 4 级不跑，persona 永远空（ISSUE-0006）。
- **成本**：检索是每轮全量池打分（`main.py:147`），条数不收敛会线性变慢。
- **设计承诺**：README/COMPARISON 的“五级淘汰/稳态 800/180 天物理清理”
  目前只有第 1 级成立。

## 建议方案

| 方案 | 做法 | 代价 | 风险 | 能否解决 |
|---|---|---|---|---|
| A. 按设计补全五级 | 统计算 `cache.active()` 全量；每天检查容量，超过 500 取最旧 50；合并允许 2 条；第 4 级接 promote；第 5 级按 forgotten 时间 + 引用计数删 blob；首因前 3 条打 `first=true` 并豁免；读 `max_episodes` | 2~3 人日；要改 merge/decay/DB，加 GC | 误删 blob 会影响回滚；合并 2 条可能过度抽象；计数/GC 需要锁 | 能 |
| B. 只修计数 + GC | `active` 全量计数；超过 500 触发；加 180 天 GC；其余不动 | 1 人日；风险小 | 合并仍要 3 条；第 4 级仍缺；首因仍缺 | 只能止血 |
| C. 只做容量告警 | 不自动处理，超 800 只记日志/通知 owner | 0.5 人日；最安全 | 不解决膨胀 | 不能 |

### 推荐

**A，按“先计数、再 GC、最后合并策略”的顺序。**

1. 把 `MAX_ACTIVE` 换成 `int(self._c("max_episodes", 500))`，计数用
   `len(cache.active())`，不再只数 scene/detail。
2. 加每日容量检查（可挂在夜间任务），超过阈值取最旧 50 条进 merge；
   周任务仍做全量六步（ISSUE-0007）。
3. `_cluster_indices` 允许 2 条成簇，但两条合并的权重/置信度要打折；
   或者加配置 `min_cluster=2|3`。
4. `decay_all` 里：`first=true` 或最早的 3 条（按 created）跳过；
   `valid_to/expires` 过期直接 forgotten；记录 forgotten_at。
5. 新增 `gc_forgotten(days=180)`：查 `state=forgotten` 且 `updated_at` 超过
   180 天、且没有 active 节点引用同一 blob 的行，删 blob + 节点（或只删 blob，
   保留节点壳）。必须先在测试库验证引用计数。
6. 非 memory 家族先加 TTL 配置，别让它们无限长。

## 验收标准

- [ ] `active` 超过 `max_episodes` 能触发整理，不再只数 scene/detail。
- [ ] 两条相似记忆可以合并（或由配置控制最小簇大小），合并后有 ledger。
- [ ] `first=true` 的最早 3 条在衰减后仍 active；普通低留存记忆正常 forgotten。
- [ ] `forgotten` 超过 180 天且无引用的 blob 会被物理删除；有引用的不删。
- [ ] `max_episodes` 配置生效；默认 500，稳态目标 800 有监控日志。
- [ ] 新增测试：计数口径、2 条合并、首因豁免、GC 引用保护、过期 valid_to。

## 决策记录

- 2026-10-21：开 issue，只记录现状，不改代码。
- 待定：首因按“最早 3 条”还是 `first` 标志；合并最小簇 2 还是 3；
  GC 是删节点还是只删 blob；非 memory 家族的 TTL。

## 参考

- `maintain/merge.py:34`、`:95-115`、`:128-141`
- `maintain/decay.py:37-66`
- `store/schema.sql:6-10`、`:24-40`
- `_conf_schema.json:54-58`
- `docs/DESIGN.md:149-174`、`:176-187`
