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
        "name": "TTFT shape comparison · 24 unique long prompts",
        "filename": "ttft-shape-comparison-24-unique-long-prompts.txt",
        "description": "Twenty-four distinct long prompts for a matched CPU-shape TTFT test. Use concurrency 1, requests 24, and max tokens 128; warm up first, then compare TTFT p95 across shapes.",
        "text": """Write a structured technical briefing on the LLM inference prefill phase for a CPU-hosted model. Explain tokenization, prompt evaluation, attention over the input context, KV-cache creation, and the moment the first output token becomes available. Include three likely CPU bottlenecks and how each would appear in a TTFT measurement.

An engineering team serves a quantized 7B instruct model on a CPU VM. A user sends a long policy document and asks for a concise summary. Describe the end-to-end work that occurs before the first generated token, then propose a fair experiment for comparing that prefill work across two otherwise identical CPU shapes.

Create a detailed troubleshooting guide for unexpectedly high time to first token in a local llama.cpp server. Cover input length, model size, quantization, CPU thread placement, memory locality, batch configuration, server queueing, and cold versus warm process state. Distinguish measurement evidence from assumptions.

Explain why a request with a long prompt and a short answer is useful for isolating prefill performance. Contrast it with a short prompt and a very long answer, and describe which latency measurements each workload emphasizes. Use a concrete CPU inference example throughout.

Write a design-review note for a team comparing two OCI CPU shapes with the same OCPU and memory allocation. They want to know whether one shape reduces p95 TTFT for a quantized model. Specify the controls, workload requirements, repetitions, and result interpretation needed for a defensible conclusion.

Summarize the relationship between model weights, activations, and the KV cache during the first pass over a user prompt. Explain why keeping the model resident in memory is appropriate for a benchmark warm-up, while reusing the prompt KV state can invalidate a cold-prefill comparison.

Produce a practical explanation of NUMA effects in CPU language-model inference. Include thread placement, memory allocation locality, remote-memory access, and why the effect might be more visible during long prompt processing than during token-by-token generation.

An application asks a local model to analyze a long incident report containing timelines, metrics, and remediation notes. Describe how the server processes this prompt before responding. Then list the benchmark settings that should remain fixed when comparing the same analysis request on two CPU shapes.

Write a technical memo explaining why TTFT is an end-to-end metric rather than a pure FLOPS measurement. Include request arrival, server scheduling, prompt-token processing, model execution, memory movement, and streaming-response overhead. Explain what a lower TTFT does and does not prove.

Compare these two tests: twenty-four distinct long prompts issued once each, versus three long prompts repeated eight times each. Explain the benefits and limitations of each for measuring CPU prefill performance, cache behavior, statistical confidence, and reproducibility.

Draft an experiment protocol for measuring long-context inference latency on two compute shapes. The model, GGUF quantization, context window, llama.cpp build settings, OCPU count, memory, prompt corpus, temperature, and output cap must be controlled. Include a warm-up phase and a reporting template.

Explain how tokenization can influence an apparent TTFT comparison even when two prompts have similar character counts. Discuss vocabulary segmentation, input-token count, chat-template overhead, and why a benchmark should record prompt token counts when available.

Write a clear explanation of why a 95th-percentile TTFT can be more informative than an average in an interactive inference service. Include examples of scheduler variability, occasional slow memory access, background contention, and small sample-size limitations.

An SRE observes that a CPU model server has stable inter-token latency but variable TTFT on long prompts. Provide a root-cause tree that separates prompt-length effects, request queueing, CPU scheduling, memory locality, cache reuse, and model-loading behavior.

Prepare a short internal guide explaining how `--ctx-size`, `--batch-size`, and `--ubatch-size` can affect prompt processing in llama.cpp. State why all three should remain unchanged while comparing CPU shapes, and identify which follow-up experiment could safely tune them.

Describe the computational difference between prefill and decode for an autoregressive language model. Explain why prefill processes many input tokens together while decode advances token by token, and why a CPU-shape advantage can appear more clearly in one phase than the other.

Write a post-run analysis checklist for a CPU-shape TTFT experiment. Include verification of successful requests, equal prompt distribution, p50/p95/p99 TTFT, latency p95, approximate inter-token latency, outlier investigation, and whether a second trial agrees with the first.

An architect wants to determine whether a CPU shape's locality features improve a RAG-style workload. Propose a prompt corpus made of distinct long retrieved contexts, explain why repeated identical contexts are a separate cache-locality test, and recommend the primary performance metric.

Explain the difference between a process warm-up and an application-level prompt-cache warm-up. For each, state what resource becomes resident or reusable, how it affects TTFT, and whether it should be included in a fair cold-prefill comparison.

Create an incident-style narrative: an inference service's p95 TTFT rises after prompts grow from 200 to 2,000 tokens, but output-token speed remains similar. Analyze what this indicates about prefill, decode, queueing, and the likely value of a CPU-shape comparison.

Write a concise benchmark-report section comparing two shapes when Shape A has lower p95 TTFT but nearly identical inter-token latency to Shape B. Give three cautious hardware-level interpretations and list additional experiments required before making a causal claim.

Summarize the data path for a long chat-completion request sent through a local endpoint to llama.cpp on an OCI VM. Include the client request, SSH tunnel if present, HTTP server, chat template, prompt evaluation, KV-cache allocation, first streamed token, and remaining decode stream.

Develop a test plan for detecting accidental prompt-cache reuse in a TTFT benchmark. Include use of unique prompts, server restart or cache controls, log inspection, request ordering, and a paired repeated-prefix experiment that intentionally demonstrates the cache effect.

Write an executive-friendly explanation of why two CPU systems with the same OCPU and memory allocation can still produce different long-prompt TTFT. Cover processor microarchitecture, memory topology, compiler instruction selection, operating-system scheduling, and measurement noise without overstating certainty.
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


def generated_unique_prefill_prompts(count: int, *, context_repetitions: int) -> str:
    """Create non-repeating prompt corpora for Lab 1 HTTP TTFT length sweeps."""

    tasks = [
        "Explain the likely prefill bottleneck and one way to measure it.",
        "Summarize the workload and identify the first-token critical path.",
        "Write a compact diagnosis of the expected CPU pressure before generation begins.",
        "Describe the controls needed to compare this request fairly across two CPU shapes.",
    ]
    shared_context = (
        "A CPU-hosted instruct model receives a technical analysis request. The server must tokenize the input, "
        "evaluate the prompt, build KV state, schedule the request, and stream a concise answer. "
    )
    prompts = []
    for index in range(count):
        unique_lead = (
            f"Unique prefill case {index + 1:02d}. This request has an independent report identifier "
            f"{70_000 + index * 137} and should not reuse an earlier request context. "
        )
        prompts.append(
            f"{unique_lead}{shared_context * context_repetitions}\n{tasks[index % len(tasks)]}"
        )
    return "\n\n".join(prompts)


def generated_shared_prefix_prompts(count: int) -> str:
    """Create an explicit cache or reuse diagnostic, separate from the cold TTFT corpus."""

    shared_prefix = (
        "Shared briefing: a team is comparing an OCI E6 Flex CPU shape with an E6 Ax Flex CPU shape using the "
        "same model, OCPU allocation, memory, inference server, and benchmark settings. They record TTFT, "
        "inter-token latency, request throughput, and any server-reported prompt-cache or prefix-cache behavior. "
    ) * 12
    prompts = []
    for index in range(count):
        prompts.append(
            f"{shared_prefix}\nQuestion {index + 1}: provide one distinct operational recommendation in two short paragraphs."
        )
    return "\n\n".join(prompts)


DEFAULT_PROMPT_SETS.extend([
    {
        "name": "TTFT length sweep · short unique prompts",
        "filename": "ttft-length-sweep-short-unique-prompts.txt",
        "description": "24 distinct short prompts for the short point in a matched TTFT length sweep. Use concurrency 1, requests 24, and max tokens 64 or 128.",
        "text": generated_unique_prefill_prompts(24, context_repetitions=1),
    },
    {
        "name": "TTFT length sweep · medium unique prompts",
        "filename": "ttft-length-sweep-medium-unique-prompts.txt",
        "description": "24 distinct medium prompts for the middle point in a matched TTFT length sweep. Hold model, server settings, requests, and max tokens fixed across every length.",
        "text": generated_unique_prefill_prompts(24, context_repetitions=8),
    },
    {
        "name": "TTFT length sweep · long unique prompts",
        "filename": "ttft-length-sweep-long-unique-prompts.txt",
        "description": "24 distinct long prompts for the final point in a matched TTFT length sweep. They are roughly 1,500 input tokens under the lab's characters-divided-by-four planning estimate; use concurrency 1, requests 24, and max tokens 128.",
        "text": generated_unique_prefill_prompts(24, context_repetitions=30),
    },
    {
        "name": "TTFT shared-prefix reuse diagnostic · 24 prompts",
        "filename": "ttft-shared-prefix-reuse-diagnostic-24-prompts.txt",
        "description": "24 prompts with an intentionally shared long prefix. Run only after the unique-prompt baseline to quantify cache or reuse sensitivity; do not use it as the primary cold-prefill shape result.",
        "text": generated_shared_prefix_prompts(24),
    },
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
