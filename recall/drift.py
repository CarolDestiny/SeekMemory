"""主动浮现：不需要线索，也会想起一件事。

人安静下来会突然想起点什么——最近发生、情绪强、久没提的事更容易冒上来。
这不是检索，所以不按 query 打分，只按"这件事有多容易被想起"加权抽一条。

隔离与安全：
- 只看 memory family 的 scene / detail / fact，不看 secret / designated / media；
- shadow 不参与（影子靠遮蔽句，不主动提）；
- 刚说过的（recent / hot）不浮现，避免复读。
"""

from __future__ import annotations

import math
import random

try:  # 作为 astrbot 插件包的一部分导入
    from ..app.ports import ArtifactCache
    from ..core.artifact import Artifact
except ImportError:  # 作为顶层包导入（脚本 / 测试）
    from app.ports import ArtifactCache
    from core.artifact import Artifact

LEVELS = ("fact", "scene", "detail")
FAMILY = "memory"
BASE_DAYS = 30.0
EMOTION_BONUS = 1.5
MIN_CHANCE = 0.06
MAX_CHANCE = 0.22


def _age_days(created: str, now_days: float) -> float:
    """按 ISO 日期算存在多少天；算不出按 0 天。"""
    try:
        import datetime

        day = datetime.date.fromisoformat(str(created)[:10]).toordinal()
        return max(0.0, float(now_days) - day)
    except (TypeError, ValueError):
        return 0.0


def _today_ordinal() -> float:
    import datetime

    return float(datetime.date.today().toordinal())


def _in_cooldown(art: Artifact) -> bool:
    """刚讲过、或还在冷却期的，别主动再提。口径与打分里的 recent 惩罚一致。"""
    payload = art.payload if isinstance(art.payload, dict) else {}
    last = payload.get("last_used") or payload.get("hot_until") or payload.get("used_at")
    try:
        hits = int(art.header.strength.hits or 0)
    except (TypeError, ValueError):
        hits = 0
    return bool(hits > 0 and last)


def eligible(art: Artifact) -> bool:
    """一条记忆能不能被主动想起：有正文、非影子、非敏感、没在冷却。"""
    try:
        if art.header.family != FAMILY:
            return False
        if str(art.header.scope) == "shadow":
            return False
        if str(art.payload.get("level") or "") not in LEVELS:
            return False
        if not str(art.payload.get("text") or "").strip():
            return False
        if _in_cooldown(art):
            return False
        return float(art.header.strength.weight) >= 0.6
    except Exception:  # noqa: BLE001 - 单条坏数据当作不能浮现
        return False


def candidate(cache: ArtifactCache, now_days: float | None = None) -> list[Artifact]:
    """挑出可以主动浮现的记忆：有正文、非影子、非敏感、没在冷却。"""
    now = _today_ordinal() if now_days is None else float(now_days)
    out: list[Artifact] = []
    try:
        active = list(cache.active())
    except Exception:  # noqa: BLE001 - 取不到就不浮现
        return out
    for art in active:
        if eligible(art):
            out.append(art)
    return out


def _score(art: Artifact, now: float, rng: random.Random) -> float:
    """越近、情绪越强、越重要，越容易被想起来；乘一个随机扰动。"""
    strength = art.header.strength
    age = _age_days(str(art.header.time.created or ""), now)
    recency = math.exp(-age / BASE_DAYS)
    emotion = 1.0 + EMOTION_BONUS * float(strength.arousal or 0.0)
    weight = max(0.1, float(strength.weight or 1.0))
    return recency * emotion * weight * (0.5 + rng.random())


def best_of(pool: list[Artifact], seed: int | str | None = None,
            now_days: float | None = None) -> Artifact | None:
    """从给定候选里按"多容易被想起"抽一条；没有合格候选返回 None。"""
    usable = [art for art in pool if eligible(art)]
    if not usable:
        return None
    now = _today_ordinal() if now_days is None else float(now_days)
    rng = random.Random(seed)
    return max(usable, key=lambda art: _score(art, now, rng))


def pick(cache: ArtifactCache, seed: int | str | None = None,
         now_days: float | None = None) -> Artifact | None:
    """按权重抽一条最容易浮现的记忆；没有候选返回 None。"""
    return best_of(candidate(cache, now_days), seed, now_days)


def should_drift(text: str, seed: int | str | None = None) -> bool:
    """闲聊时按概率主动想起一次；越短越可能（长句通常有正事）。"""
    line = str(text or "").strip()
    rng = random.Random(seed)
    if len(line) > 24:
        return False
    chance = MAX_CHANCE if len(line) <= 8 else MIN_CHANCE
    return rng.random() < chance
