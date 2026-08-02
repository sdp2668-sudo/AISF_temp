#!/usr/bin/env python3
"""Analyze run/compare JSON artifacts from concurrency experiments."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


PERF_FIELDS = [
    "case", "session_concurrency", "segment_concurrency", "repeat",
    "run_file", "compare_file", "total_elapsed_seconds", "model_calls",
    "model_elapsed_seconds", "retry_count", "final_errors", "sessions",
    "sessions_succeeded", "sessions_partial_failed", "sessions_failed",
    "segments", "segments_succeeded", "segments_failed", "session_completeness",
    "segment_completeness", "boundary_diffs", "segment_diffs", "intent_diffs",
    "business_diffs", "sub_function_diffs", "turns_union", "turns_with_any_diff",
    "diff_turn_rate", "error_rate", "throughput_segments_per_second",
]


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        value = json.load(f)
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def analyze_case(item: dict[str, Any]) -> dict[str, Any]:
    run_path = item["run"]
    compare_path = item.get("compare")
    run = load(run_path)
    summary = run.get("summary") or {}
    metrics = run.get("metrics") or []
    compare = load(compare_path) if compare_path else {}
    cs = compare.get("summary") or {}
    sessions = int(_num(summary.get("sessions")))
    succeeded_sessions = int(_num(summary.get("sessions_succeeded")))
    segments = int(_num(summary.get("segments")))
    failed_segments = int(_num(summary.get("segments_failed")))
    calls = int(_num(summary.get("model_calls"), len(metrics)))
    retries = sum(max(0, int(_num(m.get("attempts"))) - 1) for m in metrics if isinstance(m, dict))
    total_elapsed = _num(run.get("elapsed_seconds"))
    row = {
        "case": item.get("case", Path(run_path).stem),
        "session_concurrency": item.get("session_concurrency"),
        "segment_concurrency": item.get("segment_concurrency"),
        "repeat": item.get("repeat", 1),
        "run_file": str(run_path), "compare_file": str(compare_path or ""),
        "total_elapsed_seconds": total_elapsed,
        "model_calls": calls,
        "model_elapsed_seconds": _num(summary.get("model_elapsed_seconds")),
        "retry_count": retries,
        "final_errors": int(_num(summary.get("errors"), len(run.get("errors") or []))),
        "sessions": sessions, "sessions_succeeded": succeeded_sessions,
        "sessions_partial_failed": int(_num(summary.get("sessions_partial_failed"))),
        "sessions_failed": int(_num(summary.get("sessions_failed"))),
        "segments": segments, "segments_succeeded": max(0, segments - failed_segments),
        "segments_failed": failed_segments,
        "session_completeness": succeeded_sessions / sessions if sessions else None,
        "segment_completeness": (segments - failed_segments) / segments if segments else None,
        "boundary_diffs": int(_num(cs.get("boundary_diffs"))),
        "segment_diffs": int(_num(cs.get("segment_diffs"))),
        "intent_diffs": int(_num(cs.get("intent_diffs"))),
        "business_diffs": int(_num(cs.get("business_diffs"))),
        "sub_function_diffs": int(_num(cs.get("sub_function_diffs"))),
        "turns_union": int(_num(cs.get("turns_union"))),
        "turns_with_any_diff": int(_num(cs.get("turns_with_any_diff"))),
    }
    row["diff_turn_rate"] = row["turns_with_any_diff"] / row["turns_union"] if row["turns_union"] else None
    row["error_rate"] = row["final_errors"] / calls if calls else 0.0
    row["throughput_segments_per_second"] = segments / total_elapsed if total_elapsed > 0 else None
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description="汇总 eval-python run/compare JSON 并发性能结果")
    parser.add_argument("manifest", type=Path, help="实验清单 JSON 文件")
    parser.add_argument("--output-dir", type=Path, default=None, help="输出目录，默认与清单同目录")
    args = parser.parse_args()
    manifest = load(args.manifest)
    cases = manifest.get("cases") if isinstance(manifest, dict) else manifest
    if not isinstance(cases, list) or not cases:
        raise SystemExit("manifest must contain a non-empty 'cases' array")
    rows = [analyze_case(case) for case in cases]
    out_dir = args.output_dir or args.manifest.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "concurrency_analysis.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PERF_FIELDS)
        writer.writeheader(); writer.writerows(rows)
    (out_dir / "concurrency_analysis.json").write_text(json.dumps({"cases": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"json": str(out_dir / "concurrency_analysis.json"), "csv": str(out_dir / "concurrency_analysis.csv"), "cases": len(rows)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
