"""黄金集与消融数据：20 条人工标注问答 + 一份 90% 是闲聊的记忆池。

黄金集代表「理想记忆系统应该召回什么」：六类能力各给若干题，其中
「事实·跨表述」故意与记忆正文零二元组重合，「边界」题正确行为是
什么都不注入。数据全部本地生成，固定种子可复现，噪声用模板闲聊
堆到 90% 以上，避免「池子里只有标准答案」把命中率吹高。
"""

from __future__ import annotations

import random
from dataclasses import dataclass

TODAY = 30          # 数据最后一天；日期按「今天 - (30 - day)」回推
NOISE_N = 216       # 模板闲聊条数
SEED = 20261021

# 噪声里刻意不出现的词：一旦出现就会制造假命中
BANNED = (
    "吕宇轩", "bangbang", "量化", "架构师", "杭州", "原神", "团子",
    "万兴", "offer", "凌晨两点", "火锅", "领导", "睡不着", "倔",
    "心软", "小美", "面试", "加班", "请我", "朋友", "猫",
)


@dataclass(frozen=True)
class Mem:
    """一条待写入记忆池的消息；noise=True 表示模板闲聊（不计入黄金集）。"""

    day: int
    text: str
    level: str = "detail"
    tags: tuple[str, ...] = ()
    weight: float = 0.8
    arousal: float = 0.2
    valence: float = 0.0
    scope: str = "private"
    noise: bool = False


# ---------------- 黄金相关 20 条（含重复表述与 2 条正向干扰） ----------------
GOLD_MEMS: tuple[Mem, ...] = (
    # 稳定事实：名字/目标/家乡/游戏/宠物，职业单独作为「跨表述」题
    Mem(1, "他叫吕宇轩，也叫BangBang", "fact", ("名字", "称呼"), 1.8, .2, .3),
    Mem(19, "他叫吕宇轩，也叫BangBang", "fact", ("名字", "称呼"), 1.8, .2, .3),
    Mem(1, "他在做量化交易项目", "fact", ("工作", "项目"), 2.1, .2, .2),
    Mem(17, "他在做量化交易项目", "fact", ("工作", "项目"), 2.1, .2, .2),
    Mem(2, "他想成为核心架构师", "fact", ("职业", "目标"), 1.7, .4, .4),
    Mem(3, "他是杭州人", "fact", ("家乡", "哪里"), 1.3, .1, .2),
    Mem(9, "他很喜欢原神，抽卡抽空了", "fact", ("游戏", "原神"), 1.25, .5, .1),
    Mem(12, "他养了一只叫团子的猫", "fact", ("宠物", "猫"), 1.35, .3, .4),
    # 事件：面试、加班、请客
    Mem(18, "他去万兴科技面试了", "scene", ("面试", "工作"), 1.3, .7, .2),
    Mem(26, "万兴那边给他发了offer，他过了", "scene", ("offer", "工作"), .85, .9, .8),
    Mem(24, "他加班到凌晨两点才回家", "scene", ("加班", "工作"), 1.25, .8, -.5),
    Mem(22, "他请我吃火锅", "detail", ("吃饭", "火锅"), 1.0, .6, .7),
    # 情绪低潮 + 两条「看起来状态不错」的干扰
    Mem(23, "最近被领导骂了，整个人很低落", "scene", ("心情", "情绪", "工作"), 1.2, .9, -.8),
    Mem(24, "晚上老是睡不着，白天没精神", "detail", ("状态", "睡眠"), 1.15, .8, -.6),
    Mem(6, "周末去爬山，状态特别好", "detail", ("状态", "运动"), 1.35, .7, .8),
    Mem(20, "这几天项目收尾，天天熬夜但还挺兴奋", "detail", ("状态", "工作"), 1.25, .7, .1),
    # 印象层：高权重、低字面
    Mem(27, "他有点倔，嘴上不饶人，但真有事会帮", "impression", ("印象", "性格", "觉得"), 2.0, .5, .4),
    Mem(27, "他心软，见不得别人难受", "impression", ("印象", "性格"), 1.7, .5, .3),
    # 边界：别人的秘密（shadow），以及一条短期琐事
    Mem(25, "朋友偷偷喜欢小美，这事别往外说", "detail", ("秘密", "朋友"), 1.0, .7, .0, "shadow"),
    Mem(23, "他问今天几号", "detail", ("琐事",), .3, .0, .0),
)

# 20 条黄金问答：18 条可答 + 2 条边界，覆盖事实、跨表述、事件、情绪、印象、边界。
GOLD: tuple[dict, ...] = (
    # ---- 事实 ----
    {"q": "你还记得我叫什么名字吗", "expect_any": ["吕宇轩"], "expect_level": "fact",
     "note": "事实｜问句与正文零字面重合，只能靠标签「名字」"},
    {"q": "我是干什么的", "expect_any": ["量化交易"], "expect_level": "fact",
     "note": "事实·跨表述｜与问句零字面重合，标签也不命中，只能靠权重先验"},
    {"q": "我的职业目标是什么", "expect_any": ["架构师"], "expect_level": "fact",
     "note": "事实｜标签「职业」「目标」双命中"},
    {"q": "我是哪里人", "expect_any": ["杭州"], "expect_level": "fact",
     "note": "事实｜低权重事实，靠标签「哪里」"},
    {"q": "我平时玩什么游戏", "expect_any": ["原神"], "expect_level": "fact",
     "note": "事实｜标签「游戏」"},
    {"q": "我养了什么宠物", "expect_any": ["团子", "猫"], "expect_level": "fact",
     "note": "事实｜标签「宠物」，正文只说「团子」"},
    # ---- 事件 ----
    {"q": "上次面试结果怎么样", "expect_any": ["offer", "过了"], "expect_level": "scene",
     "note": "事件｜结果记忆与问句零字面重合，靠「面试」种子沿 causal 边扩散"},
    {"q": "我面试了哪家公司", "expect_any": ["万兴"], "expect_level": "scene",
     "note": "事件｜字面「面试」直接命中"},
    {"q": "我上次加班到几点", "expect_any": ["凌晨两点", "两点"], "expect_level": "scene",
     "note": "事件｜字面「加班」"},
    {"q": "上次请我吃什么", "expect_any": ["火锅"], "expect_level": "scene",
     "note": "事件｜字面「请我」，低权重靠重合度进榜"},
    # ---- 情绪 ----
    {"q": "我最近状态怎么样", "expect_any": ["领导"], "expect_level": "scene",
     "note": "情绪｜「状态」标签把正向干扰也带进来，要压过它"},
    {"q": "我的睡眠怎么样", "expect_any": ["睡不着"], "expect_level": "detail",
     "note": "情绪｜标签「睡眠」，字面只说「睡」"},
    {"q": "我最近是不是很累", "expect_any": ["睡不着"], "expect_level": "detail",
     "note": "情绪｜问句含负向词「累」，高唤醒负效价记忆应被抬高"},
    {"q": "我最近心情很差", "expect_any": ["领导"], "expect_level": "scene",
     "note": "情绪｜标签「心情」+字面「最近」，与正向干扰竞争"},
    # ---- 印象 ----
    {"q": "你觉得我这个人怎么样", "expect_any": ["倔", "心软"], "expect_level": "impression",
     "note": "印象｜标签「觉得」，两条印象层应一起进榜"},
    {"q": "我性格上有什么毛病", "expect_any": ["倔"], "expect_level": "impression",
     "note": "印象｜标签「性格」，问法换了但指向同一层"},
    {"q": "我是不是嘴硬心软", "expect_any": ["心软"], "expect_level": "impression",
     "note": "印象｜问句自带「心软」，考字面与印象层的呼应"},
    {"q": "你最了解我什么", "expect_any": ["倔", "心软"], "expect_level": "impression",
     "note": "印象｜完全开放，零字面零标签，只能靠印象权重"},
    # ---- 边界 ----
    {"q": "我朋友是不是喜欢小美", "expect_any": [], "expect_level": "none",
     "note": "边界｜别人的秘密，正确行为是返回空"},
    {"q": "今天几号", "expect_any": [], "expect_level": "none",
     "note": "边界｜短期琐事，不该动用长期记忆"},
)

# 边界题里一旦出现就算越界泄露的词
FORBIDDEN = {"我朋友是不是喜欢小美": ("小美", "偷偷喜欢")}

NOISE_TPL = (
    "他今天{}", "他下午在弄{}", "他晚上{}", "他说{}有点麻烦",
    "他问{}要不要改", "他把{}弄完了", "他吐槽{}太慢", "他刚看完{}的文档",
    "他下午要跟产品对齐{}", "他早上在处理{}", "他晚上还在改{}",
    "他中午吃饭时聊到{}", "他今天被{}卡住了", "他明天要交{}",
)
NOISE_WORDS = (
    "项目", "数据库", "接口", "部署", "文档", "测试", "会议", "报表",
    "脚本", "配置", "调度", "缓存", "索引", "图表", "日志", "告警",
    "备份", "迁移", "权限", "监控", "联调", "发版", "需求", "排期",
)
# 几条反复出现、看起来很重要但和黄金集无关的闲聊：用来验去重
NOISE_DUP = (
    (20, "项目明天要发版，他很紧张", 1.45),
    (21, "项目明天要发版，他很紧张", 1.45),
    (22, "项目明天要发版，他很紧张", 1.45),
    (19, "接口又挂了，联调了一下午", 1.35),
    (20, "接口又挂了，联调了一下午", 1.35),
)


def _noise(rng: random.Random) -> list[Mem]:
    """模板闲聊：随机主语/动词/宾语，权重多为 0.35~1.05，少量像正事。"""
    out: list[Mem] = []
    for i in range(NOISE_N):
        text = rng.choice(NOISE_TPL).format(rng.choice(NOISE_WORDS))
        weight = rng.uniform(0.35, 1.05)
        if rng.random() < 0.12:
            weight = rng.uniform(1.15, 1.45)
        out.append(Mem(rng.randint(1, TODAY), text, "detail", ("日常",),
                       round(weight, 2), round(rng.uniform(0, .4), 2),
                       round(rng.uniform(-.2, .3), 2), noise=True))
    for day, text, weight in NOISE_DUP:
        out.append(Mem(day, text, "detail", ("日常",), weight, .35, -.1, noise=True))
    return out


def build(seed: int = SEED) -> list[Mem]:
    """返回固定种子的记忆池；断言噪声占比 > 80%，并检查没有禁用词。"""
    mems = list(GOLD_MEMS) + _noise(random.Random(seed))
    noise = sum(1 for m in mems if m.noise)
    assert noise / len(mems) > 0.8, f"噪声占比只有 {noise}/{len(mems)}"
    for m in mems:
        if m.noise:
            low = m.text.lower()
            hit = [w for w in BANNED if w in low]
            assert not hit, f"噪声里混进了关键词 {hit}：{m.text}"
    return mems


def noise_share(mems: list[Mem]) -> float:
    """模板闲聊条数占比，写进报告头部。"""
    return sum(1 for m in mems if m.noise) / max(len(mems), 1)
