# Qwen 接口并发上限测试工具

本目录只保留最终需要的直接接口压测程序。它不会执行完整的 `eval-python run`，而是使用与 `eval-python` 相同的 OpenAI 兼容请求格式，直接并发调用 Qwen `/v1/chat/completions` 接口。程序逐档增加并发，达到失败停止条件后自动终止，用于快速寻找接口并发临界区间。

仅对已经获得压测授权的接口执行，避免影响其他使用者。

## 文件

- `qwen_load_test.py`：压测主程序，仅使用 Python 标准库。
- `config.example.json`：完整配置示例。
- `data.example.json`：中等长度测试数据示例。
- `README.md`：本文档。

目标电脑需要 Python 3.11 或更高版本，不需要安装第三方包，也不依赖 `eval-python`。

## 测试数据

默认配置直接读取：

```text
D:\AISF\AISF_0729_segment\eval-python\data\sessions_case.json
```

文件顶层必须是非空数组，支持以下格式。

简单字符串：

```json
["请分析这段中等长度的用户请求……"]
```

标准 Chat Completions 消息：

```json
[
  {
    "messages": [
      {"role": "system", "content": "你是文本分析助手。"},
      {"role": "user", "content": "请分析这段用户请求……"}
    ]
  }
]
```

可以直接读取 `eval-python run` 使用的 Session 数组。每个 Session 转换成一次接口请求，转换规则为：

```text
Session 1
  turns[0].human ┐
  turns[1].human ├─ 按原顺序拼成一条 user 消息
  turns[2].human ┘
```

生成的内容类似：

```text
Turn 1: 吃播美食吃播真的人。
Turn 2: 吃播真的人视频。
Turn 3: 明星吃播视频。
```

`ai`、`rewrite_query`、`timestamp` 等字段不会发送给模型。输入 Session 数少于当前并发时，程序会按顺序循环复用 Session。例如数据中有 2 个 Session、测试并发 20，则两个 Session 各被使用约 10 次。

当前 `sessions_case.json` 只有 2 个 Session（15 Turn 和 25 Turn），适合验证程序和快速摸底。正式并发上限测试建议使用同样格式但包含更多不同 Session 的数据，避免大量完全相同的请求受到模型服务缓存或重复负载特性的影响而使结果偏乐观。

这种转换用于直接接口压测，不会完整复现 `eval-python run` 的 Segment Agent 工具调用和多轮交互；它测试的是中等长度 Session 请求对接口形成的并发压力。

## 配置说明

编辑 `config.example.json`：

```json
{
  "endpoint": "http://9.15.87.94:1065/v1/chat/completions",
  "model": "Qwen3-32B",
  "api_key_env": null,
  "dataset_path": "D:\\AISF\\AISF_0729_segment\\eval-python\\data\\sessions_case.json",
  "system_prompt": "请分析以下多轮用户请求的主要意图，并返回简洁、明确的分析结果。",
  "temperature": 0.0,
  "enable_thinking": true,
  "max_tokens": 512,
  "verify_tls": false,
  "bypass_proxy": true,
  "timeout_seconds": 180,
  "concurrency_levels": [1, 5, 10, 20, 30, 40, 50],
  "requests_per_level": null,
  "repeats": 3,
  "failed_repeats_to_stop": 2,
  "warmup_requests": 5,
  "cooldown_seconds": 15,
  "stop_on_failure": true,
  "max_failure_rate": 0.0
}
```

- `endpoint`、`model`：目标 Qwen 接口和模型名。
- `dataset_path`：测试数据路径；相对路径以配置文件所在目录为基准。
- `system_prompt`：数据没有 system 消息时自动添加；空字符串表示不添加。
- `enable_thinking`：应与正式运行设置一致。
- `max_tokens`：限制最大输出长度；设为 `null` 时不发送该参数。
- `timeout_seconds`：单次请求最长等待时间。
- `concurrency_levels`：按顺序测试的同时 HTTP 请求数。
- `requests_per_level`：每个档位、每轮的请求总数。设为 `null` 时自动等于当前并发，即每档只发送一波请求；也可填固定整数进行持续压力测试，且不能小于当前并发。
- `repeats`：每个并发档位完整运行的轮数，当前为 3。
- `failed_repeats_to_stop`：多少轮超过失败率阈值后判定该并发档位超限，当前为 2，即采用“3 轮中至少 2 轮失败”的规则。
- `warmup_requests`：正式统计前的预热请求数。
- `cooldown_seconds`：两轮之间的冷却秒数。
- `stop_on_failure`：达到失败阈值后是否停止后续更高档位。
- `max_failure_rate`：单轮允许的最大失败率。`0.0` 表示任意请求失败就把该轮记为失败；`0.01` 表示该轮失败率超过 1% 才记为失败。是否停止升档仍由 `failed_repeats_to_stop` 判断。
- `api_key_env`：API 密钥所在的环境变量名称；接口无认证时为 `null`。

程序故意不重试失败请求，确保 429、5xx、连接错误和超时不会被隐藏。

## 运行方法

先在目标电脑做小规模冒烟测试：

```json
"concurrency_levels": [1, 2],
"requests_per_level": null,
"repeats": 3,
"failed_repeats_to_stop": 2
```

然后执行：

```powershell
cd D:\AISF\AISF_0729_segment\eval-concurrency

python qwen_load_test.py `
  --config config.example.json `
  --output-dir results `
  --yes
```

`--yes` 表示确认已获得接口压测授权。冒烟测试正常后，再设置正式并发阶梯，例如：

```json
"concurrency_levels": [1, 5, 10, 15, 20, 30, 40, 50],
"requests_per_level": null
```

此时并发 15 每轮只同时发送 15 个请求，共运行 3 轮；每轮结束后关闭线程池并冷却。若 3 轮中 0 或 1 轮出现失败，继续测试并发 20；若至少 2 轮出现失败，判定并发 15 超限并停止。不会把不同轮次或不同并发档位叠加。随后可缩小并发步长进一步确认临界范围。

## 输出结果

指定的输出目录中会生成：

- `load_test_summary.json`：测试结论和每个并发档位的完整汇总。
- `load_test_summary.csv`：可直接用 Excel 打开的汇总表。
- `load_test_requests.csv`：每个请求的状态、延迟、错误和 token 明细。
- `load_test.log`：按时间追加的 JSON Lines 运行日志，可在测试过程中实时查看。

运行日志记录：测试开始和结束、接口和模型（不记录 API Key）、数据路径和数量、每档每轮起止、目标请求数、实际峰值并发、成功/失败数、错误类型、总耗时、RPS、P50/P95/P99、token 吞吐、最后稳定档位、首个超限档位和停止原因。程序每轮结束后立即刷新日志和结果文件，即使后续手动中断，已完成轮次仍可追溯。

`load_test_summary.json` 的 `test_result` 包含：

- `last_stable_concurrency`：停止前最后一个全部重复轮次均满足失败率阈值的档位。
- `first_failed_concurrency`：首次超过失败率阈值的档位。
- `stopped_early`：是否因失败提前停止。
- `stop_reason`：具体停止原因。

每档关键指标：

- `actual_peak_in_flight`：客户端实际同时在途请求峰值。
- `success_rate`：返回合法 2xx Chat Completions 响应的比例。
- `requests_per_second`：每秒成功请求数。
- `latency_mean_seconds`：平均响应时间。
- `latency_p50/p95/p99_seconds`：响应延迟分位数。
- `tokens_per_second`：成功响应的总 token 吞吐。
- `error_types`：HTTP 429、5xx、超时、连接错误及非法响应计数。

单轮出现错误不会直接判定超限；当前采用 3 轮中至少 2 轮失败才停止的规则。找到临界区间后，可缩小并发步长再次验证。最终建议选择多轮稳定、P95 延迟可接受、吞吐接近最高且低于首个超限档位的并发值，并预留 10%～20% 余量。
