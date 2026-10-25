# maintain · 维护

## 职责

让长期记忆像人一样“忘、并、升、省”。

`decay.py` 按遗忘曲线重算留存率，把 `R < 0.3` 的 active 节点标成 `forgotten`；`merge.py` 在 scene/detail 超过 500 条时，把最旧一批里相似的节点合并成 `impression`；`promote.py` 挑出稳定成印象的节点作为人格蒸馏候选；`persona.py` 把候选按规则拼成第二人称人格；`link.py` 在写入时建 similar/temporal 边；`reflect.py` 用纯规则从用户前后两轮反应里读出“说错了 / 说对了”的信号。这里不调模型，也不改 `docs/`。

## 对外接口

```python
from maintain.decay import decay_all
from maintain.link import link_new, persist
from maintain.merge import merge_similar
from maintain.persona import distill_persona
from maintain.promote import promote_candidates
from maintain.reflect import signals, should_reflect

dropped = decay_all(artifacts, cache, "2026-10-21")       # 被标 forgotten 的数量
merged = merge_similar(artifacts, cache, 0.6, 50)         # 新生成的 impression 数量
edges = persist(art, artifacts, cache, graph)             # 写入 + 建边，返回新增边数
candidates = promote_candidates(cache)              # 稳定 impression，list[Artifact]
persona = distill_persona(artifacts, sources, cache, "2026-10-21")  # 新 persona 或 None
result = signals("我今天去面试了", "不是这个意思")  # {"wrong": 2, "right": 0, "reasons": [...]}
if should_reflect(result):
    ...
```

- 衰减以 `time.updated`（没有则 `time.created`）为锚点，按 `payload["shape"]` 调 `core.strength.retention`；只有 `retention < 0.3` 才淘汰，并写 `artifacts`、`cache.remove`、`ledger_append("forget", ...)`。
- 合并只在 active 的 scene/detail **总数 > 500** 时触发；每簇至少 3 条，`derived_from` 指向簇内 id，`weight = 簇内最大 weight × 1.2`，原节点置 `merged`。文本不用模型，由 `_summarize_texts` 拼成“他经常……”的句子。
- 写入建边：同 scope、内容二元组重合度 > 0.45 的 active memory 最多连 3 条 `similar`（权重 = 重合度）；同一天写入的最多连 2 条 `temporal`（权重 0.3）；单节点总边数 ≤ 5。`causal` 暂不自动建，显式接口是 `Graph.link_causal()`；建边失败只损失边，不影响写入。
- 晋升条件：`strength.weight >= 1.5`，且 `strength.hits >= 3` 或已存在 ≥ 30 天；只取 active 的 `level=impression`，按强度降序返回。
- 人格沉淀：取候选前 3 条，规则拼成第二人称文本；旧 persona 置 `merged`，新 persona 的 `derived_from` 指向来源 impression，并写 `op="merge"` 账本。没有候选时保留旧人格。
- 反思阈值：明确否定 `wrong +2`；与上轮二元组重合 > 0.6 `+1`；本轮长度 < 上轮 50% `+1`；追问/展开 `right +1`；`wrong >= 2` 才反思。

## 约定

- Dependency direction is one-way: import core and app.ports only.
- Write order: artifacts.commit first, then cache update.
- 所有公开函数带类型标注和中文 docstring；单文件控制在 200 行以内。
- 维护任务失败不应影响聊天：调用方负责 fail-open，本目录只抛真实错误，不吞掉业务异常。


Self-impression note: `maintain/self_impression.py` aggregates repeated `bot_action` fields into `subject_id=bot:self`; `distill_self_persona()` is the production persona path. `distill_persona()` remains a legacy compatibility path for per-user impressions.
