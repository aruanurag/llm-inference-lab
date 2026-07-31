from __future__ import annotations

import csv
import io
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


def generated_csv_prompts(count: int, *, long_context: bool = False) -> str:
    """Create deterministic, non-sensitive CSV workloads for the LLM-D lab."""

    topics = [
        "KV cache", "prefill", "decode", "request batching", "queueing", "prefix caching",
        "time to first token", "inter-token latency", "autoscaling", "CPU inference",
        "model routing", "concurrency", "throughput", "tail latency", "token budgeting",
    ]
    tasks = [
        "Explain", "Summarize", "Compare", "Give a practical example of", "List three trade-offs for",
        "Write a troubleshooting note about", "Describe how to measure", "Provide a concise design review for",
        "Explain the failure mode of", "State when to use",
    ]
    rows: list[list[str]] = [["prompt"]]
    context = (
        "A platform team runs an OpenAI-compatible CPU vLLM service behind an LLM-D router. "
        "They compare steady low-concurrency traffic with bursts that create queue pressure. "
        "They observe request throughput, TTFT, inter-token latency, KV-cache usage, active requests, "
        "and scale decisions in Grafana. "
    )
    for index in range(count):
        task, topic = tasks[index % len(tasks)], topics[(index // len(tasks)) % len(topics)]
        prompt = f"{task} {topic} for LLM inference experiment {index + 1}. Give a technically precise answer."
        if long_context:
            prompt = f"{context * 10}\n\n{prompt}\n\nIdentify the likely impact on TTFT, throughput, and scaling demand."
        rows.append([prompt])
    stream = io.StringIO(newline="")
    csv.writer(stream).writerows(rows)
    return stream.getvalue()


def generated_shared_prefix_csv(count: int) -> str:
    """Long requests whose initial tokens are intentionally identical."""

    shared_prefix = (
        "Shared technical briefing: an LLM-D router sends OpenAI-compatible requests to CPU vLLM decode workers. "
        "The team records request throughput, TTFT, inter-token latency, KV-cache usage, prefix-cache hits, "
        "queue depth, and active requests in Prometheus and Grafana. "
    ) * 28
    rows = [["prompt"]]
    for index in range(count):
        rows.append([f"{shared_prefix}\n\nQuestion {index + 1}: Explain one operational implication of this briefing in two paragraphs."])
    stream = io.StringIO(newline="")
    csv.writer(stream).writerows(rows)
    return stream.getvalue()


def generated_cold_long_csv(count: int) -> str:
    """Long requests with an early unique token, avoiding useful shared prefixes."""

    rows = [["prompt"]]
    for index in range(count):
        scenario = (
            f"Scenario-{index + 1:03d} has a distinct workload profile, customer history, and operational constraints. "
            f"Its request identifier is {100_000 + index * 7919}; treat this as independent context. "
        ) * 30
        rows.append([f"{scenario}\n\nSummarize the bottleneck and recommend one LLM serving action."])
    stream = io.StringIO(newline="")
    csv.writer(stream).writerows(rows)
    return stream.getvalue()


def generated_decode_heavy_csv(count: int) -> str:
    """Short inputs that explicitly request sustained generation work."""

    subjects = [
        "CPU continuous batching", "KV-cache management", "LLM-D request routing", "prefill versus decode",
        "tail latency under load", "prefix-cache locality", "KEDA demand scaling", "vLLM scheduling",
        "model-server observability", "throughput versus latency",
    ]
    rows = [["prompt"]]
    for index in range(count):
        subject = subjects[index % len(subjects)]
        rows.append([
            f"Write a detailed technical explanation of {subject} for experiment {index + 1}. "
            "Use approximately 400 words, with an introduction, three concrete mechanisms, and a practical conclusion. "
            "Do not answer in fewer than 300 words."
        ])
    stream = io.StringIO(newline="")
    csv.writer(stream).writerows(rows)
    return stream.getvalue()


DEFAULT_PROMPT_SETS.extend([
    {
        "name": "LLM-D · 100 unique prompts (CSV)",
        "filename": "llmd-100-unique-prompts.csv",
        "description": "100 distinct medium prompts. Set Requests to 100 to send every CSV row once; raise concurrency to create sustained EPP demand.",
        "text": generated_csv_prompts(100),
    },
    {
        "name": "LLM-D · 150 unique prompts (CSV)",
        "filename": "llmd-150-unique-prompts.csv",
        "description": "150 distinct medium prompts for a longer sustained traffic run. Set Requests to 150 to send every row once.",
        "text": generated_csv_prompts(150),
    },
    {
        "name": "LLM-D · long prefill prompts (CSV)",
        "filename": "llmd-long-prefill-prompts.csv",
        "description": "30 long-context prompts. Use this workload to make prefill work and TTFT visible in the LLM-D and vLLM dashboards.",
        "text": generated_csv_prompts(30, long_context=True),
    },
    {
        "name": "LLM-D · warm shared-prefix prompts (CSV)",
        "filename": "llmd-warm-shared-prefix-prompts.csv",
        "description": "100 long requests with the same initial context and unique questions. Use this after a cold run to observe prefix-cache hits and lower TTFT on later requests.",
        "text": generated_shared_prefix_csv(100),
    },
    {
        "name": "LLM-D · cold long unique prompts (CSV)",
        "filename": "llmd-cold-long-unique-prompts.csv",
        "description": "100 long independent requests whose context differs from the first tokens onward. Use as the cache-cold comparison against the shared-prefix workload.",
        "text": generated_cold_long_csv(100),
    },
    {
        "name": "LLM-D · decode-heavy prompts (CSV)",
        "filename": "llmd-decode-heavy-prompts.csv",
        "description": "50 short prompts intended for long outputs. Select this workload and use a larger Max output tokens value to focus on decode throughput and inter-token latency.",
        "text": generated_decode_heavy_csv(50),
    },
])


def parse_prompt_file(text: str, filename: str | None = None) -> list[str]:
    if filename and Path(filename).suffix.lower() == ".csv":
        reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
        if not reader.fieldnames:
            return []
        columns = {name.strip().lower(): name for name in reader.fieldnames if name}
        prompt_column = next((columns[name] for name in ("prompt", "text", "input", "message") if name in columns), None)
        if not prompt_column:
            raise ValueError("CSV prompt files need a prompt, text, input, or message column.")
        return [str(row.get(prompt_column) or "").strip() for row in reader if str(row.get(prompt_column) or "").strip()]
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
            len(parse_prompt_file(prompt_set["text"], prompt_set["filename"])),
            prompt_set["description"],
        )


def read_prompt_set(path: str | Path) -> list[str]:
    source = Path(path)
    return parse_prompt_file(source.read_text(encoding="utf-8"), source.name)
