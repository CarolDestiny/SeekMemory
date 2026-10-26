#!/usr/bin/env python3
"""Run Dream tradeoff evaluations across checkouts and render the report.

One command runs each target in its own Python process (production modules
cannot be mixed inside one interpreter), writes a content-free JSON snapshot
per target, and renders a bilingual Markdown report.

Example::

    python benchmarks/dream_tradeoff.py \
        --target cc814ce=/path/to/cc814ce \
        --target d9fc248=/path/to/d9fc248 \
        --target current=. \
        --output-json benchmarks/results/dream_tradeoff.json \
        --output-md benchmarks/results/dream_tradeoff.md

Use ``--input label=path`` to re-render from committed JSON without running.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_CORPUS = HERE / "data" / "dream_tradeoff_corpus.jsonl"
DEFAULT_RESULTS = HERE / "results"
REPORT_SCHEMA = "seekmemory.dream_tradeoff.report.v1"

PASS = {"en": "PASS", "zh": "通过"}
FAIL = {"en": "FAIL", "zh": "未通过"}
NONE = {"en": "none", "zh": "无"}
REFERENCE = {"en": "reference", "zh": "基准"}
YES = {"en": "yes", "zh": "是"}
NO = {"en": "no", "zh": "否"}

MISSING_LABELS: dict[str, tuple[str, str]] = {
    "peanut_allergy": (
        "allergy stated as 'allergic to X'",
        "以“对 X 过敏”表述的过敏信息",
    ),
    "moved_beijing": (
        "relocation stated as 'moved to X'",
        "以“搬到 X”表述的搬迁",
    ),
    "birthday": (
        "birthday stated as 'my birthday is ...'",
        "以“我的生日是……”表述的生日",
    ),
    "grandma_health": (
        "grandparent health and care",
        "祖辈健康与照护",
    ),
    "quit_smoking": (
        "habit change such as quitting smoking",
        "戒烟等习惯改变",
    ),
    "work_city": (
        "work city stated as 'I work in X'",
        "以“我在 X 工作”表述的工作城市",
    ),
    "best_friend": (
        "close friendship stated with modifiers",
        "带修饰语的好友关系",
    ),
    "stress": (
        "stress/insomnia without a high-arousal keyword",
        "未命中高强度情绪词的压力与失眠",
    ),
}


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def num(value: int) -> str:
    return f"{int(value):,}"


def truth(value: bool, lang: str) -> str:
    return PASS[lang] if value else FAIL[lang]


def table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def safe_label(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("_") or "target"


# --------------------------------------------------------------------------- #
# Comparison
# --------------------------------------------------------------------------- #


def compare_target(baseline: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    """Compute relative efficiency and the explicit tradeoff verdict."""
    base_cost = baseline["cost"]
    target_cost = target["cost"]
    base_calls = int(base_cost["extraction_calls"])
    base_tokens = int(base_cost["usage_total"])
    call_reduction = (
        1.0 - int(target_cost["extraction_calls"]) / base_calls if base_calls else 0.0
    )
    token_reduction = (
        1.0 - int(target_cost["usage_total"]) / base_tokens if base_tokens else 0.0
    )
    thresholds = target["verdict"]["thresholds"]
    quality_checks = dict(target["verdict"]["checks"])
    efficiency_checks = {
        "call_reduction": call_reduction >= float(thresholds["min_call_reduction"]),
        "token_reduction": token_reduction >= float(thresholds["min_token_reduction"]),
    }
    checks = {**quality_checks, **efficiency_checks}
    quality_ok = all(quality_checks.values())
    efficiency_ok = all(efficiency_checks.values())
    backlog_bounded = bool(target["backlog"].get("bounded"))
    if quality_ok and efficiency_ok:
        verdict = "ACCEPTED" if backlog_bounded else "ACCEPTED_WITH_BACKLOG_RISK"
    else:
        verdict = "NOT_ACCEPTED"
    return {
        "baseline": baseline["label"],
        "target": target["label"],
        "call_reduction": round(call_reduction, 4),
        "token_reduction": round(token_reduction, 4),
        "artifact_reduction": round(
            1.0
            - int(target["artifacts"]["extraction_written"])
            / max(1, int(baseline["artifacts"]["extraction_written"])),
            4,
        ),
        "quality_ok": quality_ok,
        "efficiency_ok": efficiency_ok,
        "backlog_bounded": backlog_bounded,
        "checks": checks,
        "verdict": verdict,
    }


# --------------------------------------------------------------------------- #
# Report rendering
# --------------------------------------------------------------------------- #


def _t(lang: str, en: str, zh: str) -> str:
    return en if lang == "en" else zh


def _render_body(
    lang: str,
    results: dict[str, dict[str, Any]],
    labels: list[str],
    baseline_label: str,
    target_label: str,
    corpus_path: Path,
) -> str:
    baseline = results[baseline_label]
    target = results[target_label]
    comparison = compare_target(baseline, target)
    corpus = target["corpus"]
    thresholds = target["verdict"]["thresholds"]
    headers = ["metric"] if lang == "en" else ["指标"]
    headers += labels

    def row(label_en: str, label_zh: str, values: list[Any]) -> list[Any]:
        return [_t(lang, label_en, label_zh), *values]

    def threshold_row(
        label_en: str, label_zh: str, threshold: str, *values: Any
    ) -> list[Any]:
        return [_t(lang, label_en, label_zh), threshold, *values]

    def per_target(fn) -> list[Any]:
        return [fn(results[label]) for label in labels]

    parts: list[str] = []

    # Status and verdict -----------------------------------------------------
    if lang == "en":
        parts.append(f"**Verdict ({target_label} vs {baseline_label}): "
                     f"`{comparison['verdict']}`**")
        if comparison["verdict"] == "NOT_ACCEPTED":
            parts.append(
                "\nThe optimization reduces cost, but the frozen corpus shows an "
                "unacceptable memory-quality loss under the pre-registered "
                "thresholds. It is not acceptable as-is; the recommendations below "
                "name the next tuning targets. This issue intentionally does not "
                "change the triage algorithm."
            )
        elif comparison["verdict"] == "ACCEPTED_WITH_BACKLOG_RISK":
            parts.append(
                "\nCost and quality pass the thresholds, but pending topics grow "
                "without a bound. Treat the backlog as a release blocker until a "
                "bounded aging/discard policy exists."
            )
        else:
            parts.append("\nCost, quality and backlog all pass the thresholds.")
    else:
        parts.append(f"**结论（{target_label} 对比 {baseline_label}）："
                     f"`{comparison['verdict']}`**")
        if comparison["verdict"] == "NOT_ACCEPTED":
            parts.append(
                "\n优化确实降低了成本，但在冻结语料上，记忆质量损失超过了预先约定的阈值，"
                "因此当前不可接受。下面的建议给出下一轮调参目标。本 issue 故意不修改分诊算法。"
            )
        elif comparison["verdict"] == "ACCEPTED_WITH_BACKLOG_RISK":
            parts.append(
                "\n成本与质量通过阈值，但 pending 主题无界增长。在有界的老化/丢弃策略"
                "落地前，应把积压视为发布阻塞项。"
            )
        else:
            parts.append("\n成本、质量与积压均通过阈值。")

    if lang == "en":
        parts.append(
            f"\nQuality: important-fact recall "
            f"{target['quality']['important_fact_recalled']}/"
            f"{target['quality']['important_fact_total']} "
            f"({pct(target['quality']['important_fact_recall'])}; target "
            f">= {pct(thresholds['min_important_fact_recall'])}); "
            f"self-impression coverage "
            f"{pct(target['quality']['self_impression_coverage'])} (target "
            f">= {pct(thresholds['min_self_impression_coverage'])}). "
            f"Efficiency: calls -{pct(comparison['call_reduction'])}, tokens "
            f"-{pct(comparison['token_reduction'])}. Pending growth: "
            f"{target['backlog']['growth_per_day']} topics/night, bounded="
            f"{YES['en'] if target['backlog']['bounded'] else NO['en']}."
        )
    else:
        parts.append(
            f"\n质量：重要事实召回 "
            f"{target['quality']['important_fact_recalled']}/"
            f"{target['quality']['important_fact_total']} "
            f"({pct(target['quality']['important_fact_recall'])}；目标 "
            f">= {pct(thresholds['min_important_fact_recall'])}）；"
            f"自我印象覆盖 {pct(target['quality']['self_impression_coverage'])}"
            f"（目标 >= {pct(thresholds['min_self_impression_coverage'])}）。"
            f"效率：调用 -{pct(comparison['call_reduction'])}，token "
            f"-{pct(comparison['token_reduction'])}。pending 增长：每晚 "
            f"{target['backlog']['growth_per_day']} 个主题，是否有界="
            f"{YES['zh'] if target['backlog']['bounded'] else NO['zh']}。"
        )

    parts.append(
        "\n"
        + _t(
            lang,
            f"The baseline `{baseline_label}` is the comparison anchor, not an "
            "acceptable configuration: it extracts every topic, including "
            "low-value chatter "
            f"(false-memory rate {pct(baseline['quality']['false_memory_rate'])}). "
            "The target improves false-memory and duplicate rates, but the memory "
            "coverage checks above decide whether that improvement is worth the "
            "tradeoff.",
            f"基线 `{baseline_label}` 是对比基准，不是可接受配置：它会抽取所有主题，"
            f"包括低价值闲聊（错误记忆率 "
            f"{pct(baseline['quality']['false_memory_rate'])}）。目标版本改善了错误记忆"
            "和重复率，但是否值得这个 tradeoff，由上面的记忆覆盖检查决定。",
        )
    )

    # Corpus snapshot --------------------------------------------------------
    parts.append(f"\n### {_t(lang, 'Frozen corpus', '冻结语料')}\n")
    snapshot_rows = [
        [
            _t(lang, "Dataset", "数据集"),
            f"`{corpus_path.name}` (synthetic, frozen)",
        ],
        [_t(lang, "SHA-256", "SHA-256"), f"`{corpus['sha256']}`"],
        [_t(lang, "Topics", "主题数"), corpus["topics"]],
        [
            _t(lang, "Classes", "分类"),
            ", ".join(f"{key}={value}" for key, value in corpus["classes"].items()),
        ],
        [
            _t(lang, "Important topics", "重要主题"),
            corpus["important_topics"],
        ],
        [
            _t(lang, "Sessions", "会话"),
            ", ".join(f"{key}={value}" for key, value in corpus["sessions"].items()),
        ],
        [
            _t(lang, "Behavior episodes", "行为场景"),
            ", ".join(
                f"{key}={value}" for key, value in corpus["behavior_episodes"].items()
            ),
        ],
        [_t(lang, "Fixed clock", "固定时钟"), f"`{corpus['fixed_clock']}`"],
    ]
    parts.append(table([_t(lang, "field", "字段"), _t(lang, "value", "值")], snapshot_rows))

    # Method -----------------------------------------------------------------
    parts.append(f"\n### {_t(lang, 'Method', '方法')}\n")
    if lang == "en":
        parts.append(
            "- Every target runs the production `DreamCycle -> "
            "IngestService.flush` path against an isolated in-memory SQLite store.\n"
            "- `d9fc248` and later checkouts are called with `triage=True`; "
            "`cc814ce` predates the parameter, so the harness filters unsupported "
            "kwargs and runs the same production flush path without triage. The "
            "feature-detection table records this difference.\n"
            "- The model is a deterministic provider that returns frozen extraction "
            "items keyed by the Source ids rendered in the production prompt. It "
            "never calls the network.\n"
            "- Sources are admitted through `ExtractionRepository.enqueue_extraction`, "
            "the same path `Buffer.add` uses. Artifacts are written only by "
            "`IngestService`; the harness never calls `commit`.\n"
            "- Self-impressions are produced by the production "
            "`maintain.self_impression.build_self_impressions` maintenance path.\n"
            "- Token usage is estimated from the actual prompt/output length with "
            "`int(chars/1.6) + 4*messages`; `usage_cached` is zero because no prefix "
            "cache is simulated. All targets use the same estimator.\n"
            "- One target per process avoids importing production modules from two "
            "checkouts into the same interpreter."
        )
    else:
        parts.append(
            "- 每个目标都在隔离的内存 SQLite 上运行生产 `DreamCycle -> "
            "IngestService.flush` 路径。\n"
            "- `d9fc248` 及之后版本以 `triage=True` 调用；`cc814ce` 早于该参数，"
            "评估器会过滤不支持的参数，仍走同一条生产 flush 路径但不启用分诊。"
            "特性检测表记录了这一点。\n"
            "- 模型是确定性 provider，按生产提示词中渲染的 Source id 返回冻结的抽取结果，"
            "不访问网络。\n"
            "- Source 通过 `ExtractionRepository.enqueue_extraction` 写入，与 "
            "`Buffer.add` 使用同一路径。Artifact 只由 `IngestService` 写入；"
            "评估器从不直接调用 `commit`。\n"
            "- 自我印象由生产 `maintain.self_impression.build_self_impressions` "
            "维护路径生成。\n"
            "- token 用量按实际提示词/输出长度用 `int(chars/1.6) + 4*messages` 估算；"
            "由于没有模拟前缀缓存，`usage_cached` 为零。所有目标使用同一估算器。\n"
            "- 每个目标单独进程运行，避免把多个 checkout 的生产模块导入同一解释器。"
        )

    # Run configuration ------------------------------------------------------
    parts.append(f"\n### {_t(lang, 'Run configuration', '运行配置')}\n")
    config = target["config"]
    config_rows = [
        ["`dream_max_batches`", num(config["dream_max_batches"])],
        ["`dream_max_calls`", num(config["dream_max_calls"])],
        ["`dream_token_budget`", num(config["dream_token_budget"])],
        ["`dream_batch_tokens`", num(config["dream_batch_tokens"])],
        ["`flush batch_cap`", num(config["flush_batch_cap"])],
        ["`self_impression min_evidence`", num(config["self_impression_min_evidence"])],
        [_t(lang, "`backlog nights`", "`backlog 夜数`"), num(config["backlog_days"])],
    ]
    parts.append(
        table([_t(lang, "setting", "设置"), _t(lang, "value", "值")], config_rows)
    )

    # Cost table -------------------------------------------------------------
    parts.append(f"\n### {_t(lang, 'Cost and extraction yield', '成本与抽取产出')}\n")
    cost_rows = [
        row("Extraction calls", "抽取调用数", per_target(
            lambda r: num(r["cost"]["extraction_calls"]))),
        row("usage_in", "usage_in", per_target(lambda r: num(r["cost"]["usage_in"]))),
        row("usage_cached", "usage_cached", per_target(
            lambda r: num(r["cost"]["usage_cached"]))),
        row("usage_out", "usage_out", per_target(lambda r: num(r["cost"]["usage_out"]))),
        row("Total tokens", "总 token", per_target(
            lambda r: num(r["cost"]["usage_total"]))),
        row("Calls with >1 topic", "多主题调用", per_target(
            lambda r: num(r["cost"]["calls_with_multiple_topics"]))),
        row("Max topics per call", "单次最多主题", per_target(
            lambda r: num(r["cost"]["max_topics_per_call"]))),
        row("Avg input tokens / call", "每次平均输入 token", per_target(
            lambda r: f"{r['cost']['avg_input_tokens_per_call']:.1f}")),
        row("Call reduction vs baseline", "调用相对基线下降", [
            REFERENCE[lang] if label == baseline_label else pct(
                compare_target(baseline, results[label])["call_reduction"])
            for label in labels
        ]),
        row("Token reduction vs baseline", "token 相对基线下降", [
            REFERENCE[lang] if label == baseline_label else pct(
                compare_target(baseline, results[label])["token_reduction"])
            for label in labels
        ]),
    ]
    parts.append(table(headers, cost_rows))

    # Quality table ----------------------------------------------------------
    parts.append(f"\n### {_t(lang, 'Memory quality', '记忆质量')}\n")
    quality_rows = [
        row("Important-fact recall", "重要事实召回", per_target(
            lambda r: f"{r['quality']['important_fact_recalled']}/"
                      f"{r['quality']['important_fact_total']} "
                      f"({pct(r['quality']['important_fact_recall'])})")),
        row("Bot-behavior coverage", "bot 行为覆盖", per_target(
            lambda r: f"{r['quality']['behavior_written']}/"
                      f"{r['quality']['behavior_total']} "
                      f"({pct(r['quality']['behavior_coverage'])})")),
        row("Self-impression coverage", "自我印象覆盖", per_target(
            lambda r: f"{len(r['quality']['self_impression_written_kinds'])}/"
                      f"{len(r['quality']['self_impression_expected_kinds'])} "
                      f"({pct(r['quality']['self_impression_coverage'])})")),
        row("False-memory rate", "错误记忆率", per_target(
            lambda r: pct(r["quality"]["false_memory_rate"]))),
        row("Duplicate rate", "重复率", per_target(
            lambda r: pct(r["quality"]["duplicate_rate"]))),
        row("Extraction artifacts", "抽取写入 Artifact", per_target(
            lambda r: num(r["artifacts"]["extraction_written"]))),
        row("Unclassified artifacts", "未分类 Artifact", per_target(
            lambda r: num(r["artifacts"]["unclassified"]))),
    ]
    parts.append(table(headers, quality_rows))

    # Topics table -----------------------------------------------------------
    parts.append(f"\n### {_t(lang, 'Topic selection and pending backlog', '主题选择与 pending 积压')}\n")
    topic_rows = [
        row("Topics seen", "看到的主题", per_target(lambda r: num(r["topics"]["seen"]))),
        row("Eligible", "达到阈值", per_target(
            lambda r: NONE[lang] if r["topics"]["eligible"] is None
            else num(r["topics"]["eligible"]))),
        row("Selected", "已选中", per_target(lambda r: num(r["topics"]["selected"]))),
        row("Skipped", "跳过", per_target(lambda r: num(r["topics"]["skipped"]))),
        row("Skipped low-value", "跳过的低价值", per_target(
            lambda r: NONE[lang] if r["topics"]["skipped_low_value"] is None
            else num(r["topics"]["skipped_low_value"]))),
        row("Skipped important (false negative)", "跳过的重要主题（漏判）", per_target(
            lambda r: NONE[lang] if r["topics"]["skipped_important"] is None
            else num(r["topics"]["skipped_important"]))),
        row("Pending topics", "pending 主题", per_target(
            lambda r: num(r["pending"]["topics"]))),
        row("Pending important", "pending 重要主题", per_target(
            lambda r: num(r["pending"]["important_topics"]))),
        row("Pending low-value", "pending 低价值主题", per_target(
            lambda r: num(r["pending"]["low_value_topics"]))),
        row("Pending rows", "pending 行", per_target(
            lambda r: num(r["pending"]["rows"]))),
        row("Oldest pending age (days)", "最老 pending 年龄（天）", per_target(
            lambda r: f"{r['pending']['oldest_age_days']:.3f}")),
        row("Mean pending age (days)", "平均 pending 年龄（天）", per_target(
            lambda r: f"{r['pending']['mean_age_days']:.3f}")),
        row("Topics processed by Dream", "Dream 处理主题数", per_target(
            lambda r: num(r["dream"]["batches"]))),
        row("Budget stopped", "预算停止原因", per_target(
            lambda r: (
                NONE[lang]
                if not isinstance(r["dream"].get("budget"), dict)
                else (r["dream"]["budget"].get("stopped") or NONE[lang])
            ))),
        row("Budget calls used", "预算已用调用", per_target(
            lambda r: (
                NONE[lang]
                if not isinstance(r["dream"].get("budget"), dict)
                else num(r["dream"]["budget"].get("calls_used", 0))
            ))),
        row("Dream status", "Dream 状态", per_target(
            lambda r: r["dream"]["status"])),
    ]
    parts.append(table(headers, topic_rows))

    # Triage distribution ----------------------------------------------------
    if target.get("triage", {}).get("applied"):
        parts.append(f"\n### {_t(lang, 'Triage score distribution', '分诊分数分布')}\n")
        distribution = target["triage"].get("distribution") or {}
        classes = ["fact", "behavior", "chatter", "backlog"]
        dist_rows = []
        for bucket in ("0", "1", "2-3", "4+"):
            counts = distribution.get(bucket, {})
            dist_rows.append(
                [f"`{bucket}`", *[num(counts.get(name, 0)) for name in classes]]
            )
        parts.append(
            table(
                [
                    _t(lang, "score bucket", "分数区间"),
                    *[
                        _t(lang, name, {"fact": "事实", "behavior": "行为",
                                        "chatter": "闲聊", "backlog": "积压"}[name])
                        for name in classes
                    ],
                ],
                dist_rows,
            )
        )

    # Verdict table ----------------------------------------------------------
    parts.append(f"\n### {_t(lang, 'Thresholds and verdict', '阈值与结论')}\n")
    threshold_rows = [
        threshold_row("Important-fact recall", "重要事实召回",
            f">= {pct(thresholds['min_important_fact_recall'])}",
            *[truth(results[label]["verdict"]["checks"]["important_fact_recall"], lang)
              for label in labels]),
        threshold_row("Bot-behavior coverage", "bot 行为覆盖",
            f">= {pct(thresholds['min_behavior_coverage'])}",
            *[truth(results[label]["verdict"]["checks"]["behavior_coverage"], lang)
              for label in labels]),
        threshold_row("Self-impression coverage", "自我印象覆盖",
            f">= {pct(thresholds['min_self_impression_coverage'])}",
            *[truth(results[label]["verdict"]["checks"]["self_impression_coverage"], lang)
              for label in labels]),
        threshold_row("False-memory rate", "错误记忆率",
            f"<= {pct(thresholds['max_false_memory_rate'])}",
            *[truth(results[label]["verdict"]["checks"]["false_memory_rate"], lang)
              for label in labels]),
        threshold_row("Duplicate rate", "重复率",
            f"<= {pct(thresholds['max_duplicate_rate'])}",
            *[truth(results[label]["verdict"]["checks"]["duplicate_rate"], lang)
              for label in labels]),
        threshold_row("Pending ratio", "pending 比例",
            f"<= {pct(thresholds['max_pending_ratio'])}",
            *[truth(results[label]["verdict"]["checks"]["pending_ratio"], lang)
              for label in labels]),
        threshold_row("Call reduction", "调用下降",
            f">= {pct(thresholds['min_call_reduction'])}",
            *[
                REFERENCE[lang] if label == baseline_label else truth(
                    compare_target(baseline, results[label])["checks"]["call_reduction"],
                    lang,
                )
                for label in labels
            ]),
        threshold_row("Token reduction", "token 下降",
            f">= {pct(thresholds['min_token_reduction'])}",
            *[
                REFERENCE[lang] if label == baseline_label else truth(
                    compare_target(baseline, results[label])["checks"]["token_reduction"],
                    lang,
                )
                for label in labels
            ]),
        threshold_row("Backlog bounded", "积压有界", _t(lang, "growth <= 0", "增长 <= 0"),
            *[truth(results[label]["backlog"]["bounded"], lang) for label in labels]),
        threshold_row("Overall", "总体", _t(lang, "all checks", "全部检查"),
            *[
                REFERENCE[lang] if label == baseline_label else
                str(compare_target(baseline, results[label])["verdict"])
                for label in labels
            ]),
    ]
    parts.append(
        table(
            [
                _t(lang, "check", "检查项"),
                _t(lang, "threshold", "阈值"),
                *labels,
            ],
            threshold_rows,
        )
    )

    # Backlog simulation -----------------------------------------------------
    parts.append(f"\n### {_t(lang, 'Pending growth simulation', 'Pending 增长模拟')}\n")
    backlog = target["backlog"]
    backlog_rows = [
        [
            day["day"],
            num(day["new_topics"]),
            num(day["pending_topics"]),
            num(day["pending_rows"]),
            f"{day['oldest_age_days']:.3f}",
            num(day["extraction_calls"]),
        ]
        for day in backlog["per_day"]
    ]
    parts.append(
        table(
            [
                _t(lang, "night", "第几晚"),
                _t(lang, "new low-value topics", "新增低价值主题"),
                _t(lang, "pending topics", "pending 主题"),
                _t(lang, "pending rows", "pending 行"),
                _t(lang, "oldest age (days)", "最老年龄（天）"),
                _t(lang, "extraction calls", "抽取调用"),
            ],
            backlog_rows,
        )
    )
    parts.append(
        "\n"
        + _t(
            lang,
            f"Growth per night: **{backlog['growth_per_day']}** topics; "
            f"bounded: **{YES[lang] if backlog['bounded'] else NO[lang]}**; "
            f"risk: `{backlog['risk']}`. Low-value pool: {backlog['low_value_pool']} topics.",
            f"每晚增长：**{backlog['growth_per_day']}** 个主题；"
            f"是否有界：**{YES[lang] if backlog['bounded'] else NO[lang]}**；"
            f"风险：`{backlog['risk']}`。低价值池：{backlog['low_value_pool']} 个主题。",
        )
    )
    if not backlog["bounded"]:
        parts.append(
            "\n"
            + _t(
                lang,
                "The merged implementation leaves low-value topics pending forever. "
                "Dream-only triage never expires or re-queues them, and the oldest "
                "pending age grows with every night. In this simulation the queue "
                f"grows linearly by {backlog['growth_per_day']} topics per night, so "
                "it is unbounded until an aging/discard policy is added.",
                "合并实现的低价值主题会永久停留在 pending。Dream-only 分诊从不使它们过期或"
                "重新入队，最老 pending 年龄逐晚增长。本模拟中队列每晚线性增长 "
                f"{backlog['growth_per_day']} 个主题，因此在加入老化/丢弃策略前是无界的。",
            )
        )

    # Feature paths ----------------------------------------------------------
    parts.append(f"\n### {_t(lang, 'Feature paths exercised', '实际走到的特性路径')}\n")
    feature_names = sorted(target["feature_paths"])
    feature_rows = [
        [f"`{name}`", *[
            YES[lang] if results[label]["feature_paths"].get(name) else NO[lang]
            for label in labels
        ]]
        for name in feature_names
    ]
    parts.append(
        table([_t(lang, "feature", "特性"), *labels], feature_rows)
    )

    # Missing coverage -------------------------------------------------------
    parts.append(f"\n### {_t(lang, 'Where coverage is lost', '覆盖损失在哪里')}\n")
    missing_keys = target["quality"]["missing_fact_keys"]
    missing_topics = target["quality"]["missing_fact_topic_ids"]
    missing_behavior = target["quality"]["missing_behavior_topic_ids"]
    if missing_keys:
        rows = []
        topics_by_key = target["quality"].get("missing_fact_topics") or {}
        for key in missing_keys:
            label_en, label_zh = MISSING_LABELS.get(key, (key, key))
            topic_ids = topics_by_key.get(key, [])
            score = None
            for tid in topic_ids:
                info = target["triage"]["scores"].get(tid)
                if info:
                    score = info.get("score")
                    break
            rows.append(
                [
                    f"`{key}`",
                    _t(lang, label_en, label_zh),
                    ", ".join(f"`{tid}`" for tid in topic_ids) or "-",
                    "-" if score is None else f"{score}",
                ]
            )
        parts.append(
            table(
                [
                    _t(lang, "fact key", "事实标签"),
                    _t(lang, "phrasing class", "表述类型"),
                    _t(lang, "topic ids", "主题 ID"),
                    _t(lang, "triage score", "分诊分数"),
                ],
                rows,
            )
        )
    else:
        parts.append(_t(lang, "No important fact was missed.", "没有重要事实被漏掉。"))
    parts.append(
        "\n"
        + _t(
            lang,
            f"Missing behavior episodes: {', '.join(missing_behavior) or NONE[lang]}. "
            f"Self-impression kinds expected: "
            f"{', '.join(target['quality']['self_impression_expected_kinds']) or NONE[lang]}; "
            f"written: "
            f"{', '.join(target['quality']['self_impression_written_kinds']) or NONE[lang]}.",
            f"缺失行为场景：{', '.join(missing_behavior) or NONE[lang]}。"
            f"预期自我印象类型："
            f"{', '.join(target['quality']['self_impression_expected_kinds']) or NONE[lang]}；"
            f"实际写入："
            f"{', '.join(target['quality']['self_impression_written_kinds']) or NONE[lang]}。",
        )
    )

    # Recommendations --------------------------------------------------------
    parts.append(f"\n### {_t(lang, 'Recommendations', '后续建议')}\n")
    if lang == "en":
        parts.append(
            "1. Extend first-person/possessive triage coverage for the eight missed "
            "fact classes: `我对X过敏`, `搬到X`, `我的生日`, grandparent kinship, "
            "habit change (`戒烟/戒酒`), `我在X工作`, `我最好的朋友`, and "
            "stress/insomnia without a high-arousal keyword. Keep the triage pure and "
            "local; this issue does not change it.\n"
            "2. Decouple bot-behavior episode admission from user-memory triage, or add "
            "a behavior-first selection lane. One missed comfort reply reduced "
            "self-impression coverage from 1/1 to 0/1 because the impression requires "
            "three distinct episodes.\n"
            "3. Add a bounded pending policy: age-based escalation/re-triage or an "
            "explicit discard after N nights. The current Dream-only path keeps both "
            "low-value and labeled-important topics pending forever.\n"
            "4. Keep same-session batching. It produced the measured call and token "
            "reduction with zero duplicate regression and no observed output overflow "
            "on this corpus.\n"
            "5. Add a holdout corpus before tuning on these numbers; do not tune "
            "thresholds on the same 40 topics used for the report.\n"
            "6. Re-run this harness after every signal, batch or pending-policy change, "
            "and keep the `cc814ce` / `d9fc248` comparison in the results directory."
        )
    else:
        parts.append(
            "1. 补齐八类漏判事实的第一人称/所有格分诊覆盖：`我对X过敏`、`搬到X`、"
            "`我的生日`、祖辈亲属、习惯改变（`戒烟/戒酒`）、`我在X工作`、"
            "`我最好的朋友`，以及未命中高强度情绪词的压力/失眠。分诊保持纯本地；"
            "本 issue 不修改它。\n"
            "2. 将 bot 行为场景准入与用户记忆分诊解耦，或增加行为优先的选择通道。"
            "一条安慰回复被漏掉，就使自我印象覆盖从 1/1 降到 0/1，因为印象需要"
            "三个独立场景。\n"
            "3. 增加有界 pending 策略：按年龄升级/重新分诊，或在 N 晚后显式丢弃。"
            "当前 Dream-only 路径会让低价值和标注为重要的主题都永久 pending。\n"
            "4. 保留同会话批处理。在本语料上，它带来了实测的调用/token 下降，"
            "重复率没有回退，也没有观察到输出截断。\n"
            "5. 在按这些数字调参前增加 holdout 语料；不要用报告所用的同一批 40 个"
            "主题来调阈值。\n"
            "6. 每次修改信号、批处理或 pending 策略后重跑本评估，并在结果目录中"
            "保留 `cc814ce` / `d9fc248` 对比。"
        )

    # Generated result policy -------------------------------------------------
    parts.append(f"\n### {_t(lang, 'Generated result policy', '生成结果政策')}\n")
    policy_rows = [
        [
            "`benchmarks/results/dream_tradeoff.md`",
            _t(lang, "canonical human report; generated, do not hand-edit",
               "人类可读的规范报告；由脚本生成，不要手改"),
            _t(lang, "derived from the three JSON snapshots",
               "由三份 JSON 快照派生"),
        ],
        [
            "`benchmarks/results/dream_tradeoff.json`",
            _t(lang, "canonical aggregate (comparison + all targets)",
               "规范聚合结果（comparison + 全部目标）"),
            _t(lang, "rebuilt with the report", "随报告一起重建"),
        ],
        [
            "`benchmarks/results/dream_tradeoff_cc814ce.json`",
            _t(lang, "historical pre-optimization baseline", "优化前历史基线"),
            _t(lang, "immutable; re-record as a new dated file",
               "不可变；重录需新增带日期的文件"),
        ],
        [
            "`benchmarks/results/dream_tradeoff_d9fc248.json`",
            _t(lang, "historical merged implementation", "合并实现历史快照"),
            _t(lang, "immutable; re-record as a new dated file",
               "不可变；重录需新增带日期的文件"),
        ],
        [
            "`benchmarks/results/dream_tradeoff_current.json`",
            _t(lang, "snapshot of the current checkout", "当前 checkout 快照"),
            _t(lang, "regenerate after relevant changes", "相关变更后重新生成"),
        ],
        [
            "`benchmarks/data/dream_tradeoff_corpus.jsonl`",
            _t(lang, "frozen synthetic corpus", "冻结合成语料"),
            _t(lang, "change only with a new snapshot set and report",
               "变更时必须配套新的快照集和报告"),
        ],
    ]
    parts.append(
        table(
            [
                _t(lang, "file", "文件"),
                _t(lang, "role", "角色"),
                _t(lang, "expected to change", "是否预期变化"),
            ],
            policy_rows,
        )
    )
    parts.append(
        "\n"
        + _t(
            lang,
            "Regenerate only `dream_tradeoff_current.json` with `python benchmarks/dream_eval.py --repo . --label current --output benchmarks/results/dream_tradeoff_current.json`; then rebuild the aggregate and report from the three snapshots with `python benchmarks/dream_tradeoff.py --input cc814ce=benchmarks/results/dream_tradeoff_cc814ce.json --input d9fc248=benchmarks/results/dream_tradeoff_d9fc248.json --input current=benchmarks/results/dream_tradeoff_current.json --baseline cc814ce --target-label d9fc248 --output-json benchmarks/results/dream_tradeoff.json --output-md benchmarks/results/dream_tradeoff.md`. Do not regenerate `cc814ce`/`d9fc248` in place. Detailed policy: `benchmarks/results/README.md`.",
            "仅 `dream_tradeoff_current.json` 预期随当前树变化，用 `python benchmarks/dream_eval.py --repo . --label current --output benchmarks/results/dream_tradeoff_current.json` 重新生成；再基于三份快照用 `python benchmarks/dream_tradeoff.py --input cc814ce=benchmarks/results/dream_tradeoff_cc814ce.json --input d9fc248=benchmarks/results/dream_tradeoff_d9fc248.json --input current=benchmarks/results/dream_tradeoff_current.json --baseline cc814ce --target-label d9fc248 --output-json benchmarks/results/dream_tradeoff.json --output-md benchmarks/results/dream_tradeoff.md` 重建聚合与报告。不要原地重生成 `cc814ce` / `d9fc248`。详细政策见 `benchmarks/results/README.md`。",
        )
    )

    # Limitations ------------------------------------------------------------
    parts.append(f"\n### {_t(lang, 'Limitations', '限制')}\n")
    if lang == "en":
        parts.append(
            "- The corpus is hand-authored and synthetic (40 topics); it is not a "
            "representative sample of real users, languages or group dynamics.\n"
            "- The fake provider returns pre-recorded extraction items. Parse errors, "
            "schema failures, provider variance and true model hallucination are out of "
            "scope. 'False memory' here means artifacts produced from labeled "
            "low-value chatter, not a measurement of model hallucination.\n"
            "- Token usage is a character-based estimate, not provider-reported; "
            "`usage_cached` is zero because no prefix cache is simulated.\n"
            "- No live AstrBot host is started; host-layer tests remain skipped in CI "
            "shells.\n"
            "- One deterministic clock and one run per target; no sampling or "
            "confidence interval is reported.\n"
            "- The committed snapshots were produced on `win32` (`environment.platform=win32`). That field is historical provenance, not a "
            "cross-platform assertion; the in-memory store, fixed clock and "
            "deterministic provider keep the counts platform-independent.\n"
            "- `d9fc248` and the current tree share the same production extraction "
            "code, so their identical metrics validate the harness rather than a new "
            "production change.\n"
            "- `cc814ce` predates the triage and budget parameters. The harness filters "
            "unsupported kwargs and runs the same production `DreamCycle -> flush` "
            "path without triage; this is the only adaptation."
        )
    else:
        parts.append(
            "- 语料为手工编写的合成数据（40 个主题），不能代表真实用户、语言或群聊动态。\n"
            "- fake provider 返回预记录的抽取结果。解析错误、schema 失败、provider 波动和"
            "真实模型幻觉不在范围内。这里的“错误记忆”指由标注为低价值闲聊产生的 Artifact，"
            "不是对模型幻觉的测量。\n"
            "- token 用量是基于字符的估算，不是 provider 上报值；由于没有模拟前缀缓存，"
            "`usage_cached` 为零。\n"
            "- 不启动真实 AstrBot host；host 层测试在 CI shell 中仍会跳过。\n"
            "- 每个目标使用一个确定性时钟和一次运行；不做采样，也不报告置信区间。\n"
            "- 已提交快照在 `win32` 生成（`environment.platform=win32`）。该字段是历史来源，"
            "不是跨平台断言；内存存储、固定时钟和确定性 provider 使计数与平台无关。\n"
            "- `d9fc248` 与当前工作树共享同一套生产抽取代码，因此指标相同；这说明评估器"
            "可复现，而不是新的生产变更。\n"
            "- `cc814ce` 早于分诊和预算参数。评估器过滤不支持的参数，仍走同一条生产 "
            "`DreamCycle -> flush` 路径，只是不启用分诊；这是唯一适配。"
        )

    # Reproduction -----------------------------------------------------------
    parts.append(f"\n### {_t(lang, 'Reproduction', '复现方式')}\n")
    parts.append(
        "```bash\n"
        "python benchmarks/dream_eval.py --repo . --label current \\\n"
        "  --output benchmarks/results/dream_tradeoff_current.json\n\n"
        "python benchmarks/dream_tradeoff.py \\\n"
        "  --target cc814ce=/path/to/cc814ce \\\n"
        "  --target d9fc248=/path/to/d9fc248 \\\n"
        "  --target current=. \\\n"
        "  --output-json benchmarks/results/dream_tradeoff.json \\\n"
        "  --output-md benchmarks/results/dream_tradeoff.md\n"
        "```"
    )

    return "\n".join(parts)


def render_report(
    results: dict[str, dict[str, Any]],
    *,
    baseline_label: str,
    target_label: str,
    corpus_path: Path,
) -> str:
    labels = list(results)
    if baseline_label not in results:
        raise KeyError(f"unknown baseline label: {baseline_label}")
    if target_label not in results:
        raise KeyError(f"unknown target label: {target_label}")
    header = "# Dream triage tradeoff evaluation"
    zh_header = "### Dream 分诊权衡评估"
    english = _render_body(
        "en", results, labels, baseline_label, target_label, corpus_path
    )
    chinese = _render_body(
        "zh", results, labels, baseline_label, target_label, corpus_path
    )
    return (
        f"{header}\n\n"
        f"Generated by `benchmarks/dream_tradeoff.py` from content-free JSON "
        f"snapshots. Corpus: `{corpus_path.name}`. No live model call, no "
        f"production chat content.\n\n"
        f"{english}\n\n"
        f"---\n\n"
        f"## Chinese translation\n\n"
        f"{zh_header}\n\n"
        f"由 `benchmarks/dream_tradeoff.py` 从无正文 JSON 快照生成。语料："
        f"`{corpus_path.name}`。没有真实模型调用，也没有生产聊天正文。\n\n"
        f"{chinese}\n"
    )


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_target(
    label: str,
    repo: str,
    *,
    corpus: Path,
    backlog_days: int,
    timeout: int = 600,
) -> dict[str, Any]:
    """Run one checkout in its own interpreter and return its JSON report."""
    work = Path(tempfile.mkdtemp(prefix="seekmemory-tradeoff-"))
    output = work / "report.json"
    log = work / "child.log"
    command = [
        sys.executable,
        str(HERE / "dream_eval.py"),
        "--repo",
        str(repo),
        "--label",
        label,
        "--corpus",
        str(corpus),
        "--backlog-days",
        str(backlog_days),
        "--output",
        str(output),
    ]
    try:
        with log.open("w", encoding="utf-8") as handle:
            completed = subprocess.run(
                command,
                cwd=str(ROOT),
                stdout=subprocess.DEVNULL,
                stderr=handle,
                env=_child_env(),
                timeout=timeout,
            )
        if completed.returncode != 0 or not output.exists():
            tail = log.read_text(encoding="utf-8", errors="replace")[-2000:]
            raise RuntimeError(
                f"evaluation for {label} failed with {completed.returncode}:\n{tail}"
            )
        return json.loads(output.read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _parse_pairs(values: list[str], kind: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for value in values:
        if "=" not in value:
            raise SystemExit(f"{kind} must be label=path, got: {value}")
        label, path = value.split("=", 1)
        if not label or not path:
            raise SystemExit(f"{kind} must be label=path, got: {value}")
        pairs.append((label, path))
    return pairs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target", action="append", default=[], metavar="LABEL=PATH",
        help="checkout to evaluate (repeatable)",
    )
    parser.add_argument(
        "--input", action="append", default=[], metavar="LABEL=JSON",
        help="use an existing JSON snapshot instead of running",
    )
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--backlog-days", type=int, default=3)
    parser.add_argument("--baseline", default="")
    parser.add_argument("--target-label", default="")
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS))
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args(argv)

    corpus = Path(args.corpus).resolve()
    results: dict[str, dict[str, Any]] = {}
    if args.input and args.target:
        raise SystemExit("use either --input or --target, not both")
    if args.input:
        for label, path in _parse_pairs(args.input, "--input"):
            results[label] = json.loads(Path(path).read_text(encoding="utf-8"))
    elif args.target:
        targets = _parse_pairs(args.target, "--target")
        results_dir = Path(args.results_dir)
        results_dir.mkdir(parents=True, exist_ok=True)
        for label, repo in targets:
            report = run_target(
                label,
                repo,
                corpus=corpus,
                backlog_days=args.backlog_days,
                timeout=args.timeout,
            )
            results[label] = report
            target_path = results_dir / f"dream_tradeoff_{safe_label(label)}.json"
            target_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    else:
        raise SystemExit("provide --target LABEL=PATH or --input LABEL=JSON")

    labels = list(results)
    baseline_label = args.baseline or labels[0]
    target_label = args.target_label or labels[-1]
    comparison = compare_target(results[baseline_label], results[target_label])
    combined = {
        "schema": REPORT_SCHEMA,
        "baseline": baseline_label,
        "target": target_label,
        "comparison": comparison,
        "corpus": results[target_label]["corpus"],
        "results": results,
    }
    output_json = Path(
        args.output_json or (Path(args.results_dir) / "dream_tradeoff.json")
    )
    output_md = Path(
        args.output_md or (Path(args.results_dir) / "dream_tradeoff.md")
    )
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(combined, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    output_md.write_text(
        render_report(
            results,
            baseline_label=baseline_label,
            target_label=target_label,
            corpus_path=corpus,
        ),
        encoding="utf-8",
    )
    print(
        f"{target_label} vs {baseline_label}: {comparison['verdict']} "
        f"(calls -{pct(comparison['call_reduction'])}, "
        f"tokens -{pct(comparison['token_reduction'])})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
