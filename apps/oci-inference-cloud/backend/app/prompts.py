from __future__ import annotations

from pathlib import Path

from .config import PROMPTS_DIR
from .state import list_prompt_sets, upsert_prompt_set


DEFAULT_PROMPT_SETS = [
    {
        "name": "Latency smoke prompts",
        "filename": "latency-smoke-prompts.txt",
        "description": "Short factual prompts with short answers. Use this first to validate the server and measure latency, TTFT, and approximate ITL.",
        "text": """Explain KV cache in two sentences.

Explain why batching improves LLM inference throughput.

Define time to first token in one sentence.

Explain what quantization changes in a local LLM.
""",
    },
    {
        "name": "Inference learning prompts",
        "filename": "inference-learning-prompts.txt",
        "description": "Medium educational prompts about serving concepts. Useful for comparing normal assistant workloads at low to moderate concurrency.",
        "text": """Explain KV cache in two sentences.

Explain why batching improves LLM inference throughput.

Write a compact tutorial on prefill versus decode.

Explain how prompt length affects time to first token.

Explain the difference between throughput and latency in LLM inference.
""",
    },
    {
        "name": "Long context prefill prompts",
        "filename": "long-context-prefill-prompts.txt",
        "description": "Longer prompts that force more prefill work before generation starts. Use this to observe TTFT changes and CPU prompt-processing cost.",
        "text": """You are preparing a technical note for a new engineer. Explain local LLM serving with llama.cpp, including GGUF models, quantization, context size, batching, prompt processing, decode, and why CPU inference behaves differently from GPU inference. Keep the answer structured.

Summarize the following scenario and identify likely bottlenecks: a CPU instance is running llama-server with a small quantized instruct model. Users send a mix of short and long prompts. Concurrency increases from one to eight. The team observes that time to first token rises before output throughput improves. Explain what is happening.

Write a detailed explanation of how request batching changes resource utilization during LLM inference. Include prefill, decode, queueing delay, concurrency, and why p95 latency can increase while aggregate throughput improves.
""",
    },
    {
        "name": "Long decode prompts",
        "filename": "long-decode-prompts.txt",
        "description": "Short prompts that request longer answers. Use this to stress decode throughput and compare output characters/sec or approximate tokens/sec.",
        "text": """Write a detailed checklist for benchmarking a local LLM server.

Create a step-by-step guide for tuning llama.cpp server settings on a CPU instance.

Write a detailed comparison of CPU inference and GPU inference for small language models.
""",
    },
    {
        "name": "Concurrency mixed workload",
        "filename": "concurrency-mixed-workload.txt",
        "description": "Mixed short and medium prompts intended for concurrency tests. Use this with concurrency 2, 4, 8, or higher to inspect queueing and throughput.",
        "text": """Give three reasons TTFT can increase under load.

Explain batching to a backend engineer.

Write a concise incident note for an inference service with high p95 latency.

Explain how max tokens affects benchmark duration.

List the metrics a team should track when comparing two inference server configurations.
""",
    },
    {
        "name": "Throughput comparison prompts",
        "filename": "throughput-comparison-prompts.txt",
        "description": "Repeatable prompts for model, shape, and deploy-setting throughput tests. Use the same prompt set, model, max tokens, and concurrency across runs.",
        "text": """Write a practical checklist for deciding whether CPU inference is enough for a hackathon app.

Explain how output tokens per second changes when concurrency increases.

Summarize why larger shapes or optimized deploy settings can improve aggregate throughput for many simultaneous users.

Create a short decision guide for routing requests between a local inference endpoint and an external model endpoint.

Explain the difference between per-request latency and aggregate throughput in LLM serving.

List the measurements needed to compare two OCI shapes or two llama.cpp model configurations.
""",
    },
]


def parse_prompt_file(text: str) -> list[str]:
    return [chunk.strip() for chunk in text.split("\n\n") if chunk.strip()]


def seed_default_prompts() -> None:
    list_prompt_sets()
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    for prompt_set in DEFAULT_PROMPT_SETS:
        path = PROMPTS_DIR / prompt_set["filename"]
        path.write_text(prompt_set["text"], encoding="utf-8")
        upsert_prompt_set(
            prompt_set["name"],
            path,
            len(parse_prompt_file(prompt_set["text"])),
            prompt_set["description"],
        )


def read_prompt_set(path: str | Path) -> list[str]:
    return parse_prompt_file(Path(path).read_text(encoding="utf-8"))
