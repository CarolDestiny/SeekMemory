"""印象轨迹：同一件事她以前怎么想、现在怎么想。

版本链存在 versions 表里（每次落库都留一份）。这里只负责把链读成一句话：
"以前觉得…，现在觉得…"。没有变化就返回空串——没变的事不值得提。
"""

from __future__ import annotations

try:  # 作为 astrbot 插件包的一部分导入
    from ..core.artifact import Artifact
    from ..store.cache import Cache
except ImportError:  # 作为顶层包导入（脚本 / 测试）
    from core.artifact import Artifact
    from store.cache import Cache

MAX_SIDE = 20   # 单边最长字数，超了就截断
MAX_SUM = 46    # 两边加起来超过这个长度就不显示，免得喧宾夺主


def _texts(cache: Cache, art: Artifact) -> list[str]:
    """取这条记忆的正文版本链（旧→新），去掉连续重复。"""
    db = getattr(cache, "db", None)
    if db is None:
        return []
    try:
        rows = db.history(art.header.id)
    except Exception:  # noqa: BLE001 - 读不到历史就当作没有
        return []
    out: list[str] = []
    for row in rows:
        payload = row.get("payload") or {}
        text = str(payload.get("text") or "").strip()
        if text and (not out or out[-1] != text):
            out.append(text)
    return out


def _trim(text: str) -> str:
    """去掉第三人称开头与句末标点，方便拼进一句话。"""
    body = text.strip().rstrip("。！？!?；;")
    for prefix in ("他", "她", "他们", "她们"):
        if body.startswith(prefix):
            body = body[len(prefix):]
            break
    return body[:MAX_SIDE]


def trajectory(cache: Cache, art: Artifact) -> str:
    """返回「以前…，现在…」；只有一版、或太长、或没变，返回空串。"""
    texts = _texts(cache, art)
    if len(texts) < 2:
        return ""
    old, new = _trim(texts[0]), _trim(texts[-1])
    if not old or not new or old == new:
        return ""
    if len(old) + len(new) > MAX_SUM:
        return ""
    return f"（以前觉得{old}，现在觉得{new}）"
