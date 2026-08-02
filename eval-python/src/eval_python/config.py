"""YAML configuration loading with validation at the process boundary."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import ConfigError


@dataclass(frozen=True)
class ModelConfig:
    endpoint: str
    name: str
    api_key_env: str | None
    temperature: float
    enable_thinking: bool
    verify_tls: bool
    bypass_proxy: bool
    connect_timeout_seconds: float
    read_timeout_seconds: float
    max_retries: int
    retry_backoff_seconds: float


@dataclass(frozen=True)
class FeatureConfig:
    enable_subscene: bool
    enable_ai_unsupported: bool


@dataclass(frozen=True)
class PipelineConfig:
    episode_gap_minutes: float
    segment_window_size: int
    session_concurrency: int
    segment_concurrency: int
    max_agent_rounds: int


@dataclass(frozen=True)
class FilterConfig:
    excluded_user_ids: tuple[str, ...]
    max_episode_turns: int | None


@dataclass(frozen=True)
class OutputConfig:
    include_raw_model_response: bool


@dataclass(frozen=True)
class AppConfig:
    taxonomy_path: Path
    model: ModelConfig
    features: FeatureConfig
    pipeline: PipelineConfig
    filters: FilterConfig
    output: OutputConfig

    def sanitized_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["taxonomy_path"] = str(self.taxonomy_path)
        return value


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).resolve()
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Unable to read config {config_path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {config_path}: {exc}") from exc

    root = _mapping(loaded, "config")
    model = _mapping(root.get("model"), "model")
    features = _mapping(root.get("features", {}), "features")
    pipeline = _mapping(root.get("pipeline", {}), "pipeline")
    filters = _mapping(root.get("filters", {}), "filters")
    output = _mapping(root.get("output", {}), "output")

    taxonomy_value = _nonempty_string(root.get("taxonomy_path"), "taxonomy_path")
    taxonomy_path = Path(taxonomy_value)
    if not taxonomy_path.is_absolute():
        taxonomy_path = (config_path.parent / taxonomy_path).resolve()
    if not taxonomy_path.is_file():
        raise ConfigError(f"taxonomy_path does not exist: {taxonomy_path}")

    api_key_env = model.get("api_key_env")
    if api_key_env is not None:
        api_key_env = _nonempty_string(api_key_env, "model.api_key_env")

    excluded = filters.get("excluded_user_ids", [])
    if not isinstance(excluded, list) or any(not isinstance(item, str) or not item.strip() for item in excluded):
        raise ConfigError("filters.excluded_user_ids must be a list of non-empty strings")
    excluded_ids = tuple(dict.fromkeys(item.strip() for item in excluded))

    max_episode_turns = filters.get("max_episode_turns")
    if max_episode_turns is not None:
        max_episode_turns = _integer(max_episode_turns, "filters.max_episode_turns", minimum=1)

    return AppConfig(
        taxonomy_path=taxonomy_path,
        model=ModelConfig(
            endpoint=_nonempty_string(model.get("endpoint"), "model.endpoint"),
            name=_nonempty_string(model.get("name"), "model.name"),
            api_key_env=api_key_env,
            temperature=_number(model.get("temperature", 0.0), "model.temperature", minimum=0),
            enable_thinking=_boolean(model.get("enable_thinking", False), "model.enable_thinking"),
            verify_tls=_boolean(model.get("verify_tls", False), "model.verify_tls"),
            bypass_proxy=_boolean(model.get("bypass_proxy", True), "model.bypass_proxy"),
            connect_timeout_seconds=_number(
                model.get("connect_timeout_seconds", 10), "model.connect_timeout_seconds", minimum=0.001,
            ),
            read_timeout_seconds=_number(
                model.get("read_timeout_seconds", 120), "model.read_timeout_seconds", minimum=0.001,
            ),
            max_retries=_integer(model.get("max_retries", 2), "model.max_retries", minimum=0),
            retry_backoff_seconds=_number(
                model.get("retry_backoff_seconds", 2), "model.retry_backoff_seconds", minimum=0,
            ),
        ),
        features=FeatureConfig(
            enable_subscene=_boolean(features.get("enable_subscene", True), "features.enable_subscene"),
            enable_ai_unsupported=_boolean(
                features.get("enable_ai_unsupported", True), "features.enable_ai_unsupported",
            ),
        ),
        pipeline=PipelineConfig(
            episode_gap_minutes=_number(
                pipeline.get("episode_gap_minutes", 30), "pipeline.episode_gap_minutes", minimum=0,
            ),
            segment_window_size=_integer(
                pipeline.get("segment_window_size", 8), "pipeline.segment_window_size", minimum=1,
            ),
            session_concurrency=_integer(
                pipeline.get("session_concurrency", 5), "pipeline.session_concurrency", minimum=1,
            ),
            segment_concurrency=_integer(
                pipeline.get("segment_concurrency", 5), "pipeline.segment_concurrency", minimum=1,
            ),
            max_agent_rounds=_integer(
                pipeline.get("max_agent_rounds", 120), "pipeline.max_agent_rounds", minimum=1,
            ),
        ),
        filters=FilterConfig(excluded_user_ids=excluded_ids, max_episode_turns=max_episode_turns),
        output=OutputConfig(
            include_raw_model_response=_boolean(
                output.get("include_raw_model_response", True), "output.include_raw_model_response",
            ),
        ),
    )


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{field} must be a mapping")
    return value


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} must be a non-empty string")
    return value.strip()


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{field} must be true or false")
    return value


def _number(value: Any, field: str, *, minimum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{field} must be a number")
    parsed = float(value)
    if parsed < minimum:
        raise ConfigError(f"{field} must be >= {minimum}")
    return parsed


def _integer(value: Any, field: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{field} must be an integer")
    if value < minimum:
        raise ConfigError(f"{field} must be >= {minimum}")
    return value

