# perceive · 感知

## 职责

把“当天聊了什么”变成“值得记住的印象”。

`extract.py` 负责一次模型调用的两端：`build_prompt` 给出“抽印象而不是抽事实清单”的提示词，`parse_response` 安全解析模型返回的 JSON 数组；`filter_duplicates` 在写入前做字面去重。`compress.py` 提供更省 token 的三行摘要（情绪 / 未完成 / 事实），用于短期缓冲的冷压缩。这里不建 Artifact、不碰数据库，也不决定写不写。

## 对外接口

```python
from perceive.extract import build_prompt, parse_response, filter_duplicates
from perceive.compress import build_compress_prompt, parse_compress

prompt = build_prompt(["用户：今天又加班", "她：你最近好累"])
items = parse_response(model_text)          # list[dict]，失败返回 []
items = filter_duplicates(items, existing_texts)

prompt = build_compress_prompt(dialogue)
summary = parse_compress(model_text)
# {"emotion": "累", "unfinished": "还在等面试结果", "facts": ["他在做量化"]}
```

`parse_response` 只保证返回 `list[dict]`，不替模型补字段；空文本、坏 JSON、被 Markdown 包裹的 JSON 都不会抛异常。去重使用规范化后的字面文本（去空白/标点、小写），批次内与已有记忆一起查重。

## 约定

- 只依赖标准库，不 import `core` / `store`，保持纯函数、可单测。
- 提示词里明确层级：`impression` 印象 → `scene` 场景 → `detail` 细节；不按“事实/偏好/事件”分类。
- 宁可少抽，不要抽碎；模型没有值得记的内容时应返回 `[]`。
- 三行压缩的键固定为英文 `emotion` / `unfinished` / `facts`，事实最多两条，`无` 归一成空值。
