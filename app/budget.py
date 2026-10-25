"""上下文预算：单轮请求该带多少字。

模型的账几乎全在输入：语料 few-shot、群聊上下文、记忆注入、对话历史。
这里把这几项收成一处策略，算出一个"这一轮大概多少 token"的估计，
给注入、日志和报表共用；不改变任何业务语义。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable

# 中文按 1.6 字/token 估；每条消息另有 role 开销。
CHARS_PER_TOKEN = 1.6
MESSAGE_OVERHEAD = 4


@dataclass(frozen=True)
class ContextBudget:
    """一套请求侧的预算数字，单位都是字/条。"""

    injection_chars: int = 600      # 记忆注入上限
    system_chars: int = 1600        # 人格提示词 + 系统说明
    group_context_messages: int = 20  # 群聊流水最多注入多少条
    history_messages: int = 24      # 会话历史保留条数
    source_recall_enabled: bool = True
    source_recall_hours: int = 12
    source_recall_max_candidates: int = 80

    @property
    def estimate_tokens(self) -> int:
        """不含对话历史时的保守估计。"""
        return estimate_tokens(self.system_chars + self.injection_chars)

    def as_dict(self) -> dict:
        data = asdict(self)
        data["estimate_tokens"] = self.estimate_tokens
        return data


def estimate_tokens(chars: int, messages: int = 0) -> int:
    """按字数估 token；文本越长越接近 1.6 字/token。"""
    body = int(max(0, int(chars)) / CHARS_PER_TOKEN)
    return body + MESSAGE_OVERHEAD * max(0, int(messages))


def estimate_messages(texts: list[str]) -> int:
    """按消息列表估 token，用于语料与群聊流水。"""
    return estimate_tokens(sum(len(str(t)) for t in texts), len(texts))


def budget_from_config(conf: Callable[[str, object], object]) -> ContextBudget:
    """从插件配置读取预算；缺省值就是默认策略。"""
    default = ContextBudget()

    def _num(key: str, fallback: int, minimum: int = 1) -> int:
        raw = conf(key, fallback)
        if raw is None or raw == "":
            raw = fallback
        try:
            value = int(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return fallback
        return max(minimum, value)

    def _bool(key: str, fallback: bool) -> bool:
        value = conf(key, fallback)
        if isinstance(value, str):
            return value.strip().lower() not in ("", "0", "false", "no", "off")
        return bool(value)

    return ContextBudget(
        injection_chars=_num("budget_chars", default.injection_chars),
        system_chars=_num("context_system_chars", default.system_chars),
        group_context_messages=_num(
            "group_context_messages", default.group_context_messages
        ),
        history_messages=_num("history_messages", default.history_messages),
        source_recall_enabled=_bool(
            "source_recall_enabled", default.source_recall_enabled
        ),
        source_recall_hours=_num(
            "source_recall_hours", default.source_recall_hours
        ),
        source_recall_max_candidates=_num(
            "source_recall_max_candidates", default.source_recall_max_candidates
        ),
    )


def clamp_chars(text: str, limit: int) -> tuple[str, int]:
    """把文本裁到预算内；优先在标点处断开，返回 (文本, 原长度)。"""
    body = str(text or "")
    size = len(body)
    limit = max(0, int(limit))
    if size <= limit:
        return body, size
    cut = body[:limit]
    for mark in ("。", "；", "，", "\n"):
        index = cut.rfind(mark)
        if index >= limit // 2:
            cut = cut[: index + 1]
            break
    return cut, size
