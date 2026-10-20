# 代码索引

> 新人从这里开始。三个 README 读完就能改代码：根目录 → 目标文件夹 → 文件头部 docstring。

## 目录总览

| 目录 | 管什么 | 开始读 |
|---|---|---|
| `core/` | **原语**：Artifact 的定义、强度算法、抽象树、关系图 | [core/README](core/README.md) |
| `store/` | **持久化**：SQLite、内存缓存、追加日志 | [store/README](store/README.md) |
| `recall/` | **检索**：种子提取、激活扩散、打分、组装 | [recall/README](recall/README.md) |
| `perceive/` | **抽取**：从对话里提炼印象 | [perceive/README](perceive/README.md) |
| `maintain/` | **维护**：衰减、合并、晋升、反思 | [maintain/README](maintain/README.md) |
| `tests/` | 单元测试 | — |
| `docs/` | 设计文档 | [DESIGN](DESIGN.md) · [CONTRACT](CONTRACT.md) |

## 依赖方向（单向，不许反向）

```
main.py
  ↓
perceive/  maintain/  recall/
  ↓            ↓        ↓
        core/  ←───────┘
          ↓
        store/
```

- `core/` 不 import 任何人
- `store/` 只 import `core/`
- `recall/` `perceive/` `maintain/` 可以 import `core/` 和 `store/`
- **没有任何模块 import `main.py`**

## 两条硬规则

1. **只有 `core/artifact.py` 定义数据结构** —— 改结构只改一个文件
2. **只有 `store/db.py` 写 SQL** —— 换存储只改一个文件

## 一次请求的完整路径

```
QQ 消息
  → main.py  buffer_message      存进当天缓冲
  → main.py  inject_memory
       → recall/seed.py          从消息里找种子
       → recall/spread.py        沿关系边扩散
       → recall/score.py         打分 + 探索
       → recall/assemble.py      按层级措辞，卡预算
  → 拼进 system_prompt 中部
  → LLM 回复
```

## 每晚的路径

```
23:50
  → main.py _nightly
  → perceive/extract.py   抽印象（一次模型调用）
  → store/db.py           写入 + 追加日志
  → store/cache.py        更新内存

周日 23:55
  → maintain/decay.py     重算留存率，标 forgotten
  → maintain/merge.py     相似场景合并成印象
```

## 文件行数约定

- 单文件 ≤ 300 行，目标 150
- 超过就拆，拆的依据是**职责**，不是行数
