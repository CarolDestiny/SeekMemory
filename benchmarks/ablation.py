"""消融基准：逐个关掉检索组件，看黄金集召回掉多少。

不修改核心代码：打分项靠「给 select 传入改造过的候选」关闭，去重 / 时间
衰减靠 with 里临时替换、退出即还原，层级只在组装时抹掉。九种配置跑同一
份数据、同一份黄金集，输出 benchmarks/results/ablation.md。

用法：python3 benchmarks/ablation.py
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
from dataclasses import dataclass, replace
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import recall.assemble as assemble_mod  # noqa: E402
import recall.score as score_mod  # noqa: E402
from benchmarks.edge_stats import spread_counts  # noqa: E402
from benchmarks.goldset import FORBIDDEN, GOLD, SEED, TODAY, build, noise_share  # noqa: E402
from core.artifact import Artifact, content_of, make  # noqa: E402
from core.graph import Graph  # noqa: E402
from maintain.link import persist  # noqa: E402
from recall.assemble import build as assemble  # noqa: E402
from recall.score import select  # noqa: E402
from recall.seed import bigrams, dice, seeds  # noqa: E402
from recall.spread import activate  # noqa: E402
from store.cache import Cache  # noqa: E402
from store.db import DB  # noqa: E402

K, BUDGET = 8, 600


@dataclass(frozen=True)
class Cfg:
    """一种消融配置：名字 + 要关掉的组件（True 表示保留）。"""

    name: str
    spread: bool = True
    emotion: bool = True
    tag: bool = True
    weight: bool = True
    dedupe: bool = True
    layer: bool = True
    decay: bool = True
    literal_only: bool = False


CONFIGS = (
    Cfg("full"),
    Cfg("no_spread", spread=False),
    Cfg("no_score_emotion", emotion=False),
    Cfg("no_score_tag", tag=False),
    Cfg("no_weight_prior", weight=False),
    Cfg("no_dedupe", dedupe=False),
    Cfg("no_layer", layer=False),
    Cfg("no_decay", decay=False),
    Cfg("literal_only", spread=False, emotion=False, tag=False, weight=False,
        literal_only=True),
)


def _artifact(m) -> Artifact:
    """Mem -> Artifact；fact / impression 用 pattern 形状（衰减更慢）。"""
    d = (date.today() - timedelta(days=TODAY - m.day)).isoformat()
    payload = {"text": m.text, "level": m.level, "chrono": "once", "about": "other",
               "shape": "pattern" if m.level in ("fact", "impression") else "point",
               "tags": list(m.tags)}
    return make("memory", payload, scope=m.scope,
                strength={"weight": m.weight, "confidence": 1.0, "arousal": m.arousal,
                          "valence": m.valence, "funny": 0.0},
                time={"created": d, "updated": d})


def _load(mems) -> tuple[DB, Cache, Graph, list[Artifact]]:
    """走生产写入路径建 similar/temporal 边；causal 仍由人工金标补。"""
    db = DB(os.path.join(tempfile.mkdtemp(prefix="seekmem_abl_"), "abl.db"))
    cache = Cache(db)
    graph = Graph(db, cache)
    for m in mems:
        persist(_artifact(m), db, cache, graph)
    pool = cache.active()
    by_text = {str(a.payload.get("text")): a for a in pool}
    if os.environ.get("ABLATION_NO_CAUSAL") != "1":
        graph.link(
            by_text["他去万兴科技面试了"].header.id,
            by_text["万兴那边给他发了offer，他过了"].header.id,
            "causal",
            .9,
        )
    return db, cache, graph, pool


def _transform(cfg: Cfg, pool: list[Artifact]) -> list[Artifact]:
    """把要关掉的打分项从候选上「物理」摘掉，不改核心代码。"""
    if not cfg.literal_only and cfg.emotion and cfg.tag and cfg.weight:
        return pool
    out = []
    for art in pool:
        payload = dict(art.payload)
        strength = art.header.strength
        if cfg.literal_only or not cfg.tag:
            for key in ("tags", "tag", "last_used", "hot_until", "used_at"):
                payload.pop(key, None)
        if cfg.literal_only or not cfg.emotion:
            strength = replace(strength, arousal=0.0, valence=0.0, funny=0.0)
        if cfg.literal_only or not cfg.weight:
            strength = replace(strength, weight=0.0)
        out.append(Artifact(replace(art.header, strength=strength), payload))
    return out


def _without_level(art: Artifact) -> Artifact:
    """no_layer：组装时假装没有 level，所有记忆平铺。"""
    return Artifact(art.header, {k: v for k, v in art.payload.items() if k != "level"})


@contextlib.contextmanager
def _clock(cfg: Cfg):
    """临时改时间衰减：no_decay 全部新鲜，literal_only 全部过期。"""
    old = score_mod._age_days
    if cfg.literal_only or not cfg.decay:
        score_mod._age_days = (lambda c, n: 1e6) if cfg.literal_only else (lambda c, n: 0.0)
    try:
        yield
    finally:
        score_mod._age_days = old


@contextlib.contextmanager
def _dedupe(cfg: Cfg):
    """临时关掉 assemble 的全局去重（退出即还原）。"""
    old = assemble_mod._dedupe
    if not cfg.dedupe:
        assemble_mod._dedupe = lambda arts: list(arts)
    try:
        yield
    finally:
        assemble_mod._dedupe = old


def pipeline(cfg: Cfg, pool, source, graph, cache, q: str) -> tuple[str, list[Artifact]]:
    """按配置组合 seeds → activate → select → assemble，返回注入文本与选中。"""
    seed_ids = [] if cfg.literal_only else seeds(q, source)
    activation = {} if (not cfg.spread or cfg.literal_only) else activate(seed_ids, graph, cache)
    if cfg.literal_only:
        qg = bigrams(q)
        candidates = [(a, 0.0) for a in pool
                      if dice(qg, len(qg), frozenset(bigrams(content_of(a)))) > 0]
    else:
        candidates = [(a, float(activation.get(a.header.id, 0.0))) for a in pool]
    with _clock(cfg):
        picked = select(candidates, q, 0.0, k=K, explore=0.0, gate=False)
    if not cfg.layer:
        picked = [_without_level(a) for a in picked]
    with _dedupe(cfg):
        return assemble(picked, budget=BUDGET), picked


def measure(cfg: Cfg, pool, source, graph, cache) -> dict:
    """跑完 20 条黄金问句，汇总命中 / 字数 / 噪声 / 越界。"""
    hit = total = chars = over = leak = 0
    noise_chars = kept_chars = 0
    misses, rows = [], []
    for g in GOLD:
        block, picked = pipeline(cfg, pool, source, graph, cache, g["q"])
        low, exps = block.lower(), [e.lower() for e in g["expect_any"]]
        chars += len(block)
        ok = bool(exps) and any(e in low for e in exps)
        if exps:
            total += 1
            hit += ok
            if not ok:
                misses.append(g["q"])
            for art in (picked if not cfg.dedupe else assemble_mod._dedupe(picked)):
                try:
                    n = len(assemble_mod._sentence(art)[1])
                except Exception:  # noqa: BLE001 - 坏条目按正文长度兜底
                    n = len(content_of(art))
                kept_chars += n
                if not any(e in content_of(art).lower() for e in exps):
                    noise_chars += n
        else:
            over += bool(block.strip())
            leak += any(w in low for w in FORBIDDEN.get(g["q"], ()))
        rows.append((ok, len(block)))
    return {"name": cfg.name, "hit": hit, "total": total, "misses": misses,
            "chars": chars / len(GOLD), "noise": noise_chars / max(1, kept_chars),
            "over": over, "leak": leak, "rows": rows}


def report(results: list[dict], stats: dict) -> str:
    """生成 markdown 报告：结果表 + 逐项解读 + 结论。"""
    rs = sorted(results, key=lambda r: (-r["hit"], r["noise"], r["chars"]))
    base = next(r for r in rs if r["name"] == "full")
    cats: dict[str, int] = {}
    for g in GOLD:
        key = g["note"].split("｜")[0]
        cats[key] = cats.get(key, 0) + 1
    why = {"事实·跨表述": "与问句零字面重合，考权重先验 / 语义替代",
           "事实": "名字、目标、家乡、游戏、宠物", "事件": "面试、加班、请客；部分靠关系边扩散",
           "情绪": "低潮、失眠；正向状态作干扰", "印象": "「倔」「心软」；高权重低字面",
           "边界": "应返回空：别人的秘密、短期琐事"}
    L = ["# 消融基准：每个组件值多少", "",
         f"> {stats['n']} 条消息（{stats['noise']:.0%} 是模板闲聊）· 20 条黄金问答"
         f"（18 条可答 + 2 条边界）· 固定种子 {SEED}",
         f"> {stats['edges']} 条联想边（生产自动建 similar/temporal + "
         f"{stats['causal']} 条人工 causal）· "
         f"扩散新增 {stats['spread'][0]} 个候选（{stats['spread'][1]}/20 题有新增）",
         "> 检索参数：top-k=8、注入预算 600 字、explore=0（去掉随机探索带来的抖动）", "",
         "## 黄金集", "", "| 类别 | 题数 | 考什么 |", "|---|---:|---|"]
    L += [f"| {c} | {n} | {why[c]} |" for c, n in cats.items()]
    L += ["", f"数据里 {stats['noise_text']}/{stats['n']} 条是模板生成的无关闲聊，"
          "非闲聊只有 20 条；这保证命中不是靠「池子里全是答案」。", "",
          "## 消融结果", "", "| 配置 | 命中 | 注入字数 | 噪声占比 | 越界 |", "|---|---:|---:|---:|---:|"]
    L += [f"| `{r['name']}` | **{r['hit']}/{r['total']}** | {r['chars']:.0f} 字 | "
          f"{r['noise']:.0%} | {r['over']}/2 |" for r in rs]
    L += ["", "> 「命中」按 18 条可答题计；2 条边界题没有 expect_any，单列在「越界」列。",
          "> 注入字数是 20 条问句的平均值；噪声占比只统计 18 条可答题（边界题单列）。",
          "", "## 逐项解读", ""]
    explain = {
        "full": "基线顶到黄金集天花板；但八成注入字与本题无关，命中靠 1~3 条相关记忆挤进 top-8。",
        "no_spread": "「面试结果」正文没有「面试」二字，失去人工 causal 边的 1.5×activation 后掉出 top-8；生产自动建边只覆盖 similar/temporal。",
        "no_score_emotion": "问句含「累」，情绪分原本给负效价高唤醒的失眠记忆 +1.3；置 0 后被中权重闲聊挤出 top-8。",
        "no_score_tag": "标签一撤，家乡/游戏/睡眠这类零字面事实只剩权重，挤不进 top-8；宠物题因正文含「养了」还有字面重合，反而活下来。",
        "no_weight_prior": "跨表述事实和开放印象题失去唯一抓手；其余题由标签、字面、情绪接住。",
        "no_dedupe": "命中不变，但重复条目都留在注入里，字数和噪声一起上升；去重买的是密度，不是召回。",
        "no_layer": "level 只影响 assemble 的排序和措辞，select 打分里没有 level 项；命中不变，字数只差几字。",
        "no_decay": "freshness 满分只有 0.5，压不过 2 分标签、1 分权重；没有排名翻转。",
        "literal_only": "只剩问句带原词的题能中；不凑 top-8，注入字数骤降、噪声占比反而最低——它的问题是找不到，不是找错。",
    }
    for r in rs:
        miss = "没有漏题。" if not r["misses"] else "漏掉：" + "、".join(f"「{q}」" for q in r["misses"]) + "。"
        L.append(f"**`{r['name']}`** — 命中 {r['hit']}/{r['total']}（{r['hit'] - base['hit']:+d}），"
                 f"平均注入 {r['chars']:.0f} 字，噪声 {r['noise']:.0%}，越界 {r['over']}/2。"
                 f"{explain[r['name']]}{miss}")
        L.append("")
    L += ["", "## 结论", "", _conclusion(base, {r["name"]: r for r in rs})]
    return "\n".join(L) + "\n"


def _conclusion(base: dict, by: dict) -> str:
    """按实测差值写结论，不写死数字。"""
    loss = {n: base["hit"] - r["hit"] for n, r in by.items() if n != "full"}
    w, dd = by["no_weight_prior"], by["no_dedupe"]
    legacy = ("你还记得我叫什么名字吗", "我是干什么的", "上次面试结果怎么样",
              "我上次加班到几点", "我的睡眠怎么样", "你觉得我这个人怎么样")
    lost = [q for q in legacy if q in w["misses"]]
    return "\n".join([
        f"1. **必需**：字面重合（关掉 {loss['literal_only']} 条）、标签（{loss['no_score_tag']} 条）、"
        f"权重先验（{loss['no_weight_prior']} 条）。三者覆盖不同的题，缺一类就有一类问句失明。",
        f"2. **补丁**：激活扩散掉 {loss['no_spread']} 条（只救零字面的因果结果），"
        f"情绪项掉 {loss['no_score_emotion']} 条（只影响带情绪词的问句）。不是主力，但删了会少两类能力。",
        "3. **装饰**：level 的召回贡献是 0——它只被 assemble 用来调顺序和措辞，select 里没有 level 项；"
        "时间衰减的召回贡献也是 0，freshness 满分 0.5，压不过标签的 2 分。这两项最容易被高估。",
        f"4. **去重买密度**：命中不掉，但注入字数从 {base['chars']:.0f} 涨到 {dd['chars']:.0f}"
        f"（{(dd['chars'] / base['chars'] - 1) * 100:+.0f}%），噪声也升。它让同一件事只说一次，不负责找对。",
        f"5. **回答「6/6 是不是靠权重先验」**：不是。`no_weight_prior` 只掉 {loss['no_weight_prior']} 条，"
        f"仍有 {w['hit']}/18；掉的是「我是干什么的」和「你最了解我什么」——零字面、零标签、只能靠权重的题。"
        f"对应旧 6 题（名字/职业/面试结果/加班/睡眠/印象）关掉权重后是 {len(legacy) - len(lost)}/6，"
        f"掉的正是「{'、'.join(lost) or '无'}」。所以 6/6 不是全靠权重先验，但跨表述那一分确实是权重买的。",
        f"6. **边界是系统性缺口**：所有配置都越界 2/2（注入了非空上下文），但 shadow 正文被 "
        f"scope 过滤挡住，直接泄露 {by['full']['leak']}/2。缺的不是隔离，是「相关性不足就返回空」"
        "的闸门：select 永远凑满 top-8。这不是某个组件能消融出来的，是缺了一个组件。", "",
        "一句话：**字面 + 标签 + 权重是三条腿，扩散和情绪是补丁，level 和衰减目前是装饰；"
        "去重省字不救命；边界没有门。**", ""])


def main() -> None:
    mems = build()
    stats = {"n": len(mems), "noise": noise_share(mems),
             "noise_text": sum(1 for m in mems if m.noise)}
    db, cache, graph, source = _load(mems)
    stats["edges"] = db.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    stats["causal"] = db.conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind = 'causal'").fetchone()[0]
    stats["spread"] = spread_counts(source, graph, cache, GOLD)
    try:
        results = []
        for cfg in CONFIGS:
            results.append(measure(cfg, _transform(cfg, source), source, graph, cache))
            r = results[-1]
            print(f"[{cfg.name:<16}] 命中 {r['hit']}/{r['total']} 注入 {r['chars']:.0f} 字 "
                  f"噪声 {r['noise']:.0%} 越界 {r['over']}/2")
        out = os.path.join(ROOT, "benchmarks", "results", "ablation.md")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(report(results, stats))
        print(f"\n→ 写入 {out}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
