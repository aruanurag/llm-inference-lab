#!/usr/bin/env python3
"""Collect raw benchmark JSON files into summary JSON and CSV."""

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
    return parser.parse_args()


def flatten_summary(path: Path, summary: dict[str, Any]) -> dict[str, Any]:
    latency = summary.get("latency_seconds", {})
    ttft = summary.get("ttft_seconds", {})
    approx_itl = summary.get("approx_itl_seconds", {})
    return {
        "file": str(path),
        "experiment": summary.get("experiment"),
        "requests": summary.get("requests"),
        "successful_requests": summary.get("successful_requests"),
        "concurrency": summary.get("concurrency"),
        "wall_seconds": summary.get("wall_seconds"),
        "requests_per_second": summary.get("requests_per_second"),
        "output_chars_per_second": summary.get("output_chars_per_second"),
        "latency_p50_seconds": latency.get("p50"),
        "latency_p95_seconds": latency.get("p95"),
        "latency_p99_seconds": latency.get("p99"),
        "ttft_p50_seconds": ttft.get("p50"),
        "ttft_p95_seconds": ttft.get("p95"),
        "ttft_p99_seconds": ttft.get("p99"),
        "approx_itl_p50_seconds": approx_itl.get("p50"),
        "approx_itl_p95_seconds": approx_itl.get("p95"),
        "approx_itl_p99_seconds": approx_itl.get("p99"),
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
            rows.append(flatten_summary(path, summary))

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
