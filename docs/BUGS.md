# 缺陷档案

> 记录开发期抓到的真实缺陷，作为回归与优化依据。
> 核对基准：代码树 `b55e6a5`（2026-10-21）。行号为该提交下的代码；改动后行号会漂移，按每条的文件名与代码锚点重新定位。
> 修复提交：`b55e6a5`（父提交 `c650633`）。本文所有“修复前”行为都在该父提交的完整副本上实测过。

## BUG-001 · decay 误杀非 memory 家族，人格 37 天后被“遗忘”

- **严重度**：高
- **发现方式**：测试 agent 的衰减边界探测——造一条 37 天前创建、默认强度的 persona，跑 `decay_all` 看 state。现有单测只构造 memory，探不到。
- **现象**：persona（以及 media/example/secret/designated）的 payload 没有 `level`，被当成普通 point 场景衰减。默认 `Strength()`（weight=1.0、arousal=0.3）的稳定度 S=30 天：R(36)=0.3012 仍存活，R(37)=0.2913 跌破 0.3，节点被标 `forgotten`、从 cache 移除、写一条 `forget` 账本。人格沉淀会凭空消失。
- **根因**：`maintain/decay.py:43-45`。`decay_all` 遍历 `cache.active()`（六个 family 全在里面），旧代码没有 family 判断；`level` 取到空串后绕过了 level 豁免（旧代码是 `level in ("fact", "impression")`，现在 `:50-52` 只判 fact）；`shape` 缺省 `point`，稳定度按 30 天算，于是 37 天必死。
- **修复**：`maintain/decay.py:44-45` 先判 `art.header.family != "memory"` 直接 continue。同一提交把 `:51` 的豁免从 `level in ("fact", "impression")` 收窄为 `level == "fact"`：印象不再永久豁免，改由 `pattern` 的 3× 稳定度自然慢衰减（`core/strength.py:20-25`）。
- **回归**：**无直接用例（盲区）**。`tests/test_maintain.py:74-129` 的 4 条 DecayTest 全部只走 `_memory()`（固定 family=memory），`test_fact_is_never_eliminated` 守的是 fact 豁免，不是 family 豁免。建议补：37 天前的 persona 跑完 `decay_all` 后仍 `active` 且留在 cache。

## BUG-002 · 抽取出的情绪字段被整体丢弃

- **严重度**：高
- **发现方式**：测试 agent 对照抽取 prompt 与落库的 `Strength`。基准发现不了：`benchmarks/*` 直接构造 `Strength`，绕过了抽取→写入这条路径。
- **现象**：`perceive/extract.py:26-28` 要求模型输出 `arousal`、`valence`、`funny`，但写入时 `make("memory", it)` 只把 item 原样塞进 payload，`Strength` 取默认值（arousal=0.3、valence=0.0、funny=0.0，`core/artifact.py:38-43`）。一条被标为 arousal=0.9、valence=-0.8 的争吵记忆，落库后情绪系数是 1.0 而不是 2.25（`core/strength.py:41-55`），稳定度 30 天 vs 应有的 67.5 天；打分侧 `_emotion_value`（`recall/score.py:85-98`）也永远拿不到情绪差异。情绪对留存和排序同时失效。
- **根因**：`main.py:233`。旧代码 `make("memory", it)` 没有 `strength=`；`Strength` 的默认值把模型输出覆盖成常量。
- **修复**：新增 `_strength_of()`（`main.py:47-61`），从 item 取三个情绪字段并按值域 clamp：arousal∈[0,1]（`:51`）、valence∈[-1,1]（`:52`）、funny∈[0,1]（`:53`），非法/NaN 回落默认值（`_clamp` `:36-44`）；可选 `hits` 取非负整数（`:55-60`）；在 `main.py:233` 传入 `strength=_strength_of(it)`。
- **回归**：**无**。`main.py` 依赖 `astrbot`，不在 63 条单测的导入范围内；`tests/test_artifact.py:100-111` 只测 `Strength` 能接收 hits，不测抽取映射。建议把 `_strength_of` 挪到无外部依赖的模块，补 clamp/缺省/NaN 三组断言。

## BUG-003 · 生产写入路径不校验，坏数据入库后拖垮注入

- **严重度**：中高
- **发现方式**：测试 agent 的写入链路审查——`validate()` 有定义、有单测，但修复前生产代码零调用（`grep -rn "validate("` 只命中 `core/` 的定义与 `tests/`；现在唯一调用点是 `main.py:234`）。
- **现象**：抽取结果缺 `text`/`level` 或 level 非法也能 `db.upsert` 入库。缺 `text` 的坏数据一直躺到 recall 组装时才由 `content_of` 抛 `ValueError`（`core/artifact.py:137-141`），被 `main.py:142-143` 的兜底捕获，表现为“这一轮注入直接消失”；非法 `level` 不炸，但会被 `assemble._sentence` 静默当成 `scene`。修好后坏条目在写库前就被跳过并记 warning，不再污染 store。
- **根因**：`main.py:231-242`。旧循环先 `make` 再 `db.upsert`，中间没有 `validate(art)`；校验函数定义在 `core/artifact.py:127-134`，唯一生产调用点缺失（现在在 `main.py:234`）。
- **修复**：`main.py:234` 在 `make` 之后、`upsert` 之前调 `validate(art)`；`except ValueError` 记 `logger.warning` 并 `continue`（`:235-237`），其它构造异常记 error 并跳过（`:238-240`）；只有 `db.upsert` + `cache.put` 都成功才 `written += 1`（`:241-247`），日志改为实际写入条数（`:249`）。
- **回归**：**只测了函数，没测调用点**。`validate()` 本身在 `tests/test_artifact.py:80-167` 有 6 组用例；`main._nightly` 无测试。建议用假 provider（固定返回坏 JSON）跑一遍 `_nightly`，断言坏条目不入库、好条目照写。

## BUG-004 · 去重不是 fail-open，一条坏记忆让整轮注入消失

- **严重度**：中
- **发现方式**：测试 agent 用缺 `shadow_text` 的 secret 节点 + 一条正常 memory 跑 `assemble.build`。
- **现象**：`build([bad_secret, good_memory])` 直接抛 `ValueError: secret payload 缺少字段：shadow_text`（实测）。`main.inject_memory` 的兜底只记日志（`main.py:142-143`），结果一条坏节点把同一轮所有记忆都带走了——包括本来能正常注入的那条。
- **根因**：`recall/assemble.py:161-176`。旧 `_dedupe` 在 `:167` 无保护调用 `content_of(a)`；secret 的文本字段是 `shadow_text`（`core/artifact.py:26-31`），缺字段时 `_field` 抛错（`:137-141`）。去重位于 `build` 的第一步（`:187`），所以异常发生在任何组装之前。
- **修复**：`recall/assemble.py:166-169` 用 try/except 包住 `content_of`，取不到文本的坏条目直接跳过。顺带把去重从“每条都与已保留项重算 `content_of`”改成维护 `seen` 文本列表（`:164`、`:170-175`），每节点只解析一次文本。
- **回归**：**无**。`tests/test_recall.py:209-216` 的 `test_duplicate_content_kept_once` 只测内容重复，不测坏节点。建议补：`secret` 缺 `shadow_text` + 正常 memory → `build` 不抛且输出包含正常 memory。

## BUG-005 · hits 两套读法，晋升与“刚用过”惩罚失效

- **严重度**：中
- **发现方式**：测试 agent 构造 `header.strength.hits=12`、payload 无 `hits` 的节点，分别调 `promote_candidates(min_hits=10)` 与 `_recently_used`。
- **现象**：`promote_candidates` 在正常写入路径下永远筛不出人——它读 `payload["hits"]`，而写入端只写 `header.strength.hits`（promote 目前还没接进主流程，接上即失效）；`score` 的“刚用过” -2.0 惩罚则是当下就失效。实测同一节点（weight=2.0、hits=12、payload 有 `last_used`）：修复前 promote 0 条、`_recently_used`=0.0；修复后 1 条、1.0。
- **根因**：写入端在 `header.strength`：`main.py:55-60` → `core/artifact.py:43` → `store/db.py:97`（整块 JSON 落库）→ `:214` 还原。读端却各读各的：`maintain/promote.py:17` 旧代码 `art.payload.get("hits", 0)`，`recall/score.py:132` 旧代码 `payload.get("hits", 0)`。两个来源，写一个读另一个。
- **修复**：两个读端统一读 `art.header.strength.hits`：`maintain/promote.py:17`、`recall/score.py:132`；非法值回落 0（`maintain/promote.py:18-21`、`recall/score.py:133-134`）。
- **回归**：**无直接用例**。`tests/test_store.py:63-93` 只验证 hits 能 roundtrip 回 header（`:78` 写入 7），不验证读者；`maintain/promote.py` 没有任何测试引用。建议补：hits=12 → `promote_candidates` 命中；hits>0 且有 `last_used` → 分数比无 hits 低 2.0。

## BUG-006 · reflect 子串误判：反问被判否定，单字“对”被判追问

- **严重度**：中
- **发现方式**：测试 agent 的口语化输入探测（“是不是这样”“对方今天怎么样”），观察 `signals()` 的 wrong/right。
- **现象**：修复前 `signals("我今天加班到很晚", "是不是这样")` 返回 wrong=2、reasons=`明确否定（不是）`，语义上等于“她上轮说错了”（`should_reflect` 阈值 ≥2）；`signals(..., "对方今天怎么样")` 返回 right=1、reasons=`追问（对）`。修复后两者均为 0/0。`signals` 目前只被测试调用、尚未接进主流程，但这两类输入在日常对话里很常见，接线后就是直接的误判来源。
- **根因**：`maintain/reflect.py:53-63`。旧 `_find_negation` 是裸子串 `word in text`，“是不是”里命中“不是”；`:66-74` 旧 `_FOLLOWUPS` 含单字“对”，“对方”里命中“对”。
- **修复**：四处配合——`:17` 先剔除 7 个疑问式（是不是/对不对/好不好/行不行/能不能/要不要/有没有）；`:30-34` 否定改为整句正则，要求落在句首或标点/空白之后，句首允许一个短主语；`:18-28` 追问词去掉单字“对”，改成“对啊/对的/没错”等多字形式；`:59-63` 先 replace 疑问式再 `search`。
- **回归**：**部分覆盖，且守不住这两例**。`tests/test_maintain.py:135-155` 的 ReflectTest 覆盖“不是这个意思”“然后呢”“不对”，但“不对”在旧实现里也会先剔否定词再判追问，所以修复前同样通过；“是不是这样”“对方怎么样”没有用例。建议把这两个输入直接写成断言（wrong=0、right=0）。

## BUG-007 · merge 不写账本，审计链缺段

- **严重度**：低
- **发现方式**：测试 agent 合并后检查 `db.ledger_entries()`，发现只有节点状态变化、没有 merge 记录。
- **现象**：合并只 `db.upsert`，账本里查不到“哪条并进了哪条”。实测 501 条相似场景合并 50 条：修复前 ledger 0 条，修复后 51 条（1 条新印象 + 50 条成员，`op` 全为 `merge`）。哈希链本身没断（`verify()` 仍为 True），但审计上少了一段，无法从账本重建合并关系。
- **根因**：`maintain/merge.py:182-200`。新印象 `db.upsert`（`:182`）+ `cache.put`（`:183`）和成员 `revise(state="merged")`（`:192`）+ `cache.remove`（`:193`）都没有 `ledger_append`；`db.upsert` 本身不记账本，账本只由显式调用写入。
- **修复**：新印象记一条（`maintain/merge.py:184-190`）：`op="merge"`、before=None、after=新 id、reason 带条数与摘要文本；每个被合并成员各记一条（`:194-200`）：before=成员 id、after=新 id、reason 带“与另外 N-1 条合并”。
- **回归**：**无**。`tests/test_maintain.py:158-196` 的 MergeTest 只断言 impression 生成、成员 `merged`、cache 计数，不查 ledger；`tests/test_store.py:155-208` 只验证已有记录的哈希链连续/防篡改。建议补：合并后 `ledger_entries()` 的 merge 条数 = 1 + 成员数，且 `verify()` 为 True。

## BUG-008 · 相关性闸门对 `full` 配置完全无效

- **严重度**：中
- **发现方式**：`benchmarks/ablation.py` 加 `no_gate` 对照后，两行数字一模一样。
- **现象**：PR-0017 的双阈值闸门（`score >= max(1.2, top_score × 0.35)`）落地后，
  `full` 的噪声仍是 81%、注入仍是 104 字，与关掉闸门逐字相同——闸门等于没装。
- **根因**：`select()` 打的是五项加权和，`weight` 先验最高可到 2.1、`freshness` 再加
  0.5，两者合起来就足以把完全无关的记忆顶过 1.2。阈值调高到能切噪声时（`min_rel=0.9`），
  命中掉到 14/18。**先验分不能当相关性证据用**。
- **修复**：PR-0018 改为证据闸门——`evidence = 字面 + 标签 + 情绪 + 激活`，
  `weight` / `freshness` / `recent` 只参与排序、不能单独过门；实测检索层噪声
  81% → 40%。同时把人格与印象层提为「常驻层」不经闸门（否则「你觉得我这个人怎么样」
  会返回空）。回归：`tests/test_gate.py` 22 条。

## BUG-009 · 基准合成数据缺 tags，闸门在基准里被低估

- **严重度**：中
- **发现方式**：证据闸门上线后 `run.py` 从 98 掉到 84，逐题诊断发现「你觉得我这个人怎么样」
  的命中条 evidence 只有 0.22——标签项为 0。
- **根因**：`benchmarks/run.py` 的 `to_artifact()` 没把事件的 `tags` 写进 payload，
  `simdata.py` 的合成记忆也完全没有标签；而生产 `perceive/extract.py` 产出的记忆一定带 tags。
  基准数据与生产数据不同构，闸门在基准里少了最有力的一维证据。
- **修复**：PR-0018 让 `run.py` 透传事件标签、`dataset.py` 与 `simdata.py` 从文本主题派生标签。
  修完 `run.py` 层级命中 57% → 100%。**这是口径修复，没有改任何期望值。**

## BUG-010 · 基准期望值要求召回别人的秘密正文

- **严重度**：中
- **发现方式**：`run.py` 收尾时逐题诊断，最后一分卡在「我是不是跟你说过一件事不让说」。
- **现象**：该题期望在注入块里召回 `私事`（别人的秘密正文），与 DESIGN 的秘密/影子语义
  直接冲突——`family=secret` / `scope=shadow` 只交付遮蔽句、不交付正文。
  PR-0003 时代的基线里这题同样是 0/1，说明它一直是个错误期望。
- **修复**：PR-0018 把期望改为「不应召回」，并在 PR 里逐项列出修正前后的分母变化。
  正文交付的正确性由 `tests/test_scope.py` 与 `recall/assemble.py` 的影子遮蔽用例保证，
  不靠一条召回命中来证明。

## 附：回归覆盖缺口

本次整理做了回退验证：把 `b55e6a5` 回退到父提交 `c650633`（`git archive c650633` 解到独立目录，逐个跑 `tests/test_*.py`），**63 条单测仍全部通过**。也就是说，这 7 条缺陷目前没有被测试守住；修复只是把行为改对，回归仍靠人工。

| 编号 | 最接近的现有用例 | 修复前能否失败 | 缺口 |
|---|---|---|---|
| BUG-001 | `tests/test_maintain.py:74-129` DecayTest | 否 | 只造 memory，无 persona/media |
| BUG-002 | 无（`tests/test_artifact.py:100-111` 只测 Strength 字段） | 否 | 抽取→Strength 映射无测试 |
| BUG-003 | `tests/test_artifact.py:80-167` validate 函数 | 否 | `main._nightly` 写入路径无测试 |
| BUG-004 | `tests/test_recall.py:209-216` 去重 | 否 | 无坏节点用例 |
| BUG-005 | `tests/test_store.py:63-93` hits 存取 | 否 | 读者（promote/score）无测试 |
| BUG-006 | `tests/test_maintain.py:135-155` ReflectTest | 否 | 两个真实误判输入未固化 |
| BUG-007 | `tests/test_maintain.py:158-196` MergeTest | 否 | 不查 ledger |

补测优先级：001/002/003 是数据正确性与人格存续，先补；004/005 影响召回，次之；006/007 影响反思与审计，最后补。

## 复查方法

```bash
# 行号定位（任选其一，改动后重跑）
grep -n 'family != "memory"' maintain/decay.py
grep -n '_strength_of\|validate(art)' main.py
grep -n 't = content_of' recall/assemble.py
grep -n 'header.strength, "hits"\|header.strength.hits' maintain/promote.py recall/score.py
grep -n '_NEGATION_RE\|_QUESTION_FORMS' maintain/reflect.py
grep -n 'ledger_append' maintain/merge.py

# 定向回归（当前应全绿）
python3 tests/test_maintain.py
python3 tests/test_recall.py
python3 tests/test_store.py
```

行为复核脚本（用临时库、可丢弃）：构造 37 天前的 persona 跑 `decay_all`；用缺 `shadow_text` 的 secret + 正常 memory 跑 `build`；构造 `hits=12` 的节点跑 `promote_candidates`；用 `"是不是这样"`/`"对方今天怎么样"` 跑 `signals`。四组都应看到本文“修复后”的结果。
