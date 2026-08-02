# 并发性能分析工具

本目录的 `analyze_concurrency.py` 用于汇总多个 `eval-python run` / `compare` 档位的 JSON 结果。它不调用 Qwen、不重新执行评测，也不修改原始结果。

## 输入

创建一个清单文件，例如 `experiments.json`：

```json
{
  "cases": [
    {"case": "c1_s1", "session_concurrency": 1, "segment_concurrency": 1, "repeat": 1,
     "run": "..\\output\\run_c1.json", "compare": "..\\output_compare\\compare_c1.json"},
    {"case": "c2_s2", "session_concurrency": 2, "segment_concurrency": 2, "repeat": 1,
     "run": "..\\output\\run_c2.json", "compare": "..\\output_compare\\compare_c2.json"}
  ]
}
```

`compare` 可省略；省略时只分析 `run` 性能指标。路径相对于执行命令的当前目录解释。

## 运行

在项目根目录执行：

```powershell
python concurrency\analyze_concurrency.py concurrency\experiments.json
```

也可以指定输出目录：

```powershell
python concurrency\analyze_concurrency.py concurrency\experiments.json --output-dir concurrency\results
```

## 输出参数

程序生成 `concurrency_analysis.json` 和 UTF-8-BOM 编码的 `concurrency_analysis.csv`。

- `total_elapsed_seconds`：run 顶层总耗时。
- `model_calls`：模型调用次数。
- `model_elapsed_seconds`：模型调用耗时总和。
- `retry_count`：逐条 `metrics[*].attempts - 1` 累加。
- `final_errors`：最终错误数。
- `sessions_succeeded` / `segments_succeeded`：成功数量。
- `session_completeness` / `segment_completeness`：成功数量除以总数量。
- `throughput_segments_per_second`：Segment 数除以总耗时。
- `boundary_diffs`、`segment_diffs`、`intent_diffs`、`business_diffs`、`sub_function_diffs`：来自 compare JSON 的差异计数。
- `diff_turn_rate`：`turns_with_any_diff / turns_union`，表示与基线存在任意差异的 Turn 比例。
- `error_rate`：最终错误数除以模型调用次数。

建议按 `session_concurrency` 和 `segment_concurrency` 逐档运行，重复 3 次，再用本工具汇总。最大稳定并发应结合 `final_errors=0`、完整率为 1，以及耗时/吞吐趋势判断；差异率反映与基线的差异，不单独等同于模型正确率。
