# Segment 划分质量评估工作流

## 目标与数据职责

本工作流评估 Qwen 与 DeepSeek 在多轮会话中“应该在哪里切开一个完整意图”的接近程度。它不评价业务分类、子功能或 AI 是否明确回复不支持。

| 文件 | 职责 |
| --- | --- |
| Qwen `run` JSON | 自动评估的 Qwen 运行事实：Episode/Segment 层级、状态、过滤和错误。 |
| DeepSeek XLSX | 边界比较参考：每个 Turn 所属 Episode 和 Segment。 |
| Qwen `run` XLSX | 人工复核时与 DeepSeek XLSX 并排查看。 |

DeepSeek 只是参考对象。自动指标衡量的是 Qwen 与 DeepSeek 的接近程度，最终的质量判断仍应由差异样本的人工复核完成。

## 为什么以 Episode 为最小单元

Episode 由时间间隔确定性划分，Segment 才由模型根据用户意图划分。因此先以 `session_id + start_turn + end_turn` 对齐 Episode。只有范围完全一致，且 Qwen `episode.status` 为 `succeeded` 的 Episode 才可比较。

Qwen 过滤 Episode、失败 Session、DeepSeek 缺失 Episode 或范围不一致 Episode 都要单列，但不进入边界质量分母。当前 Qwen `run` 输出不能精确恢复失败 Episode 数，只能可靠报告失败 Session 数。

## 从 Segment 到边界缝隙

一个 Episode 有 N 个 Turn 时，前 N-1 个 Turn 间的缝隙才是候选边界。每个非末尾 Segment 的结束 Turn 表示一个边界；Episode 最后一个 Turn 只是自然结束，不表示意图切换。

```text
Segment：1-3、4-7、8-10
边界：Turn 3 后、Turn 7 后
```

边界按 Episode 内有效 Turn 的排序位置比较，避免 `turn_index` 不连续时把编号差误判为轮次差。

## 严格与宽松的一对一匹配

严格模式的容差是 0：两侧必须在同一个缝隙切开。

宽松模式默认容差是 1：Qwen 边界可以与前后一个有效 Turn 的 DeepSeek 边界匹配。

匹配始终一对一、保序。一个 DeepSeek 边界已经匹配一个 Qwen 边界后，不能再抵消另一个 Qwen 的多切。宽松模式优先最大化匹配数量，再最小化总偏移，因此精确边界会优先匹配。

```text
TP：两侧匹配成功的边界。
FP：Qwen 未匹配边界，通常表示多切。
FN：DeepSeek 未匹配边界，通常表示漏切。
```

严格与宽松会分别计算 TP、FP、FN、Precision、Recall、F1。

## Episode 级与全局指标

每个 Episode 输出 Segment 数量差和两套 P/R/F1，并归类：

```text
严格一致：严格模式无 FP、无 FN。
仅宽松一致：严格不一致，但宽松模式无 FP、无 FN。
数量相同但明显错位：两侧 Segment 数相同，宽松模式仍有 FP 或 FN。
Qwen 净多切：Qwen Segment 数更多。
Qwen 净漏切：Qwen Segment 数更少。
```

`segment_delta` 用于说明问题形态，不能代替边界评价。相同的 Segment 数量并不代表边界位置正确；不同数量也不代表全部边界错误。

全局指标有两种聚合方式：

```text
Micro：先汇总所有 Episode 的 TP/FP/FN，再计算 P/R/F1；长 Episode 权重更大。
Macro：先计算每个 Episode 的 P/R/F1，再平均；每个 Episode 权重相同。
```

当 Micro 高而 Macro 低时，很多短 Episode 可能有差异；当 Macro 高而 Micro 低时，通常是少数长 Episode 差异严重。

## 人工复核

优先检查宽松模式仍不一致、FP/FN 较多、净多切、净漏切或 Episode 很长的案例。复核时应查看原始 Turn 和两侧边界，而不是仅看 Segment ID；结论可记录为“Qwen 更好、等价、Qwen 更差”。
