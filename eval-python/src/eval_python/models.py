"""Shared typed contracts for input, agents, pipeline, and exporters."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


class EvalPythonError(Exception):
    """Base class for expected evaluator failures."""


class ConfigError(EvalPythonError):
    """Configuration is missing or invalid."""


class InputError(EvalPythonError):
    """Input data violates the Session JSON contract."""


class ModelError(EvalPythonError):
    """The configured model endpoint failed or returned an invalid envelope."""


class AgentError(EvalPythonError):
    """An agent did not submit a valid result within its bounded loop."""


class ExportError(EvalPythonError):
    """A result artifact could not be written safely."""


class ComparisonError(EvalPythonError):
    """Comparison inputs do not satisfy the shared Turn contract."""


@dataclass(frozen=True)
class Turn:
    turn_no: int
    human: str
    ai: str | None
    rewrite_query: str | None
    timestamp: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SessionInput:
    session_id: str
    user_id: str
    turns: tuple[Turn, ...]
    declared_turn_count: int | None = None


@dataclass(frozen=True)
class Episode:
    episode_id: str
    turns: tuple[Turn, ...]
    gap_before_minutes: float | None

    @property
    def start_turn(self) -> int:
        return self.turns[0].turn_no

    @property
    def end_turn(self) -> int:
        return self.turns[-1].turn_no


@dataclass(frozen=True)
class SegmentBoundary:
    segment_id: str
    start_turn: int
    end_turn: int
    intent_summary: str
    noise_turns: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "start_turn": self.start_turn,
            "end_turn": self.end_turn,
            "intent_summary": self.intent_summary,
            "noise_turns": list(self.noise_turns),
        }


@dataclass(frozen=True)
class ScenarioResult:
    business: str
    sub_function: str | None
    is_control: bool | None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class RefusalFinding:
    turn_no: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"turn_no": self.turn_no, "reason": self.reason}


@dataclass(frozen=True)
class RefusalResult:
    ai_unsupported: str | None
    judgment_reason: str | None
    findings: tuple[RefusalFinding, ...] | None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class CallMetric:
    stage: str
    elapsed_seconds: float
    attempts: int
    session_id: str = ""
    episode_id: str = ""
    segment_id: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ChatResult:
    message: dict[str, Any]
    usage: dict[str, int]
    elapsed_seconds: float
    attempts: int
    raw_response: dict[str, Any] | None = None


@dataclass(frozen=True)
class StageResult:
    value: Any
    metrics: tuple[CallMetric, ...] = ()
    raw_messages: tuple[dict[str, Any], ...] = ()


@dataclass
class RunAccumulator:
    metrics: list[CallMetric] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    filtered: list[dict[str, Any]] = field(default_factory=list)

