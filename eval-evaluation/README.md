# eval-evaluation

独立的 Qwen 与 DeepSeek Segment 划分质量评估工具。它不会调用模型，也不会修改 `eval-python`；每次执行只读取一份 Qwen `run` 结果 JSON 和一份 DeepSeek 标注 XLSX。

## 安装

```powershell
cd D:\AISF\AISF_0729_segment\eval-evaluation
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

## 运行

每次必须显式提供输入与输出路径，程序不包含固定样例路径：

```powershell
python -m eval_evaluation evaluate `
  --qwen-json <Qwen-run-result.json> `
  --deepseek-xlsx <DeepSeek-label.xlsx> `
  --output-dir <result-directory>
```

可选参数：

```text
--deepseek-sheet <worksheet-name>  默认第一个工作表
--loose-tolerance <int>            宽松边界容差，默认 1 个有效 Turn
```

输出目录不存在时会自动创建；同名结果已存在时，程序拒绝覆盖。

## 输入格式

Qwen 输入必须是 `eval-python run` 输出的完整 JSON。工具使用其中的 `sessions -> episodes -> segments -> turns` 层级、Episode 状态、过滤记录和运行错误。

DeepSeek 输入必须是扁平 XLSX，数据表至少应包含：

```text
session_id, episode_id, segment_id, turn_index, human, ai
```

与 Qwen `run` XLSX 的 `sessions` 表相同的 13 列格式可直接使用。DeepSeek XLSX 是参考标注；Qwen JSON 是 Qwen 的实际运行事实。Qwen XLSX 适用于人工并排复核，不参与自动质量计算。

## 输出

每次运行生成：

```text
<qwen-json-stem>__segment_evaluation.json
<qwen-json-stem>__segment_evaluation.xlsx
```

JSON 保存完整、可机器复算的评估结果：来源、评估参数、Qwen 运行可观测性、全局汇总、未对齐 Episode 和全量 Episode 明细。

XLSX 包含五个工作表：

| 工作表 | 内容 |
| --- | --- |
| `summary` | 严格/宽松的 Micro、Macro 指标和 Episode 分类分布。 |
| `episode_metrics` | 每个可比较 Episode 的数量差、TP/FP/FN、P/R/F1 和分类。 |
| `boundary_comparison` | 每个严格/宽松边界匹配、FP、FN 与偏移量。 |
| `turn_review` | 每个可比较 Episode 的逐 Turn 文本、两侧 Segment 和边界标记。 |
| `run_observability` | Qwen 运行汇总、过滤项、失败 Session、错误和未对齐 Episode。 |

## 指标解释

每个 Episode 内，非最后一个 Segment 的结束位置表示一个边界，即“这一轮之后是否应开始新的 Segment”。

```text
TP：Qwen 与 DeepSeek 成功一对一匹配的边界。
FP：Qwen 存在但 DeepSeek 未匹配的边界，通常表示 Qwen 多切。
FN：DeepSeek 存在但 Qwen 未匹配的边界，通常表示 Qwen 漏切。
Precision = TP / (TP + FP)
Recall    = TP / (TP + FN)
F1        = 2PR / (P + R)
```

严格指标只认可同一 Turn 缝隙上的边界；宽松指标允许前后偏移 `--loose-tolerance` 个有效 Turn。两套指标分别报告，不会混合。

```text
Precision 低：Qwen 多切偏多，Segment 可能过碎。
Recall 低：Qwen 漏切偏多，不同意图可能被合并。
严格 F1 低、宽松 F1 高：总体边界相近，但常发生一轮偏移。
Micro 高、Macro 低：很多短 Episode 有差异，但长 Episode 整体表现较好。
Macro 高、Micro 低：少数长 Episode 的边界差异严重。
```

`segment_delta = Qwen Segment 数 - DeepSeek Segment 数` 仅用于诊断净多切或净漏切，不作为边界评价的前置条件。DeepSeek 是比较参考，不是绝对真值；对于差异 Episode，应在 `turn_review` 中进行人工判断。

## 已知限制

当前 Qwen `run` 结果会在 Segment 阶段异常时按 Session 记录失败，不能可靠恢复该 Session 中每一个失败 Episode。因此工具报告 `sessions_failed`，但不会伪造失败 Episode 数或失败率。
