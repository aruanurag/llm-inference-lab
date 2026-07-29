from __future__ import annotations

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
    request_id: int
    prompt_index: int
    status: str
    error: str | None
    prompt_chars: int
    max_tokens: int
    started_at: float
    ended_at: float
    ttft_seconds: float | None
    latency_seconds: float
    streamed_chunks: int
    inter_chunk_latencies_seconds: list[float]
    output_chars: int
    output_text: str


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((pct / 100) * (len(ordered) - 1)))
    return ordered[index]


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
    prompt: str,
    prompt_index: int,
    request_id: int,
    max_tokens: int,
    temperature: float,
    model: str = "local-model",
) -> RequestMetrics:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    started = time.perf_counter()
    first_token_at: float | None = None
    chunk_times: list[float] = []
    output_parts: list[str] = []
    status = "ok"
    error: str | None = None

    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                text = extract_delta_text(data)
                if text:
                    now = time.perf_counter()
                    if first_token_at is None:
                        first_token_at = now
                    chunk_times.append(now)
                    output_parts.append(text)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        status = "error"
        error = str(exc)

    ended = time.perf_counter()
    output_text = "".join(output_parts)
    return RequestMetrics(
        request_id=request_id,
        prompt_index=prompt_index,
        status=status,
        error=error,
        prompt_chars=len(prompt),
        max_tokens=max_tokens,
        started_at=started,
        ended_at=ended,
        ttft_seconds=None if first_token_at is None else first_token_at - started,
        latency_seconds=ended - started,
        streamed_chunks=len(chunk_times),
        inter_chunk_latencies_seconds=[later - earlier for earlier, later in zip(chunk_times, chunk_times[1:])],
        output_chars=len(output_text),
        output_text=output_text,
    )


async def run_benchmark(
    *,
    url: str,
    prompts: list[str],
    concurrency: int,
    requests: int,
    max_tokens: int,
    temperature: float,
    model: str = "local-model",
) -> dict[str, Any]:
    semaphore = asyncio.Semaphore(concurrency)

    async def one(request_id: int) -> RequestMetrics:
        prompt_index = (request_id - 1) % len(prompts)
        async with semaphore:
            return await asyncio.to_thread(
                post_streaming_request,
                url=url,
                prompt=prompts[prompt_index],
                prompt_index=prompt_index,
                request_id=request_id,
                max_tokens=max_tokens,
                temperature=temperature,
                model=model,
            )

    results = await asyncio.gather(*[one(i + 1) for i in range(max(requests, concurrency))])
    latencies = [result.latency_seconds for result in results if result.status == "ok"]
    ttfts = [result.ttft_seconds for result in results if result.status == "ok" and result.ttft_seconds is not None]
    itls = [itl for result in results if result.status == "ok" for itl in result.inter_chunk_latencies_seconds]
    output_chars = sum(result.output_chars for result in results if result.status == "ok")
    wall_seconds = max(result.ended_at for result in results) - min(result.started_at for result in results)
    approx_output_tokens = output_chars / 4

    summary = {
        "requests": len(results),
        "successful_requests": sum(1 for result in results if result.status == "ok"),
        "concurrency": concurrency,
        "prompt_count": len(prompts),
        "max_tokens": max_tokens,
        "wall_seconds": wall_seconds,
        "requests_per_second": sum(1 for result in results if result.status == "ok") / wall_seconds if wall_seconds > 0 else 0,
        "output_chars": output_chars,
        "output_chars_per_second": output_chars / wall_seconds if wall_seconds > 0 else 0,
        "approx_output_tokens": approx_output_tokens,
        "approx_output_tokens_per_second": approx_output_tokens / wall_seconds if wall_seconds > 0 else 0,
        "latency_seconds": {
            "mean": statistics.mean(latencies) if latencies else None,
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
            "p99": percentile(latencies, 99),
        },
        "ttft_seconds": {
            "mean": statistics.mean(ttfts) if ttfts else None,
            "p50": percentile(ttfts, 50),
            "p95": percentile(ttfts, 95),
            "p99": percentile(ttfts, 99),
        },
        "approx_itl_seconds": {
            "note": "Estimated from gaps between non-empty streamed text chunks.",
            "mean": statistics.mean(itls) if itls else None,
            "p50": percentile(itls, 50),
            "p95": percentile(itls, 95),
            "p99": percentile(itls, 99),
        },
    }
    return {"summary": summary, "requests": [asdict(result) for result in results]}


def write_benchmark_result(output_dir: Path, name: str, data: dict[str, Any]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    raw_path = output_dir / f"{timestamp}-{name}.json"
    summary_path = output_dir / f"{timestamp}-{name}-summary.json"
    raw_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    summary_path.write_text(json.dumps(data["summary"], indent=2), encoding="utf-8")
    return raw_path, summary_path
