# SeekMemory

**SeekMemory makes your agent bot more like people.**

<p align="center">
  <img alt="python" src="https://img.shields.io/badge/python-3.10%2B-blue">
  <img alt="license" src="https://img.shields.io/badge/license-MIT-green">
  <img alt="astrbot" src="https://img.shields.io/badge/AstrBot-4.x-76bad9">
  <img alt="lines" src="https://img.shields.io/badge/code-2.6k%20lines-lightgrey">
</p>

一个给 IM 机器人用的**分层记忆系统**。它不是"把对话塞进向量库、每次捞前五条"那种检索增强，而是一套完整的人类记忆模型：**印象沉淀、艾宾浩斯遗忘、情绪着色、激活扩散检索、跨会话人格养成**。

> 人记得的是印象。
>
> 你不会记得 10 月 18 号 23:40 对方说了什么，但你记得"那阵子他不太好"。SeekMemory 复现的是后者。

---

## 功能表

| 能力 | 实现 |
|---|---|
| **记忆分层** | `印象 impression` → `场景 scene` → `细节 detail`，三层抽象树，检索按层下钻 |
| **短期缓冲** | 当日话题按"话题单元"聚合，24h 后才判断是否沉淀，避免"早上说辞职、晚上说算了"被记错 |
| **遗忘曲线** | 艾宾浩斯 `R = e^(−t/S)`，`S` 由显著度、有效命中、形状、情绪四因子决定 |
| **情绪着色** | `arousal`（唤醒度）× `valence`（正负效价）双维：高唤醒负效价几乎不忘，低唤醒负效价快速褪色 |
| **首因效应** | 最早三条记忆不参与衰减，作为人格底噪 |
| **记忆强化** | 四来源：被检索 +0.1 / 她主动说出 +0.3 / 对方确认 +0.2 / 共同经历 ×1.5 |
| **命中冷却** | 30 分钟窗口内的重复命中合并计一次，跨天一天最多一次 |
| **激活扩散** | 非精确匹配：种子激活 → 沿 `similar/causal/temporal` 三型边扩散 → 按激活度取候选 |
| **五维打分** | 字面重合 ×3.0 + 标签 ×2.0 + 情绪 ×1.5 + 权重 ×1.0 + 新鲜度 ×0.5，减去近期使用与 hot 惩罚 |
| **10% 探索** | 九成按分数取最相关，一成随机捞一条不相关的——让她偶尔"突然想起别的事" |
| **内容寻址** | 所有记忆内容按 `sha256` 寻址存 blob，天然去重，为将来同步/回滚留好格式 |
| **不可变历史** | 追加日志 + 哈希链，每条写入可重放、可校验、可 diff 任意两个时间点 |
| **证据分离** | `Source`（原始对话，只追加不可改）与 `Artifact`（她的理解，可修订）分离，理解错了能回到原话对账 |
| **人格蒸馏** | 高频记忆晋升为 `persona` 家族，从"记得"变成"是这样的人" |
| **指定交付** | `family=designated`：明确托付的内容（"帮我记一下密码"），私聊 + 触发词才归还 |
| **影子记忆** | `scope=shadow`：秘密只留"有这件事"，内容锁死当事人，影响沉淀为守口的人格 |
| **RBAC** | `owner / trusted / guest / blocked` 四角色，权限跟人走不跟群走，按发送者判权 |
| **自我反思** | 纯规则信号（明确否定 / 重复解释 / 回复骤短 / 追问接梗），24h 冷处理后才确认，错误留负权重 |
| **叙述式注入** | 注入的是"你印象里他有点倔"这样的叙述句，不是项目符号列表 |
| **三档不确定** | `confidence > 0.9` 直说；`0.6~0.9` 说"你好像说过"；`< 0.6` 说"我是不是听你提过" |
| **相对时间** | 数据存绝对时间戳，注入时翻译成"三天前""上个月" |
| **metamemory** | 区分"我忘了"和"你没说过"，同话题有 forgotten 记忆时说前者 |
| **预算组装** | `PreparedContext` 模式：头部常驻人格与印象，中部可丢，尾部给本轮消息，总预算 2000 字 |
| **抗迷失** | 按 lost-in-the-middle 现象排布：越影响"她是谁"越靠上，越影响"这次怎么回"越靠下 |
| **fail-open** | 任何记忆模块异常都不影响正常回复，只记日志 |
| **零命令交互** | 没有 `/memory` `/forget`，想看什么直接问，想让她忘就用话跟她说 |

---

## 记忆架构

```
Layer 0  Source      原始对话，只追加、不可改、永不删
Layer 1  Artifact    从 Source 提炼的记忆，可修订、会错、允许矛盾
Layer 2  Persona     从 Artifact 沉淀的人格，版本链可回溯
```

**通用头 + 类型化 payload**（借鉴 OceanBase PowerContext 的 Artifact 模型）：头部十字段锁定行为语义——`family / revision / state / scope / lineage / strength / time / said_by / shareable`；payload 按家族区分。加能力是加 `family`，不是给表加列。

| family | 语义 |
|---|---|
| `memory` | 普通记忆，含 `level / shape / chrono / about` 四维 |
| `persona` | 人格骨架，版本化 |
| `example` | 人格语料（few-shot 问答对） |
| `media` | 媒体引用，只存摘要与 URL |
| `secret` | 秘密影子，只留"有这件事" |
| `designated` | 指定交付，触发词归还 |

---

## 遗忘

```
R = e^(−t / S)
S = BASE_DAYS × salience × (1 + 0.5 × hits) × shape × emotion
```

| 因子 | 取值 |
|---|---|
| `salience` | 权重截断到 `[0.3, 3.0]`，重要的事寿命长 |
| `shape` | `point 1.0` / `span 1.2` / `pattern 3.0` / `rule 999.0` |
| `emotion` | 高唤醒 ×1.5，低唤醒 ×0.8；负效价叠加：高唤醒再 ×1.5，低唤醒再 ×0.6 |

留存率跌破 `0.3` 即标记 `forgotten`：**不删除，只是不再注入**。`forgotten` 超过 180 天且无引用才物理清理。

---

## 上下文

```
┌ 头部：常驻（她是谁）
│  人格骨架 · 关系状态 · 最相关记忆
├ 中部：可丢（偶尔想起）
│  历史摘要 · 事实类记忆 · 检索式语料
├ 尾部：高注意力（这次怎么回）
│  最近两轮原文 · 本轮消息
└
总预算 2000 字，超限按 语料 → 事实 → 摘要 的顺序砍
```

**每轮对话零模型调用。** 检索在内存完成，只有夜间抽取与每周整理才调模型。

---

## Benchmark

两个指标，跑 `python3 benchmarks/run.py`，固定数据可复现。

### 指标一：像人

**综合像人指数：`98 / 100`**

| 维度 | 权重 | 结果 | 含义 |
|---|---|---|
| 层级命中率 | 30% | **100%** | 问"你觉得我怎么样"命中印象层 |
| 叙述化比例 | 20% | **100%** | 注入文本无项目符号，全为叙述句 |
| 遗忘正确性 | 25% | **15/15** | 重要 12 条全留，琐事 3 条全忘 |
| 强化有效性 | 15% | **2.1×** | 多次提及的记忆权重显著高于一次性的 |
| 召回命中率 | 10% | **86%** | 期望记忆出现在 top-8 |

### 指标二：Token

**1000 条记忆时压缩 `98×`，每轮额外模型调用 `0` 次。**

| 记忆条数 | 朴素全量注入 | SeekMemory | 压缩比 |
|---|---|---|---|
| 50 | 674 字 | 161 字 | 4× |
| 200 | 2821 字 | 147 字 | 19× |
| 500 | 7145 字 | 147 字 | 49× |
| 1000 | 14452 字 | 147 字 | **98×** |

**记忆量翻二十倍，注入成本持平。** 检索式注入对全量注入的本质优势。

---

## 快速开始

```bash
cd <AstrBot>/data/plugins
git clone https://github.com/<you>/SeekMemory astrbot_plugin_seekmemory
```

重启 AstrBot，WebUI → 插件 → SeekMemory 配置：

```jsonc
{
  "owner_umo": "napcat:FriendMessage:123456",   // 只从这个会话抽取
  "open_to": "owner_only",                       // owner_only | owner_and_trusted | everyone
  "budget_chars": 600,
  "recall_k": 8,
  "summary_time": "23:50"
}
```

跑测试与基准：

```bash
python3 tests/test_smoke.py
python3 benchmarks/run.py
```

---

## 设计来源

| 来源 | 借了什么 |
|---|---|
| [PowerContext](https://github.com/oceanbase/powercontext) | Source/Artifact 分离、通用头 + 类型化 payload、`PreparedContext` 有界视图、写入决策门控 |
| git | 内容寻址、不可变历史、追加日志、Merkle 式校验 |
| 认知科学 | 艾宾浩斯遗忘曲线、闪光灯记忆、激活扩散、首因效应、metamemory |

---

## License

MIT
