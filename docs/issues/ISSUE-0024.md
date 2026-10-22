# ISSUE-0024 BM25 hybrid retrieval for Chinese memory recall

| item | value |
|---|---|
| id | ISSUE-0024 |
| level | P1 |
| status | open |
| date | 2026-10-21 |
| GitHub | [#4](https://github.com/NeverENG/SeekMemory/issues/4) |
| branch | feat/issue-0024-bm25 |
| proposal | docs/BM25-PROPOSAL.md |

## Problem

Current recall depends on character-bigram overlap, tags and graph activation. Queries that
paraphrase or reorder the original memory often return zero candidates.

RetrievalCandidate.lexical already exists, but no retriever fills it. This is the smallest
surface for adding BM25 without changing the cognitive model, evidence gate or disclosure rules.

## Scope

- Add a tokenizer boundary with a zero-dependency character-bigram default.
- Add an in-memory BM25 index with text and tag fields.
- Add HybridRetriever that merges graph activation and lexical scores.
- Add config keys bm25_enabled and bm25_weight.
- Keep BM25 off by default during shadow rollout.
- Calibrate evidence gate thresholds and lexical weight with benchmarks.
- Keep disclosure and cross-session privacy unchanged.

## Acceptance criteria

- [ ] BM25 index supports add/remove/search and normalized lexical scores.
- [ ] HybridRetriever returns one candidate per Artifact with activation and lexical.
- [ ] BM25 score contributes to evidence gate only through lexical evidence.
- [ ] Empty/punctuation-only queries produce zero lexical evidence.
- [ ] Recall remains correct when bm25_enabled is false.
- [ ] Unit tests cover tokenizer, index, hybrid merge and empty query.
- [ ] Ablation reports hit rate, noise, injected chars and latency on/off.
- [ ] Production default changes only after shadow and staging comparison.

## Implementation checklist

- [ ] recall/tokenizer.py
- [ ] recall/bm25.py
- [ ] Cache.version and index rebuild policy
- [ ] HybridRetriever
- [ ] recall/score.py configurable lexical weight
- [ ] config keys and docs
- [ ] tests/test_bm25.py
- [ ] benchmark before/after

## 补充：2026-10-22 实现决策与校准

- 使用纯本地、无新依赖的字符 bigram BM25，不引入模型、下载器、网络调用或外部服务。
- 不维护人工中文停词表；空输入/纯标点无词项，单字符保留自身，文档保留词频。
- 归一化改为固定映射 `s/(s+C)`，不使用逐查询最大值；正文/标签按 0.75/0.25 融合。
- 保留旧黄金集与证据闸门。权重 2.0 导致旧消融基准 17/18 降至 16/18，已向用户报告。
- 经用户确认扩大权重校准至 0.5/1/1.5/2，与 C=1/2/4/8 交叉比较。
- 冻结参数 C=8、默认权重 1.0：旧集 17/18、检索层噪声 0.4000→0.3723；
  五条字面校准题 0/5→3/5。独立验收集运行前选定，不根据验收结果再调参。
- 原末五条探索题曾观察结果，不作为独立 holdout。新的五条独立合成数据位于
  `benchmarks/bm25_holdout.py`，冻结 SHA256：
  `2C2ADE9A29AEF9D8DD55664B816988340BE09143A31177978EAAB6CCF3BE3569`。
- BM25 默认关闭。复用现有 Retriever 协议，不添加 semantic 占位字段；
  本地向量仅另写提案，用户预装模型、运行时离线，其否决不影响本次 BM25 能力。

## 补充：2026-10-22 验证与评审完成

- 实现与验证记录：[PR-0024](PR-0024.md)。状态保持 open，待 Lead 审阅和 staging 对照。
- [x] tokenizer、正文/标签 BM25 倒排表、Cache.version 和 HybridRetriever 已实现。
- [x] 配置、调用契约、默认关闭兼容、完整管线及 WebUI 诊断只读已验证。
- [x] 旧集保持 17/18、噪声 40.00%→37.23%；独立题 1/5→2/5，未修改数据或金标。
- [x] Python 256 项测试检查通过（11 项宿主测试跳过）；真实 AstrBot 4.28.1 单独运行 11 项全通过。
- [x] 前端类型、lint、29 项测试、2 项跨语言契约及生产构建通过；LF 副本格式检查通过。
- [x] Standards 与 Spec 两轴评审各发现一项问题，均修复并独立复核；没有未解决发现。
- [ ] Lead 审阅、staging 效果和资源对照、生产启用决策。
