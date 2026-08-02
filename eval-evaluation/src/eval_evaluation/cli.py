"""CLI for independent episode-level segment evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .alignment import align_and_evaluate
from .export import write_artifacts
from .input_deepseek import load_deepseek_episodes
from .input_qwen import load_qwen_run, qwen_episodes, run_observability
from .metrics import aggregate, classification_summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eval-evaluation", description="Evaluate Qwen segment boundaries against DeepSeek XLSX labels.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    evaluate = commands.add_parser("evaluate", help="Evaluate one Qwen run JSON against one DeepSeek XLSX.")
    evaluate.add_argument("--qwen-json", required=True, type=Path)
    evaluate.add_argument("--deepseek-xlsx", required=True, type=Path)
    evaluate.add_argument("--output-dir", required=True, type=Path)
    evaluate.add_argument("--deepseek-sheet")
    evaluate.add_argument("--loose-tolerance", type=int, default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.loose_tolerance < 0:
            raise ValueError("--loose-tolerance must be non-negative")
        qwen_run = load_qwen_run(args.qwen_json)
        qwen, qwen_excluded = qwen_episodes(qwen_run)
        deepseek, sheet = load_deepseek_episodes(args.deepseek_xlsx, args.deepseek_sheet)
        episodes, alignment_excluded = align_and_evaluate(qwen, deepseek, args.loose_tolerance)
        observability = run_observability(qwen_run, qwen_excluded)
        observability["deepseek_episodes_observed"] = len(deepseek)
        observability["qwen_successful_episodes_loaded"] = len(qwen)
        observability["comparable_episodes"] = len(episodes)
        result = {
            "schema_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "sources": {"qwen_json": str(args.qwen_json.resolve()), "deepseek_xlsx": str(args.deepseek_xlsx.resolve()), "deepseek_sheet": sheet},
            "evaluation_config": {"episode_alignment_key": ["session_id", "start_turn", "end_turn"], "strict_tolerance": 0, "loose_tolerance": args.loose_tolerance, "boundary_definition": "Every non-final segment end, compared by ordered effective-turn position."},
            "run_observability": observability,
            "alignment_excluded": alignment_excluded,
            "summary": {"comparable_episodes": len(episodes), "strict": aggregate(episodes, "strict"), "loose": aggregate(episodes, "loose"), "classification": classification_summary(episodes)},
            "episodes": episodes,
        }
        json_path, xlsx_path = write_artifacts(result, args.qwen_json, args.output_dir)
        print(json.dumps({"json": str(json_path), "xlsx": str(xlsx_path), "summary": result["summary"]}, ensure_ascii=False, indent=2))
        return 0
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

