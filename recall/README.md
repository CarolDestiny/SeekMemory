# recall · 检索与组装

## 管什么

输入一条用户消息和当前记忆池，输出一段可直接拼进 system prompt 的中文记忆。
链路是 `seeds → activate → score → select → build`：找种子、沿关系边扩散激活、
综合打分、取 top-k 并留 10% 探索位、最后改写成叙述句。全程纯本地计算，不调模型；
任何一条坏记忆都在函数内 fail-open，不影响聊天。

## 文件表

| 文件 | 行数 | 职责 |
| --- | ---: | --- |
| `__init__.py` | 0 | 空包标记 |
| `seed.py` | 66 | `seeds()`：二元组重合度 + 梗标签加分，取 top-limit 个种子 id |
| `spread.py` | 71 | `activate()`：每跳乘 0.5、每轮只留 top 20 的激活扩散 |
| `score.py` | 139 | `score()` 按 DESIGN 5.1 打分；`select()` 取 top-k + 10% 探索 |
| `assemble.py` | 199 | `build()`：叙述化组装，超预算先砍 example 再砍 detail |
| `README.md` | 33 | 本文件 |

## 依赖方向

```
seed      → core.artifact (Artifact, content_of)
spread    → core.graph (Graph), store.cache (Cache)
score     → core.artifact, recall.seed (overlap, tags_of)
assemble  → core.artifact (Artifact, content_of)
```

只向下依赖 `core/` 与 `store/`，不反向依赖、不 import `astrbot`、不碰 SQL。
`build()` 信任 `arts` 的传入顺序就是相关度降序；`select()` 的 `activation`
可选，直接接 `activate()` 的返回值即可；`now_days` 传「距今多少天」或
绝对天数（epoch days / ordinal）都能被 `score()` 正确归一。
