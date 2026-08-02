"""Qwen HTTP client matching the supplied test_one_case.py request form."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

import requests

from .config import ModelConfig
from .models import ChatResult, ConfigError, ModelError


class QwenClient:
    def __init__(
        self,
        config: ModelConfig,
        *,
        session: requests.Session | Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        include_raw_response: bool = True,
    ) -> None:
        self.config = config
        self.session = session or requests.Session()
        if config.bypass_proxy and hasattr(self.session, "trust_env"):
            self.session.trust_env = False
        self.sleep = sleep
        self.include_raw_response = include_raw_response
        self._api_key = self._load_api_key()

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResult:
        payload: dict[str, Any] = {
            "model": self.config.name,
            "messages": messages,
            "temperature": self.config.temperature,
            "chat_template_kwargs": {"enable_thinking": self.config.enable_thinking},
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        started = time.perf_counter()
        last_error = ""
        total_attempts = self.config.max_retries + 1
        for attempt in range(1, total_attempts + 1):
            try:
                response = self.session.post(
                    self.config.endpoint,
                    json=payload,
                    headers=headers,
                    verify=self.config.verify_tls,
                    timeout=(self.config.connect_timeout_seconds, self.config.read_timeout_seconds),
                )
            except requests.RequestException as exc:
                last_error = f"Qwen request failed: {exc}"
                if attempt < total_attempts:
                    self._backoff(attempt)
                    continue
                raise ModelError(last_error) from exc

            status = int(getattr(response, "status_code", 0))
            try:
                body = response.json()
            except (ValueError, TypeError) as exc:
                last_error = f"Qwen returned non-JSON HTTP {status}"
                if status >= 500 and attempt < total_attempts:
                    self._backoff(attempt)
                    continue
                raise ModelError(last_error) from exc
            if not isinstance(body, dict):
                raise ModelError(f"Qwen returned a non-object JSON envelope for HTTP {status}")

            if status < 200 or status >= 300:
                detail = _error_detail(body)
                last_error = f"Qwen HTTP {status}: {detail}"
                if (status == 429 or status >= 500) and attempt < total_attempts:
                    self._backoff(attempt)
                    continue
                raise ModelError(last_error)

            message = _assistant_from_body(body)
            usage = _usage_from_body(body)
            return ChatResult(
                message=message,
                usage=usage,
                elapsed_seconds=round(time.perf_counter() - started, 6),
                attempts=attempt,
                raw_response=body if self.include_raw_response else None,
            )

        raise ModelError(last_error or "Qwen request failed")

    def _load_api_key(self) -> str | None:
        env_name = self.config.api_key_env
        if not env_name:
            return None
        value = os.environ.get(env_name)
        if not value:
            raise ConfigError(f"Environment variable {env_name} is required by model.api_key_env")
        return value

    def _backoff(self, attempt: int) -> None:
        delay = self.config.retry_backoff_seconds * (2 ** (attempt - 1))
        if delay > 0:
            self.sleep(delay)


def _assistant_from_body(body: dict[str, Any]) -> dict[str, Any]:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ModelError("Qwen response has no choices[0]")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ModelError("Qwen response has no choices[0].message")
    role = message.get("role")
    if role not in (None, "assistant"):
        raise ModelError(f"Qwen response message has unexpected role: {role}")
    return message


def _usage_from_body(body: dict[str, Any]) -> dict[str, int]:
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    return {
        "prompt_tokens": _safe_nonnegative_int(usage.get("prompt_tokens")),
        "completion_tokens": _safe_nonnegative_int(usage.get("completion_tokens")),
        "total_tokens": _safe_nonnegative_int(usage.get("total_tokens")),
    }


def _safe_nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _error_detail(body: dict[str, Any]) -> str:
    error = body.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"][:500]
    return str(body)[:500]

