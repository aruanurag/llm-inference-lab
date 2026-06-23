#!/usr/bin/env python3
"""Streaming benchmark for vLLM OpenAI-compatible GPU servers.

This script measures the same user-visible inference behavior as Lab 1:
TTFT, approximate ITL, end-to-end latency, throughput, and concurrency.

Approximate ITL is measured from gaps between non-empty streamed text chunks.
A streamed chunk is not guaranteed to equal one tokenizer token, so this is a
practical serving-level estimate rather than exact tokenizer-level ITL.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


CHARS_PER_TOKEN_ESTIMATE = 4.0


@dataclass
class RequestMetrics:
    experiment: str
    model: str
    request_id: int
    concurrency: int
    prompt_chars: int
    approx_prompt_tokens: float
    max_tokens: int
    status: str
    error: str | None
    started_at: float
    ended_at: float
    ttft_seconds: float | None
    latency_seconds: float
    streamed_chunks: int
    chunk_timestamps: list[float]
    inter_chunk_latencies_seconds: list[float]
    mean_itl_seconds: float | None
    p50_itl_seconds: float | None
    p95_itl_seconds: float | None
    output_chars: int
    approx_output_tokens: float
    output_text: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000/v1/chat/completions")
    parser.add_argument("--model", default="Qwen/Qwen2.5-1.5B-Instruct")
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--prompt")
    parser.add_argument("--prompt-file")
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--requests", type=int, default=1)
    parser.add_argument("--output-dir", default="results/raw")
    return parser.parse_args()


def load_prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8")
    if args.prompt:
        return args.prompt
    raise SystemExit("Provide --prompt or --prompt-file")


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((pct / 100) * (len(ordered) - 1)))
    return ordered[index]


def estimate_tokens(text: str) -> float:
    return len(text) / CHARS_PER_TOKEN_ESTIMATE


def extract_delta_text(data: str) -> str:
    parsed: dict[str, Any] = json.loads(data)
    choices = parsed.get("choices", [])
    if not choices:
        return ""
    delta = choices[0].get("delta", {})
    return delta.get("content") or ""


def post_streaming_request(
    *,
    url: str,
    model: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
    experiment: str,
    request_id: int,
    concurrency: int,
) -> RequestMetrics:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    started = time.perf_counter()
    first_token_at: float | None = None
    chunk_timestamps: list[float] = []
    output_parts: list[str] = []
    error: str | None = None
    status = "ok"

    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                token_text = extract_delta_text(data)
                if token_text:
                    chunk_at = time.perf_counter()
                    if first_token_at is None:
                        first_token_at = chunk_at
                    chunk_timestamps.append(chunk_at)
                    output_parts.append(token_text)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        status = "error"
        error = str(exc)

    ended = time.perf_counter()
    output_text = "".join(output_parts)
    inter_chunk_latencies = [
        later - earlier
        for earlier, later in zip(chunk_timestamps, chunk_timestamps[1:])
    ]

    return RequestMetrics(
        experiment=experiment,
        model=model,
        request_id=request_id,
        concurrency=concurrency,
        prompt_chars=len(prompt),
        approx_prompt_tokens=estimate_tokens(prompt),
        max_tokens=max_tokens,
        status=status,
        error=error,
        started_at=started,
        ended_at=ended,
        ttft_seconds=None if first_token_at is None else first_token_at - started,
        latency_seconds=ended - started,
        streamed_chunks=len(chunk_timestamps),
        chunk_timestamps=chunk_timestamps,
        inter_chunk_latencies_seconds=inter_chunk_latencies,
        mean_itl_seconds=(
            statistics.mean(inter_chunk_latencies) if inter_chunk_latencies else None
        ),
        p50_itl_seconds=percentile(inter_chunk_latencies, 50),
        p95_itl_seconds=percentile(inter_chunk_latencies, 95),
        output_chars=len(output_text),
        approx_output_tokens=estimate_tokens(output_text),
        output_text=output_text,
    )


async def run_one(args: argparse.Namespace, prompt: str, request_id: int) -> RequestMetrics:
    return await asyncio.to_thread(
        post_streaming_request,
        url=args.url,
        model=args.model,
        prompt=prompt,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        experiment=args.experiment,
        request_id=request_id,
        concurrency=args.concurrency,
    )


async def run_benchmark(args: argparse.Namespace, prompt: str) -> list[RequestMetrics]:
    semaphore = asyncio.Semaphore(args.concurrency)

    async def limited(request_id: int) -> RequestMetrics:
        async with semaphore:
            return await run_one(args, prompt, request_id)

    tasks = [limited(i + 1) for i in range(args.requests)]
    return await asyncio.gather(*tasks)


def summarize(results: list[RequestMetrics]) -> dict[str, Any]:
    if not results:
        return {}

    latencies = [r.latency_seconds for r in results if r.status == "ok"]
    ttfts = [r.ttft_seconds for r in results if r.status == "ok" and r.ttft_seconds is not None]
    itls = [
        itl
        for r in results
        if r.status == "ok"
        for itl in r.inter_chunk_latencies_seconds
    ]
    output_chars = sum(r.output_chars for r in results if r.status == "ok")
    approx_output_tokens = sum(r.approx_output_tokens for r in results if r.status == "ok")
    wall_seconds = max(r.ended_at for r in results) - min(r.started_at for r in results)

    return {
        "experiment": results[0].experiment,
        "model": results[0].model,
        "requests": len(results),
        "successful_requests": sum(1 for r in results if r.status == "ok"),
        "concurrency": results[0].concurrency,
        "wall_seconds": wall_seconds,
        "requests_per_second": len(results) / wall_seconds if wall_seconds > 0 else 0.0,
        "output_chars": output_chars,
        "output_chars_per_second": output_chars / wall_seconds if wall_seconds > 0 else 0.0,
        "approx_output_tokens": approx_output_tokens,
        "approx_output_tokens_per_second": (
            approx_output_tokens / wall_seconds if wall_seconds > 0 else 0.0
        ),
        "token_estimate_note": "Approximate tokens use output characters / 4.0.",
        "latency_seconds": {
            "min": min(latencies) if latencies else None,
            "mean": statistics.mean(latencies) if latencies else None,
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
            "p99": percentile(latencies, 99),
            "max": max(latencies) if latencies else None,
        },
        "ttft_seconds": {
            "min": min(ttfts) if ttfts else None,
            "mean": statistics.mean(ttfts) if ttfts else None,
            "p50": percentile(ttfts, 50),
            "p95": percentile(ttfts, 95),
            "p99": percentile(ttfts, 99),
            "max": max(ttfts) if ttfts else None,
        },
        "approx_itl_seconds": {
            "note": "Estimated from gaps between non-empty streamed text chunks.",
            "min": min(itls) if itls else None,
            "mean": statistics.mean(itls) if itls else None,
            "p50": percentile(itls, 50),
            "p95": percentile(itls, 95),
            "p99": percentile(itls, 99),
            "max": max(itls) if itls else None,
        },
    }


def main() -> None:
    args = parse_args()
    prompt = load_prompt(args)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.requests < args.concurrency:
        args.requests = args.concurrency

    results = asyncio.run(run_benchmark(args, prompt))
    summary = summarize(results)

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    output_path = output_dir / f"{timestamp}-{args.experiment}.json"
    output_path.write_text(
        json.dumps(
            {
                "summary": summary,
                "requests": [asdict(result) for result in results],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(json.dumps(summary, indent=2))
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
