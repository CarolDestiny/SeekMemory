# PR-XXXX 标题

| 项 | 值 |
|---|---|
| 关联 issue | ISSUE-XXXX |
| 分支 | `fix/issue-XXXX-short-name` → `main` |
| 提交 | `<hash>` |
| 评审人 | |
| 状态 | draft / review / merged / closed |
| GitHub | 待同步 |

## 改动摘要

<!-- 一段话说清"为什么改、改了什么、明确没改什么"。 -->

-
-

## 验证方式

### 自动化

```bash
for f in tests/test_*.py; do python3 "$f"; done
python3 benchmarks/run.py
```

结果：

```text
```

### 手工 / 基准对比

| 指标 | main | 本分支 | 说明 |
|---|---:|---:|---|
| | | | |

<!-- 检索/打分相关必须给出数字来源：benchmarks/results/*.md，或本次运行的完整命令。 -->

## 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| | | |

回滚：`git revert -m 1 <merge-commit>`。

## 检查清单

- [ ] 关联 issue 已写，级别正确
- [ ] 只改本 issue 范围内的文件
- [ ] 新功能有测试；bug 有能复现的测试
- [ ] 全部测试通过
- [ ] 影响检索/打分的改动附 benchmark 对比
- [ ] 文档（INDEX / DESIGN / CONTRACT）已同步
- [ ] 无调试代码、密钥、临时文件
- [ ] commit 符合 `type(scope): 摘要`

## 评审记录

| 日期 | 评审人 | 结论 | 意见 |
|---|---|---|---|
| | | 通过 / 需修改 | |

## 合并

- merge commit：
- 合并后 issue 状态：closed
