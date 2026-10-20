# ISSUE-0005 RBAC 只有一道写入门控：trusted 的 80 字、guest/blocked 的角色语义都没有

> 一句话：`_may_remember()` 只回答“能不能用记忆”这一个布尔值，读路径拿到 true
> 就按同一个 `budget_chars`（默认 600）注入；`trusted` 没有 80 字上限，
> `guest` 的 0 字是“整段不注入”的副作用，`blocked` 角色不存在，反思/改人格
> 的权限也没有落点。

| 项 | 值 |
|---|---|
| 编号 | ISSUE-0005 |
| 级别 | P2（能力缺失：权限模型不完整，但不直接导致崩溃/泄漏） |
| 状态 | open |
| 报告人 | 审计记录（agent） |
| 日期 | 2026-10-21 |
| 关联 PR | 待开（建议分支 `feat/issue-0005-rbac`） |
| 影响版本 | `main` @ `1be8baa` |
| GitHub | 待同步 |

## 症状

- `open_to=owner_and_trusted` 时，trusted 用户和 owner 拿到同一套注入预算
  （配置里的 600 字），DESIGN 要求 trusted 只有 80 字。
- `guest` 目前完全不注入；这碰巧等于“0 字”，但它和“没有权限”是同一个分支，
  无法表达“guest 可以看一点公共记忆但不能写”。
- 没有 `blocked` 角色；`everyone` 模式会把陌生人当 owner 一样给 600 字。
- 反思深度、改人格权限没有代码可挂：反思模块本身没接线（ISSUE-0014），
  人格写入也没实现（ISSUE-0006）。

## 现状（代码证据）

```text
main.py:113   def _may_remember(self, event: AstrMessageEvent) -> bool:
main.py:114       mode = str(self._c("open_to", "owner_only"))
main.py:115       if mode == "everyone":
main.py:116           return True
main.py:117       umo = getattr(event, "unified_msg_origin", "")
main.py:118       if umo == self.owner_umo:
main.py:119           return True
main.py:120       if mode == "owner_and_trusted":
main.py:121           sid = str(event.get_sender_id())
main.py:122           return sid in self.trusted_ids or umo == self.owner_umo
main.py:123       return False
```

读路径只做一次布尔判断，预算来自全局配置：

```text
main.py:131       if not self._may_remember(event):
main.py:132           return
main.py:161       return assemble_text(picked, budget=self._c("budget_chars", 600))
```

配置里只有一个 `budget_chars`：

```text
_conf_schema.json:24   "budget_chars": {
_conf_schema.json:25       "description": "每轮注入记忆的字数上限",
_conf_schema.json:27       "default": 600
_conf_schema.json:8    "open_to": ...
_conf_schema.json:14   "trusted": ...
```

全仓库没有 `blocked` / `guest` 角色常量，也没有按角色查预算的函数。

## 设计期望

DESIGN §7.2（`docs/DESIGN.md:327-336`）明确四角色：

| 能力 | owner | trusted | guest |
|---|---|---|---|
| 注入字数 | 600 | 80 | 0 |
| 写入 | ✅ | ✅ | ❌ |
| 反思 | 深度 | 仅“没人接” | ❌ |
| 改人格 | ✅ | ❌ | ❌ |

并强调“**权限跟着人走，不跟着群走**”。

## 差距

1. **没有角色模型**：只有 `open_to` 三个模式 + 一个 bool，`trusted` 是集合，
   `owner` 是 umo 字符串；没有统一的 `Role` 解析。
2. **没有按角色预算**：`budget_chars` 是全局配置；trusted 拿 600，不是 80。
3. **guest/blocked 语义缺失**：guest 的 0 字是“直接 return”的副作用；
   blocked 根本没有入口，无法显式拉黑。
4. **反思/人格权限没有落点**：`enable_reflect` 配置（`_conf_schema.json:49-53`）
   没有被读；人格写入不存在，所以“owner 才能改人格”无法执行。
5. **“跟人不跟群”只做了一半**：trusted 按 sender id 判断（`main.py:121`），
   owner 按 umo 判断（`:118`）；群里的 owner 发言会因 umo 不同而被当成非 owner。

## 影响

- **预算**：trusted 用户可能拿到 600 字，把 owner 的主预算挤掉；`everyone`
  模式下陌生人也能拿 600 字，成本和隐私都失控。
- **产品语义**：RBAC 是 README/COMPARISON 里明确承诺的能力（README “关系的边界”
  一节）；现在只有“谁能触发”没有“谁能看多少/改什么”，对外说法与实现不一致。
- **安全**：没有 blocked 角色，只能靠清空 `trusted`/切 `owner_only` 间接实现。
- **不涉及**：默认 `owner_only` 下，guest/trusted 都不会进来，短期不暴露；
  这是“配置一改就出问题”的潜在缺陷。

## 建议方案

| 方案 | 做法 | 代价 | 风险 | 能否解决 |
|---|---|---|---|---|
| A. 引入 `Role` 解析 + 权限表 | `resolve_role(event) -> owner/trusted/guest/blocked`；`ROLE_BUDGET = {owner:600, trusted:80, guest:0}`；`can_write/can_reflect/can_edit_persona` 三个谓词；`_recall_block` 接收 budget | 1~2 人日；要改 `inject_memory`/`_may_remember` 调用点；配置加 blocked | 角色判定错会把 owner 降级；需要兼容旧配置 | 能 |
| B. 只加 trusted 预算 + blocked | 保留 bool，读路径按 `sid in trusted` 选 80/600；加 blocked 集合 | 0.5~1 人日；改动小 | 仍然没有反思/人格权限；guest 语义仍靠副作用 | 只能解决预算和拉黑 |
| C. 完全配置化 | 角色→预算/能力放在 `_conf_schema.json`，运行时读 | 2~3 人日；灵活 | 配置复杂度上升；默认值容易配错 | 能，但过度设计 |

### 推荐

**A 的最小版**：先做角色解析和注入预算，反思/人格权限先留谓词占位。

1. `resolve_role(event)`：owner 按 sender id 或配置的 owner umo；trusted 按
   sender id；blocked 新增配置；其余 guest。
2. `ROLE_BUDGET = {"owner": 600, "trusted": 80, "guest": 0, "blocked": 0}`，
   `_recall_block(text, budget)` 用角色预算，不再读全局 `budget_chars`
   （保留配置作为 owner 的可调上限）。
3. 写入仍用 `can_write`（owner/trusted）；反思、改人格先留
   `can_reflect`/`can_edit_persona`，等 ISSUE-0014/0006 接线时使用。
4. 补测试：四种角色 × 注入预算/写入的矩阵；群里 owner 发言仍识别为 owner。

## 验收标准

- [ ] 同一段查询，owner 注入约 600 字、trusted 约 80 字、guest/blocked 为 0。
- [ ] `blocked` 用户即使出现在 `trusted` 名单里也不能写入/注入。
- [ ] owner 在群里发言仍被识别为 owner（“跟人不跟群”）。
- [ ] `can_write` 对 guest/blocked 为 false；反思/人格谓词有明确返回值。
- [ ] 配置向后兼容：旧 `open_to`/`trusted` 不改也能跑。
- [ ] 新增角色矩阵回归测试。

## 决策记录

- 2026-10-21：开 issue，只记录现状，不改代码。
- 待定：owner 判定用 sender id 还是 umo；`budget_chars` 是否保留为 owner 上限；
  blocked 是配置还是数据库表。

## 参考

- `main.py:113-123`、`:131-132`、`:161`
- `_conf_schema.json:8-18`、`:24-28`、`:49-53`
- `docs/DESIGN.md:327-336`
- `docs/CONTRACT.md`（没有角色/预算接口）
