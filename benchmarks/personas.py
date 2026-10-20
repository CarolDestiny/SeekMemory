"""六种用户人格画像：固定种子生成 180 天私聊 + 群聊，并给出 60 题黄金集。

静态数据（锚点、干扰、闲聊模板、黄金题）放在 personas_data.py；
本文件只负责按固定种子展开成 messages，并提供元数据与日期映射。
"""

from __future__ import annotations

import datetime as dt
import random

from personas_data import DAYS, ORDER, SHADOW, SPECS, TODAY


def build(key):
    """生成某个人格画像的 (messages, gold)。"""
    spec = SPECS[key]
    rng = random.Random(spec["seed"])
    by_day = {}
    for item in spec["anchors"] + spec["distractors"]:
        by_day.setdefault(item["day"], []).append(item)
    msgs = []
    for day in range(1, DAYS + 1):
        acts = by_day.get(day, [])
        own = [a["text"] for a in acts if a["uid"] == "u0" and a["scope"] == "private"]
        count = max(rng.randint(3, 6), len(own))
        texts = own + [rng.choice(spec["private_noise"]) for _ in range(count - len(own))]
        for text in texts:
            msgs.append((day, "u0", "private", text))
        for item in acts:
            if item["uid"] != "u0" and item["scope"] != "shared":
                msgs.append((day, item["uid"], "private", item["text"]))
        for i in range(rng.randint(20, 30)):
            uid = ("u0", "u1", "u2")[i % 3]
            msgs.append((day, uid, "group", rng.choice(spec["group_noise"][uid])))
        for item in acts:
            if item["scope"] == "shared":
                msgs.append((day, item["uid"], "group", item["text"]))
    msgs.sort(key=lambda m: (m[0], 0 if m[2] == "private" else 1))
    return msgs, [dict(q) for q in spec["gold"]]


def meta_of(key):
    """返回该画像所有锚点 / 干扰的 text -> 元数据映射，供评测写入标签与权重。"""
    spec = SPECS[key]
    return {item["text"]: item for item in spec["anchors"] + spec["distractors"]}


def date_of(day):
    """把第 day 天映射成相对 today 的 ISO 日期，day=180 即今天。"""
    return (TODAY - dt.timedelta(days=DAYS - day)).isoformat()
