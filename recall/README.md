# recall · 检索与组装

## 管什么

输入一条用户消息和当前记忆池，输出一段可直接拼进 system prompt 的中文记忆。
链路是 `visible → seeds → activate → score → select → build`：先按 scope 过滤
候选池，再找种子、沿关系边扩散激活、综合打分、取 top-k 并留 10% 探索位、
最后改写成叙述句。全程纯本地计算，不调模型；任何一条坏记忆都在函数内
fail-open，不影响聊天。

## 文件表

| 文件 | 行数 | 职责 |
| --- | ---: | --- |
| `__init__.py` | 0 | 空包标记 |
| `scope.py` | 64 | `visible()`：private 只给归属会话，shared / shadow 全员可见 |
| `designated.py` | 85 | 指定记忆交付：私聊 + 触发词 + given 三条硬条件 |
| `seed.py` | 173 | `seeds()`：二元组重合度 + 梗标签加分，取 top-limit 个种子 id |
| `spread.py` | 75 | `activate()`：每跳乘 0.5、每轮只留 top 20 的激活扩散 |
| `score.py` | 247 | `score()` 按 DESIGN 5.1 打分；`select()` 取 top-k + 10% 探索 |
| `assemble.py` | 264 | `build()`：叙述化组装；shadow 只给影子句，超预算先砍 example 再砍 detail |
| `README.md` | 41 | 本文件 |

## 依赖方向

```
scope       → core.artifact (Artifact)
designated  → core.artifact (Artifact, revise)
seed        → core.artifact (Artifact, content_of)
spread      → core.graph (Graph), store.cache (Cache)
score       → core.artifact, recall.seed (overlap, tags_of)
assemble    → core.artifact, recall.designated (deliverable, triggers_of)
```

只向下依赖 `core/` 与 `store/`，不反向依赖、不 import `astrbot`、不碰 SQL。
`build()` 信任 `arts` 的传入顺序就是相关度降序；`select()` 的候选既可以是
裸 `Artifact`，也可以是 `(Artifact, activation)` 二元组（`main.py` 即后者）；
`now_days` 传 0 会用 `time.created` 推算年龄，传正小数视为年龄，传大数
视为绝对天数（epoch days / ordinal）。`build()` 的 `text` / `is_private` 是
可选会话上下文：不传时 designated 只给托付提示（旧行为），传了才按三条硬
条件交付正文。
