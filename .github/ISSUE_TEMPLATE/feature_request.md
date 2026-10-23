---
name: Feature request
about: 提出新的检索、内存或运行时功能
title: "[Feature] "
labels: enhancement
assignees: ""
---

## Why this issue / Why now

Explain the user-visible or architectural reason. Link the current context: what is thin,
what is coupled, what becomes possible after this change, and why it should not remain
implicit in `main.py`.

## Current constraints / Evidence

- Current entry points and files:
- What is mixed together today:
- What cannot be tested or changed safely today:

## Adapter boundary

Describe the host boundary explicitly. AstrBot remains the host; the new layer must depend
on ports rather than AstrBot event classes. State what is adapter-only and what is
runtime/domain logic.

## Problem / 问题

这解决了什么用户可见或架构问题？

## Proposal / 提议

描述最小的一致实现。

## Priority / 优先级

P0 / P1 / P2

## Scope / 要做什么

- [ ] 本次要做：
- [ ] 不做就不会影响验收：

## Non-goals / 不做什么

- [ ] 本次明确不做：
- [ ] 不接受的隐含扩展：

## Later / 以后再做

- [ ] 下一个版本或更后的事：

## Acceptance criteria / 验收标准

- [ ] 可验证的行为变化：
- [ ] 回归测试：

## Architecture impact / 架构影响

- 这是否会添加或更改 Artifact 字段？
- 这是否会改变 Source 事实、版本、证据或账本语义？
- 此更改是否影响召回评分、隐私或披露？
- 这是否会添加外部依赖项或调用边界？
- 这需要数据库迁移吗？
- 所需的新测试：
- 所需的基准测试或实时探针：

## Alternatives considered / 考虑的替代方案

## Rollout and rollback / 推出和回滚

## Additional context / 补充信息
