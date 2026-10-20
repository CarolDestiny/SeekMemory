# ISSUE-0012 时间只做了半截：相对时间缺“上个月/很久以前”，事件时间被写成写入时间，chrono/有效期不参与检索

> 一句话：`assemble._when()` 只有今天/昨天/前几天/前阵子/N个月前/去年六档，
> 没有“上个月”“很久以前”，而且用 `date.today()` 现算；更根本的是
> `core.artifact._stamp()` 把 `created` 写成“入库那一刻”，抽取提示词没有事件时间，
> 所以任何“上个月发生的事”都会在第二天被说成“昨天/今天”。`chrono`、
> `valid_from/valid_to/expires` 在检索和衰减里都没有被读。

| 项 | 值 |
|---|---|
| 编号 | ISSUE-0012 |
| 级别 | P2（能力缺失 + 时间表达错误：会注入错误的时间锚点） |
| 状态 | open |
| 报告人 | 审计记录（agent） |
| 日期 | 2026-10-21 |
| 关联 PR | 待开（建议分支 `fix/issue-0012-time`） |
| 影响版本 | `main` @ `1be8baa` |
| GitHub | 待同步 |

## 症状

- 三天前的事能说“前几天”，但 40 天前会说“1个月前”，不是“上个月”；
  半年以上只会说“N个月前/去年”，没有“很久以前”。
- 记忆的 `created` 是夜间入库时间，不是事情发生时间。昨天聊到“上个月我搬家”，
  今天注入会说“你今天说上个月搬家”或“昨天…”，相对时间锚点错了。
- `chrono=periodic/annual` 没有加权：作息不会在窗口 ×1.5，生日不会当天 ×2.0。
- `valid_to/expires` 过期的 span 仍然 active、仍然可被检索；`rule` 的时间窗
  也没有参与打分。
- 如果 `created` 是未来日期（模拟数据或时钟回拨），`_when()` 的 `delta < 0`
  会落进“今天”。

## 现状（代码证据）

`_when()` 的六档：

```text
recall/assemble.py:61    def _when(created: str) -> str:
recall/assemble.py:64        day = date.fromisoformat(str(created)[:10])
recall/assemble.py:67        delta = (date.today() - day).days
recall/assemble.py:68        for limit, word in ((0, "今天"), (1, "昨天"), (10, "前几天"), (30, "前阵子")):
recall/assemble.py:69            if delta <= limit:
recall/assemble.py:70                return word
recall/assemble.py:71        return f"{delta // 30}个月前" if delta < 365 else "去年"
```

- 31~59 天 → “1个月前”，没有“上个月”这个更自然的说法；
- 60~364 天 → “2~12个月前”，没有“半年前”“很久以前”；
- `delta < 0`（未来）→ `delta <= 0` 命中“今天”；
- 用 `date.today()`，测试无法注入固定时间。

`created` 是入库时间：

```text
core/artifact.py:99    def _stamp(time: TimeSpan) -> TimeSpan:
core/artifact.py:100       now = _now()
core/artifact.py:101       return replace(time, created=time.created or now, updated=time.updated or now)
core/artifact.py:111       kw["time"] = _stamp(kw.get("time") or TimeSpan())
main.py:233               art = make("memory", it, strength=_strength_of(it))
```

`main.py:233` 没有传 `time`，所以 `created` 是当晚 23:50；抽取提示词也没有
事件时间字段：

```text
perceive/extract.py:22   每条输出一个对象，字段固定：
perceive/extract.py:23   - level: ...
perceive/extract.py:24   - text: ...
perceive/extract.py:25   - about: ...
perceive/extract.py:26   - arousal: ...
perceive/extract.py:27   - valence: ...
perceive/extract.py:28   - funny: ...
perceive/extract.py:29   - first: ...
```

`chrono`/有效期不参与检索：

```text
recall/score.py:168   return (
recall/score.py:169       3.0 * dice(...)
recall/score.py:170       + 2.0 * _tag_match(...)
recall/score.py:171       + 1.5 * _emotion_value(...)
recall/score.py:172       + 1.0 * weight
recall/score.py:173       + 0.5 * _freshness(created, now_days)
recall/score.py:174       + 1.5 * max(0.0, activation)
recall/score.py:175       - 2.0 * recent
recall/score.py:176   )
```

`_freshness()` 只看 `created`（`recall/score.py:115-126`）；`valid_from/valid_to/
expires` 在 `recall/` 里没有被读。`decay.py` 也不看它们（`maintain/decay.py:46-54`）。

## 设计期望

- DESIGN §6.3（`docs/DESIGN.md:294-299`）：数据存绝对 `2026-10-18`，
  注入用相对“三天前”；README 明确说“上个月”。
- DESIGN §2 `chrono`（`:88-94`）：`periodic` 落在窗口 ×1.5；`annual` 当天 ×2.0。
- DESIGN §10 时间锚点（`:428-438`）：`rule + periodic` 作息窗口 ×1.5；
  `point + annual` 生日当天 ×2.0；`relation` 纪念日；应验才强化；
  节日表硬编码未来 3 年，可配置。
- DESIGN §1 `time`（`:43-49`）：`at`（发生时间）、`valid_from/valid_to/slot/tolerance`。
- **规格缺口**：DESIGN §1 有 `time.at`，但 v3 的 `TimeSpan`（`docs/CONTRACT.md:21-27`、
  `core/artifact.py:46-53`）没有 `at` 字段；实现前要先决定“事件时间”放哪
  （`at` / `valid_from` / 新字段）。

## 差距

1. **缺少“上个月/很久以前”档**：只有六档，且用 `delta//30`，不是日历月。
2. **锚点错**：`created` = 入库时间，不是事件时间；抽取不产出 `at`，
   写入不传 `time`。
3. **`_when` 不可测试**：硬编码 `date.today()`，没有 `now` 参数。
4. **未来日期当今天**：`delta < 0` 没有处理。
5. **chrono 不参与打分**：`periodic`/`annual` 的 ×1.5/×2.0 都没实现。
6. **有效期不过滤**：`valid_to/expires` 过期仍 active、仍注入。
7. **`rule` 时间窗不参与**：没有“现在是不是他通常吃饭的时间”的判断。
8. **没有节日/纪念日表**：DESIGN 要求硬编码未来 3 年，可配置；代码里没有。

## 影响

- **用户可感知**：bot 会把旧事说成“昨天/今天”，或者把“上个月”说成“1个月前”；
  时间感是“像人”的核心，错了很出戏。
- **检索**：过期的事实（旧地址/旧工作）继续被注入；生日/作息永远不会被强调。
- **衰减**：`valid_to` 过期不 forgotten，只能等 retention 慢慢掉。
- **基准**：`ANALYSIS.md:145` 已记录“合成日期有部分落在当前时间之后，
  `_freshness` 把负年龄截成 0、`_when` 标成今天”，说明这不是纯理论问题。

## 建议方案

| 方案 | 做法 | 代价 | 风险 | 能否解决 |
|---|---|---|---|---|
| A. 补事件时间 + 日历档 + chrono/有效期 | 抽取增加 `at`（可空）；写入落 `time.valid_from` 或新字段；`_when(created, now)` 改成日历感知（今天/昨天/前天/上周/上个月/前几个月/去年/很久以前）；score 加 chrono 系数、过滤 `valid_to/expires`；rule 窗口 ×1.5；节日表 | 2~3 人日；要改 CONTRACT/TimeSpan/抽取 prompt/迁移 | 模型给的时间可能错；日历档边界多；迁移旧数据 | 能 |
| B. 只修相对时间档 | `_when` 加“上个月/很久以前”、接 `now` 参数、处理未来；不动事件时间 | 0.3~0.5 人日；测试友好 | 锚点仍是入库时间，旧事还是错 | 只能解决表达 |
| C. 用消息时间戳做锚点 | 缓冲里保存每条消息的 `event.time`，抽取时取最早/最晚；不依赖模型 | 1 人日；比模型可靠 | 只能精确到“对话发生时间”，不能精确到“他说的上个月” | 能改善大多数场景 |

### 推荐

**C + B 先做，A 分阶段。**

1. **先修表达**：`_when(created, now)` 接 `now`，档位改成
   今天/昨天/前天/上周/上个月/前几个月/去年/很久以前；`delta < 0` 返回“刚刚/今天”
   并记 warning。
2. **再修锚点**：缓冲保存消息时间戳（ISSUE-0002 的 buffer 表加 `at`）；
   抽取时把对话时间范围给模型，并要求可选 `at`；没有 `at` 时用对话时间，
   而不是入库时间。
3. **最后接 chrono/有效期**：`score` 里读 `payload.chrono` 和 `time.valid_to/expires`；
   `periodic` 在 `slot` 窗口 ×1.5，`annual` 当天 ×2.0；过期直接排除；
   `rule` 的 `slot/tolerance` 参与。
4. **规格**：先把 `time.at` 与 `TimeSpan` 的差异写进 DESIGN/CONTRACT，
   避免实现时又出现“两套时间字段”。

节日的硬编码表可以最后做；没有它，生日仍然能靠 `annual` 当天 ×2.0 被强调，
只是不知道“今天是他的生日”这个语义。

## 验收标准

- [ ] 固定 `now` 的测试里，1 天/3 天/10 天/40 天/200 天/400 天分别输出
      “昨天/前几天/前阵子/上个月/N个月前/很久以前”，不再出现“1个月前”。
- [ ] 未来日期的记忆不显示“今天”，有明确回退（如“刚刚”或空）。
- [ ] 事件时间可写入：昨天聊“上个月搬家”，注入锚点是“上个月”，不是“昨天”。
- [ ] `valid_to` 已过期的记忆不再被检索/注入；`expires` 同理。
- [ ] `periodic` 落在窗口时得分提高；`annual` 当天得分提高（用固定日期验证）。
- [ ] DESIGN/CONTRACT 对“事件时间”字段有唯一约定。
- [ ] 新增测试：相对时间档位、未来日期、过期过滤、periodic/annual 加权。

## 决策记录

- 2026-10-21：开 issue，只记录现状，不改代码。确认 DESIGN §1 的 `time.at`
  在当前 `TimeSpan` 里不存在，需要先补规格。
- 待定：事件时间放 `at` 还是 `valid_from`；相对时间用日历还是天数；
  `rule` 窗口的 `slot/tolerance` 语义；节日表数据来源。

## 参考

- `recall/assemble.py:61-71`、`:121`（只有 scene 才加时间前缀）
- `core/artifact.py:43-52`、`:99-112`
- `perceive/extract.py:22-29`
- `main.py:233`
- `recall/score.py:115-126`、`:168-176`
- `maintain/decay.py:46-54`
- `benchmarks/results/ANALYSIS.md:145`
- `docs/DESIGN.md:43-49`、`:88-94`、`:294-299`、`:428-438`
- `docs/CONTRACT.md:21-27`
