# ISSUE-0001 无 BM25 / 向量检索，同跨度问法的召回为 0

> 一句话：零字面重合时 `seeds = 0`；`scale.md` 里这一题的 ✅ 是 weight 先验兜底，
> 不是语义召回。高权重事实一多就会变成 0 命中（见复现 3）。

| 项 | 值 |
|---|---|
| 编号 | ISSUE-0001 |
| 级别 | P1（功能失效；未达到 P0 的"数据损坏/隐私泄漏/崩溃"） |
| 状态 | open |
| 报告人 | NeverENG |
| 日期 | 2026-10-21 |
| 关联 PR | 待开（建议分支 `fix/issue-0001-paraphrase-recall`） |
| 影响版本 | `main` @ `f5cb2b9` |
| GitHub | 待同步 |

## 症状

当用户的问法与记忆原文**不共享任何字符二元组**时，`recall/seed.py` 一个种子都提不出来；
此时 `select()` 仍会按 weight、新鲜度、情绪返回 top-k，看起来"有召回"，实际是重要性
先验在碰运气。高权重事实一多，目标记忆被挤出 top-k，召回就是 0，而系统不报错、
也不会说"不知道"。

本文把"同跨度问法"定义为：问法和记忆原文用不同的词指代同一件事，二者没有共享的
字符二元组。典型例子：

- 问：`我是干什么的`
- 记忆：`我在做量化交易项目`
- 两组 bigram 交集为空，`overlap()` 返回 `0.0`。

这不是孤例。很多"换个说法"的提问都会遇到，例如「我靠什么吃饭」「我的营生是什么」
「我现在靠啥挣钱」，与「我在做量化交易项目」同样零重合（可用复现 1 的 `bigrams()`
逐条复核）。

## 复现

环境：仓库根目录，Python 3.10+（本地 3.9.6 也能跑），不依赖模型、数据库或网络。

### 复现 1：字面重合度为 0

```bash
python3 - <<'PY'
from recall.seed import bigrams, overlap

q, m = "我是干什么的", "我在做量化交易项目"
print("q =", sorted(bigrams(q)))
print("m =", sorted(bigrams(m)))
print("intersection =", bigrams(q) & bigrams(m))
print("overlap =", overlap(q, m))
PY
```

实测输出（2026-10-21）：

```text
q = ['么的', '什么', '干什', '我是', '是干']
m = ['交易', '做量', '化交', '在做', '我在', '易项', '量化', '项目']
intersection = set()
overlap = 0.0
```

### 复现 2：seeds 为空，记忆仍被注入（靠 weight）

```bash
python3 - <<'PY'
from datetime import date
from benchmarks.simdata import to_art
from recall.seed import seeds, overlap
from recall.score import select
from recall.assemble import build

fact = to_art(30, 0, "我在做量化交易项目")   # weight=2.0
noise = to_art(31, 0, "今天地铁好挤")        # weight=0.6
pool = [noise, fact]
q = "我是干什么的"
now = date(2026, 10, 21).toordinal()        # 固定时间基准，保证可复现

print("overlap =", overlap(q, "我在做量化交易项目"))
print("seeds   =", seeds(q, pool))

picked = select([(a, 0.0) for a in pool], q, now, k=8, explore=0.0)
print("picked  =", [a.payload["text"] for a in picked])
print("inject  =", build(picked, budget=600))
PY
```

实测输出：

```text
overlap = 0.0
seeds   = []
picked  = ['我在做量化交易项目', '今天地铁好挤']
inject  = 你记得你在做量化交易项目。2个月前今天地铁好挤。
```

种子是 0，`activate()` 不可能扩散出新候选；命中完全来自 `select()` 里的
`+1.0×weight`。同时注意无关的 `今天地铁好挤` 也被注入了：`select()` 没有相关性
下限，只要候选池非空就凑满 top-k。脚本里固定了 `now`，所以注入文案也固定。

### 复现 3：高权重事实一多，召回真的变成 0

11 条 `weight=2.0` 的事实（1 条目标 + 10 条干扰），查询仍是 `我是干什么的`：

```bash
python3 - <<'PY'
from datetime import date
from core.artifact import make
from recall.seed import seeds
from recall.score import select
from recall.assemble import build

def fact(i, text, created):
    return make("memory", {"text": text, "level": "fact", "shape": "point",
                           "chrono": "once", "about": "other"},
                id=f"m{i:02d}", scope="private",
                strength={"weight": 2.0, "arousal": 0.4, "valence": 0.0},
                time={"created": created})

pool = [fact(1, "我在做量化交易项目", "2026-07-01")]
decoys = ["我面试了万兴科技", "我加班到两点", "我想成为核心架构师", "我叫吕宇轩",
          "我最近睡不着", "我被领导骂了", "我要早点睡", "我养了只猫",
          "我周末去爬山", "我在学做饭"]
pool += [fact(i + 2, t, "2026-10-20") for i, t in enumerate(decoys)]

q = "我是干什么的"
now = date(2026, 10, 21).toordinal()        # 固定时间基准，保证可复现
picked = select([(a, 0.0) for a in pool], q, now, k=8, explore=0.0)
block = build(picked, budget=600)

print("seeds =", seeds(q, pool))
print("picked =", [a.payload["text"] for a in picked])
print("含“量化” =", "量化" in block)
PY
```

实测输出：

```text
seeds = []
picked = ['我面试了万兴科技', '我加班到两点', '我想成为核心架构师', '我叫吕宇轩', '我最近睡不着', '我被领导骂了', '我要早点睡', '我养了只猫']
含“量化” = False
```

同一个问法，在规模基准里"命中"，在重要事实变多后 0 命中。差别只在 weight/新鲜度
的排序，不在检索能力。

## 根因分析

调用链（`main.py:151-160`）：

```text
seeds(text, pool) → activate(seed_ids, graph, cache) → select(candidates, text, ...) → assemble(picked)
```

1. **`recall/seed.py:139` `seeds()` 只认字面二元组。** 候选来自倒排索引 `postings`，
   只有与消息共享至少一个 bigram 的 artifact 才能进入候选，再用 `dice()` 算重合度。
   零共享 → `candidates` 为空 → 直接返回 `[]`。`limit=5` 的默认值在这里没有意义，
   因为没有候选可排。
2. **`recall/spread.py:44` `activate()` 只能从种子出发。** `seed_ids` 为空时
   `scores = {}`，`frontier` 为空，循环不执行，返回空激活。扩散层没有机会跨过
   语义鸿沟。
3. **`recall/score.py:179` `select()` 不做相关性门控。** 它给所有候选打分并取 top-k；
   字面项为 0 时，排序退化为：
   `+1.0×weight + 0.5×新鲜度 + 1.5×情绪 − 2.0×近期使用`。
   这不是"召回"，是"重要性先验排序"。
4. **没有词级检索或向量检索层。** 代码里没有 BM25、TF-IDF、embedding；字符 bigram
   Dice 是唯一的字面信号。

这解释了 `benchmarks/results/scale.md` 里看起来矛盾的一行：

- 伪向量基线在 `我是干什么的` 上 ❌，SeekMemory ✅；
- 但 `benchmarks/results/ANALYSIS.md` §3.6 明确记录：该题 `seeds = 0`、注入 68 字、
  **纯 weight 先验，无任何字面重合**；`我在做量化交易项目` 靠 weight=2.0 排到
  第 4 位才被组装进去。
- 同一份分析：594 条 owner 记忆里，46 条事实副本是 weight=2.0，548 条模板闲聊是
  weight=0.6；1.4 分的先验差刚好把事实顶进 top-8。换个数据分布就失效。

伪向量在这题上直接返回空（交集为 0、余弦全为 0，注入 0 字，见 `ANALYSIS.md` §3.4）；
SeekMemory 则用 weight 先验补了一个位置。前者不会假装记得，后者会——这正是本 issue
最危险的地方：失败被"有输出"掩盖了。

所以当前 6/6 不是"跨问法召回成功"，而是"查询恰好落在高权重事实上"。
**SeekMemory 赢伪向量的唯一一题，赢在重要性先验，不在语义理解。**

## 影响面

- **真实用户**：不会用记忆原文提问。"我是干什么的 / 我靠什么吃饭 / 我的营生"
  与"我在做量化交易项目"都没有共享二字；系统要么注入无关的高权重记忆，要么在
  事实变多后完全漏掉。这是"记忆系统像不像人"的核心体验，不是边缘 case。
- **召回链路**：`seeds`、`activate` 两层在零字面重合时整体失效，只剩 `select` 的
  weight 排序；四层记忆和激活扩散的设计价值在这类问法上归零。`ANALYSIS.md` §4
  还指出：当前 scale 基准里图没有边，`activate()` 本来就只返回种子，扩散从未被
  真正考到。
- **Benchmark 有效性**：`e2e.md` 的 9 个问题大多保留了记忆原文的关键二字
  （`我是做什么的` 对 `我是做量化交易的`、`我的职业目标` 对 `我的职业目标是成为
  核心架构师`、`我面试了哪家` 对 `我面试了万兴科技`）；`你觉得我这个人怎么样`
  虽然与存储的印象文本「我有点倔，但真有事会帮」没有共享二字，但命中了标签里的
  「人」「觉得」。所以 9/9 仍不能证明"零字面/零标签"的跨问法能力。`scale.md` 的
  6 个查询里，也只有 `我是干什么的` 真正跨了表述（其余 5 个都能和预期记忆共享
  二字，如 `我叫`、`面试`、`加班`、`睡不`、`我想`），而它靠 weight 命中。对外引用
  6/6、9/9 时必须带上这个限制。
- **规模**：高权重事实越多，先验排序越拥挤；top-k=8、预算 600 字固定，目标记忆
  被挤出的概率随事实数上升。复现 3 用 11 条事实就复现了 0 命中。
- **不涉及**：无数据损坏、无跨 scope 泄漏（`scale.md` 跨 scope 检查 0 条，
  `e2e.md` 探针中 SeekMemory 未泄漏）、无崩溃。因此按分级定义是 P1，不是 P0。

## 关键数字与出处

| 数字 | 含义 | 出处 |
|---|---|---|
| 0.0 | `我是干什么的` 与 `我在做量化交易项目` 的 bigram Dice | 本 issue 复现 1；`recall/seed.py:50` |
| 0 | 该查询在 scale 基准里的 seed 数 | `benchmarks/results/ANALYSIS.md` §3.6 |
| 68 字 | 该查询的注入字数（纯 weight 先验） | `benchmarks/results/ANALYSIS.md` §3.6 |
| 594 / 46 / 548 | owner 记忆 / 事实副本 / 模板闲聊 | `benchmarks/results/scale.md`、`ANALYSIS.md` §1 |
| 6/6 vs 5/6 | SeekMemory vs 伪向量 top-8 的召回 | `benchmarks/results/scale.md` |
| 40 字 / 39 字 | SeekMemory / 伪向量的平均注入字数 | `benchmarks/results/scale.md` |
| 3.89ms / 0.53ms | SeekMemory / 伪向量的平均检索耗时 | `benchmarks/results/scale.md` |
| 9/9、77 字、4.44 | e2e 的事实命中、平均注入字数、人味均分 | `benchmarks/results/e2e.md` |
| 8574 字 / 111.2× | 全量注入的每轮字数 / SeekMemory 的节省倍数 | `benchmarks/results/e2e.md` |

## 候选方案

| 方案 | 做法 | 代价（估算） | 能解决本 issue 吗 | 风险 |
|---|---|---|---|---|
| A. BM25 | 分词（jieba 或字符 bigram）后建 BM25 倒排，替换/增强 `seed` 的 Dice 打分 | 1–2 人日；新增分词依赖或自己维护 bigram 版本；索引要持久化/重建；594 条规模延迟仍在毫秒级 | **不能单独解决**：BM25 仍要求共享词项。`干什么` 与 `做量化交易` 交集为 0，BM25 对全池都接近 0 分；它只能改善有部分重合时的排序（IDF、长度归一化） | 分词歧义；短查询 IDF 不稳定；索引与缓存失效逻辑变复杂 |
| B. 轻量向量 | 本地小中文 embedding，记忆向量离线建库，查询时编码，与字面分混合（RRF/加权） | 3–5 人日；模型体积、内存、首启延迟和每轮编码耗时需选型时实测；要存向量、处理冷启动和插件打包 | **能**：`干什么` 与 `做量化交易` 语义接近，可跨过零字面重合 | 依赖体积与首启延迟；可能召回"语义相关但事实不对"的记忆，需要阈值 + 字面 rerank；换模型要重建索引 |
| C. 同义词 / 查询扩展 | 维护"干什么→工作/职业/项目/做"等同义词表，或每晚用 LLM 生成查询扩展，扩展词参与 seed 打分 | 0.5–1 人日；无运行时模型 | **只能止血**：覆盖手工枚举的说法。`做量化交易` 不是 `干什么` 的同义词，而是它的答案，词表无法穷举 | 维护成本随领域增长；过度扩展会降精度；LLM 扩展增加延迟、成本、不确定性；每晚生成还需存版本 |

### 推荐

**以 B 为修复方向，A 作为第一阶段的字面底座，C 只做短期兼容，不作为长期架构。**

1. **短期止血（C + 可观测性）**：在 `seed` 层加"零种子"标记和相关度下限，禁止
   `select()` 在零字面信号时把 weight 先验伪装成召回（至少写 debug 日志，必要时
   返回空而不是塞满 top-k）；同时补少量高频同义词（干什么/做什么/职业/工作）。
   这一步不改架构，先让问题可见、可测。
2. **第一阶段（A）**：把字面打分抽象成可替换的 `LexicalIndex`，接 BM25（字符
   bigram 或 jieba 词级都行），统一 `score_lexical(query, memory)` 接口。它不解决
   零重合，但为混合检索搭好底座，并改善"睡不好/睡不着"这类部分重合的排序。
3. **第二阶段（B）**：新增可选 `EmbeddingIndex`，与 BM25 做 RRF 或加权融合；
   只在字面分低于阈值时才走向量，控制延迟；配置项默认关闭、按需开启；单测用
   固定假 embedder，避免 CI 依赖模型下载。
4. **不建议只做 A**：BM25 是必要的底座，但把它当本 issue 的完整修复，会在
   `我是干什么的` 这个例子上直接失败。
5. **不建议只做 C**：同义词表可以救几个高频问法，但覆盖不了开放域换词；把它
   当长期方案会把维护成本转嫁给每个新用户。

## 验收标准

- [ ] 在**所有记忆 weight 相同**的条件下，`我是干什么的` 仍能召回
      `我在做量化交易项目`（top-k 内），不依赖 weight 先验。
- [ ] 新增"无相关记忆时返回空/低置信"用例，禁止用无关高权重记忆凑满 top-k。
- [ ] 至少补 10 组"问法 ≠ 原文"的跨表述回归用例，记录修复前后的召回率。
- [ ] 现有 6 个 scale 查询和 9 个 e2e 问题不回退；跨 scope 零泄漏检查保持 0 条。
- [ ] PR 附 `python3 benchmarks/scale.py` 前后的注入字数与检索耗时对比。

## 决策记录

- 2026-10-21：开 issue，只记录，不动代码。等方案评审后再开
  `fix/issue-0001-paraphrase-recall` 分支。
- 待定：A/B 的取舍、embedding 模型选型、是否引入 jieba 依赖、默认开关、
  是否把 BM25 与向量做成两个独立 PR。

## 参考

- `benchmarks/results/scale.md`：六方案总表、逐查询命中、跨 scope 检查
- `benchmarks/results/e2e.md`：九问、人味、注入字数
- `benchmarks/results/ANALYSIS.md` §3.6、§4：`我是干什么的` seeds=0、纯 weight
  先验的拆解；激活扩散在本次基准中贡献为 0
- `recall/seed.py:139`、`recall/spread.py:44`、`recall/score.py:179`、`main.py:151`
- `benchmarks/simdata.py:33`：`我在做量化交易项目` 是 `OWNER_FACTS` 之一
