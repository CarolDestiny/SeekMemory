#!/usr/bin/env bash
# 提交前扫一遍暂存区：出现 API key、长数字 ID 就拦下来。
set -euo pipefail
PATTERN="sk-[A-Za-z0-9]{20,}|[0-9]{9,10}"
HIT="$(git diff --cached -U0 | grep -E "^\+" | grep -vE "^\+\+\+" | grep -nE "$PATTERN" || true)"
if [ -n "$HIT" ]; then
  echo "⛔ 暂存区里疑似有密钥或私有 QQ 号："
  echo "$HIT"
  echo "确认无误后用 git commit --no-verify 跳过。"
  exit 1
fi
