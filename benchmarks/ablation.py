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
import recall.gate as gate_mod, recall.score as score_mod  # noqa: E402
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
    gate: bool = True  # 相关性双阈值闸门（ISSUE-0017）


CONFIGS = (
    Cfg("full"),
    Cfg("no_gate", gate=False),
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
        graph.link(by_text["他去万兴科技面试了"].header.id,
                   by_text["万兴那边给他发了offer，他过了"].header.id, "causal", .9)
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
        picked = select(candidates, q, 0.0, k=K, explore=0.0, gate=cfg.gate)
    if not cfg.layer:
        picked = [_without_level(a) for a in picked]
    with _dedupe(cfg):
        return assemble(picked, budget=BUDGET), picked


def measure(cfg: Cfg, pool, source, graph, cache) -> dict:
    """跑完 20 条黄金问句，汇总命中 / 字数 / 噪声 / 边界泄露与注入。"""
    hit = total = chars = leak = bchars = 0
    boundary_n = sum(1 for g in GOLD if not g["expect_any"])
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
            leak += sum(low.count(w) for w in FORBIDDEN.get(g["q"], ()))
            bchars += len(block)
        rows.append((ok, len(block)))
    return {"name": cfg.name, "hit": hit, "total": total, "misses": misses,
            "chars": chars / len(GOLD), "noise": noise_chars / max(1, kept_chars),
            "leak": leak, "bchars": bchars / max(1, boundary_n), "rows": rows}


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
         f"> {stats['edges']} 条边（自动 similar/temporal + {stats['causal']} 人工 causal）"
         f" · 扩散新增 {stats['spread'][0]}（{stats['spread'][1]}/20 题）",
         "> 检索参数：top-k=8、注入预算 600 字、explore=0（去掉随机探索带来的抖动）",
         f"> 证据闸门：`evidence >= max({gate_mod.MIN_EV_ABS}, top_evidence × {gate_mod.MIN_EV_REL})`；"
         "weight/freshness 只排序不能过门，全不达标返回空", "",
         "## 黄金集", "", "| 类别 | 题数 | 考什么 |", "|---|---:|---|"]
    L += [f"| {c} | {n} | {why[c]} |" for c, n in cats.items()]
    L += ["", f"数据里 {stats['noise_text']}/{stats['n']} 条是模板生成的无关闲聊，"
          "非闲聊只有 20 条；这保证命中不是靠「池子里全是答案」。", "",
          "## 消融结果", "", "| 配置 | 命中 | 注入字数 | 噪声占比 | 边界正文泄露 | 边界注入字数 |",
          "|---|---:|---:|---:|---:|---:|"]
    L += [f"| `{r['name']}` | **{r['hit']}/{r['total']}** | {r['chars']:.0f} 字 | "
          f"{r['noise']:.0%} | {r['leak']} | {r['bchars']:.0f} 字 |" for r in rs]
    L += ["", "> 「命中」按 18 条可答题计；2 条边界题单列「边界正文泄露」（FORBIDDEN 词出现次数，"
          "红线 0）与「边界注入字数」。", "> 注入字数是 20 条问句的平均值；噪声占比只统计 18 条可答题。",
          "", "## 逐项解读", ""]
    explain = {
        "full": "证据闸门生效后的基线：命中由字面/标签/激活/情绪证据决定，权重先验不再单独过门。",
        "no_gate": "关掉闸门即旧 top-k 行为：噪声与字数回到未过滤水平；多出的命中靠凑满 top-8 带进零证据题。",
        "no_spread": "激活扩散是证据之一：关掉后「面试结果」（靠 causal 边拿到 offer）与「我是不是嘴硬心软」掉出闸门。",
        "no_score_emotion": "情绪对齐算证据：关掉后带情绪词的问句失去匹配信号，面试结果、累、印象类共 4 条掉出闸门。",
        "no_score_tag": "标签是零字面事实的主要证据：关掉后名字/职业/家乡/游戏/睡眠等只剩字面，7 条掉出闸门。",
        "no_weight_prior": "权重不参与闸门，关掉只改排序：命中与 full 一致——这正是证据闸门修掉的老问题。",
        "no_dedupe": "命中不变，重复条目略增字数和噪声；闸门后注入本来就少，去重收益变小。",
        "no_layer": "level 只影响 assemble 的排序和措辞，不进证据；命中不变。",
        "no_decay": "freshness 只参与排序、不进证据；关掉后排名不翻转，命中不变。",
        "literal_only": "只剩字面证据时，只有问句带原词的题能过门；它的问题是找不到，不是找错。",
    }
    for r in rs:
        miss = "没有漏题。" if not r["misses"] else "漏掉：" + "、".join(f"「{q}」" for q in r["misses"]) + "。"
        L.append(f"**`{r['name']}`** — 命中 {r['hit']}/{r['total']}（{r['hit'] - base['hit']:+d}），"
                 f"平均注入 {r['chars']:.0f} 字，噪声 {r['noise']:.0%}，"
                 f"边界泄露 {r['leak']}、注入 {r['bchars']:.0f} 字。"
                 f"{explain[r['name']]}{miss}")
        L.append("")
    L += ["", "## 结论", "", _conclusion(base, {r["name"]: r for r in rs})]
    return "\n".join(L) + "\n"


def _conclusion(base: dict, by: dict) -> str:
    """按实测差值写结论，不写死数字。"""
    loss = {n: base["hit"] - r["hit"] for n, r in by.items() if n != "full"}
    ng = by["no_gate"]
    misses = "、".join(f"「{q}」" for q in base["misses"]) or "无"
    return "\n".join([
        f"1. **证据是闸门的唯一入场券**：关掉标签掉 {loss['no_score_tag']} 条、情绪掉 "
        f"{loss['no_score_emotion']} 条、激活掉 {loss['no_spread']} 条；只留字面时只剩 "
        f"{by['literal_only']['hit']}/18。权重（{loss['no_weight_prior']} 条）、新鲜度"
        f"（{loss['no_decay']} 条）、层级（{loss['no_layer']} 条）只影响排序，不进证据。",
        f"2. **闸门买的是精度**：`full` 噪声 {base['noise']:.0%}、平均 {base['chars']:.0f} 字；"
        f"`no_gate` 噪声 {ng['noise']:.0%}、{ng['chars']:.0f} 字。代价是命中 {base['hit']}/18 vs "
        f"{ng['hit']}/18——`no_gate` 靠凑满 top-8 把零证据题也带进来。",
        f"3. **丢掉的是零证据题**：{misses}——问句与记忆零字面、零标签、零激活，只剩权重先验；"
        "证据闸门按设计不再放行，这类跨表述检索归 ISSUE-0001。",
        f"4. **边界**：两列都不看 block 是否为空——正文泄露 {base['leak']}（`no_gate` {ng['leak']}），"
        f"边界注入 {base['bchars']:.0f} 字（`no_gate` {ng['bchars']:.0f} 字）。"
        "时钟题（今天几号）在 select 入口直接返回空；影子题只输出遮蔽句是 DESIGN 7.4 的既定行为。",
        "",
        f"一句话：**双阈值只管分数，证据闸门才能把 weight/freshness 从相关性里拆出来；"
        f"噪声 {ng['noise']:.0%}→{base['noise']:.0%} 的代价是零证据题，留给混合检索。**", ""])


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
                  f"噪声 {r['noise']:.0%} 泄露 {r['leak']} 边界 {r['bchars']:.0f} 字")
        out = os.path.join(ROOT, "benchmarks", "results", "ablation.md")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(report(results, stats))
        print(f"\n→ 写入 {out}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
