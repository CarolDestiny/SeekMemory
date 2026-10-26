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

- [ ] 我阅读了 [repository development skill](../skills/seekmemory-dev/SKILL.md) 和相关技术契约。
- [ ] 生产 Artifact 写入使用 `ArtifactStore.commit()`；`ArtifactRepository.upsert()` 仅用于 seed/benchmark。
- [ ] SQL 只放在 `store/`，并由 repository 持有。
- [ ] 日志中没有秘密或消息正文。
- [ ] 测试覆盖调用者可观察到的行为，外部依赖在系统边界 fake。
- [ ] 本地验证按风险选择；命令、结果和跳过项原因已记录。
- [ ] UI/可见文案改动按 skill 的 UI quality guidance 完成人工检查；如果扫描器已加入，也已判断所有命中。
- [ ] 持久化数据和公开配置的兼容策略由 Lead 明确决定，或确认本次不受影响。
- [ ] 新增 changelog 条目同时包含简体中文和英文。
- [ ] CI 全量检查通过；生产变更/发布仅由 Lead 授权。
