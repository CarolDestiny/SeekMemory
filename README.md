# SeekMemory

**SeekMemory makes your agent bot more like people.**

<p align="center">
  <img alt="python" src="https://img.shields.io/badge/python-3.10%2B-blue">
  <img alt="astrbot" src="https://img.shields.io/badge/AstrBot-4.x-76bad9">
  <img alt="license" src="https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-green">
</p>

一个给 IM 机器人用的分层记忆系统。它不是"把对话塞进向量库、每次捞前五条"那种检索增强，而是一套完整的人类记忆模型：印象沉淀、艾宾浩斯遗忘、情绪着色、激活扩散检索、跨会话人格养成。

**人记得的是印象。**

你不会记得某天 23:40 对方具体说了什么，但你记得"那阵子他不太好"。SeekMemory 复现的是后者。

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

- **三档 scope**：当前实现中 `private` 按归属会话过滤；`shared` 跨会话进入候选；`shadow` 跨会话进入候选但只注入影子句。
  群聊抽取默认写 shared，来源群不是访问隔离边界。可在 [插件视图](docs/webui/README.md) 用 UMO 和实际说话人做只读诊断。
- **影子记忆**：`secret` family 只存 `ref` 与 `shadow_text`，内容锁死当事人 scope。全局可见的只有"有件事你答应过别人不说"，长期影响沉淀成"别人的事你守得住"。
- **指定交付**：`designated` family 有三条硬条件——只在私聊、必须命中触发词、命中后归还。群里问就打岔。
- **RBAC**：`owner / trusted / guest / blocked` 四角色。注入字数 600 / 80 / 0，写入对 owner 与 trusted 开放，改人格仅 owner。
- **第三方信息**：`said_by = third_party`，置信度 0.7，低于亲口 1.0；记到当事人 scope，不向外扩散。

群聊仿真压测跨 scope 检查 0 条泄漏；端到端 60 题里 `keyword` 与 `full` 都泄漏过私密内容（块级 3/7、7/7），SeekMemory 块级与回答都是 0。

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

四组固定数据。像人指数与规模测试不依赖模型，结果可复现；端到端固定模型与问题集，看趋势。原始数据见 [latest.md](benchmarks/results/latest.md)、[scale.md](benchmarks/results/scale.md)、[ablation.md](benchmarks/results/ablation.md)、[large_e2e.md](benchmarks/results/large_e2e.md)。

### 像人指数：100 / 100

19 条模拟事件、8 个查询、模拟 30 天。问"你觉得我这个人怎么样"时，注入文本的第一句是印象层结论。
这套题已经饱和（见 [ISSUE-0019](docs/issues/ISSUE-0019.md)），更难的任务集在 ISSUE-0019 里排期。

| 维度 | 权重 | 结果 | 含义 |
|---|---|---|---|
| 层级命中率 | 30% | **100%** | 问印象时命中印象层 |
| 叙述化比例 | 20% | **100%** | 注入文本无项目符号 |
| 遗忘正确性 | 25% | **15/15** | 重要 12 条全留，琐事 3 条全忘 |
| 强化有效性 | 15% | **2.1×** | 多次提及与一次提及的权重比 |
| 召回命中率 | 10% | **100%** | 期望记忆出现，或按语义不该召回时确实不召回 |

### Token 规模：1000 条压缩 850×

记忆从 50 条涨到 1000 条，朴素全量注入从 674 字涨到 14452 字，检索层稳定在 17 字。记忆量翻二十倍，检索成本不动。
另有常驻层（人格 + 印象）固定 38 字/轮不计入本表，实际每轮约 55 字。

| 记忆条数 | 朴素全量注入 | SeekMemory 检索层 | 压缩比 |
|---|---|---|---|
| 50 | 674 字 | 17 字 | 40× |
| 200 | 2821 字 | 17 字 | 166× |
| 500 | 7145 字 | 17 字 | 420× |
| 1000 | 14452 字 | 17 字 | **850×** |

每轮额外模型调用：**0 次**。

更大规模看群聊仿真：8 个用户、60 天、2400 条消息（`SCALE_USERS` / `SCALE_DAYS` 可调）。

| 方案 | 每轮注入 | 召回命中 | 平均检索耗时 |
|---|---|---|---|
| 朴素全量注入 | **3012 字** | 6/6 | 0.13ms |
| 滑窗 20 条 | **191 字** | 2/6 | <0.01ms |
| 关键词匹配 | **66 字** | 2/6 | 0.06ms |
| 伪向量 top-8 | **53 字** | 5/6 | 0.26ms |
| 摘要 近 7 天 | **285 字** | 3/6 | <0.01ms |
| **SeekMemory** | **13 字** | **5/6** | 1.39ms |

全量注入每轮 3012 字，SeekMemory 13 字，压缩 232×；代价是检索耗时 1.39ms，仍在毫秒级。
召回 5/6：掉的那题是零字面同义问法，要靠 ISSUE-0001 的混合检索；伪向量在这个数据上也是 5/6，但每轮 53 字。

### 端到端：6 种人格画像、31,926 条消息、同一个模型

模型固定 `deepseek-flash`、`temperature=0`，背景数据是 6 个不同画像的 180 天私聊与群聊
（31,926 条，私聊 4,904 / 群聊 27,022），60 道黄金题，只换记忆策略。主回答与 LLM 判分
各一次调用，共 480 次，0 失败，总耗时 91 秒。

| 策略 | 命中 | 非边界命中 | 人味均分 | 常驻层字数 | 检索层字数 | 等效 token |
|---|---|---|---|---|---|---|
| 不给记忆 | 2/60 | 0/53 | 2.60 | 0 | 0 | 10,873 |
| 全量注入（16k 字） | 24/60 | 20/53 | 3.53 | 0 | 15,991 | 94,817 |
| 关键词匹配 | 42/60 | 39/53 | 3.78 | 0 | 49 | 12,758 |
| **SeekMemory** | **49/60** | **47/53** | **4.27** | 23 | 42 | **13,551** |

- 对比全量注入：命中 +41.7pp，等效成本约 **1/7**。
- 对比关键词匹配：命中 +7 题（+11.7pp）、人味 +0.48，等效成本 **1.06×**。
  准确率赢 7~8 题，成本贵 6%——**不能说"更省 token 又更准"**。
- 边界：7 道隐私题，SeekMemory 块级泄漏 **0/7**、回答泄漏 0；全量注入块级泄漏 7/7。
- 一次相关性闸门（PR-0018）前后：命中 52→49，检索层 117→42 字（−64%），等效 token −12%。
  闸门买的是成本，不是命中。

等效 token = 未命中输入 + 0.1 × 命中缓存输入 + 输出。全量注入的输入有 98% 命中缓存，
账面 token 会把它的成本高估约 8 倍，所以这里用等效口径。

> 单次采样、判分有主观性。逐题 60 行明细、分人格、分题型、块级预检都在
> [large_e2e.md](benchmarks/results/large_e2e.md)；另有 3 用户 9 题的旧版 [e2e.md](benchmarks/results/e2e.md)。

## 快速开始

存储是单文件 SQLite，检索在内存完成；不依赖向量库或外部服务。

安装请到 [Releases](https://github.com/NeverENG/SeekMemory/releases) 下载附件
`astrbot_plugin_seekmemory.zip`，通过 AstrBot 插件页的 ZIP 安装入口上传。
安装包已包含 Python 运行文件和构建好的 `pages/memory/`，使用者无需安装 Node.js 或现场构建。
可用同一 Release 的 `SHA256SUMS` 校验下载文件。

GitHub 的 **Source code (zip/tar.gz)**、Code → Download ZIP 和 `git clone`
都用于源码开发，不包含构建产物，不作为完整插件安装包使用。
WebUI 包含记忆编辑、scope/会话筛选、版本与账本、召回诊断、任务和生命周期日志。
请使用支持插件视图和插件 Web API 的 AstrBot（已在 4.28.1 验证宿主 API）。
安装后重载插件，从插件卡片的视图入口打开。详见 [WebUI 使用说明](docs/webui/README.md)。

自定义插件源若支持 `download_url`，应指定
`https://github.com/NeverENG/SeekMemory/releases/latest/download/astrbot_plugin_seekmemory.zip`；
固定版本则使用 `/releases/download/vX.Y.Z/astrbot_plugin_seekmemory.zip`。
单填仓库地址仍可能走源码下载，Release 工作流不会改变 AstrBot 的下载策略。
首次发布成功前，这些附件链接尚不可用。

源码开发与打包：

```bash
git clone https://github.com/NeverENG/SeekMemory astrbot_plugin_seekmemory
cd astrbot_plugin_seekmemory/dashboard
pnpm install --frozen-lockfile
pnpm check
pnpm build
cd ..
python scripts/package_plugin.py
```

产物是 `dist/astrbot_plugin_seekmemory.zip` 和 `dist/SHA256SUMS`。
后端保留必要的 `.py` 和 SQL 资源，不分发平台相关的 `.pyc` 或虚拟环境。
前端源码、Mock、测试、基准数据、开发文档、依赖目录和本地数据均不进入安装包。
纯排版开发直接运行 `pnpm dev`，详见 [dashboard 开发说明](dashboard/README.md)。

重启 AstrBot，在 WebUI → 插件 → SeekMemory 中配置：

```jsonc
{
  "owner_umo": "napcat:FriendMessage:100000000", // 主用户会话，只从这里抽取
  "open_to": "owner_only",          // owner_only | owner_and_trusted | everyone
  "trusted": "",                    // 受信用户 QQ 号，逗号分隔
  "db_path": "",                    // 留空则用插件数据目录
  "budget_chars": 600,              // 每轮注入记忆的字数上限
  "recall_k": 8,                    // 每轮最多注入几条记忆
  "explore_rate": 0.1,              // 随机探索比例（0~1）
  "recall_min_ev_abs": 0.5,         // 证据闸门绝对下限（字面/标签/情绪/激活）
  "recall_min_ev_rel": 0.3,         // 证据闸门相对下限（占本轮最高证据）
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
