"""recall.assemble：把记忆组装成一段叙述化的注入文本。"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

try:  # 作为 astrbot 插件包的一部分导入
    from ..core.artifact import Artifact, content_of
    from .designated import deliverable, triggers_of
except ImportError:  # 作为顶层 recall 包导入（脚本 / 测试）
    from core.artifact import Artifact, content_of
    from recall.designated import deliverable, triggers_of

MEDIA = {
    "video": ("个", "视频"),
    "music": ("首", "歌"),
    "audio": ("段", "音频"),
    "image": ("张", "照片"),
    "photo": ("张", "照片"),
    "article": ("篇", "文章"),
    "link": ("篇", "文章"),
}
CORE_LAYERS = ("persona", "impression")
SHADOW_SENTENCE = "有件事你答应过别人不说"


def _clean(value: Any, limit: int = 180) -> str:
    """压平空白、补「但」前逗号、去句末符号，最后加上句号。"""
    text = " ".join(str(value or "").split())
    text = re.sub(r"(?<=[^，。！？；：、\s不非])但", "，但", text)
    text = text.strip("。！？!?；;，,、 ")
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text + "。" if text else ""


def _clip(value: Any, limit: int = 60) -> str:
    """截断引语或标题，不带句号。"""
    text = _clean(value, limit)
    return text[:-1] if text.endswith("。") else text


def _raw(art: Artifact) -> str:
    """取通用可读文本，最后回退 content_of。"""
    for key in ("text", "shadow_text", "summary", "title"):
        value = art.payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    try:
        return content_of(art)
    except Exception:
        return ""


def _voice(text: str, about: str) -> str:
    """把记忆里的第一人称改写成注入时的第二人称。"""
    if about == "relation":
        text = text.replace("我们", "你们")
    return text.replace("我的", "你的").replace("我", "你")


def _when(created: str) -> str:
    """绝对日期转相对时间前缀（DESIGN 6.3）。"""
    try:
        day = date.fromisoformat(str(created)[:10])
    except (TypeError, ValueError):
        return ""
    delta = (date.today() - day).days
    for limit, word in ((0, "今天"), (1, "昨天"), (10, "前几天"), (30, "前阵子")):
        if delta <= limit:
            return word
    return f"{delta // 30}个月前" if delta < 365 else "去年"


def _media_sentence(art: Artifact) -> str:
    """media 层：谁给谁看过什么，带类型与主题。"""
    payload = art.payload
    kind = str(payload.get("type") or "video").lower()
    measure, noun = MEDIA.get(kind, ("个", "视频"))
    topic = _clip(payload.get("title") or payload.get("summary"), 60)
    for tail in ("是怎么来的", "的由来", "是怎么火起来的", "是什么", "的介绍"):
        if topic.endswith(tail) and len(topic) > len(tail):
            topic = topic[: -len(tail)]
            break
    verb = "叫" if kind == "music" else "讲" if kind in ("video", "article", "link") else "关于"
    thing = f"一{measure}{verb}{topic}的{noun}" if topic else f"一{measure}{noun}"
    who = str(payload.get("shared_by") or art.header.said_by or "other")
    if who in ("self", "bot", "you"):
        return f"你还记得给他看过{thing}。"
    return f"他给你看过{thing}。"


def _example_sentence(art: Artifact) -> str:
    """example 层：他说的原话与你当时的回应。"""
    user, reply = _clip(art.payload.get("user")), _clip(art.payload.get("assistant"))
    if user and reply:
        return f"你记得有一次他说「{user}」，你回「{reply}」。"
    if user:
        return f"你记得有一次他说「{user}」。"
    return f"你记得有一次你回「{reply}」。" if reply else ""


def _guarded_sentence(art: Artifact) -> str:
    """secret / designated 层：只给影子句或托付提示，不泄露内容。"""
    if art.header.family == "designated":
        trigger = _clip("、".join(triggers_of(art)) or "那个东西", 40)
        return f"他让你记着一件事，等提到「{trigger}」时再告诉他。"
    shadow = _clean(art.payload.get("shadow_text") or SHADOW_SENTENCE)
    return f"你记得，{shadow}" if shadow else ""


def _shadow_sentence(art: Artifact) -> str:
    """scope=shadow：任何会话都只注入影子句，正文绝不进入输出。"""
    shadow = _clean(art.payload.get("shadow_text") or SHADOW_SENTENCE)
    return f"你记得，{shadow}" if shadow else ""


def _designated_sentence(art: Artifact) -> str:
    """designated 已满足三条硬条件：交出完整正文，而不是提示句。"""
    body = _clean(art.payload.get("text"), 600)
    if not body:
        return ""
    return f"你记得他让你记的事，现在他问起来了，你可以告诉他：{body}"


def _memory_sentence(art: Artifact) -> str:
    """memory 层：场景带相对时间，细节回指，印象换一种开头。"""
    text = _clean(_voice(_raw(art), str(art.payload.get("about") or "")))
    if not text:
        return ""
    level = str(art.payload.get("level") or "")
    if level == "impression":
        return f"你印象里{text}"
    if level == "detail":
        return f"你还记得{text}"
    when = _when(art.header.time.created) if level == "scene" else ""
    return f"{when}{text}" if when else f"你记得{text}"


def _persona_sentence(art: Artifact) -> str:
    """persona 层：人格沉淀本身已是第二人称自述，不再补「你记得」。"""
    return _clean(_voice(_raw(art), "self"))


def _sentence(art: Artifact, text: str | None = None,
              is_private: bool | None = None) -> tuple[str, str]:
    """按 scope / family / level 选措辞，返回 (裁剪层, 句子)。

    text / is_private 为 None 表示调用方没有会话上下文（脚本或旧调用），
    designated 只输出托付提示；传入上下文后按三条硬条件决定是否交付正文。
    """
    if str(art.header.scope or "") == "shadow":
        return "shadow", _shadow_sentence(art)
    family = art.header.family
    if family == "media":
        return "media", _media_sentence(art)
    if family == "designated":
        if text is None or is_private is None:
            return family, _guarded_sentence(art)
        if not deliverable(art, text, is_private):
            return family, ""
        return family, _designated_sentence(art)
    if family == "secret":
        return family, _guarded_sentence(art)
    if family == "example":
        return "example", _example_sentence(art)
    if family == "persona":
        return "persona", _persona_sentence(art)
    level = str(art.payload.get("level") or "scene")
    layer = level if level in ("fact", "impression", "scene", "detail") else "scene"
    return layer, _memory_sentence(art)


def _render(items: list[tuple[str, str]]) -> str:
    """把句子按顺序拼成一段。"""
    return "".join(sentence for _, sentence in items)


def _drop(items: list[tuple[str, str]], layers: tuple[str, ...]) -> bool:
    """从后往前删一条属于 layers 的句子，删到返回 True。"""
    index = next((i for i in range(len(items) - 1, -1, -1) if items[i][0] in layers), None)
    if index is None:
        return False
    del items[index]
    return True


def _dedupe_key(art: Artifact) -> str:
    """去重键：shadow 用影子句，避免正文参与比较，也避免被同文正文吃掉。"""
    if str(art.header.scope or "") == "shadow":
        shadow = str(art.payload.get("shadow_text") or "").strip()
        return "shadow:" + (shadow or art.header.id)
    return content_of(art)


def _dedupe(arts: list[Artifact]) -> list[Artifact]:
    """内容去重：同一段话只保留一条；取不到文本的坏条目直接跳过（fail-open）。"""
    kept: list[Artifact] = []
    seen: list[str] = []
    for a in arts:
        try:
            t = _dedupe_key(a).strip()
        except Exception:  # noqa: BLE001 - 单条坏记忆不能拖垮整段注入
            continue
        if not t:
            continue
        if any(t == o or t in o or o in t for o in seen):
            continue
        kept.append(a)
        seen.append(t)
    return kept


def build(arts: list[Artifact], budget: int = 2000,
          *, text: str | None = None, is_private: bool | None = None) -> str:
    """
    组装叙述式注入文本（DESIGN 5.3 / 6.1）。

    头部：persona、impression、传入顺序最相关 3 条；中部：其余场景 /
    细节 / 例子；尾部留给调用方。超 budget 时从后往前砍，先 example
    再 detail，最后砍其余中部。

    text / is_private 是当前会话上下文：传了才允许 designated 交付正文，
    不传时维持旧的“只给托付提示”；scope=shadow 始终只输出影子句。
    """
    arts = _dedupe(arts)
    if not arts or budget <= 0:
        return ""
    entries: list[tuple[str, str]] = []
    for art in arts:
        layer, sentence = _sentence(art, text, is_private)
        if sentence:
            entries.append((layer, sentence))
    if not entries:
        return ""
    header = [i for i, (layer, _) in enumerate(entries) if layer == "persona"]
    header += [i for i, (layer, _) in enumerate(entries) if layer == "impression"][:1]
    header += [
        i
        for i, (layer, _) in enumerate(entries)
        if i not in header and layer != "impression"
    ][:3]
    middle = [i for i in range(len(entries)) if i not in header]
    items = [entries[i] for i in header + middle]
    for layer in ("example", "detail"):
        while len(_render(items)) > budget and _drop(items, (layer,)):
            pass
    rest = ("media", "secret", "designated", "shadow", "fact", "scene", "memory")
    while len(_render(items)) > budget and _drop(items, rest):
        pass
    text = _render(items)
    if text and not text.startswith("你"):
        text = "你记得，" + text
    if len(text) > budget:
        cut = text[: max(0, budget - 2)]
        # 尽量切在句末，避免半句话
        pos = max(cut.rfind("。"), cut.rfind("；"), cut.rfind("，"))
        if pos > budget * 0.6:
            cut = cut[: pos + 1]
        text = cut.rstrip("，。；、 ") + "……"
    return text if len(text) <= budget else "…" * budget
