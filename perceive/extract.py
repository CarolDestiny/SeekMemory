"""从当天对话中抽取“印象”：生成提示词、解析模型 JSON、按字面去重。"""

from __future__ import annotations

import json
import re
from typing import Any

_PROMPT = """你是她的记忆整理者。请从今天的对话里提炼 0~3 条“印象”，而不是一份“事实清单”。

先问自己三个问题：
1. 这条记下来，是为了知道“他说过什么”，还是为了知道“他这个人怎么样”？
2. 几天后她想起他时，会不会自然地说出这句话？
3. 能不能把几句碎话合成一条印象？

原则：
- 印象 > 场景 > 细节。能上升一层就上升一层，能合并就合并。
- 宁可少而准，不要多而碎；没有值得留下的，就输出 []。
- 只写对话里能推出来的，不要编造，也不要把原话照抄成长句。
- 不要按“事实 / 偏好 / 事件”做类型分类，只记录对他的感觉和一起经历过的事。

每条输出一个对象，字段固定：
- level: "impression"（他这个人怎么样）| "scene"（某一次具体经历）| "detail"（支撑场景的细节）
- text: 一句完整、自然的中文，不要用“用户说”开头
- about: "self" | "other" | "relation" | "world"
- arousal: 0.0~1.0，当时的情绪强度
- valence: -1.0~1.0，从负面到正面
- funny: 0.0~1.0，有趣程度
- first: true/false，这是不是第一次出现

反例（太碎，像数据库）：
[{"level": "detail", "text": "他叫吕宇轩"}]
正例（是印象，像人记得的）：
[{"level": "impression", "text": "他有点倔，嘴上不饶人，但真有事会帮", "about": "other", "arousal": 0.4, "valence": 0.3, "funny": 0.2, "first": false}]

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
