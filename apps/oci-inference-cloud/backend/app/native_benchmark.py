from __future__ import annotations

import json
import re
import shlex
import textwrap
from typing import Any

from .ssh import run_ssh


BENCHMARK_TOOLS = {
    "http_streaming": "HTTP streaming",
    "llama_bench": "llama-bench",
    "vllm_bench_serve": "vLLM bench serve",
}


def recommended_tool(engine: str | None) -> str:
    if engine == "vllm_cpu":
        return "vllm_bench_serve"
    return "llama_bench"


def _number(value: str) -> float | None:
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


def _match_number(text: str, *labels: str) -> float | None:
    for label in labels:
        pattern = rf"{re.escape(label)}\s*[:=]\s*([0-9][0-9,]*(?:\.[0-9]+)?)"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _number(match.group(1))
    return None


def _match_ms(text: str, *labels: str) -> float | None:
    value = _match_number(text, *labels)
    return value / 1000 if value is not None else None


def _llama_bench_records(stdout: str) -> list[dict[str, Any]]:
    """Extract llama-bench's JSON array even if a login shell printed text first."""
    match = re.search(r"(?ms)^\s*\[\s*\{.*\}\s*\]\s*$", stdout)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return [item for item in data if isinstance(item, dict)]


def _native_summary(
    *,
    tool: str,
    engine: str,
    model: str,
    requests: int,
    concurrency: int,
    max_tokens: int,
    prompt_count: int,
    prompt_tokens: int,
    stdout: str,
) -> dict[str, Any]:
    """Normalize the useful fields from native tool output without fabricating metrics.

    llama-bench is a model microbenchmark, while vLLM bench serve is a serving
    workload. Fields the selected tool does not emit stay ``None`` so result
    tables do not accidentally compare unlike measurements.
    """
    summary: dict[str, Any] = {
        "benchmark_tool": tool,
        "benchmark_tool_label": BENCHMARK_TOOLS[tool],
        "benchmark_kind": "engine-native",
        "inference_engine": engine,
        "model": model,
        "requests": requests,
        "successful_requests": None,
        "concurrency": concurrency,
        "prompt_count": prompt_count,
        "prompt_tokens_requested": prompt_tokens,
        "max_tokens": max_tokens,
        "wall_seconds": None,
        "requests_per_second": None,
        "output_chars": None,
        "output_chars_per_second": None,
        "approx_output_tokens": None,
        "approx_output_tokens_per_second": None,
        "latency_seconds": {"mean": None, "p50": None, "p95": None, "p99": None},
        "ttft_seconds": {"mean": None, "p50": None, "p95": None, "p99": None},
        "approx_itl_seconds": {"note": "Native tool did not emit a token-stream ITL metric.", "mean": None, "p50": None, "p95": None, "p99": None},
    }

    if tool == "vllm_bench_serve":
        summary["successful_requests"] = _match_number(stdout, "Successful requests")
        summary["wall_seconds"] = _match_number(stdout, "Benchmark duration (s)", "Duration (s)")
        summary["requests_per_second"] = _match_number(stdout, "Request throughput (req/s)", "Request throughput")
        output_tps = _match_number(stdout, "Output token throughput (tok/s)", "Output token throughput")
        summary["approx_output_tokens_per_second"] = output_tps
        summary["ttft_seconds"] = {
            "mean": _match_ms(stdout, "Mean TTFT (ms)"),
            "p50": _match_ms(stdout, "Median TTFT (ms)", "P50 TTFT (ms)"),
            "p95": _match_ms(stdout, "P95 TTFT (ms)"),
            "p99": _match_ms(stdout, "P99 TTFT (ms)"),
        }
        summary["approx_itl_seconds"] = {
            "note": "vLLM reports time per output token (TPOT); it is a serving-side approximation of inter-token latency.",
            "mean": _match_ms(stdout, "Mean TPOT (ms)"),
            "p50": _match_ms(stdout, "Median TPOT (ms)", "P50 TPOT (ms)"),
            "p95": _match_ms(stdout, "P95 TPOT (ms)"),
            "p99": _match_ms(stdout, "P99 TPOT (ms)"),
        }
    else:
        records = _llama_bench_records(stdout)
        prompt_record = next((item for item in records if int(item.get("n_prompt") or 0) > 0), {})
        decode_record = next((item for item in records if int(item.get("n_gen") or 0) > 0), {})
        prompt_tps = prompt_record.get("avg_ts") or _match_number(stdout, "prompt t/s", "prompt tokens/s")
        decode_tps = decode_record.get("avg_ts") or _match_number(stdout, "gen t/s", "decode t/s", "generation tokens/s")
        summary["successful_requests"] = requests
        summary["native_repetitions"] = requests
        summary["prompt_tokens_per_second"] = prompt_tps
        summary["decode_tokens_per_second"] = decode_tps
        # Reuse the output-throughput field for chart/table continuity, but
        # preserve the explicit name above so it cannot be confused with an
        # end-to-end stream measurement.
        summary["approx_output_tokens_per_second"] = decode_tps
        summary["native_metric_note"] = "llama-bench completed isolated prompt and generation repetitions; it does not issue networked requests and therefore has no TTFT or HTTP request rate."
    return summary


def native_benchmark_script(
    *,
    tool: str,
    model: dict[str, Any],
    prompt_tokens: int,
    max_tokens: int,
    requests: int,
    concurrency: int,
) -> str:
    if tool == "llama_bench":
        model_filename = shlex.quote(model["filename"])
        return textwrap.dedent(
            f"""
            set -euo pipefail
            MODEL_FILENAME={model_filename}
            MODEL_PATH="$HOME/oci-inference-cloud/models/$MODEL_FILENAME"
            BENCH="$HOME/oci-inference-cloud/llama.cpp/build/bin/llama-bench"
            test -x "$BENCH" || {{ echo "llama-bench is not installed; deploy llama.cpp first."; exit 1; }}
            test -f "$MODEL_PATH" || {{ echo "Model file is missing: $MODEL_PATH"; exit 1; }}
            "$BENCH" -m "$MODEL_PATH" -p {prompt_tokens} -n {max_tokens} -r {requests} -o json
            """
        ).strip()
    if tool == "vllm_bench_serve":
        model_ref = shlex.quote(model["url"])
        return textwrap.dedent(
            f"""
            set -euo pipefail
            VENV="$HOME/oci-inference-cloud/vllm-cpu-venv"
            test -x "$VENV/bin/vllm" || {{ echo "CPU vLLM is not installed; deploy CPU vLLM first."; exit 1; }}
            test -f "$HOME/oci-inference-cloud/vllm-cpu.env" && source "$HOME/oci-inference-cloud/vllm-cpu.env" || true
            "$VENV/bin/vllm" bench serve \\
              --backend openai-chat \\
              --host 127.0.0.1 --port 8080 \\
              --model {model_ref} \\
              --random-input-len {prompt_tokens} \\
              --random-output-len {max_tokens} \\
              --num-prompts {requests} \\
              --max-concurrency {concurrency}
            """
        ).strip()
    raise ValueError(f"Unknown native benchmark tool: {tool}")


def run_native_benchmark(
    *,
    private_key_path: str,
    user: str,
    host: str,
    tool: str,
    engine: str | None,
    model: dict[str, Any],
    prompts: list[str],
    requests: int,
    concurrency: int,
    max_tokens: int,
) -> dict[str, Any]:
    expected = recommended_tool(engine)
    if tool != expected:
        raise ValueError(f"{BENCHMARK_TOOLS.get(tool, tool)} does not match the deployed {engine or 'unknown'} engine. Choose {BENCHMARK_TOOLS[expected]} or HTTP streaming.")
    prompt_tokens = max(1, round(sum(len(prompt) for prompt in prompts) / len(prompts) / 4))
    script = native_benchmark_script(
        tool=tool,
        model=model,
        prompt_tokens=prompt_tokens,
        max_tokens=max_tokens,
        requests=requests,
        concurrency=concurrency,
    )
    result = run_ssh(private_key_path, user, host, script, timeout=None)
    raw = {"tool": tool, "engine": engine, "command_output": result.stdout, "command_error": result.stderr, "returncode": result.returncode}
    if result.returncode != 0:
        tail = "\n".join((result.stdout + "\n" + result.stderr).splitlines()[-40:])
        raise RuntimeError(f"{BENCHMARK_TOOLS[tool]} failed. Last output lines:\n{tail}")
    return {
        "summary": _native_summary(
            tool=tool,
            engine=engine or "unknown",
            model=model["name"],
            requests=requests,
            concurrency=concurrency,
            max_tokens=max_tokens,
            prompt_count=len(prompts),
            prompt_tokens=prompt_tokens,
            stdout=result.stdout,
        ),
        "requests": [],
        "native_output": raw,
    }
