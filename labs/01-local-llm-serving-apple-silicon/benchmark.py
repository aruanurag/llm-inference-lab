#!/usr/bin/env python3
"""Small streaming benchmark for OpenAI-compatible local chat servers.

This script sends chat-completion requests to a local server such as
`llama-server` and records the timing behavior we care about in this lab.

The important detail is that requests are streamed. Streaming lets us measure
TTFT, which is the time between sending the request and receiving the first
non-empty generated text chunk.

The script also estimates ITL as inter-chunk latency: the time gaps between
non-empty streamed text chunks. This is close to inter-token latency for many
local streaming runs, but a streamed chunk is not guaranteed to equal exactly
one tokenizer token.
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


@dataclass
class RequestMetrics:
    """Metrics captured for one HTTP request.

    The benchmark stores one of these records per request so that the raw result
    file can be inspected later, not just the aggregate summary.
    """

    experiment: str
    request_id: int
    concurrency: int
    prompt_chars: int
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
    output_text: str

    @property
    def output_chars_per_second(self) -> float:
        """Approximate output speed for this one request.

        This uses characters instead of tokens because different local servers
        expose token accounting differently. It is good enough for comparing
        runs in this first lab, but later labs can add tokenizer-based counts.
        """

        if self.latency_seconds <= 0:
            return 0.0
        return self.output_chars / self.latency_seconds


def parse_args() -> argparse.Namespace:
    """Define the benchmark controls exposed on the command line."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8080/v1/chat/completions")
    parser.add_argument("--model", default="local-model")
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
    """Load a prompt either directly from --prompt or from --prompt-file."""

    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8")
    if args.prompt:
        return args.prompt
    raise SystemExit("Provide --prompt or --prompt-file")


def percentile(values: list[float], pct: float) -> float | None:
    """Return an approximate percentile from a small local result set."""

    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((pct / 100) * (len(ordered) - 1)))
    return ordered[index]


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
    """Send one streaming chat-completion request and measure its timing.

    This is the core benchmark function:

    1. Build an OpenAI-compatible chat completion payload.
    2. Set `"stream": True` so the server returns token chunks as they are ready.
    3. Start a high-resolution timer immediately before the HTTP request.
    4. Read each server-sent event line from the response.
    5. Record the timestamp of the first generated text chunk as TTFT.
    6. Record total request latency when the stream ends.

    For `llama-server`, streamed responses look like lines prefixed with
    `data:`. The last line is usually `data: [DONE]`.
    """

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

    # perf_counter is monotonic and precise enough for latency measurement.
    started = time.perf_counter()
    first_token_at: float | None = None
    chunks = 0
    output_parts: list[str] = []
    error: str | None = None
    status = "ok"
    chunk_timestamps: list[float] = []

    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            for raw_line in response:
                # OpenAI-compatible streaming APIs commonly use server-sent
                # event lines. Empty lines and non-data lines are ignored.
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue

                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break

                token_text = extract_delta_text(data)
                if token_text:
                    # TTFT is measured at the first non-empty content chunk,
                    # not at the first HTTP byte. This better represents when
                    # useful generated text begins to arrive.
                    chunk_at = time.perf_counter()
                    if first_token_at is None:
                        first_token_at = chunk_at
                    chunk_timestamps.append(chunk_at)
                    output_parts.append(token_text)
                    chunks += 1
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
        request_id=request_id,
        concurrency=concurrency,
        prompt_chars=len(prompt),
        max_tokens=max_tokens,
        status=status,
        error=error,
        started_at=started,
        ended_at=ended,
        ttft_seconds=None if first_token_at is None else first_token_at - started,
        latency_seconds=ended - started,
        streamed_chunks=chunks,
        chunk_timestamps=chunk_timestamps,
        inter_chunk_latencies_seconds=inter_chunk_latencies,
        mean_itl_seconds=(
            statistics.mean(inter_chunk_latencies) if inter_chunk_latencies else None
        ),
        p50_itl_seconds=percentile(inter_chunk_latencies, 50),
        p95_itl_seconds=percentile(inter_chunk_latencies, 95),
        output_chars=len(output_text),
        output_text=output_text,
    )


def extract_delta_text(data: str) -> str:
    """Extract generated text from one streamed OpenAI-style JSON event."""

    parsed: dict[str, Any] = json.loads(data)
    choices = parsed.get("choices", [])
    if not choices:
        return ""
    delta = choices[0].get("delta", {})
    return delta.get("content") or ""


async def run_one(args: argparse.Namespace, prompt: str, request_id: int) -> RequestMetrics:
    """Run one blocking HTTP request in a worker thread.

    urllib is synchronous, so asyncio.to_thread lets multiple requests run at
    once without adding third-party dependencies.
    """

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
    """Run N requests while limiting the number active at the same time.

    `--requests` controls total work.
    `--concurrency` controls how many requests are in flight together.

    Example: requests=12 and concurrency=4 means run 12 total requests, with at
    most 4 active at any instant.
    """

    semaphore = asyncio.Semaphore(args.concurrency)

    async def limited(request_id: int) -> RequestMetrics:
        async with semaphore:
            return await run_one(args, prompt, request_id)

    tasks = [limited(i + 1) for i in range(args.requests)]
    return await asyncio.gather(*tasks)


def summarize(results: list[RequestMetrics]) -> dict[str, Any]:
    """Aggregate per-request measurements into lab-friendly summary metrics."""

    latencies = [r.latency_seconds for r in results if r.status == "ok"]
    ttfts = [r.ttft_seconds for r in results if r.status == "ok" and r.ttft_seconds is not None]
    itls = [
        itl
        for r in results
        if r.status == "ok"
        for itl in r.inter_chunk_latencies_seconds
    ]
    total_chars = sum(r.output_chars for r in results if r.status == "ok")

    # Wall time spans the first request start to the last request finish. This
    # is what we use for requests/sec across a concurrent run.
    wall_seconds = max(r.ended_at for r in results) - min(r.started_at for r in results)

    return {
        "experiment": results[0].experiment if results else None,
        "requests": len(results),
        "successful_requests": sum(1 for r in results if r.status == "ok"),
        "concurrency": results[0].concurrency if results else None,
        "wall_seconds": wall_seconds,
        "requests_per_second": len(results) / wall_seconds if wall_seconds > 0 else 0.0,
        "output_chars_per_second": total_chars / wall_seconds if wall_seconds > 0 else 0.0,
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
    """CLI entry point used by the tutorial commands."""

    args = parse_args()
    prompt = load_prompt(args)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # If the user asks for concurrency higher than total request count, increase
    # total requests so the requested concurrency is actually exercised.
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
