# maintain · 维护

## 职责

让长期记忆像人一样“忘、并、升、省”。

`decay.py` 按遗忘曲线重算留存率，把 `R < 0.3` 的 active 节点标成 `forgotten`；`merge.py` 在 scene/detail 超过 500 条时，把最旧一批里相似的节点合并成 `impression`；`promote.py` 挑出反复被命中的节点作为人格蒸馏候选；`reflect.py` 用纯规则从用户前后两轮反应里读出“说错了 / 说对了”的信号。这里不调模型，也不改 `docs/`。

## 对外接口

```python
from maintain.decay import decay_all
from maintain.merge import merge_similar
from maintain.promote import promote_candidates
from maintain.reflect import signals, should_reflect

dropped = decay_all(db, cache, "2026-10-21")       # 被标 forgotten 的数量
merged = merge_similar(db, cache, 0.6, 50)         # 新生成的 impression 数量
candidates = promote_candidates(cache, 10)         # list[Artifact]
result = signals("我今天去面试了", "不是这个意思")  # {"wrong": 2, "right": 0, "reasons": [...]}
if should_reflect(result):
    ...
```

- 衰减以 `time.updated`（没有则 `time.created`）为锚点，按 `payload["shape"]` 调 `core.strength.retention`；只有 `retention < 0.3` 才淘汰，并写 `db`、`cache.remove`、`ledger_append("forget", ...)`。
- 合并只在 active 的 scene/detail **总数 > 500** 时触发；每簇至少 3 条，`derived_from` 指向簇内 id，`weight = 簇内最大 weight × 1.2`，原节点置 `merged`。文本不用模型，由 `_summarize_texts` 拼成“他经常……”的句子。
- 晋升条件：`strength.weight > 1.5` 且 `payload["hits"] > min_hits`，按强度降序返回。
- 反思阈值：明确否定 `wrong +2`；与上轮二元组重合 > 0.6 `+1`；本轮长度 < 上轮 50% `+1`；追问/展开 `right +1`；`wrong >= 2` 才反思。

## 约定

- 依赖方向单向：只 import `core` 与 `store`，不反向 import `main.py`。
- 写入顺序统一为“先 `db.upsert`，再更新 `cache`”；被淘汰/合并的节点必须从 cache 移除。
- 所有公开函数带类型标注和中文 docstring；单文件控制在 200 行以内。
- 维护任务失败不应影响聊天：调用方负责 fail-open，本目录只抛真实错误，不吞掉业务异常。
