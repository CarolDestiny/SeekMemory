"""印象轨迹：这条印象以前是什么说法。

版本链存在 versions 表里（每次落库都留一份）。当前印象已经会正常注入，
所以这里只补一句「以前觉得…」——不用再把现在重复一遍。"""


from __future__ import annotations

import json

try:  # 作为 astrbot 插件包的一部分导入
    from ..core.artifact import Artifact, make
    from ..core.disclosure import DisclosureLevel, RecallScene, decide
    from ..store.cache import Cache
except ImportError:  # 作为顶层包导入（脚本 / 测试）
    from core.artifact import Artifact, make
    from core.disclosure import DisclosureLevel, RecallScene, decide
    from store.cache import Cache

MAX_SIDE = 22   # 旧说法最长字数，超了就截断


def _history(cache: Cache, art: Artifact) -> list[dict]:
    """只读完整历史快照；缺少隐私元数据的旧记录不能据此输出正文。"""
    db = getattr(cache, "db", None)
    if db is None:
        return []
    try:
        return db.history(art.header.id)
    except Exception:  # noqa: BLE001 - 读不到历史就当作没有
        return []


def _snapshot(row: dict, entity_id: str) -> Artifact | None:
    """只按该版本自己的头和正文重建，不借用当前版本的归属或来源。"""
    header = row.get("header")
    required = {"revision", "scope", "shareable", "subject_id", "lineage"}
    if not isinstance(header, dict) or not required.issubset(header):
        return None
    if header.get("id", entity_id) != entity_id or header.get("family", "memory") != "memory":
        return None
    payload = row.get("payload")
    if not isinstance(payload, dict) or payload.get("level") != "impression":
        return None
    try:
        fields = {key: value for key, value in header.items() if key != "family"}
        fields["id"] = entity_id
        for key in ("lineage", "strength", "time"):
            if isinstance(fields.get(key), str):
                fields[key] = json.loads(fields[key])
        return make("memory", payload, **fields)
    except (TypeError, ValueError):
        return None


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


def trajectory(cache: Cache, art: Artifact, scene: RecallScene | None = None,
               relevance: float = 1.0) -> str:
    """返回允许全文披露的旧印象；未知会话或缺少版本头时保守省略。"""
    if scene is None:
        return ""
    current = str(art.payload.get("text") or "").strip()
    db = getattr(cache, "db", None)
    rows = _history(cache, art)
    snapshots = [_snapshot(row, art.header.id) for row in rows]
    source_ids = list(dict.fromkeys(
        source_id for snapshot in snapshots if snapshot is not None
        for source_id in snapshot.header.lineage.sources
    ))
    try:
        origin_by_source = db.source_umos(source_ids) if db is not None else {}
    except Exception:  # noqa: BLE001 - do not infer origins after a read failure
        return ""
    for row, snapshot in zip(rows, snapshots):
        if snapshot is None or snapshot.header.revision >= art.header.revision:
            continue
        text = str(snapshot.payload.get("text") or "").strip()
        if not text or text == current:
            continue
        try:
            origins = tuple(origin_by_source.get(source_id, "")
                            for source_id in snapshot.header.lineage.sources)
            if decide(snapshot, scene, relevance, origins).level != DisclosureLevel.FULL:
                continue
        except Exception:  # noqa: BLE001 - historical context is optional
            continue
        old = _trim(text)
        if old:
            return f"（{_when(str(row.get('at') or ''))}觉得{old}）"
    return ""
