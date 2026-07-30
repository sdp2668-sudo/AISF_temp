---
title: 两个 LLM API 的 Intent Segment 划分质量比较
type: topic
tags:
  - llm-evaluation
  - badcase
  - mature
sources:
  - "/Users/derrick92/.codex/sessions/2026/07/28/rollout-2026-07-28T16-18-15-019fa7cd-92a2-7eb3-80b5-ccf422655447.jsonl"
created: 2026-07-29
updated: 2026-07-29
summary: 在固定 episode 的前提下，逐 episode 比较两个 LLM API 的 segment 数量和意图切换边界，再由人工复核差异样本。
---

# 两个 LLM API 的 Intent Segment 划分质量比较

## 概述

比较两个模型的 segment 划分质量时，要把 **episode 划分**和 **episode 内的 segment 划分**分开：

- episode 由代码根据时间间隔确定性切分。
- segment 由 LLM 在每个 episode 内按用户意图切分。
- 因此两个模型必须使用相同输入和相同 episode 参数，再逐 episode 比较 segment。

第一版采用轻量方案：**代码自动粗筛近似一致的 episode，只把有明显差异的 episode 交给人工复核。**

> [!important] 结论边界
> 自动粗筛只能衡量候选模型与 baseline 有多接近，不能证明 baseline 或候选模型绝对正确。真正的质量结论仍来自差异样本的人工判断和少量人工明确边界的 case。

## 比较对象

假设一个 episode 覆盖第 1～10 轮，模型输出 3 个 segment：

```text
Segment 1：1～3
Segment 2：4～7
Segment 3：8～10
```

真正的意图切换边界是：

```text
[3, 7]
```

最后一个 segment 的 `endTurn = 10` 只是 episode 结束位置，不表示发生了意图切换，所以不参与比较。

由此可得：

```text
边界数量 = segment 数量 - 1
```

## 第一版自动粗筛规则

对同一个 episode 的 baseline 和 candidate 依次判断：

1. 两个模型的 segment 数量是否相同。
2. 如果相同，提取除最后一个 segment 外的所有 `endTurn`。
3. 按顺序比较对应边界，每个边界偏移是否不超过 1 轮。
4. 全部满足则标记为“近似一致”；否则标记为“需要人工复核”。

可以把规则写成：

```text
baseline boundaries = [b1, b2, ..., bn]
candidate boundaries = [c1, c2, ..., cn]

近似一致条件：
1. baseline segment count == candidate segment count
2. 对每个 i，都有 |bi - ci| <= 1
```

其中“允许偏移 1 轮”是首版粗筛参数，不是 segment 质量的客观定律。若业务中一轮偏移就会改变完整意图，应把容差调整为 0。

## 示例

### 近似一致

```text
Baseline：1～3、4～7、8～10
边界：[3, 7]

Candidate：1～4、5～8、9～10
边界：[4, 8]
```

两个模型都是 3 个 segment，并且两个边界都只偏移 1 轮，因此通过自动粗筛。

### 需要人工复核

```text
Baseline：1～3、4～7、8～10
边界：[3, 7]

Candidate：1～4、5～10
边界：[4]
```

Candidate 只有 2 个 segment，可能合并了两个不同意图，也可能是 Baseline 过度切分。自动规则不能判断谁正确，因此交给人工。

## 端到端评估流程

```text
固定同一批 session、prompt、工具、模型参数和 episode 切分参数
  ↓
分别调用 baseline API 和 candidate API
  ↓
按 session + episodeId 对齐结果
  ↓
提取每个 episode 内的意图切换边界
  ↓
自动粗筛：segment 数量相同且对应边界偏移不超过 1 轮
  ↓
近似一致 → 记入一致统计
存在差异 → 隐藏模型名后交给人工复核
```

首轮可选 20～30 个代表性 episode，覆盖：

- 长对话。
- 连续追问和澄清。
- 噪声或 ASR 错误。
- 多意图切换。
- 容易过度切分或错误合并的边界案例。

## 人工复核如何判断

人工只看差异 episode，并在隐藏模型名的情况下判断：

- `candidate 更好`：切出的每段更接近一个完整意图。
- `两者相同`：边界差异不影响完整意图。
- `candidate 更差`：出现明显错误合并、过度切分或边界错位。

建议额外准备至少 5 个由人工事先写明正确边界的典型 case，防止两个模型在同一位置共同犯错。

`intentSummary` 可以用于抽查 segment 的语义是否完整，但不应作为主要质量指标；主要指标仍是 segment 边界是否合理。

## 统计指标

| 指标 | 计算或含义 |
| --- | --- |
| 可比较 episode 数 | 两个模型都成功返回结果的 episode 数 |
| 近似一致率 | 通过自动粗筛的 episode 数 / 可比较 episode 数 |
| 人工复核率 | 自动粗筛未通过的 episode 数 / 可比较 episode 数 |
| Candidate 更好/相同/更差 | 对差异 episode 的盲评结果 |
| 失败数 | API 错误、超时或无有效输出的次数 |
| p50 / p95 耗时 | 完整 segment runner 的端到端延迟分位数 |

速度和质量要分开报告。每个模型对同一 episode 重复运行多次，再报告 p50、p95 和失败数；不要用单次耗时或平均值下结论。

## 最终决策表

| 模型 | 近似一致率 | 需人工复核 | 更好 | 更差 | p50 | p95 | 失败数 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline | 基准 | - | - | - | 待测 | 待测 | 待测 |
| Candidate | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 |

模型切换的判断顺序是：

1. 先确认 Candidate 没有在关键案例类型上集中退化。
2. 再看人工复核中的“更差”案例是否可接受。
3. 最后比较 p95、吞吐、失败数和成本。

## 与回复相关性评估的边界

本主题判断的是“对话应该在哪里切成完整意图片段”。[[llm-response-relevance-evaluation]] 判断的是“切分完成后，AI 回复是否回应或推进了片段中的意图”。前者是后者的上游地基，不能用回复相关性结果替代 segment 划分质量。

该问题也是 [[eval-agent现状盘点与架构对齐]] 中“意图实例切分必须配独立质量复核”的具体落地方式。

## 结论

第一版不需要先建设完整 gold set。先固定 episode，逐 episode 比较两个模型的 segment 数量和边界；近似一致的自动通过，有差异的只做小规模盲评人工复核。这样既能快速判断候选模型与现有 baseline 的差距，又不会把 baseline 错当成真实答案。

## 参考源

- Codex 会话《评估API模型切换》，Session ID：`019fa7cd-92a2-7eb3-80b5-ccf422655447`，2026-07-28。
- [[llm-response-relevance-evaluation]]：已切分意图片段上的回复相关性判定协议。
- [[eval-agent现状盘点与架构对齐]]：segment 是下游评估的基础单元，需要独立质量复核。
