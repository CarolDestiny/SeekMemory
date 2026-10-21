# 变更记录

## 0.1.0 — 2026-10-21

首个可用版本。作为 AstrBot 插件接入 QQ，记忆链路端到端跑通。

### 记忆

- **Artifact 模型**：10 字段公共头（id / family / revision / state / scope / lineage /
  strength / time / said_by / shareable）+ 类型化 payload；六个 family（memory / example /
  persona / media / secret / designated）；记忆分 fact / scene / detail / impression 四级。
- **遗忘曲线**：`R = e^(−t/S)`，`S` 由基准天数、权重、命中次数、形态、情绪共同决定；
  定时衰减，重要记忆留下、琐事忘掉。
- **检索打分**：字面重合、标签、情绪、权重、新鲜度五维 + 激活扩散，减去近期已用与过热惩罚，
  留 10% 随机探索。大库下走倒排二元组索引，实测 10ms 量级。
- **相关性闸门**：只认相关性证据（字面 / 标签 / 情绪 / 激活），权重与新鲜度只参与排序、
  不能单独让一条记忆过门；不相关就返回空。检索层噪声 81% → 40%。
- **常驻层**：人格与印象层固定注入（38 字/轮），不经过闸门——「你觉得我这个人怎么样」
  这类零字面问题靠它接住。
- **组装**：头（人格 / 印象 / 最相关）/ 中（摘要 / 事实 / 例子）/ 尾（最近两轮），
  按预算裁剪并在标点处截断，防 lost-in-the-middle。
- **写入侧建边**：同 scope 相似度建 similar 边、同日建 temporal 边，出度上限 5，fail-open。
- **人格沉淀**：每周把稳定的 impression 拼成第二人称 persona，旧版本标 merged，写账本。
- **scope 隔离**：private 只给归属会话，shared 全放，shadow 只输出遮蔽句；指定记忆
  三条硬条件（私聊、触发词、未给过）才交付正文。

### 存储与审计

- 内容寻址 blob（sha256）、不可变修订、哈希链账本（`self_hash = sha256(prev + payload)[:16]`）。
- 只有 `store/db.py` 写 SQL；`core/` 不依赖上层；全链路 fail-open。

### 评测

- `run.py` 像人指数 100/100（已饱和，见 ISSUE-0019）、1000 条记忆压缩 850×。
- `scale.py` 8 用户 / 60 天 / 2400 条：每轮 13 字、232×、召回 5/6。
- `ablation.py` 组件消融 + `no_gate` 对照。
- `large_e2e.py` 6 种人格画像 × 180 天 × 31,926 条消息 × 60 题 × 4 策略，固定
  `deepseek-flash` / temperature=0：SeekMemory 命中 49/60、人味 4.27，关键词基线 42/60，
  全量注入 24/60。等效 token 约为全量注入的 1/7，比关键词基线贵 6%。

### 已知限制

- 零字面同义问法召回不了（无 BM25 / 向量检索，见 ISSUE-0001）。
- 静态黄金集已饱和，难任务集待建（ISSUE-0019）。
- 缓冲层、三档不确定措辞、反思接线、容量治理第三级以后仍未完成（ISSUE-0002 / 0015 / 0014 / 0010）。
