# ISSUE-0004 指定记忆永远不会归还：私聊、触发词、已给状态三条硬条件全缺

> 一句话：`assemble` 对 `family=designated` 只输出“他让你记着一件事，等提到「X」时
> 再告诉他”，`payload["text"]` 从来没有被读出来；`given` 只在校验器里出现，
> 没有任何代码判断私聊、匹配触发词或标记已给。

| 项 | 值 |
|---|---|
| 编号 | ISSUE-0004 |
| 级别 | P1（功能失效：指定记忆存进去就取不回来） |
| 状态 | open |
| 报告人 | 审计记录（agent） |
| 日期 | 2026-10-21 |
| 关联 PR | 待开（建议分支 `fix/issue-0004-designated-return`） |
| 影响版本 | `main` @ `1be8baa` |
| GitHub | 待同步 |

## 症状

- 用户说“帮我记一下，密码是 123，触发词是‘那个东西’”。这条 `designated`
  写进去后，每次注入只会说“他让你记着一件事，等提到「那个东西」时再告诉他”，
  不会把“密码是 123”给她。
- 即使她在私聊里说了“那个东西”，也没有任何路径把 `text` 交出来。
- 群里有人问“那个东西”，也没有“这儿不方便”的打岔逻辑。
- `given` 字段永远不存在，无法知道这条是否已经交付过；重复触发会重复给。

## 现状（代码证据）

```text
recall/assemble.py:102  def _guarded_sentence(art: Artifact) -> str:
recall/assemble.py:104      if art.header.family == "designated":
recall/assemble.py:105          trigger = _clip(art.payload.get("trigger") or "那个东西", 20)
recall/assemble.py:106          return f"他让你记着一件事，等提到「{trigger}」时再告诉他。"
recall/assemble.py:107      shadow = _clean(art.payload.get("shadow_text") or "有件事你答应过别人不说")
recall/assemble.py:108      return f"你记得，{shadow}" if shadow else ""
```

`designated` 的 `text` 是必填（`core/families/designated.py:22`），
`content_of()` 也会返回 `text`（`core/artifact.py:153-156`），但注入路径走
`_guarded_sentence()`，直接忽略 `text`。

`given` 只在校验器里被检查类型：

```text
core/families/designated.py:24   given = payload.get("given")
core/families/designated.py:25   if given is not None and not isinstance(given, (bool, str)):
core/families/designated.py:26       raise ValueError("designated.given 必须是 bool 或时间字符串")
```

全仓库没有第二处 `given`（`grep -rn "given" --include="*.py" .` 只命中
`core/families/designated.py` 与测试）。`trigger` 也只出现在上面的提示句和校验器里，
没有做子串/关键词匹配。

注入入口也没有判断私聊：

```text
main.py:126   @filter.on_llm_request()
main.py:127   async def inject_memory(self, event: AstrMessageEvent, req) -> None:
main.py:133       text = (event.message_str or "").strip()
main.py:137       block = self._recall_block(text)
main.py:139       req.system_prompt = (req.system_prompt or "") + "\n\n" + block + "\n"
```

`event` 是拿得到的，但只取 `message_str`；没有任何 `event.is_private` /
`message_type` / `group_id` 判断。

## 设计期望

- DESIGN §7.1（`docs/DESIGN.md:312-325`）：敏感内容两档——被动听到只留影子；
  **指定记录完整保存，可归还**。指定记忆的取回有**三条硬条件**：
  ① 只在私聊（群里问就打岔/“这儿不方便”）；
  ② 必须触发（密码/上次让我记的/那个东西）；
  ③ 触发后给出。
- DESIGN §7.4（`:346-352`）：影子内容锁死当事人 scope，影子全局可见。
- DESIGN v3 payload（`:520`）：`designated: {text, trigger, given}`。

## 差距

1. **归还路径不存在**：`_guarded_sentence()` 永远返回提示句，不返回 `text`；
   没有“触发后替换成正文”的分支。
2. **没有私聊判断**：`inject_memory` 拿到 `event` 但不用；群里和私聊走同一段逻辑。
3. **没有触发词匹配**：没有 `trigger in text` 或同义词/模糊匹配；提示句里虽然
   写了触发词，但模型看到的是“等提到”，不是“现在已经提到了”。
4. **没有 `given` 状态**：写回、去重、防重复交付都没有。
5. **影子只按 family 保护**：`family=secret` 的 `shadow_text` 路径可用，但
   `scope=shadow` 的普通 memory 仍会全文注入（见 ISSUE-0003）。
6. **写入端没有 designated 抽取**：`perceive/extract.py` 只产出 `memory`；
   “帮我记一下”不会被识别成 designated（见 ISSUE-0013 的来源/写入链路）。

## 影响

- **用户可感知**：指定记忆是最明确的“她答应帮我记”承诺；现在等于只记了个标题，
  永远不兑现。用户会认为她“答应了但没记住”。
- **安全**：反过来，如果以后有人简单地把 `text` 加进提示句，又可能在没有私聊/
  触发条件时泄漏；当前是“过度保守导致失效”，不是泄漏，但修复时容易引入泄漏。
- **模型行为**：注入的提示句会诱导模型自己编“我记着呢，你说那个东西”，
  实际拿不出内容，属于典型的“假装记得”。

## 建议方案

| 方案 | 做法 | 代价 | 风险 | 能否解决 |
|---|---|---|---|---|
| A. 在 `inject_memory` 做交付协议 | 取 `event` 的私聊标志与 `text`；遍历 designated：私聊 + `trigger in text` + 未 `given` → 把 `text` 作为单独一段“现在可以告诉他：…”注入，并 `revise(given=now)` 落库；群里命中触发词 → 注入“这儿不方便，私聊说”；私聊未触发 → 只给提示句 | 1~2 人日；要确认 AstrBot 的私聊 API；要处理一条内容多次触发 | 触发词误匹配；`given` 写回失败会重复给；群里打岔可能被模型忽略 | 能覆盖三条硬条件 |
| B. 独立 `designated` resolver | 在组装前跑一个纯函数 `resolve(arts, text, is_private) -> (block, updates)`；`assemble` 不碰 designated | 1.5~2 人日；多一层调用 | 需要新的返回协议；测试面变大 | 能，边界更干净 |
| C. 只做私聊 + 子串触发 | 不做模糊匹配、不做 `given`，命中就给 | 0.5 人日；止血 | 群里仍可能给；重复给；触发词覆盖窄 | 只能止血 |

### 推荐

**A 先落地，B 作为重构方向。** 具体：

1. 在 `inject_memory` 里先判断私聊；群里不走 designated 正文。
2. 触发词先用精确子串 + 去空白匹配；命中且 `given` 为空 → 把
   `payload["text"]` 注入为“他现在问的就是那件事，你可以告诉他：<text>”。
3. 交付后 `revise(art, payload={**payload, "given": now})`，`db.upsert` +
   `cache.put`；同一轮只交付一次。
4. 群里命中触发词只注入“这儿不方便，私聊说”，不注入正文。
5. 补测试：私聊命中、私聊未命中、群聊命中、重复命中、`given` 已存在五种。

不建议把 `text` 直接拼进 `_guarded_sentence()`：那会让所有 designated 每次
都全文注入，等于绕过三条硬条件。

## 验收标准

- [ ] 私聊 + 触发词命中 + 未 given：注入正文，且 `given` 被写回。
- [ ] 私聊 + 未命中：只给提示句，不出现正文。
- [ ] 群聊 + 命中：只出现“这儿不方便/私聊说”，正文不出现。
- [ ] 已 given 的记忆再次触发不重复交付（或按配置只提示“已经给过”）。
- [ ] `grep -rn "given" --include="*.py"` 不再只有校验器；有写回路径。
- [ ] 新增回归测试覆盖上述五种组合。

## 决策记录

- 2026-10-21：开 issue，只记录现状，不改代码。
- 待定：AstrBot 私聊判断用哪个字段；触发词是否支持模糊/同义；交付后是否保留
  `given` 时间而不是布尔；群里打岔的固定文案。

## 参考

- `recall/assemble.py:102-108`
- `core/families/designated.py:17-29`
- `core/artifact.py:144-156`
- `main.py:126-143`
- `docs/DESIGN.md:312-325`、`:346-352`、`:520`
