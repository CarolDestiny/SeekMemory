# ISSUE-0007 每周整理只跑“衰减 + 合并”两步：六步流程缺四步，Dream 矛盾检查与审批完全没有

> 一句话：`_weekly_loop()` 确实会跑，`_weekly()` 也确实被调用，但它只调用了
> `decay_all()` 和 `merge_similar()`；DESIGN §4.5 的“缓冲沉淀 → 衰减 → 合并 →
> 晋升 → 关系曲线 → 反思复盘”只实现了第 2、3 步，Dream 的矛盾检查/提案/审批
> 在代码里不存在。

| 项 | 值 |
|---|---|
| 编号 | ISSUE-0007 |
| 级别 | P2（能力缺失：周任务编排与 Dream 审批流未实现） |
| 状态 | open |
| 报告人 | 审计记录（agent） |
| 日期 | 2026-10-21 |
| 关联 PR | 待开（建议分支 `feat/issue-0007-weekly-dream`） |
| 影响版本 | `main` @ `1be8baa` |
| GitHub | 待同步 |

## 症状

- 周任务在周日 23:55 触发，日志只有“遗忘 N 条，合并 M 组”，没有缓冲沉淀、
  没有晋升、没有关系曲线、没有反思复盘。
- 如果周日 23:55 插件不在线，这一周不会补跑；没有“上次成功时间”的持久化记录。
- 没有 Dream：不会检查“上周说在杭州、这周说在上海”这类矛盾，也不会生成
  “待确认/待审批”的提案；更没有 owner 批准/拒绝的路径。
- 周任务固定 23:55，DESIGN 写的是周日 23:50；`summary_time` 可配，周任务时间
  不可配。

## 现状（代码证据）

调度确实存在：

```text
main.py:177   @filter.on_astrbot_loaded()
main.py:178   async def start_jobs(self) -> None:
main.py:179       asyncio.create_task(self._nightly_loop())
main.py:180       asyncio.create_task(self._weekly_loop())

main.py:190   async def _weekly_loop(self) -> None:
main.py:191       while True:
main.py:192           await asyncio.sleep(self._seconds_until("23:55", weekday=self._c("weekly_day", 6)))
main.py:193           try:
main.py:194               await self._weekly()
```

但 `_weekly()` 只有两步：

```text
main.py:258   async def _weekly(self) -> None:
main.py:259       from .maintain.decay import decay_all
main.py:260       from .maintain.merge import merge_similar
main.py:264       today = datetime.date.today().isoformat()
main.py:265       dropped = decay_all(self.db, self.cache, today)
main.py:266       merged = merge_similar(self.db, self.cache, threshold=0.6)
main.py:267       logger.info(f"[seekmemory] 每周整理：遗忘 {dropped} 条，合并 {merged} 组")
```

没有 import `promote`、`reflect`、任何 relationship 模块；`grep -rn "dream"`
全仓库 0 命中。`store/schema.sql` 没有 proposal / review / job_run 表
（`:1-69` 只有 blobs/ledger/nodes/edges/sources/evidence）。

`_seconds_until()` 每次只算“下一个目标时刻”，没有持久化“上次成功”：

```text
main.py:198   @staticmethod
main.py:199   def _seconds_until(hhmm: str, weekday: int | None = None) -> float:
main.py:204       now = datetime.datetime.now()
main.py:205       target = now.replace(hour=hh, minute=mm, ...)
main.py:206       if target <= now:
main.py:207           target += datetime.timedelta(days=1)
main.py:208       if weekday is not None:
main.py:209           while target.weekday() != weekday:
main.py:210               target += datetime.timedelta(days=1)
main.py:211       return max((target - now).total_seconds(), 60)
```

重启后从“下一个周日 23:55”重新等，错过的那次不会补。

## 设计期望

- DESIGN §4.5（`docs/DESIGN.md:176-187`）：双触发——定期每周日 23:50 全量六步；
  紧急 `active > 500` 只合并最旧 50 条。每周六步：
  `1 缓冲沉淀 → 2 衰减计算 → 3 聚类合并 → 4 晋升检查 → 5 关系曲线滑窗 → 6 反思复盘`。
- DESIGN §4.4（`:164-174`）：五级淘汰，其中第 4 级晋升、 第 5 级物理清理
  都属于周任务的一部分。
- DESIGN 开头（`:4`）与 v2（`:476`）：`Dream` 审批流是明确的设计来源/能力。
- DESIGN §13 v2（`:476`）：`Dream 审批` 属于 v2 范围。
- DESIGN §11（`:442-450`）：没有命令面，审批也只能通过对话完成，不能加 `/approve`。

## 差距

1. **六步缺四步**：第 1 步缓冲沉淀（周任务不做，只有夜间做）、第 4 步晋升
   （`promote_candidates` 无调用方，见 ISSUE-0006）、第 5 步关系曲线
   （没有模块，见 ISSUE-0008）、第 6 步反思复盘（`reflect.signals` 无调用方，
   见 ISSUE-0014）。
2. **没有 Dream**：没有矛盾检测（同主体/同属性/相反值）、没有提案对象、
   没有审批状态机、没有回滚。
3. **没有补跑**：没有 `job_runs`/`last_weekly_at`；停机错过就等下周。
4. **没有失败重试/断点**：任一步抛异常，后面的步骤不执行；没有“从第 N 步继续”。
5. **时间不一致**：DESIGN 周日 23:50，代码 23:55；周任务时间不可配。
6. **紧急触发没有独立检查**：`active > 500` 只在周任务里通过 `merge_similar`
   的池子大小判断（见 ISSUE-0010），不是“随时检查”。

## 影响

- **用户可感知**：人格不会晋升、关系不会更新、错误不会复盘；周任务看起来在跑，
  实际只做了“忘掉一些、合并一些”。
- **数据**：合并后的印象没有晋升，永远停在 impression；矛盾事实（旧地址/新地址）
  同时 active，检索时随机给一个。
- **可运维性**：错过一次要等 7 天；没有 last_run 日志，无法判断“到底跑没跑”。
- **产品承诺**：README/COMPARISON 把“每周整理 2 次模型调用”“Dream 审批”作为
  设计卖点；当前只有 0 次模型调用的两步。

## 建议方案

| 方案 | 做法 | 代价 | 风险 | 能否解决 |
|---|---|---|---|---|
| A. 六步编排 + job_runs + 补跑 | `_weekly` 改成六个幂等函数，逐步 try/except + 日志；新增 `job_runs(job, started_at, finished_at, status, detail)`；启动时若 `last_weekly_at > 7d` 立即补跑；周任务时间可配 | 2~3 人日；要设计幂等键 | 补跑可能一次处理太多；某步失败要能跳过 | 能解决编排/补跑 |
| B. 只补缺失调用 | 在 `_weekly` 里加 `promote_candidates`、`relationship`、`reflect` 调用；不做 job_runs | 0.5~1 人日；快 | 仍无补跑/断点；失败即中断 | 只能让六步“存在” |
| C. Dream 单独子系统 | 新增 proposal 表 + 每周矛盾检测 + owner 对话审批；不并入六步 | 3~5 人日；复杂 | 审批入口与“无命令”原则冲突，需要设计对话协议 | 能，但工作量大 |

### 推荐

**先 A 的编排骨架，再单独做 C 的 Dream。** 分三步：

1. 把六步拆成 `_weekly_settle/_weekly_decay/_weekly_merge/_weekly_promote/
   _weekly_relation/_weekly_reflect`，每步独立 try/except，最后汇总日志。
2. 加 `job_runs` 表，记录开始/结束/状态/计数；启动时检查上次成功时间，
   超过 7 天补跑一次（只补一次，避免雪崩）。
3. Dream 单独 issue/PR：先做“同主体 + 同属性 + 相反值”的规则检测，
   产出 `proposal`（不改原记忆）；审批先走 owner 私聊的一句确认，
   批准后写新 revision，拒绝则记 ledger。不要加 `/approve` 命令。

## 验收标准

- [ ] 周任务日志能分别看到六步的输入/输出计数，任一步失败不影响后续步骤。
- [ ] 启动时若距上次成功 >7 天，会自动补跑一次，并记录 `job_runs`。
- [ ] 六步中至少第 1/4/5/6 步有真实调用（不是空函数占位）。
- [ ] Dream 能对“旧地址/新地址”这类矛盾产出 proposal，且不自动覆盖原记忆。
- [ ] owner 能在对话里批准/拒绝 proposal；批准后有 revision/ledger，拒绝有记录。
- [ ] 周任务时间可配置，默认与 DESIGN 的周日 23:50 对齐（或明确改设计）。
- [ ] 新增测试：六步顺序、失败继续、补跑、proposal 状态机。

## 决策记录

- 2026-10-21：开 issue，只记录现状，不改代码。
- 待定：`job_runs` 放 SQLite 还是文件；补跑窗口；Dream 审批的对话协议；
  周任务时间是否直接改 DESIGN 为 23:55。

## 参考

- `main.py:177-180`、`:190-211`、`:258-267`
- `store/schema.sql:1-69`（无 job/proposal 表）
- `maintain/promote.py:24-32`、`maintain/reflect.py:77-111`
- `docs/DESIGN.md:4`、`:164-174`、`:176-187`、`:442-450`、`:476`
