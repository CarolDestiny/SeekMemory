## Summary / 概括

## Related issue / 相关问题

Closes #

## Changes / 变更

-

## What was intentionally not changed / 明确未改动的内容

## Verification / 验证

- [ ] 语法检查
- [ ] 单元测试
- [ ] 基准/消融
- [ ] 真实的 AstrBot 阶段验证
- [ ] 线上探测（仅限 Lead 批准）

命令和结果：

## Data and privacy impact / 数据和隐私影响

- Source 证据：
- Artifact 字段/版本更改：
- 数据库迁移：
- Cross-session 披露：
- 日志输出影响：

## Risk and rollback / 风险与回滚

## Agent checklist / Agent 检查清单

- [ ] 我阅读了 AGENTS.md 和 docs/ARCHITECTURE.md。
- [ ] 生产写入使用 DB.commit()。
- [ ] store/db.py 之外没有 SQL。
- [ ] 日志中没有秘密或消息正文。
- [ ] 新行为有回归测试。
- [ ] Lead 已审查部署步骤。
