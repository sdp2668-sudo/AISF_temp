# eval-python

独立的 Qwen Session Episode/Segment 评估工具。主流程把一天的 Session JSON 划分为 Episode 和 Segment，并识别意图、业务、可选子功能及可选的“AI 明确回复不支持”。结果同时导出 JSON 和 XLSX。

项目逻辑以 `eval-agent` 的 `AIsayno@cfd3cc71d3f29ab99557d02fa92c5bd3bb2ef6c5` 为基线，并额外保留当前输入契约中的可选 `rewrite_query` 字段。Segment、场景和拒识提示词使用该基线的完整规则，不使用 `badcaseOps` worker 中的简化提示词。

## 环境准备

- Python 3.11 或更高版本
- 可以访问配置中的 Qwen OpenAI 兼容接口（只有实际执行 `run` 时需要）

```powershell
cd D:\1WorkCode\eval-python
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

自动化测试使用模拟 HTTP 客户端，不会访问真实 Qwen 接口：

```powershell
python -B -m unittest discover -s tests -t . -v
```

## 输入

`run` 接收一个 JSON 文件，顶层必须是 Session 数组。Session 和 Turn 契约如下：

```json
[
  {
    "session_id": "session-001",
    "user_id": "user-001",
    "turn_count": 2,
    "turns": [
      {
        "turn_no": 1,
        "human": "打开空调",
        "ai": "好的",
        "rewrite_query": "打开空调",
        "timestamp": "2026-07-27T10:00:00+08:00"
      },
      {
        "turn_no": 2,
        "human": "调到二十六度",
        "ai": null,
        "timestamp": "2026-07-27T10:01:00+08:00"
      }
    ]
  }
]
```

字段规则：

- `session_id`、`user_id` 和非空 `turns` 必填。
- `turn_no`、`human` 必填；Turn 会按 `turn_no` 排序，重复编号会报错。
- `ai`、`rewrite_query`、`timestamp` 可为 `null`；空 `ai` 归一化为 `null`。
- `turn_count` 可省略；提供时必须等于 `turns` 数量。
- `rewrite_query` 原样输出，但不参与 Segment 边界判断。

## 配置

默认示例在 `config\qwen.example.yaml`：

```yaml
taxonomy_path: scenario-taxonomy.json

model:
  endpoint: http://9.15.87.94:1065/v1/chat/completions
  name: Qwen3-32B
  api_key_env: null
  temperature: 0.0
  enable_thinking: false
  verify_tls: false
  bypass_proxy: true
  connect_timeout_seconds: 10
  read_timeout_seconds: 120
  max_retries: 2
  retry_backoff_seconds: 2

features:
  enable_subscene: true
  enable_ai_unsupported: true

pipeline:
  episode_gap_minutes: 30
  segment_window_size: 8
  session_concurrency: 5
  segment_concurrency: 5
  max_agent_rounds: 120

filters:
  excluded_user_ids: []
  max_episode_turns: null

output:
  include_raw_model_response: true
```

关键语义：

- 相邻两轮有效时间严格超过 `episode_gap_minutes` 才创建新 Episode。
- `enable_subscene: false` 仍调用模型识别业务，但不要求或校验子功能；JSON 中 `sub_function` 为 `null`，Excel 留空。
- `enable_ai_unsupported: false` 不调用拒识模型；相关 JSON 字段为 `null`，Excel 留空。
- 拒识功能启用但未命中时输出 `ai_unsupported: "否"`、空原因和空 `refusal_findings` 数组，和禁用状态明确区分。
- 用户黑名单与 Episode 最大轮数过滤默认关闭。启用后，所有排除项及原因写入结果元数据。
- 噪声 Turn 只写入 `noise_turns`，不会从 Segment 中删除。
- `api_key_env` 为 `null` 时不发送 Authorization；如接口需要认证，填环境变量名，不要把密钥写进 YAML。

建议首次运行时先把 Session 和 Segment 并发调低，再根据接口容量逐步增加。

## 运行分析

```powershell
python -m eval_python run `
  --input data\sessions_2026-07-27.json `
  --config config\qwen.example.yaml `
  --output-dir output
```

`run` 只执行 Qwen 分析并生成两个带输入名、模型名和 run ID 的文件：

```text
output\sessions_2026-07-27__Qwen3-32B__<run-id>.json
output\sessions_2026-07-27__Qwen3-32B__<run-id>.xlsx
```

JSON 保留完整 Session → Episode → Segment → Turn 层级，以及：

- Segment 范围、意图、业务、子功能、拒识结论和噪声 Turn；
- 功能开关、过滤记录、Session/Segment 状态和错误；
- 模型名、总耗时、每次模型调用耗时、重试次数和 token usage；
- 可选的原始模型响应。

XLSX 第一张表固定为 `sessions`，列顺序与 `badcaseOps`“全量会话”导出一致：

```text
session_id, episode_id, segment_id, turn_index, total_turns, time,
intent_summary, 业务, 子功能, human, rewritten_query, ai,
AI明确回复不支持问题
```

其余工作表为 `run_summary`、`performance` 和 `errors`。输出文件已存在时命令拒绝覆盖。

## 独立对比

对比是可选离线命令，不属于 `run`，不会调用 Qwen，也不会重新划分 Segment：

```powershell
python -m eval_python compare `
  --qwen-json output\sessions_2026-07-27__Qwen3-32B__<run-id>.json `
  --baseline-xlsx D:\path\full_conversations_2026-07-27.xlsx `
  --output-dir output\comparison
```

对比按 `session_id + turn_index` 对齐两侧并拒绝重复键。输出包括：

- `<qwen-name>__comparison.json`
- `<qwen-name>__comparison.xlsx`
- Turn 级存在性、Episode/Segment 值、Segment 边界、意图、业务、子功能和拒识差异
- Session 级与全局差异计数

对比结果只呈现差异，不判断 Qwen 或当前 DeepSeek 结果哪一侧正确。

## 命令帮助

```powershell
python -m eval_python --help
python -m eval_python run --help
python -m eval_python compare --help
```

本项目没有对真实 Qwen 连通性或服务端 tool-call 支持做自动探测。接口不可达、返回格式不兼容或模型未在限定轮数内提交合法工具调用时，会在运行结果和 `errors` 工作表中记录失败。
