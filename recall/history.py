"""印象轨迹：这条印象以前是什么说法。

版本链存在 versions 表里（每次落库都留一份）。当前印象已经会正常注入，
所以这里只补一句「以前觉得…」——不用再把现在重复一遍。"""


from __future__ import annotations

try:  # 作为 astrbot 插件包的一部分导入
    from ..core.artifact import Artifact
    from ..store.cache import Cache
except ImportError:  # 作为顶层包导入（脚本 / 测试）
    from core.artifact import Artifact
    from store.cache import Cache

MAX_SIDE = 22   # 旧说法最长字数，超了就截断


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


def _when(iso: str) -> str:
    """把版本时间说成人话：几周前 / 三个月前 / 以前。"""
    try:
        import datetime

        day = datetime.date.fromisoformat(str(iso)[:10])
        days = max(0, (datetime.date.today() - day).days)
    except (TypeError, ValueError):
        return "以前"
    if days >= 60:
        return f"{days // 30} 个月前"
    if days >= 14:
        return f"{days // 7} 周前"
    if days >= 2:
        return f"{days} 天前"
    return "以前"


def _first_at(cache: Cache, art: Artifact) -> str:
    """最早一版的时间，用来把「以前」说具体。"""
    db = getattr(cache, "db", None)
    if db is None:
        return ""
    try:
        rows = db.history(art.header.id)
    except Exception:  # noqa: BLE001
        return ""
    return str(rows[0].get("at") or "") if rows else ""


def trajectory(cache: Cache, art: Artifact) -> str:
    """返回「（三周前觉得…）」；只有一版、没变、太长，都返回空串。"""
    texts = _texts(cache, art)
    if len(texts) < 2:
        return ""
    old = _trim(texts[0])
    if not old:
        return ""
    return f"（{_when(_first_at(cache, art))}觉得{old}）"
