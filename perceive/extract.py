"""从当天对话中抽取“印象”：生成提示词、解析模型 JSON、按字面去重。"""

from __future__ import annotations

import json
import re
from typing import Any

_PROMPT = """你是她的记忆整理者。请从这段对话里提炼 0~6 条记忆，事实和印象都要。

分级原则（四层都要，别只写印象）：
- fact：稳定的个人事实——名字、称呼、工作、城市、住哪、家人、宠物、长期偏好。有一条写一条。
- scene：某一次具体经历——那天发生了什么、结果如何。
- detail：支撑场景的细节——时间、地点、数字、原话。
- impression：他这个人怎么样——性格、习惯、情绪模式。可以合并几条碎话成一条印象。

每条必须给 tags：3~6 个中文关键词，用空格分隔，是日后检索用的线索词
（例：「杭州 出差 下周 行程」「猫 名字 Bug 宠物」）。tags 要写他会怎么问，而不是照抄正文。

归属原则：
- 对话行里的 user(数字) 是说话人的 QQ 号。群里别人说的事，正文要写清是谁说的
  （用 QQ 号或对话里出现的称呼），不要用"他"——"他"只指主人。
- 群里发生的事按人记："12345 说他养了只猫"，而不是"他养了只猫"。

原则：
- 事实不能漏：他把名字、地点、时间、计划说出来，就单独记一条 fact。
- 印象能合并就合并，不要碎成一堆。
- 只写对话里能推出来的，不要编造，也不要照抄成长句。
- 没有值得留下的，就输出 []。

每条输出一个对象，字段固定：
- level: "fact" | "scene" | "detail" | "impression"
- text: 一句完整、自然的中文，不要用“用户说”开头
- tags: 3~6 个中文关键词，空格分隔
- about: "self" | "other" | "relation" | "world"
- arousal: 0.0~1.0，当时的情绪强度
- valence: -1.0~1.0，从负面到正面
- funny: 0.0~1.0，有趣程度
- first: true/false，这是不是第一次出现

Additional required fields for every item:
- subject_kind: owner | speaker | third_party | relation | world | self
- subject_id: stable person id if known; owner maps to the owner QQ id; world maps to world
- subject_name: optional human-readable name
- event_at: ISO datetime when the remembered event happened
- valid_from / valid_to: ISO date or null for plans and time-bound facts

Dialogue lines may start with [ISO timestamp]. Resolve relative dates against that timestamp,
never against extraction time. If the exact event time is unclear, use the earliest dialogue time.

正例：
[{"level": "fact", "text": "他下周三要去杭州出差", "tags": "杭州 出差 下周 行程", "about": "world", "arousal": 0.3, "valence": 0.0, "funny": 0.0, "first": true},
 {"level": "impression", "text": "他有点倔，嘴上不饶人，但真有事会帮", "tags": "性格 倔 嘴硬心软", "about": "other", "arousal": 0.4, "valence": 0.3, "funny": 0.2, "first": false}]

Example with the additional fields:
[{"level": "fact", "text": "owner is preparing a job interview", "tags": "job interview plan", "about": "other", "arousal": 0.3, "valence": 0.0, "funny": 0.0, "first": true, "subject_kind": "owner", "subject_id": "12345", "subject_name": "", "event_at": "2026-10-20T23:14:00", "valid_from": "2026-10-21", "valid_to": null}]

只输出 JSON 数组，不要解释，不要 Markdown 代码块。"""


def build_prompt(messages: list[str]) -> str:
    """生成抽取印象的提示词；messages 为空时只返回规则部分。"""
    lines = [str(message).strip() for message in messages if str(message).strip()]
    if not lines:
        return _PROMPT
    return _PROMPT + "\n\n【今天的对话】\n" + "\n".join(lines) + "\n\n现在输出 JSON 数组："


def _fenced_blocks(text: str) -> list[str]:
    """取出 Markdown 代码块内容，避免模型把 JSON 包在 ``` 里。"""
    pattern = r"```(?:json)?\s*(.*?)```"
    return [m.group(1).strip() for m in re.finditer(pattern, text, re.S | re.I)]


def _balanced_arrays(text: str) -> list[str]:
    """扫描文本，取出所有括号配平的 [...] 片段（忽略字符串里的括号）。"""
    found: list[str] = []
    start = -1
    depth = 0
    quote = ""
    escaped = False
    for index, char in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char == '"':
            quote = char
        elif char == "[":
            if depth == 0:
                start = index
            depth += 1
        elif char == "]" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                found.append(text[start : index + 1])
                start = -1
    return found


def _loads(block: str) -> Any:
    """先严格解析，失败后去掉尾逗号再试一次；都失败返回 None。"""
    block = block.strip()
    if not block:
        return None
    try:
        return json.loads(block, strict=False)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    cleaned = re.sub(r",\s*([\]}])", r"\1", block)
    if cleaned == block:
        return None
    try:
        return json.loads(cleaned, strict=False)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def parse_response(text: str) -> list[dict]:
    """尽力从模型输出中解析 JSON 数组；任何失败都返回空列表。"""
    if not isinstance(text, str) or not text.strip():
        return []
    blocks = [text.strip(), *_fenced_blocks(text), *_balanced_arrays(text)]
    tried: set[str] = set()
    for block in blocks:
        if not block or block in tried:
            continue
        tried.add(block)
        data = _loads(block)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    return []


def _normalize(text: str) -> str:
    """去掉空白和标点并转小写，得到用于字面比较的键。"""
    return re.sub(r"[\s\W_]+", "", text).lower()


def _is_duplicate(key: str, other: str) -> bool:
    """规范化后相同，或较短文本完整包含在较长文本里（至少 4 字）。"""
    if not key or not other:
        return False
    if key == other:
        return True
    short, long = sorted((key, other), key=len)
    return len(short) >= 4 and short in long


def filter_duplicates(items: list[dict], existing_texts: list[str]) -> list[dict]:
    """按字面去重（批次内 + 与已有记忆），保留首次出现的条目。"""
    seen: list[str] = []
    for raw in existing_texts:
        if isinstance(raw, str):
            key = _normalize(raw)
            if key:
                seen.append(key)
    kept: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        key = _normalize(text)
        if not key or any(_is_duplicate(key, old) for old in seen):
            continue
        seen.append(key)
        kept.append(item)
    return kept
