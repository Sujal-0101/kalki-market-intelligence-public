"""Offline CLI for reproducible Phase 13 reports."""

from __future__ import annotations

import argparse
from pathlib import Path

from kalki_market_intelligence.backtesting.engine import evaluate_dataset, load_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a point-in-time historical dataset")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate_dataset(load_dataset(args.dataset))
    rendered = report.model_dump_json(indent=2)
    if args.output is None:
        print(rendered)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0
