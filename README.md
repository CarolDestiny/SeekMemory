# SeekMemory

**SeekMemory makes your agent bot more like people.**

<p align="center">
  <img alt="python" src="https://img.shields.io/badge/python-3.10%2B-blue">
  <img alt="astrbot" src="https://img.shields.io/badge/AstrBot-4.x-76bad9">
  <img alt="license" src="https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-green">
</p>

机器人聊三天就忘了你是谁。上下文一滚，名字、职业、上次面试的结果一起消失，再见面时它客气得像第一次认识；检索增强能捞回几句相似的原话，却拼不出"对一个人的印象"。

SeekMemory 给 AstrBot 补上这一层：把对话沉淀成事实、记忆、印象、人格四级结构，按艾宾浩斯曲线遗忘，按激活扩散检索，用叙述句写回上下文。1000 条记忆时每轮注入 147 字，额外模型调用 0 次。

> 人记得的是印象。
>
> 你不会记得某天深夜对方具体说了什么，但你记得"那阵子他不太好"。

---

## 四层记忆：事实、记忆、印象、人格

> 越往下越具体、越易变；越往上越抽象、越持久。

一条消息先成为缓冲，再成为记忆，最后成为印象。层级由 payload 里的 `level` 与抽象树上的位置决定；人格与印象常驻注入，场景与细节按需下钻。

```
人格 Persona    底色。全局唯一，不分对象，决定"她是谁"
  ↑ 沉淀
印象 Impression 对某一个人的感觉。按 scope 隔离，A 的印象 ≠ B 的印象
  ↑ 提炼
记忆 Memory     场景与细节。会衰减、会褪色、会被合并成印象
  ↑ 抽象
事实 Fact       客观稳定的信息。名字、职业、偏好，不衰减
```

| 层 | 例子 | 衰减 | 作用域 |
|---|---|---|---|
| 事实 | 「他叫吕宇轩」 | 不衰减 | 单一对象 |
| 记忆 | 「他那天加班到两点」 | 艾宾浩斯 | 单一对象 |
| 印象 | 「他有点倔，但心软」 | 极慢 | **按 scope，一人一份** |
| 人格 | 「你不轻易说重话」 | 不变，只增修订 | 全局唯一 |

**人格是底色，只有一个。** 印象是"对某个人"的——她对你的印象和对别人的印象是两份数据，互不覆盖。

- **话题缓冲**：当天对话按话题单元聚合，24 小时后才判断是否沉淀。早上说"要辞职"、晚上说"算了"，写进长期的是后者。
- **写入门控**：每晚 23:50 读缓冲，模型只判断 0~3 条值得沉淀，并为每条标 `about / shape / scope / chrono` 与 strength。写入前按字面去重，重复内容不落库。
- **抽象树**：`impression → scene → detail` 三级父子关系。能合成一句"他有点倔，但心软"，就不留三条原话。
- **人格蒸馏**：`hits` 高的记忆进入人格候选，蒸馏成 `persona` family；`revision` 随修订递增，人格只做增量修订。
- **证据分离**：`Source` 存原始对话、只追加；`Artifact` 存她的理解、可修订。每条结论带 `lineage.sources`，理解错了能回原话对账。

四层共用一套存储与检索。区别只在 `level`、衰减豁免与注入位置：事实永久豁免衰减，印象靠 `shape=pattern` 慢速褪色，人格不参与衰减。

## Artifact 原语：一个头，六个家族

> 加能力是加 family，不是给表加列。

所有记忆共用同一条 `Artifact` 结构：十个通用头字段锁定行为语义，payload 按 family 类型化。结构定义集中在 `core/artifact.py`，SQL 只出现在 `store/db.py`。

```jsonc
{
  "id": "n_01",
  "family": "memory",        // memory | example | persona | media | secret | designated
  "revision": 2,
  "state": "active",         // active | forgotten | merged
  "scope": "private",        // private | shared | shadow
  "lineage": {"sources": ["s_01"], "derived_from": []},
  "strength": {"weight": 1.2, "confidence": 1.0, "arousal": 0.6, "valence": 0.3, "funny": 0.2},
  "time": {"created": "", "updated": "", "valid_from": "", "valid_to": null, "expires": null},
  "said_by": "owner",        // owner | third_party | web | inferred
  "shareable": "private_only"
}
```

| family | payload | 语义 |
|---|---|---|
| `memory` | `text / level / shape / chrono / about / first` | 普通记忆，`level` 取 `fact / scene / detail / impression` |
| `example` | `user / assistant / tags` | 人格语料，few-shot 问答对 |
| `persona` | `text` | 人格骨架，版本化 |
| `media` | `type / title / url / summary / shared_by` | 媒体引用，只存摘要与 URL |
| `secret` | `ref / shadow_text` | 秘密影子，只留"有这件事" |
| `designated` | `text / trigger / given` | 指定交付，触发词归还 |

新增能力只需要一个新 family：一套 payload 校验、一段措辞模板、一个注入位置。`nodes` 表不动，旧 family 的检索不受影响。payload 序列化后按 `sha256` 内容寻址存进 `blobs`，相同内容天然去重；衰减与合并会向 `ledger` 追加 `prev_hash → self_hash`，形成可校验的哈希链，历史可重放、可 diff 任意两个时间点。

## 遗忘的数学：艾宾浩斯与情绪着色

> 记得住不等于一直记得。留存率是连续值，决定一条记忆还配不配被想起。

```
R = e^(−t / S)
S = BASE_DAYS × salience × (1 + 0.5 × hits) × shape × emotion
```

| 因子 | 取值 |
|---|---|
| `salience` | `weight` 截断到 `[0.3, 3.0]`，重要的事寿命更长 |
| `hits` | 每次有效命中把 `S` 乘 `(1 + 0.5 × hits)` |
| `shape` | `point 1.0` / `span 1.2` / `pattern 3.0` / `rule 999.0` |
| `emotion` | 高唤醒 ×1.5，低唤醒 ×0.8；负效价再叠加：高唤醒 ×1.5，低唤醒 ×0.6 |

- **遗忘不删除数据**：留存率跌破 `0.3` 标 `forgotten`，退出注入但留在库里。`forgotten` 超过 180 天且无引用，才物理清理 blob。
- **情绪着色**：同一时间跨度下，高唤醒负效价的争吵几乎不掉，低唤醒的琐碎快速褪色。`arousal`（唤醒度）与 `valence`（效价）是 `strength` 上的两个独立维度。
- **首因**：抽取时标 `first`，最早出现的记忆作为人格底噪。
- **命中冷却**：30 分钟内的重复命中合并计一次，跨天一天最多一次。长聊不会把某条记忆的权重刷满。
- **变更留痕**：遗忘与合并写 `ledger`，带 `reason`，可回放某个时间点的记忆状态。

淘汰分五级：

| 级别 | 触发 | 动作 |
|---|---|---|
| 1 | `R < 0.3` | `state = forgotten` |
| 2 | `active > 500` | 最旧 50 条进整理 |
| 3 | 整理中相似 > 0.6 | 合并成 `pattern` |
| 4 | `hits > 10` | 晋升人格候选 |
| 5 | `forgotten > 180 天` 且无引用 | 物理删 blob |

设计稳态约 800 条，每天进 3~5 出 3~5。

## 检索的联想：激活扩散与五维打分

> 精确匹配覆盖同词问法，覆盖不了"我突然想起另一件事"。

检索分三步：从当前消息提种子，沿关系边扩散激活，再按多维度打分取 top-k。默认 `recall_k = 8`。

- **种子**：bigram 倒排索引把候选压到共享二元组的范围，再算 Dice 重合度。梗词（「咕咕嘎嘎」「原神」「鸣潮」「抽象」）额外加权。
- **扩散**：`similar / causal / temporal` 三型边，种子满激活，逐跳乘边权与衰减，同一节点取最大路径，每轮截断前沿，避免大图指数膨胀。
- **五维打分**：字面重合 ×3.0 + 标签 ×2.0 + 情绪 ×1.5 + 权重 ×1.0 + 新鲜度 ×0.5，再叠加激活量，减去 `2.0 ×` 近期已用。
- **探索**：九成按分数取最相关，一成随机捞一条不相关的，让她偶尔"突然想起别的事"。
- **无语境回忆**：没有 query 时按 `funny × weight × 随机扰动` 排序，排除 hot 与 sensitive，素材来自长期库与当天缓冲。

同一段话只保留一条，去重按字面包含关系做。

## 上下文的编排：PreparedContext 与预算裁剪

> 注入是一段有固定预算的叙述，按注意力顺序排布。

`PreparedContext` 把上下文切成三段：头部常驻、中部可丢、尾部高注意力。组装上限默认 2000 字；插件每轮按 `budget_chars` 传入，默认 600。

```
┌ 头部：常驻（她是谁）
│  人格骨架 · 关系状态 · 最相关记忆（≤3 条）
├ 中部：可丢（偶尔想起）
│  历史摘要 · 事实类记忆 · 检索式语料
├ 尾部：高注意力（这次怎么回）
│  最近两轮原文 · 本轮消息
└
超出预算：先砍语料与例子，再砍细节，最后砍其余中部
```

- **抗迷失**：按 lost-in-the-middle 现象排布。越影响"她是谁"越靠上，越影响"这次怎么回"越靠下。
- **切口落在句末**：预算超限时从后往前删整句；必须截断时切在句末并补 `……`，不留半句话。
- **叙述式注入**：项目符号会被改写成"你印象里他有点倔，但真有事会帮"这样的叙述句。
- **三档不确定**：`confidence > 0.9` 直说；`0.6 ~ 0.9` 说"你好像说过"；`< 0.6` 说"我是不是听你提过"。
- **相对时间与 metamemory**：数据存绝对时间戳，注入时译成"三天前""上个月"；同话题有 `forgotten` 记忆时说"我好像忘了，你再说一遍"，完全没有时说"这事你没跟我说过"。

每轮检索在内存完成，零模型调用。夜间抽取 1 次，每周整理 2 次，反思只在判断出错时 1 次。任何记忆模块异常都不影响正常回复（fail-open），错误只进日志。

系统没有 `/memory` `/forget` 之类的命令：想看什么直接问，想让她忘就用话说。

## 关系的边界：scope、影子与 RBAC

> 权限跟人走，不跟群走。

可见性由 `scope` 与发送者角色共同决定。印象按 scope 隔离，秘密只留影子。

- **三档 scope**：`private` 只对当事人、全文注入；`shared` 是共同经历、人称"你们"；`shadow` 只注入影子句。
- **影子记忆**：`secret` family 只存 `ref` 与 `shadow_text`，内容锁死当事人 scope。全局可见的只有"有件事你答应过别人不说"，长期影响沉淀成"别人的事你守得住"。
- **指定交付**：`designated` family 有三条硬条件——只在私聊、必须命中触发词、命中后归还。群里问就打岔。
- **RBAC**：`owner / trusted / guest / blocked` 四角色。注入字数 600 / 80 / 0，写入对 owner 与 trusted 开放，改人格仅 owner。
- **第三方信息**：`said_by = third_party`，置信度 0.7，低于亲口 1.0；记到当事人 scope，不向外扩散。

群聊仿真用 20 个用户、120 天、12000 条消息压测，跨 scope 检查 0 条泄漏；端到端探针里 `keyword` 与 `full` 泄漏了私密内容，SeekMemory 未泄漏。

## 自我的演化：反思、强化与人格蒸馏

> 判断会错，错了要留下痕迹。

反思只看规则信号，不额外调模型；确认走冷处理，避免把一次情绪当成长期结论。

- **四个信号**：明确否定 +2、重复解释同一件事 +1、回复骤短 +1、追问接梗 +1。错分 ≥ 2 触发反思，对分 ≥ 2 触发强化。
- **24 小时冷处理**：疑似错误挂起；再出现才确认并写 `mistake`，没出现就撤案。
- **错误留档**：错误记忆带 `weight = -0.3`，负权重让同类判断下次收着点。
- **四来源强化**：被检索 +0.1、她主动说出 +0.3、对方确认 +0.2、共同经历 ×1.5。
- **人格演化**：`persona` 带 `revision` 与 `lineage`，每次修订版本号递增，改动能追溯到来源；长期情绪低落会触发那段经历的细节褪色，情绪标签保留。

人格由高频记忆蒸馏而来：先"记得他总在加班"，再"他是那种把事扛住的人"，最后成为"你不轻易说重话"。这条链路每一步都有 evidence 可查。

## 评测

三组固定数据。像人指数与规模测试不依赖模型，结果可复现；端到端固定模型与问题集，看趋势。原始数据见 [latest.md](benchmarks/results/latest.md)、[scale.md](benchmarks/results/scale.md)、[e2e.md](benchmarks/results/e2e.md)。

### 像人指数：98 / 100

19 条模拟事件、8 个查询、模拟 30 天。问"你觉得我这个人怎么样"时，注入文本的第一句是印象层结论。

| 维度 | 权重 | 结果 | 含义 |
|---|---|---|---|
| 层级命中率 | 30% | **100%** | 问印象时命中印象层 |
| 叙述化比例 | 20% | **100%** | 注入文本无项目符号 |
| 遗忘正确性 | 25% | **15/15** | 重要 12 条全留，琐事 3 条全忘 |
| 强化有效性 | 15% | **2.1×** | 多次提及与一次提及的权重比 |
| 召回命中率 | 10% | **86%** | 期望记忆出现在 top-8 |

### Token 规模：1000 条压缩 98×

记忆从 50 条涨到 1000 条，朴素全量注入从 674 字涨到 14452 字，SeekMemory 从 161 字压到 147 字。记忆量翻二十倍，注入成本持平。

| 记忆条数 | 朴素全量注入 | SeekMemory | 压缩比 |
|---|---|---|---|
| 50 | 674 字 | 161 字 | 4× |
| 200 | 2821 字 | 147 字 | 19× |
| 500 | 7145 字 | 147 字 | 49× |
| 1000 | 14452 字 | 147 字 | **98×** |

每轮额外模型调用：**0 次**。

更大规模看群聊仿真：20 个用户、120 天、12000 条消息，建库 3.2s。

| 方案 | 每轮注入 | 召回命中 | 平均检索耗时 |
|---|---|---|---|
| 朴素全量注入 | **5628 字** | 6/6 | 0.29ms |
| 滑窗 20 条 | **177 字** | 1/6 | <0.01ms |
| 关键词匹配 | **67 字** | 2/6 | 0.11ms |
| 伪向量 top-8 | **39 字** | 5/6 | 0.53ms |
| 摘要 近 7 天 | **285 字** | 2/6 | <0.01ms |
| **SeekMemory** | **40 字** | **6/6** | 3.89ms |

全量注入每轮 5628 字，SeekMemory 40 字，压缩 141×，召回 6/6；代价是检索耗时 3.89ms，仍在毫秒级。伪向量 39 字、5/6，字符二元组覆盖同词问法，覆盖不了没有共享二字的同义问法。

### 端到端：同一个模型，六种策略

模型固定为 `deepseek-flash`，3 个用户、60 天、9 个问题，只换记忆策略。SeekMemory 事实命中 9/9、人味 4.44，平均注入 77 字；全量注入同样 9/9，但每轮 8574 字，人味 4.11。

| 策略 | 事实命中 | 人味均分 | 平均注入字数 | 私密泄漏 |
|---|---|---|---|---|
| 不给记忆 | 0/9 | 2.56 | 0 | 无 |
| 最近 10 条 | 0/9 | 2.22 | 121 | 无 |
| 每日摘要 | 0/9 | 2.56 | 306 | 无 |
| 关键词匹配 | 9/9 | 3.67 | 43 | **泄漏** |
| 全量注入 | 9/9 | 4.11 | 8574 | **泄漏** |
| **SeekMemory** | **9/9** | **4.44** | **77** | 无 |

相比全量注入，每轮省 8497 字（约 111.2×），人味高 0.33，且不泄漏他人私密内容。

> 单次采样、主回答 `temperature=0.7`、LLM 判分有主观性，结论看趋势。

## 快速开始

存储是单文件 SQLite，检索在内存完成；不依赖向量库或外部服务。

```bash
cd <AstrBot>/data/plugins
git clone https://github.com/<you>/SeekMemory astrbot_plugin_seekmemory
```

重启 AstrBot，在 WebUI → 插件 → SeekMemory 中配置：

```jsonc
{
  "owner_umo": "napcat:FriendMessage:2967094107", // 主用户会话，只从这里抽取
  "open_to": "owner_only",          // owner_only | owner_and_trusted | everyone
  "trusted": "",                    // 受信用户 QQ 号，逗号分隔
  "db_path": "",                    // 留空则用插件数据目录
  "budget_chars": 600,              // 每轮注入记忆的字数上限
  "recall_k": 8,                    // 每轮最多注入几条记忆
  "explore_rate": 0.1,              // 随机探索比例（0~1）
  "summary_time": "23:50",          // 每晚抽取记忆的时间
  "weekly_day": 6,                  // 每周整理日（0=周一 … 6=周日）
  "enable_reflect": true,           // 启用自我反思
  "max_episodes": 500,              // 场景/细节上限，超过触发合并
  "debug_log": false                // 输出检索与注入调试日志
}
```

跑测试与基准：

```bash
python3 tests/test_smoke.py
python3 benchmarks/run.py      # 像人指数 + Token 规模
python3 benchmarks/scale.py    # 群聊规模仿真
python3 benchmarks/e2e.py      # 端到端六策略，需要模型 API
```

## 设计来源

| 来源 | 借了什么 |
|---|---|
| [PowerContext](https://github.com/oceanbase/powercontext) | Source/Artifact 分离、通用头 + 类型化 payload、`PreparedContext` 有界视图、写入决策门控 |
| git | 内容寻址、不可变历史、追加日志、哈希链校验 |
| 认知科学 | 艾宾浩斯遗忘曲线、情绪增强记忆、激活扩散、首因效应、metamemory |

协议细节见 [CONTRACT.md](docs/CONTRACT.md)，完整规格见 [DESIGN.md](docs/DESIGN.md)，目录与依赖见 [INDEX.md](docs/INDEX.md)。

## License

本项目采用 **MIT OR Apache-2.0** 双协议，使用者可任选其一：

- [LICENSE-MIT](LICENSE-MIT)
- [LICENSE-APACHE](LICENSE-APACHE)
