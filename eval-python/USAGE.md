# eval-python 使用说明

本文介绍如何准备输入、调整 Qwen 配置、运行 Segment 分析、查看 JSON/XLSX 结果，以及按需执行离线对比。

项目目录：

```text
D:\1WorkCode\eval-python
```

## 1. 功能概览

项目提供两个相互独立的命令：

```text
run      Session JSON -> Qwen 分析 -> 结果 JSON + XLSX
compare  已有 Qwen JSON + badcaseOps XLSX -> 对比 JSON + XLSX
```

`run` 执行以下步骤：

1. 校验并按 `turn_no` 排序 Session Turn。
2. 相邻有效时间严格超过配置阈值时划分新 Episode。
3. 使用完整 `AIsayno@cfd3cc7` 规则划分 Segment，并生成意图摘要。
4. 识别业务以及可选的子功能。
5. 可选识别“AI 是否明确回复不支持”。
6. 输出完整层级 JSON 和与“全量会话”对齐的 XLSX。

`compare` 只读取现有文件，不调用 Qwen，也不会重新执行 Segment 划分。

## 2. 安装

要求 Python 3.11 或更高版本。

```powershell
cd D:\1WorkCode\eval-python
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

安装后检查命令：

```powershell
python -m eval_python --help
python -m eval_python run --help
python -m eval_python compare --help
```

## 3. 快速运行示例

项目提供了示例输入：

```text
examples\sessions.example.json
```

复制一份本地配置：

```powershell
Copy-Item config\qwen.example.yaml config\qwen.yaml
```

确认 `config\qwen.yaml` 中的 endpoint 和模型名称正确，然后运行：

```powershell
python -m eval_python run `
  --input examples\sessions.example.json `
  --config config\qwen.yaml `
  --output-dir output
```

命令完成后会在控制台输出实际文件路径和汇总信息，例如：

```json
{
  "json": "D:\\1WorkCode\\eval-python\\output\\sessions.example__Qwen3-32B__<run-id>.json",
  "xlsx": "D:\\1WorkCode\\eval-python\\output\\sessions.example__Qwen3-32B__<run-id>.xlsx",
  "summary": {
    "sessions": 1,
    "episodes": 2,
    "segments": 2,
    "turn_rows": 5,
    "model_calls": 6,
    "errors": 0
  }
}
```

Episode/Segment 数量和模型调用次数由模型实际划分结果及功能开关决定，上面的数值只是格式示例。

## 4. 输入 JSON

顶层必须是 Session 数组：

```json
[
  {
    "session_id": "session-001",
    "user_id": "user-001",
    "turn_count": 2,
    "turns": [
      {
        "turn_no": 1,
        "human": "打开酷狗",
        "ai": "已为您打开酷狗",
        "rewrite_query": "打开酷狗音乐",
        "timestamp": "2026-07-27T10:00:00+08:00"
      },
      {
        "turn_no": 2,
        "human": "播放青花瓷",
        "ai": "正在为您播放周杰伦的青花瓷",
        "rewrite_query": null,
        "timestamp": "2026-07-27T10:01:00+08:00"
      }
    ]
  }
]
```

字段约束：

| 层级 | 字段 | 必填 | 说明 |
| --- | --- | --- | --- |
| Session | `session_id` | 是 | 文件内必须唯一 |
| Session | `user_id` | 是 | 非空字符串 |
| Session | `turn_count` | 否 | 提供时必须等于 `turns` 数量 |
| Session | `turns` | 是 | 非空数组 |
| Turn | `turn_no` | 是 | 正整数，同一 Session 内不能重复 |
| Turn | `human` | 是 | 可以是空字符串，但必须是字符串 |
| Turn | `ai` | 否 | 字符串或 `null`；空字符串归一化为 `null` |
| Turn | `rewrite_query` | 否 | 原样导出，不参与 Segment 边界判断 |
| Turn | `timestamp` | 否 | ISO 时间字符串或 `null` |

示例文件中的第 3 轮到第 4 轮间隔超过 30 分钟，因此默认会确定性地创建第二个 Episode。Segment 边界由 Qwen 根据语义判断，可能因模型行为产生差异。

## 5. 配置说明

完整配置参考 `config\qwen.example.yaml`。

### 5.1 模型配置

```yaml
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
```

默认请求与给定的 `test_one_case.py` 保持一致：Qwen3-32B、temperature 为 0，并关闭 thinking。

接口需要 Bearer Token 时，只在配置中填写环境变量名：

```yaml
model:
  api_key_env: QWEN_API_KEY
```

然后在当前终端设置密钥：

```powershell
$env:QWEN_API_KEY = "实际密钥"
python -m eval_python run --input <input.json> --config config\qwen.yaml --output-dir output
```

不要把实际密钥写入 YAML、示例文件或 Git。

### 5.2 功能开关

完整分析：

```yaml
features:
  enable_subscene: true
  enable_ai_unsupported: true
```

较快的 Segment/意图/业务实验：

```yaml
features:
  enable_subscene: false
  enable_ai_unsupported: false
```

关闭子功能时仍会识别业务，但 JSON 中 `sub_function` 为 `null`，Excel 留空。关闭不支持识别时不会执行拒识模型调用，相关 JSON 字段为 `null`，Excel 留空。

项目提供了对应示例配置：

```powershell
python -m eval_python run `
  --input examples\sessions.example.json `
  --config examples\qwen.fast.example.yaml `
  --output-dir output\fast
```

### 5.3 并发与重试

```yaml
pipeline:
  session_concurrency: 5
  segment_concurrency: 5
  max_agent_rounds: 120
```

- `session_concurrency`：同时处理的 Session 数。
- `segment_concurrency`：同时执行场景/拒识的 Segment 数。
- `max_agent_rounds`：模型工具参数不合法时允许继续修正的最大轮数。
- `max_retries`：网络异常、HTTP 429 和部分服务端错误的重试次数。

第一次运行建议将两个并发值设为 `1` 或 `2`，确认接口容量后再逐步增加。

### 5.4 可选过滤

默认不过滤任何 Session 或 Episode：

```yaml
filters:
  excluded_user_ids: []
  max_episode_turns: null
```

过滤示例：

```yaml
filters:
  excluded_user_ids:
    - test-user-001
    - test-user-002
  max_episode_turns: 100
```

被过滤的数据及原因会记录在 JSON 的 `filters.excluded_items`，不会静默丢弃。

## 6. 输出说明

### 6.1 JSON

JSON 保留完整层级：

```text
run
└── sessions[]
    └── episodes[]
        └── segments[]
            └── turns[]
```

Segment 结果示例：

```json
{
  "segment_id": "s1",
  "status": "succeeded",
  "start_turn": 1,
  "end_turn": 3,
  "intent_summary": "打开音乐应用、播放歌曲并控制暂停",
  "noise_turns": [],
  "business": "音乐",
  "sub_function": "控制",
  "is_control": true,
  "ai_unsupported": "否",
  "judgment_reason": "",
  "refusal_findings": [],
  "turns": []
}
```

启用不支持识别但没有命中时：

```json
{
  "ai_unsupported": "否",
  "judgment_reason": "",
  "refusal_findings": []
}
```

关闭不支持识别时：

```json
{
  "ai_unsupported": null,
  "judgment_reason": null,
  "refusal_findings": null
}
```

顶层 `summary` 和 `metrics` 可用于评估速度，包括总耗时、调用次数、每次调用耗时、重试次数及 token usage。

### 6.2 XLSX

第一张工作表固定为 `sessions`，每个 Turn 一行，列顺序为：

```text
session_id
episode_id
segment_id
turn_index
total_turns
time
intent_summary
业务
子功能
human
rewritten_query
ai
AI明确回复不支持问题
```

其他工作表：

| 工作表 | 内容 |
| --- | --- |
| `run_summary` | 模型、开关、输入文件、运行汇总 |
| `performance` | 每次模型调用的阶段、耗时、重试和 token |
| `errors` | Session/Segment 阶段错误 |

## 7. 离线对比示例

先找到 `run` 生成的 Qwen JSON，再准备同一天从 `badcaseOps`“全量会话”页面导出的 XLSX：

```powershell
python -m eval_python compare `
  --qwen-json output\sessions_2026-07-27__Qwen3-32B__<run-id>.json `
  --baseline-xlsx D:\data\full_conversations_2026-07-27.xlsx `
  --output-dir output\comparison
```

对比按下面的联合键对齐：

```text
session_id + turn_index
```

两侧存在重复键时命令会报错，不会按 Excel 行号猜测对应关系。

对比 XLSX 包含：

| 工作表 | 内容 |
| --- | --- |
| `turn_comparison` | 两侧 Episode/Segment/意图/业务/子功能/不支持结果和差异标记 |
| `session_summary` | 每个 Session 的覆盖与差异计数 |
| `summary` | 全局覆盖与差异汇总 |

对比结果只表示两侧不同，不自动判断哪一侧正确。

## 8. 常见问题

### `No module named eval_python`

项目尚未安装，进入项目目录并执行：

```powershell
python -m pip install -e .
```

### 输出文件已经存在

工具不会覆盖已有结果。更换一个新的 `--output-dir`，或者确认不再需要旧结果后手动处理旧文件。

### Qwen 接口不可达

检查：

- `model.endpoint` 是否正确；
- 当前机器是否能访问目标网络；
- 是否需要设置 `api_key_env`；
- 企业代理是否影响请求；默认 `bypass_proxy: true` 会忽略系统代理。

### 模型一直没有提交有效结果

Segment、场景和拒识使用 OpenAI 兼容 function tools。服务端和模型必须支持 `tools`/`tool_calls`。如果达到 `max_agent_rounds`，错误会写入 JSON 和 XLSX 的 `errors` 工作表。

### 如何只测 Segment 速度

当前流程至少会执行 Segment、意图和业务识别。使用 `examples\qwen.fast.example.yaml` 可以关闭子功能和不支持识别，减少模型调用；业务识别仍会执行。

## 9. 验证范围

项目的自动化测试全部使用模拟 HTTP 响应：

```powershell
python -B -m unittest discover -s tests -t . -v
```

测试不会访问真实 Qwen。实际运行前仍需要确认接口连通性及服务端是否支持 OpenAI 兼容工具调用。
