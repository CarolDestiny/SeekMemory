# ISSUE-XXXX 标题（一句话说清问题，不写解决方案）

| 项 | 值 |
|---|---|
| 编号 | ISSUE-XXXX |
| 级别 | P0 / P1 / P2 |
| 状态 | open / in-progress / closed |
| 报告人 | |
| 日期 | YYYY-MM-DD |
| 关联 PR | PR-XXXX（未开则写"待开"） |
| 影响版本 | commit / tag |
| GitHub | 待同步 |

## Language requirement

Write this issue in English first, then add a complete Chinese translation under a
`## Chinese translation` heading in the same issue. Keep code identifiers and paths unchanged.

## Why this issue

Explain why this must be handled now: user-visible problem, architectural coupling, or a
prerequisite for future capability. Do not write only "add a module".

## Current context

List current entry points, files, call chain and mixed responsibilities. Distinguish facts
from guesses. Use file:line where possible.

## Change scope and boundary

| Item | In scope | Not in scope |
|---|---|---|
| New module | | |
| Adapter | | |
| Entry-point changes | | |
| Data/protocol | | |

## Adapter boundary

State what the host provides, which ports the runtime depends on, and what host types must
never leak into core/runtime code.

## 症状

<!-- 用户或调用方看到什么？错误信息、错误行为、缺失行为。只写现象，不写猜测的原因。 -->

## 复现

环境：

- 系统 / Python：
- 依赖 / 模型：
- 数据：

步骤与命令（从仓库根目录执行，尽量最小化）：

```bash
```

实测输出：

```text
```

如果问题依赖特定数据或模型，说明数据从哪来、模型怎么固定；不能稳定复现时写清概率和条件。

## 期望 vs 实际

| | 内容 |
|---|---|
| 期望 | |
| 实际 | |

## 根因分析

<!-- 指向具体文件:行，解释调用链。区分"已证实"和"猜测"；猜测要写验证方法。 -->

## 影响面

- 用户：
- 模块 / 调用链：
- 数据 / 隐私：
- 性能 / 成本：
- 兼容性 / 回滚：

## 候选方案

| 方案 | 做法 | 代价 | 风险 | 能否解决 |
|---|---|---|---|---|
| A | | | | |
| B | | | | |
| C | | | | |

### 推荐

<!-- 选哪个、为什么、分几步走、不选其他方案的理由。 -->

## 验收标准

- [ ] 用最小复现命令验证问题已消失
- [ ] 新增/补充回归测试
- [ ] 不影响无关模块的现有行为
- [ ] 涉及检索/打分的改动附 benchmark 前后对比

## 决策记录

- YYYY-MM-DD：开 issue，记录现状。
- YYYY-MM-DD：

## 参考

-
