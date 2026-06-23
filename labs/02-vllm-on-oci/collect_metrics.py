#!/usr/bin/env python3
"""Collect Lab 2 raw benchmark JSON files into summary JSON and CSV."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="results/raw")
    parser.add_argument("--output", default="results/summary.json")
    parser.add_argument("--csv-output", default="results/summary.csv")
    parser.add_argument("--hourly-cost-usd", type=float)
    return parser.parse_args()


def cost_for_wall_time(wall_seconds: float | None, hourly_cost: float | None) -> float | None:
    if wall_seconds is None or hourly_cost is None:
        return None
    return (wall_seconds / 3600.0) * hourly_cost


def cost_per_million_tokens(
    run_cost: float | None,
    approx_output_tokens: float | None,
) -> float | None:
    if run_cost is None or not approx_output_tokens:
        return None
    return run_cost / (approx_output_tokens / 1_000_000.0)


def flatten_summary(
    path: Path,
    summary: dict[str, Any],
    hourly_cost: float | None,
) -> dict[str, Any]:
    latency = summary.get("latency_seconds", {})
    ttft = summary.get("ttft_seconds", {})
    approx_itl = summary.get("approx_itl_seconds", {})
    wall_seconds = summary.get("wall_seconds")
    approx_output_tokens = summary.get("approx_output_tokens")
    run_cost = cost_for_wall_time(wall_seconds, hourly_cost)

    return {
        "file": str(path),
        "experiment": summary.get("experiment"),
        "model": summary.get("model"),
        "requests": summary.get("requests"),
        "successful_requests": summary.get("successful_requests"),
        "concurrency": summary.get("concurrency"),
        "wall_seconds": wall_seconds,
        "requests_per_second": summary.get("requests_per_second"),
        "output_chars": summary.get("output_chars"),
        "output_chars_per_second": summary.get("output_chars_per_second"),
        "approx_output_tokens": approx_output_tokens,
        "approx_output_tokens_per_second": summary.get("approx_output_tokens_per_second"),
        "latency_p50_seconds": latency.get("p50"),
        "latency_p95_seconds": latency.get("p95"),
        "latency_p99_seconds": latency.get("p99"),
        "ttft_p50_seconds": ttft.get("p50"),
        "ttft_p95_seconds": ttft.get("p95"),
        "ttft_p99_seconds": ttft.get("p99"),
        "approx_itl_p50_seconds": approx_itl.get("p50"),
        "approx_itl_p95_seconds": approx_itl.get("p95"),
        "approx_itl_p99_seconds": approx_itl.get("p99"),
        "hourly_cost_usd": hourly_cost,
        "estimated_run_cost_usd": run_cost,
        "estimated_cost_per_million_output_tokens_usd": cost_per_million_tokens(
            run_cost,
            approx_output_tokens,
        ),
    }


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input)
    output_path = Path(args.output)
    csv_path = Path(args.csv_output)

    rows: list[dict[str, Any]] = []
    for path in sorted(input_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        summary = data.get("summary")
        if summary:
            rows.append(flatten_summary(path, summary, args.hourly_cost_usd))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    if rows:
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    print(f"Collected {len(rows)} benchmark files")
    print(f"Wrote {output_path}")
    print(f"Wrote {csv_path}")


if __name__ == "__main__":
    main()
