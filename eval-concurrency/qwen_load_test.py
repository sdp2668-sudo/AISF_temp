#!/usr/bin/env python3
"""Standalone concurrent load tester for OpenAI-compatible chat endpoints."""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class RequestResult:
    concurrency: int
    repeat: int
    request_no: int
    success: bool
    status_code: int
    elapsed_seconds: float
    error_type: str
    error_detail: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class InFlightCounter:
    def __init__(self) -> None:
        self.current = 0
        self.peak = 0
        self.lock = threading.Lock()

    def enter(self) -> None:
        with self.lock:
            self.current += 1
            self.peak = max(self.peak, self.current)

    def leave(self) -> None:
        with self.lock:
            self.current -= 1


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def log_event(log_path: Path, event: str, **fields: Any) -> None:
    record = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "event": event,
        **fields,
    }
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    print(line, flush=True)
    with log_path.open("a", encoding="utf-8") as file:
        file.write(line + "\n")


def load_messages(path: Path, system_prompt: str) -> list[list[dict[str, str]]]:
    data = load_json(path)
    if not isinstance(data, list) or not data:
        raise ValueError("dataset must be a non-empty JSON array")
    result: list[list[dict[str, str]]] = []
    for index, item in enumerate(data, 1):
        if isinstance(item, str):
            messages = [{"role": "user", "content": item}]
        elif isinstance(item, dict) and isinstance(item.get("messages"), list):
            messages = item["messages"]
        elif isinstance(item, dict) and isinstance(item.get("turns"), list):
            content = "\n".join(
                f"Turn {turn.get('turn_no', number)}: {turn.get('human', '')}"
                for number, turn in enumerate(item["turns"], 1)
                if isinstance(turn, dict)
            )
            messages = [{"role": "user", "content": content}]
        else:
            raise ValueError(f"unsupported dataset item at index {index}")
        normalized = []
        for message in messages:
            if not isinstance(message, dict) or message.get("role") not in {"system", "user", "assistant"}:
                raise ValueError(f"invalid message at dataset item {index}")
            normalized.append({"role": str(message["role"]), "content": str(message.get("content", ""))})
        if system_prompt and not any(message["role"] == "system" for message in normalized):
            normalized.insert(0, {"role": "system", "content": system_prompt})
        result.append(normalized)
    return result


def make_opener(bypass_proxy: bool, verify_tls: bool) -> urllib.request.OpenerDirector:
    handlers: list[Any] = []
    if bypass_proxy:
        handlers.append(urllib.request.ProxyHandler({}))
    if not verify_tls:
        handlers.append(urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
    return urllib.request.build_opener(*handlers)


def classify_exception(error: BaseException) -> tuple[str, str]:
    if isinstance(error, (TimeoutError, socket.timeout)):
        return "timeout", str(error)
    if isinstance(error, urllib.error.URLError):
        reason = error.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return "timeout", str(reason)
        return "connection_error", str(reason)
    return "client_error", str(error)


def one_request(config: dict[str, Any], messages: list[dict[str, str]], concurrency: int,
                repeat: int, request_no: int, counter: InFlightCounter) -> RequestResult:
    payload: dict[str, Any] = {
        "model": config["model"], "messages": messages,
        "temperature": config.get("temperature", 0.0),
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": bool(config.get("enable_thinking", True))},
    }
    if config.get("max_tokens") is not None:
        payload["max_tokens"] = int(config["max_tokens"])
    headers = {"Content-Type": "application/json"}
    api_key_env = config.get("api_key_env")
    if api_key_env:
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(f"environment variable {api_key_env} is not set")
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        config["endpoint"], data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers, method="POST",
    )
    opener = make_opener(bool(config.get("bypass_proxy", True)), bool(config.get("verify_tls", False)))
    started = time.perf_counter()
    counter.enter()
    try:
        try:
            with opener.open(request, timeout=float(config.get("timeout_seconds", 180))) as response:
                status = int(response.status)
                raw = response.read()
        except urllib.error.HTTPError as error:
            status = int(error.code)
            raw = error.read()
            detail = raw.decode("utf-8", errors="replace")[:500]
            return RequestResult(concurrency, repeat, request_no, False, status,
                                 round(time.perf_counter() - started, 6), f"http_{status}", detail, 0, 0, 0)
        except BaseException as error:
            error_type, detail = classify_exception(error)
            return RequestResult(concurrency, repeat, request_no, False, 0,
                                 round(time.perf_counter() - started, 6), error_type, detail[:500], 0, 0, 0)
        try:
            body = json.loads(raw.decode("utf-8"))
            choices = body.get("choices")
            if not isinstance(choices, list) or not choices:
                raise ValueError("response has no choices")
            usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
            return RequestResult(concurrency, repeat, request_no, True, status,
                                 round(time.perf_counter() - started, 6), "", "",
                                 int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0),
                                 int(usage.get("total_tokens") or 0))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as error:
            return RequestResult(concurrency, repeat, request_no, False, status,
                                 round(time.perf_counter() - started, 6), "invalid_response", str(error), 0, 0, 0)
    finally:
        counter.leave()


def percentile(values: list[float], percentile_value: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile_value / 100 * len(ordered)))
    return round(ordered[rank - 1], 6)


def summarize(results: list[RequestResult], concurrency: int, repeat: int,
              wall_seconds: float, peak: int) -> dict[str, Any]:
    success = [result for result in results if result.success]
    latencies = [result.elapsed_seconds for result in success]
    total_tokens = sum(result.total_tokens for result in success)
    error_types: dict[str, int] = {}
    for result in results:
        if result.error_type:
            error_types[result.error_type] = error_types.get(result.error_type, 0) + 1
    return {
        "concurrency": concurrency, "repeat": repeat, "requests": len(results),
        "successes": len(success), "failures": len(results) - len(success),
        "success_rate": len(success) / len(results) if results else 0.0,
        "actual_peak_in_flight": peak, "wall_seconds": round(wall_seconds, 6),
        "requests_per_second": round(len(success) / wall_seconds, 6) if wall_seconds else 0.0,
        "latency_mean_seconds": round(sum(latencies) / len(latencies), 6) if latencies else None,
        "latency_p50_seconds": percentile(latencies, 50),
        "latency_p95_seconds": percentile(latencies, 95),
        "latency_p99_seconds": percentile(latencies, 99),
        "prompt_tokens": sum(result.prompt_tokens for result in success),
        "completion_tokens": sum(result.completion_tokens for result in success),
        "total_tokens": total_tokens,
        "tokens_per_second": round(total_tokens / wall_seconds, 6) if wall_seconds else 0.0,
        "error_types": error_types,
    }


def run_level(config: dict[str, Any], dataset: list[list[dict[str, str]]], concurrency: int,
              repeat: int) -> tuple[dict[str, Any], list[RequestResult]]:
    configured_total = config.get("requests_per_level")
    total = concurrency if configured_total in (None, "concurrency") else int(configured_total)
    if total < concurrency:
        raise ValueError(
            f"requests_per_level ({total}) cannot be less than concurrency ({concurrency})",
        )
    counter = InFlightCounter()
    started = time.perf_counter()
    results: list[RequestResult] = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(one_request, config, dataset[index % len(dataset)], concurrency,
                                   repeat, index + 1, counter) for index in range(total)]
        for future in as_completed(futures):
            results.append(future.result())
    wall = time.perf_counter() - started
    results.sort(key=lambda item: item.request_no)
    return summarize(results, concurrency, repeat, wall, counter.peak), results


def write_outputs(output_dir: Path, config_path: Path, summaries: list[dict[str, Any]],
                  details: list[RequestResult], test_result: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config_file": str(config_path.resolve()), "test_result": test_result,
        "summaries": summaries,
    }
    (output_dir / "load_test_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_headers = [
        "concurrency", "repeat", "requests", "successes", "failures", "success_rate",
        "actual_peak_in_flight", "wall_seconds", "requests_per_second", "latency_mean_seconds",
        "latency_p50_seconds", "latency_p95_seconds", "latency_p99_seconds", "prompt_tokens",
        "completion_tokens", "total_tokens", "tokens_per_second", "error_types",
    ]
    with (output_dir / "load_test_summary.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=summary_headers)
        writer.writeheader()
        for summary in summaries:
            writer.writerow({**summary, "error_types": json.dumps(summary["error_types"], ensure_ascii=False)})
    with (output_dir / "load_test_requests.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(asdict(details[0]).keys()) if details else [])
        if details:
            writer.writeheader(); writer.writerows(asdict(result) for result in details)


def main() -> None:
    parser = argparse.ArgumentParser(description="Qwen/OpenAI兼容接口并发压测工具")
    parser.add_argument("--config", type=Path, required=True, help="压测配置JSON")
    parser.add_argument("--output-dir", type=Path, default=Path("results"), help="输出目录")
    parser.add_argument("--yes", action="store_true", help="确认已获授权并执行压测")
    args = parser.parse_args()
    if not args.yes:
        raise SystemExit("压测会向接口发送大量请求；确认已获授权后添加 --yes")
    config = load_json(args.config)
    for key in ("endpoint", "model", "dataset_path", "concurrency_levels"):
        if not config.get(key):
            raise SystemExit(f"missing required config field: {key}")
    levels = [int(value) for value in config["concurrency_levels"]]
    if not levels or any(value < 1 for value in levels):
        raise SystemExit("concurrency_levels must contain positive integers")
    dataset_path = Path(config["dataset_path"])
    if not dataset_path.is_absolute():
        dataset_path = args.config.parent / dataset_path
    dataset = load_messages(dataset_path, str(config.get("system_prompt", "")))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    log_path = args.output_dir / "load_test.log"
    log_event(
        log_path, "test_started", endpoint=config["endpoint"], model=config["model"],
        dataset_path=str(dataset_path.resolve()), dataset_items=len(dataset),
        concurrency_levels=levels, requests_per_level=config.get("requests_per_level"),
        repeats=int(config.get("repeats", 3)), timeout_seconds=config.get("timeout_seconds", 180),
    )
    warmups = int(config.get("warmup_requests", 5))
    if warmups:
        warmup_concurrency = min(min(levels), warmups)
        log_event(log_path, "warmup_started", requests=warmups, concurrency=warmup_concurrency)
        warm_config = {**config, "requests_per_level": warmups}
        warm_summary, _ = run_level(warm_config, dataset, warmup_concurrency, 0)
        log_event(log_path, "warmup_completed", **warm_summary)
        if warm_summary["successes"] == 0:
            log_event(log_path, "test_aborted", reason="all warmup requests failed")
            raise SystemExit("all warmup requests failed; stop before load test")
    summaries: list[dict[str, Any]] = []
    details: list[RequestResult] = []
    repeats = int(config.get("repeats", 3))
    failed_repeats_to_stop = int(config.get("failed_repeats_to_stop", 2))
    if repeats < 1 or not 1 <= failed_repeats_to_stop <= repeats:
        raise SystemExit("failed_repeats_to_stop must be between 1 and repeats")
    cooldown = float(config.get("cooldown_seconds", 10))
    stop_on_failure = bool(config.get("stop_on_failure", True))
    max_failure_rate = float(config.get("max_failure_rate", 0.0))
    if not 0 <= max_failure_rate <= 1:
        raise SystemExit("max_failure_rate must be between 0 and 1")
    test_result: dict[str, Any] = {
        "stopped_early": False, "stop_reason": "", "last_stable_concurrency": None,
        "first_failed_concurrency": None,
    }
    should_stop = False
    for concurrency in levels:
        failed_repeats = 0
        for repeat in range(1, repeats + 1):
            log_event(
                log_path, "level_repeat_started", concurrency=concurrency,
                repeat=repeat, repeats=repeats,
                request_count=(concurrency if config.get("requests_per_level") in (None, "concurrency")
                               else int(config["requests_per_level"])),
            )
            summary, rows = run_level(config, dataset, concurrency, repeat)
            summaries.append(summary); details.extend(rows)
            log_event(log_path, "level_repeat_completed", **summary)
            failure_rate = summary["failures"] / summary["requests"] if summary["requests"] else 1.0
            if failure_rate > max_failure_rate:
                failed_repeats += 1
            write_outputs(args.output_dir, args.config, summaries, details, test_result)
            if cooldown > 0 and not (concurrency == levels[-1] and repeat == repeats):
                time.sleep(cooldown)
        if failed_repeats < failed_repeats_to_stop:
            test_result["last_stable_concurrency"] = concurrency
            write_outputs(args.output_dir, args.config, summaries, details, test_result)
        else:
            should_stop = stop_on_failure
            test_result.update({
                "stopped_early": should_stop,
                "stop_reason": (
                    f"concurrency {concurrency} failed in {failed_repeats}/{repeats} repeats; "
                    f"threshold is {failed_repeats_to_stop}/{repeats}"
                ),
                "first_failed_concurrency": concurrency,
            })
            write_outputs(args.output_dir, args.config, summaries, details, test_result)
        if should_stop:
            log_event(log_path, "limit_reached", **test_result)
            break
    if not should_stop:
        test_result["stop_reason"] = "all configured concurrency levels completed"
    write_outputs(args.output_dir, args.config, summaries, details, test_result)
    log_event(
        log_path, "test_completed", output_dir=str(args.output_dir.resolve()),
        tested_repeats=len(summaries), **test_result,
    )


if __name__ == "__main__":
    main()
