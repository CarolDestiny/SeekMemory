# ISSUE-0013 Source / evidence 从未落库，media 没有抽取路径，外部源适配器缺位

> 一句话：`DB.add_source()` / `DB.link_evidence()` 写好了但没有调用方，
> `sources` / `evidence` 表在真实写入路径里永远是空的；`media` family 有校验和
> 渲染模板，却没有任何抽取路径产出它；DESIGN §9 的 `SourceAdapter` 在代码里
> 不存在。于是“每条结论带 evidence”“媒体只存摘要+引用”“外部源可信度分级”
> 三条都没有落地。

| 项 | 值 |
|---|---|
| 编号 | ISSUE-0013 |
| 级别 | P2（能力缺失：来源链/媒体/外部源三条能力都没有入口） |
| 状态 | open |
| 报告人 | 审计记录（agent） |
| 日期 | 2026-10-21 |
| 关联 PR | 待开（建议分支 `feat/issue-0013-source-media`） |
| 影响版本 | `main` @ `1be8baa` |
| GitHub | 待同步 |

## 症状

- 每条记忆都没有 `lineage.sources`；`sources` / `evidence` 表为空，无法回到原话对账。
- 用户发视频/链接/图片时，不会产生 `media` 记忆；`media` 的校验器和
  “他给你看过一个讲…的视频”模板永远不会被触发。
- 没有 `SourceAdapter`，网页/搜索/视频标题的可信度（0.85/0.7/0.6）
  没有落点；`said_by` 永远是默认 `owner`，第三方信息没有 `third_party` + 0.7。
- 合并出来的 impression 的 `lineage.sources` 也是空（成员本身没有 sources）。

## 现状（代码证据）

Source 写入 API 存在，但没有调用方：

```text
store/db.py:153   def add_source(self, sid, umo, at, role, text, flags) -> None:
store/db.py:158-159   self.conn.execute("INSERT OR IGNORE INTO blobs(...)")
store/db.py:161-164   self.conn.execute("INSERT OR IGNORE INTO sources(id, umo, at, role, blob, flags) ...")
store/db.py:166   def link_evidence(self, node_id, source_id) -> None:
store/db.py:169       self.conn.execute("INSERT OR IGNORE INTO evidence(node, source) VALUES(?, ?)")
```

复核：

```bash
cd SeekMemory
grep -rn "add_source\|link_evidence" --include="*.py" .
# 只命中 store/db.py 的定义
```

夜间写入只 `db.upsert`：

```text
main.py:233   art = make("memory", it, strength=_strength_of(it))
main.py:242   self.db.upsert(art)
main.py:243   if self.cache:
main.py:244       self.cache.put(art)
```

`make()` 没有传 `lineage`，所以 `header.lineage.sources` 是空 tuple
（`core/artifact.py:55-58`、`:68`）。`merge_similar()` 想从成员继承 sources：

```text
maintain/merge.py:159   sources = tuple(
maintain/merge.py:160       dict.fromkeys(source for art in members for source in art.header.lineage.sources)
maintain/merge.py:161   )
```

成员没有 sources，所以合并结果也为空。

`media` 只有校验/渲染，没有生产者：

```text
core/families/media.py:17   def validate(payload):
core/families/media.py:19       _need(payload, "type")
core/families/media.py:20       _need(payload, "title")
core/families/media.py:21       _need(payload, "url")
recall/assemble.py:74       def _media_sentence(art):
recall/assemble.py:134      if family == "media": ...
perceive/extract.py:22-29  # 字段只有 level/text/about/arousal/valence/funny/first
main.py:233                # 永远 make("memory", ...)
```

`media` 只在测试里被构造（`tests/test_artifact.py:31`、`tests/test_smoke.py:50`），
生产路径没有 `make("media", ...)`。

`SourceAdapter` 不存在：

```bash
grep -rn "SourceAdapter\|adapter\|fetch(ref)\|summarize" --include="*.py" .
# 无命中
```

`said_by` 在 `make()` 里默认 `owner`（`core/artifact.py:71`），`main.py:233`
没有覆盖；没有 `third_party` 分支。

## 设计期望

- DESIGN 原则一（`docs/DESIGN.md:10`）：记忆是神圣的，**Source 不可改**。
- DESIGN §1（`:51`）：`evidence: ["s_01"]` 溯源。
- DESIGN §4.2 第 ⑤ 步（`:144`）：写入，**带 evidence**。
- DESIGN §9（`:390-406`）：media 只存摘要 + 引用，不存内容；
  示例 payload `{type,title,url,summary,shared_by}`。
- DESIGN §9 外部源适配器（`:408-424`）：`SourceAdapter` 抽象 +
  `fetch/summarize/trust`；可信度表：亲口 1.0 / 网页 0.85 / 搜索 0.7 /
  视频标题 0.6 / 自我推测 0.5。
- DESIGN §7.3（`:338-344`）：第三方信息 `said_by=third_party`、
  `confidence=0.7`，记到当事人 scope。
- DESIGN v3 数据表（`:559-566`）：`sources(id, umo, at, role, blob, flags)`、
  `evidence(node, source)`。
- DESIGN v3 media payload（`:519`）：`{type,title,url,summary,shared_by}`。

## 差距

1. **Source 不写**：缓冲里的消息没有落成 `sources`；抽取出的记忆没有
   `evidence` 关联；`lineage.sources` 全空。
2. **没有 media 抽取**：提示词不识别视频/链接/图片；`main` 永远写 memory；
   没有从消息里抽 `url/title/type/summary` 的路径。
3. **没有 SourceAdapter**：没有抽象类、没有 trust 分级、没有外部 fetch/summarize。
4. **没有第三方标记**：`said_by` 恒为 owner；没有 `third_party` / `web` /
   `inferred` 的写入分支；`confidence` 没有按来源打折。
5. **没有“只存摘要”的约束**：即使手工写 media，也没有代码阻止把正文塞进
   `summary`；校验器只检查字段非空。
6. **没有回滚/对账**：ledger 有哈希链，但没有 source 可回指，无法“回到原话”。

## 影响

- **可审计性**：用户问“你凭什么这么记得”时，拿不出来源；开发者无法查
  “这条记忆是从哪句话抽的”。这是 DESIGN 的第一原则。
- **媒体**：用户分享的视频/文章完全不会进入记忆；“媒体分享”是 README
  四层/六 family 的承诺之一。
- **可信度**：第三方转述和亲口说的记忆权重一样（`confidence=1.0`），
  会污染判断；DESIGN 明确要求 0.7。
- **人格蒸馏**：persona 的 `lineage.sources` 也依赖 source 链；没有源，
  人格修订无法追溯（ISSUE-0006）。
- **隐私**：把原始消息写进 `sources` 会增加敏感数据面，需要和 scope/加密
  一起设计；这是做之前要明确的代价。

## 建议方案

| 方案 | 做法 | 代价 | 风险 | 能否解决 |
|---|---|---|---|---|
| A. 全链路：source + evidence + media + adapter | 缓冲每条消息写 `sources`（umo/role/at/text/flags）；抽取请求带 source id，返回 `source_ids`；写记忆后 `link_evidence`；抽取新增 media 类型；定义 `SourceAdapter` 接口 + 内置 `MessageAdapter`（trust 1.0），外部源先留空实现 | 3~5 人日；改 buffer/抽取/DB/测试；sources 会放大存储 | 原始消息长期保留的隐私/体积；模型返回 source 映射可能错 | 能 |
| B. 只补 source/evidence | 缓冲落 sources；每条记忆挂 evidence；不碰 media/adapter | 1~2 人日；改动集中 | 媒体/第三方/外部源仍未解决 | 解决溯源，不解决 media |
| C. 只补 media 抽取 | 抽取 prompt 加 media 类型 + URL 检测；写 media family | 1~2 人日；用户可见 | 没有源/证据，媒体无法追溯 | 只能解决媒体 |

### 推荐

**B 先做，A 分阶段；C 可以并行。**

1. **Source/evidence（先做）**：`buffer_message` 除了 `_pending`，写一条
   `sources(id, umo, at, role, text, flags)`；夜间抽取时把 source id 列表
   一起给模型，要求每条记忆返回 `source_ids`；写入后 `link_evidence`，
   `lineage.sources` 填上。失败时保留 buffer，不阻断记忆写入。
2. **media（并行）**：抽取 prompt 增加一个 `media` 输出分支（type/title/url/
   summary），只对消息里含 URL 或视频/图片事件时调用；`main` 按返回的 family
   分别 `make("media"/"memory")`；校验器已经能挡住空 title/url。
3. **SourceAdapter（后做）**：先定义抽象接口和 `MessageAdapter`（trust=1.0），
   外部源（web/search/video）留空实现；等真正接入时再填 fetch/summarize，
   不要为了“留口”写一个假实现。
4. **第三方**：抽取时若来源是转述（“他说/听说”），写 `said_by=third_party`、
   `confidence=0.7`；这条规则先用关键词，误判可接受，后续再模型判断。

## 验收标准

- [ ] 每条新记忆都有至少一个 `source`（`evidence` 表可查），
      `lineage.sources` 非空；能通过 source 回到原消息。
- [ ] 抽取失败/写库失败时 source 不丢；重复抽取不产生重复 evidence。
- [ ] 含 URL/视频的消息能产出 `family=media`，payload 含 type/title/url/summary；
      不存正文。
- [ ] `SourceAdapter` 有抽象接口与至少一个 `MessageAdapter` 实现；
      trust 分级可读。
- [ ] 第三方转述写入 `said_by=third_party`、`confidence≈0.7`。
- [ ] 合并出的 impression 的 `lineage.sources` 是成员 sources 的并集。
- [ ] 新增测试：source/evidence、media 抽取、第三方标记、合并继承。

## 决策记录

- 2026-10-21：开 issue，只记录现状，不改代码。
- 待定：原始消息保存多久/是否加密；source id 的生成规则；media 是否单独
  调一次模型；adapter 的 trust 是否可配置。

## 参考

- `store/db.py:153-171`、`store/schema.sql:50-63`
- `main.py:233-245`
- `maintain/merge.py:159-161`
- `core/families/media.py:17-27`
- `recall/assemble.py:74-89`、`:134-135`
- `perceive/extract.py:22-29`
- `core/artifact.py:55-71`、`:151-152`
- `docs/DESIGN.md:10`、`:51`、`:144`、`:338-344`、`:390-424`、`:519`、`:559-566`
