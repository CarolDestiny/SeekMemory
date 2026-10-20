# ISSUE-0003 检索从不按 scope 过滤：private / shadow 记忆会被注入给所有人

> 一句话：`main._recall_block()` 直接 `self.cache.active()` 取全库，`select()` 和
> `assemble.build()` 都不看 `scope`；`scope=shadow` 的正文会被当普通记忆全文注入。
> benchmark 的“零泄漏”是脚本自己先按 scope 筛过池子，不是生产代码的能力。

| 项 | 值 |
|---|---|
| 编号 | ISSUE-0003 |
| 级别 | P1（功能失效 + 隐私边界失效；未到 P0 的“数据损坏/崩溃”） |
| 状态 | closed |
| 报告人 | 审计记录（agent） |
| 日期 | 2026-10-21 |
| 关联 PR | [PR-0003](PR-0003.md)（分支 `fix/issue-0003-0004-scope-and-designated`） |
| 影响版本 | `main` @ `1be8baa` |
| GitHub | 待同步 |

## 症状

- 打开 `open_to=everyone` 或 `owner_and_trusted` 后，A 的私聊记忆和 B 的私聊记忆
  进同一个缓存池；任何人的提问都可能召回别人的记忆。
- `scope=shadow` 的记忆（benchmark 里就是别人的私聊）在 `assemble` 里走
  `_memory_sentence()`，把正文原样注入，而不是只给影子句。
- 印象没有按人隔离：`merge_similar()` 生成的 impression 只带一个
  `scope=private/shared`，没有“对谁”的标识；`assemble` 取第一条 impression
  常驻头部，A 的印象会出现在 B 的上下文里。

## 现状（代码证据）

```text
main.py:145   def _recall_block(self, text: str) -> str:
main.py:147       pool = self.cache.active()          # 全库 active，无 scope 过滤
main.py:151       seed_ids = seeds(text, pool)
main.py:152       activation = activate(seed_ids, self.graph, self.cache)
main.py:153       candidates = [(a, float(activation.get(a.header.id, 0.0))) for a in pool]
main.py:154       picked = select(candidates, text, 0.0, ...)
main.py:161       return assemble_text(picked, budget=...)

store/cache.py:50   def active(self, family=None):
store/cache.py:52       ids = set(self._items) if family is None else ...
store/cache.py:53       return [self._items[i] for i in sorted(ids) if i in self._items]

store/db.py:112   def list(self, family=None, state=None):
store/db.py:116       for column, value in (("family", family), ("state", state)):
```

`scope` 只被写入、持久化和还原，没有任何筛选：

```text
core/artifact.py:67   scope: str = "private"
store/db.py:96        parent if isinstance(parent, str) else None, blob, h.state, h.scope,
store/db.py:213       scope=str(row["scope"]), ...
```

读路径没有任何一处读 `header.scope`（`recall/seed.py`、`recall/score.py`、
`recall/assemble.py` 里都没有 `scope`）。`assemble._sentence()` 只按
`family` 分派（`recall/assemble.py:131-144`）：

```text
recall/assemble.py:131  def _sentence(art):
recall/assemble.py:133      family = art.header.family
recall/assemble.py:134      if family == "media": ...
recall/assemble.py:136      if family in ("secret", "designated"): ...
recall/assemble.py:140      if family == "persona": ...
recall/assemble.py:142      level = ...
recall/assemble.py:144      return layer, _memory_sentence(art)
```

因此 `family=memory, scope=shadow` 不会走影子分支，而是走 `_memory_sentence()` 的
全文。只有 `family=secret/designated` 才被保护（见 ISSUE-0004）。

复核命令：

```bash
cd SeekMemory
grep -rn "scope" --include="*.py" recall main.py core/artifact.py store/cache.py
grep -n "self.cache.active\|def _recall_block" main.py
sed -n '50,53p' store/cache.py
```

benchmark 的 0 泄漏来自脚本自己筛池子：

```text
benchmarks/scale.py:70   owner_pool = [a for a in cache.active() if a.header.scope == "private"]
benchmarks/scale.py:71   other_pool = [a for a in cache.active() if a.header.scope == "shadow"]
benchmarks/e2e.py:284    OWNER = [a for a in CACHE.active() if a.header.scope != "shadow"]
```

也就是说，`scale.md` / `e2e.md` 测的是“如果调用方先按 scope 过滤，会不会泄漏”，
不是生产路径 `main.py:147` 的行为。

## 设计期望

- DESIGN §2 `scope` 表（`docs/DESIGN.md:80-86`）：
  `private` 只对当事人、全文；`shared` 共同经历、全文、人称“你们”；
  `shadow` 有这件事但内容不可见、只注入影子句。
- DESIGN §7.4（`:346-352`）：影子内容锁死当事人 scope，影子全局可见，
  影响沉淀 self。
- DESIGN §7.3（`:338-344`）：第三方信息“记到当事人 scope，不向外扩散”。
- DESIGN §4.2（`:142`）：写入时每条要标 `scope`（四维之一）。

## 差距

1. **读路径没有 viewer 概念**：`_recall_block(text)` 只接文本，不接 `event`/`umo`；
   即使想过滤也没有“当前是谁在看”的参数。
2. **缓存和 DB 查询都没有 scope 维度**：`Cache.active()`、`DB.list()` 只有
   family/state 过滤。
3. **shadow 只按 family 保护，不按 scope 保护**：`family=memory, scope=shadow`
   会全文注入；`family=secret` 才走 `shadow_text`。
4. **印象没有“对谁”**：`merge_similar()` 只写 `scope=shared|private`
   （`maintain/merge.py:165-167`），没有 owner/umo；`assemble` 头部取第一条
   impression（`recall/assemble.py:198`），不区分人。
5. **写入端也没标 scope**：`perceive/extract.py:22-29` 的字段清单没有 `scope`；
   `main.py:233` `make("memory", it)` 全部落默认 `private`，没有从对话/角色推断。

## 影响

- **隐私**：只要不是默认 `owner_only`，别人的私聊内容就可能进入当前对话；
  `shadow` 记忆是明文注入，不是影子句。这是用户能直接看到的泄漏。
- **人格错位**：A 的印象被注入到 B 的对话里，直接违背“A 的印象 ≠ B 的印象”。
- **基准失真**：`scale.md`/`e2e.md` 的“零泄漏”不能作为生产保证；
  对外引用时必须说明是 benchmark 预过滤后的结果。
- **不涉及**：单 owner + 单私聊的默认配置下，写入端只有 owner，短期不一定出现
  跨人泄漏；但 `scope=shadow` 的全文注入与“印象按人”仍然是错的。

## 建议方案

| 方案 | 做法 | 代价 | 风险 | 能否解决 |
|---|---|---|---|---|
| A. 在检索入口加 viewer 过滤 | `_recall_block(event)` 取 `umo`/sender/chat_type；`pool` 按 `scope` 过滤：`private` 仅 `said_by==viewer`，`shared` 全放，`shadow` 转成影子句；`select`/`assemble` 只拿过滤后的池 | 1~2 人日；要定义 viewer 身份映射（owner/trusted/guest、群成员） | 身份映射错会误伤；`said_by` 现在全是默认 owner，需要先修写入（ISSUE-0013） | 能解决 private/shared/shadow 的选择 |
| B. 在 Cache/DB 层做 scope 视图 | `Cache.active(viewer)` 或 `db.list(scope=...)`；检索层不感知 scope | 2~3 人日；缓存要多维索引，失效逻辑变复杂 | 改动面大；容易在别处绕过 | 能，且更彻底 |
| C. 只修 shadow | 在 `_sentence()` 里判断 `scope=="shadow"` 走影子句，private/shared 暂不隔离 | 0.5 人日；只堵最明显的泄漏 | 不解决“A 的印象给 B” | 只能止血 |

### 推荐

**A + 先修 C 止血。** 分两步：

1. 立刻在 `_sentence()` 增加 `scope=="shadow"` 分支，输出
   `payload.get("shadow_text")` 或固定影子句，禁止正文；同时给
   `family=memory, scope=shadow` 补回归测试。
2. 给 `_recall_block` 加 viewer 参数，先做最小规则：
   `private` 且 `said_by != viewer` 直接排除；`shared` 保留；`shadow` 只留影子句。
   `said_by` 的写入在 ISSUE-0013 里一起补，否则过滤条件没有数据可用。
3. 印象按 scope：短期先在 impression payload 里写 `owner`/`umo`，`assemble` 只取
   当前 viewer 的 impression；等写入端能稳定产出 owner 后再考虑独立表。

不建议先做 B：当前 `Cache` 只有 family/level 两个索引，加 scope 视图会牵动
所有检索测试；先让入口正确，再谈缓存层优化。

## 验收标准

- [ ] `scope=shadow` 的记忆在任何情况下都不输出 `payload["text"]`，只输出影子句。
- [ ] 用两个不同 `said_by` 的 private 记忆做探针，A 的查询结果里不出现 B 的文本。
- [ ] `shared` 记忆仍可被双方召回，人称仍是“你们”。
- [ ] 印象节点带 owner/umo，A 的 impression 不出现在 B 的注入里。
- [ ] `benchmarks/scale.py` 不再需要手动 `owner_pool` 过滤，生产路径直接跑出 0 泄漏。
- [ ] 补回归测试：private/shared/shadow 三档 + 两个 viewer 的交叉探针。

## 决策记录

- 2026-10-21：开 issue，只记录现状，不改代码。
- 2026-10-21：PR-0003 修复并合并（merge `fa26feb`）。`main._visible()` 按
  `unified_msg_origin` 过滤 private，shadow 在 `assemble` 里只输出影子句；
  新增 `recall/scope.py`、`DB.source_umo()` 与 11 条回归测试。印象 owner 与
  benchmark 去掉预过滤两项未在本 PR 处理，仍按验收标准留作后续。
- 待定：viewer 身份是否直接用 `unified_msg_origin`；群成员是否算独立 viewer；
  印象 owner 放 payload 还是新表。

## 参考

- `main.py:145-161`、`store/cache.py:50-53`、`store/db.py:112-121`
- `recall/assemble.py:131-144`
- `maintain/merge.py:165-167`
- `benchmarks/scale.py:70-71`、`benchmarks/e2e.py:284`
- `docs/DESIGN.md` §2、§7.3、§7.4
- `docs/CONTRACT.md:96`（`DB.list` 没有 scope 参数）
