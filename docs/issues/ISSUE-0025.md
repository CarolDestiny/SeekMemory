# ISSUE-0025 v0.3.2 tracking

| item | value |
|---|---|
| id | ISSUE-0025 |
| level | P0/P1 |
| status | open |
| date | 2026-10-22 |
| GitHub | [#6](https://github.com/NeverENG/SeekMemory/issues/6) |
| proposal | [#5](https://github.com/NeverENG/SeekMemory/issues/5) |
| branch | feat/issue-0025-v032 |

## 目标
在 v0.3.2 版本中完善在线系统的可信度，为未来功能扩展打下基础。

## v0.3.2 要做
- [ ] 本地 WebUI 使用指南
- [ ] 一键隧道脚本
- [ ] 复现并修复私聊漏召回问题并补充回归测试
- [ ] 通过 `bm25_enabled` 开关提供 BM25 混合检索及影子模式
- [ ] 在 WebUI 添加只读人设时间轴
- [ ] 发布说明与回滚清单

## v0.3.2 不做
- QQ 历史导入
- 完整权限控制 (RBAC)
- 容量治理
- 网络工具
- 好感度与刷屏抑制
- 上下文编排研究

## 验收标准
- 私聊漏召回问题有复现用例与回归测试
- 可以通过开关禁用 BM25 检索
- 不存在跨会话原始数据泄露
- WebUI 时间轴为只读
- 单元测试与集成测试通过
- staging 与线上已验证并记录结果

## 发布与回滚
- 先在 staging 环境部署并记录 probe
- 监控性能与错误日志，验证无异常
- 从 staging 验证后合并并发布，保留回滚路径

## 依赖
- [#3](https://github.com/NeverENG/SeekMemory/pull/3) WebUI
- [#4](https://github.com/NeverENG/SeekMemory/issues/4) BM25
- [#5](https://github.com/NeverENG/SeekMemory/issues/5) 方案评审
