"""Command-line boundary for analysis and offline comparison."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .compare import compare_artifacts, write_comparison_artifacts
from .config import load_config
from .export import write_run_artifacts
from .input import load_sessions
from .models import EvalPythonError
from .pipeline import run_pipeline
from .taxonomy import load_taxonomy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eval-python",
        description="Qwen Session Episode/Segment evaluator and offline DeepSeek comparison.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="Run Qwen segmentation and export JSON/XLSX results.")
    run.add_argument("--input", required=True, type=Path, help="One-day Session JSON file.")
    run.add_argument("--config", required=True, type=Path, help="YAML configuration file.")
    run.add_argument("--output-dir", type=Path, default=Path("output"), help="Result directory.")

    compare = commands.add_parser(
        "compare",
        help="Compare an existing Qwen JSON result with a Full Conversations XLSX.",
    )
    compare.add_argument("--qwen-json", required=True, type=Path, help="Existing result from run.")
    compare.add_argument(
        "--baseline-xlsx",
        required=True,
        type=Path,
        help="badcaseOps Full Conversations XLSX export.",
    )
    compare.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/comparison"),
        help="Comparison artifact directory.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "run":
            return _run_command(args)
        if args.command == "compare":
            return _compare_command(args)
        raise AssertionError(f"Unhandled command: {args.command}")
    except EvalPythonError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


def _run_command(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    taxonomy = load_taxonomy(config.taxonomy_path)
    sessions = load_sessions(args.input)
    result = run_pipeline(
        sessions,
        config,
        taxonomy,
        input_file=args.input,
        progress=lambda message: print(message, file=sys.stderr, flush=True),
    )
    json_path, xlsx_path = write_run_artifacts(
        result,
        input_path=args.input,
        output_dir=args.output_dir,
    )
    print(json.dumps({
        "json": str(json_path),
        "xlsx": str(xlsx_path),
        "summary": result["summary"],
    }, ensure_ascii=False, indent=2))
    return 0 if result["summary"]["errors"] == 0 else 1


def _compare_command(args: argparse.Namespace) -> int:
    comparison = compare_artifacts(args.qwen_json, args.baseline_xlsx)
    json_path, xlsx_path = write_comparison_artifacts(
        comparison,
        output_dir=args.output_dir,
        qwen_json_path=args.qwen_json,
    )
    print(json.dumps({
        "json": str(json_path),
        "xlsx": str(xlsx_path),
        "summary": comparison["summary"],
    }, ensure_ascii=False, indent=2))
    return 0

