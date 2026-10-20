# core/ —— 记忆原语

## 管什么

`core/` 只放与存储、平台无关的原语：

- **Artifact**：统一头（id/family/revision/state/scope/lineage/strength/time/said_by/shareable）
  + 按 family 区分的 payload。结构只在这里定义，并提供 `make` / `revise` / `validate` / `content_of`。
- **强度**：艾宾浩斯留存率 `R = e^(-t/S)`、衰减权重、三种强化来源、30 分钟命中冷却。
  `S` 的形状系数为 point 1.0 / span 1.2 / pattern 3.0 / rule 999.0，
  情绪系数按 arousal 与 valence 叠加；基础寿命 `BASE_DAYS = 30` 天。
- **抽象树**：`impression → scene → detail` 的父子关系、直接子节点与常驻印象查询。
- **关系图**：`similar` / `causal` / `temporal` 边的写入，按 kind 过滤的邻居查询。

不管的事：SQL、缓存、检索、抽取、定时任务、AstrBot 事件。
`make()` 只构造不校验；写入前由调用方显式调用 `validate()`。

## 文件表（含行数）

| 文件 | 行数 | 职责 |
|---|---:|---|
| `artifact.py` | 155 | dataclass、`make` / `revise` / `validate` / `content_of` |
| `strength.py` | 116 | `retention` / `decayed_weight` / `reinforce` / `hit_cooldown_ok` |
| `tree.py` | 85 | `Tree`：三级父子关系、`children` / `impressions` / `add_under` |
| `graph.py` | 53 | `Graph`：关系边写入与邻居查询 |
| `families/__init__.py` | 0 | 空包标记 |
| `families/memory.py` | 46 | memory：必填 text/level，校验 level 与 shape/chrono/about |
| `families/example.py` | 27 | example：user/assistant 对话样本 |
| `families/persona.py` | 14 | persona：非空 text |
| `families/media.py` | 27 | media：type/title/url，摘要可选 |
| `families/secret.py` | 23 | secret：ref + shadow_text（只留影子） |
| `families/designated.py` | 29 | designated：text + trigger + given |
| `__init__.py` | 0 | 空包标记 |
| `README.md` | 53 | 本文件 |

## 依赖方向

```
core/artifact.py ──→ core/families/*.py      （按 family 分派校验）
core/strength.py ──→ core/artifact.py
core/tree.py     ──→ core/artifact.py
core/graph.py    ──→ （只用 typing，无 core 内依赖）

perceive/  recall/  maintain/  main.py
                 │ import
                 ▼
               core/  ←── store/（store 会 import core.artifact）
```

- `core/` 只依赖标准库（dataclasses / typing / math / datetime）。
- `core/` **不 import** `astrbot`、`store/`、`recall/`、`perceive/`、`maintain/`、`main.py`。
- `Tree` / `Graph` 通过构造函数接收 `db`、`cache`，只调用 CONTRACT 里的方法；
  `Tree` 还会探测可选的 `db.set_parent`（存在才用）。core 自己不写 SQL。
