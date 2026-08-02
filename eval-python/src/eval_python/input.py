"""Decode the eval-agent Session JSON contract once at the input boundary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import InputError, SessionInput, Turn


def load_sessions(path: str | Path) -> list[SessionInput]:
    input_path = Path(path).resolve()
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise InputError(f"Unable to read input {input_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise InputError(f"Invalid JSON in {input_path}: {exc}") from exc
    if not isinstance(payload, list):
        raise InputError("Input JSON top level must be a Session array")

    sessions: list[SessionInput] = []
    seen_session_ids: set[str] = set()
    for index, raw in enumerate(payload):
        field = f"sessions[{index}]"
        if not isinstance(raw, dict):
            raise InputError(f"{field} must be an object")
        session_id = _nonempty_string(raw.get("session_id"), f"{field}.session_id")
        user_id = _nonempty_string(raw.get("user_id"), f"{field}.user_id")
        if session_id in seen_session_ids:
            raise InputError(f"Duplicate session_id: {session_id}")
        seen_session_ids.add(session_id)

        raw_turns = raw.get("turns")
        if not isinstance(raw_turns, list) or not raw_turns:
            raise InputError(f"{field}.turns must be a non-empty array")
        turns = tuple(sorted(
            (_decode_turn(value, f"{field}.turns[{turn_index}]") for turn_index, value in enumerate(raw_turns)),
            key=lambda turn: turn.turn_no,
        ))
        turn_numbers = [turn.turn_no for turn in turns]
        if len(turn_numbers) != len(set(turn_numbers)):
            raise InputError(f"{field}.turns contains duplicate turn_no values")

        declared = raw.get("turn_count")
        if declared is not None:
            declared = _positive_integer(declared, f"{field}.turn_count")
            if declared != len(turns):
                raise InputError(
                    f"{field}.turn_count is {declared}, but turns contains {len(turns)} items",
                )
        sessions.append(SessionInput(session_id, user_id, turns, declared))
    return sessions


def _decode_turn(raw: Any, field: str) -> Turn:
    if not isinstance(raw, dict):
        raise InputError(f"{field} must be an object")
    turn_no = _positive_integer(raw.get("turn_no"), f"{field}.turn_no")
    human = raw.get("human")
    if not isinstance(human, str):
        raise InputError(f"{field}.human must be a string")

    ai = _optional_string(raw.get("ai"), f"{field}.ai")
    if ai == "":
        ai = None
    rewrite_query = _optional_string(raw.get("rewrite_query"), f"{field}.rewrite_query")
    timestamp = _optional_string(raw.get("timestamp"), f"{field}.timestamp")
    if timestamp == "":
        timestamp = None
    return Turn(turn_no, human, ai, rewrite_query, timestamp)


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InputError(f"{field} must be a string or null")
    return value


def _positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InputError(f"{field} must be a positive integer")
    return value

