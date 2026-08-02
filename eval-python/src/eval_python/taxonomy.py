"""Scenario taxonomy loading, rendering, and pair validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ConfigError


OTHER_BUSINESS = "其他"


@dataclass(frozen=True)
class TaxonomyEntry:
    business: str
    sub_function: str
    is_control: bool
    examples: str


@dataclass(frozen=True)
class Taxonomy:
    entries: tuple[TaxonomyEntry, ...]

    @property
    def businesses(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(entry.business for entry in self.entries))

    def sub_functions(self, business: str) -> tuple[str, ...]:
        return tuple(entry.sub_function for entry in self.entries if entry.business == business)

    def is_valid_pair(self, business: str, sub_function: str) -> bool:
        return any(
            entry.business == business and entry.sub_function == sub_function
            for entry in self.entries
        )

    def is_control_pair(self, business: str, sub_function: str) -> bool:
        return any(
            entry.business == business
            and entry.sub_function == sub_function
            and entry.is_control
            for entry in self.entries
        )

    def format_for_prompt(self) -> str:
        groups: list[str] = []
        for business in self.businesses:
            lines = [
                f"  - {entry.sub_function}：{entry.examples}"
                for entry in self.entries
                if entry.business == business
            ]
            groups.append(f"### {business}\n" + "\n".join(lines))
        return "\n\n".join(groups)


def load_taxonomy(path: str | Path) -> Taxonomy:
    taxonomy_path = Path(path).resolve()
    try:
        raw = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Unable to read taxonomy {taxonomy_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid taxonomy JSON in {taxonomy_path}: {exc}") from exc
    if not isinstance(raw, list) or not raw:
        raise ConfigError("Taxonomy must be a non-empty array")

    entries: list[TaxonomyEntry] = []
    seen: set[tuple[str, str]] = set()
    for index, value in enumerate(raw):
        field = f"taxonomy[{index}]"
        if not isinstance(value, dict):
            raise ConfigError(f"{field} must be an object")
        business = _required_text(value.get("业务"), f"{field}.业务")
        sub_function = _required_text(value.get("子功能"), f"{field}.子功能")
        is_control = value.get("是否操控类")
        if not isinstance(is_control, bool):
            raise ConfigError(f"{field}.是否操控类 must be true or false")
        examples = _required_text(value.get("对象类型举例"), f"{field}.对象类型举例")
        pair = (business, sub_function)
        if pair in seen:
            raise ConfigError(f"Duplicate taxonomy pair: {business}-{sub_function}")
        seen.add(pair)
        entries.append(TaxonomyEntry(business, sub_function, is_control, examples))
    return Taxonomy(tuple(entries))


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} must be a non-empty string")
    return value.strip()

