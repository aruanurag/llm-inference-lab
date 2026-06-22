# LLM Inference Lab

A hands-on repository for learning LLM inference systems, serving infrastructure, and LLMOps through small experiments, benchmarks, and notes.

The goal is not to build a production benchmarking framework on day one. The goal is to observe real behavior: startup time, time to first token, token throughput, resource usage, concurrency, prompt length, and output length.

## Why This Repo Exists

LLM inference concepts become clearer when they are measured.

This lab series moves from theory to practical observation:

- start a local inference server
- send controlled requests
- measure latency and throughput
- change one variable at a time
- record what changed and why it might have changed

## Current Lab

### Lab 1: Local LLM Serving on Apple Silicon

The first lab uses `llama.cpp` as the default runtime for Mac mini / Apple Silicon.

vLLM is still an important serving system to study, but Apple Silicon support is more limited than the CUDA path used in most vLLM examples. For the first lab, `llama.cpp` gives us a simpler local server, Metal acceleration, GGUF model support, streaming responses, and an OpenAI-compatible API surface.

Start here:

[labs/01-local-llm-serving-apple-silicon/README.md](labs/01-local-llm-serving-apple-silicon/README.md)

## Repository Structure

```text
llm-inference-lab/
├── README.md
├── labs/
│   ├── 01-local-llm-serving-apple-silicon/
│   │   ├── README.md
│   │   ├── setup.md
│   │   ├── run.sh
│   │   ├── benchmark.py
│   │   ├── collect_metrics.py
│   │   └── results/
│   └── templates/
├── notes/
├── results/
├── scripts/
└── docs/
```

## Learning Style

Each lab is written as a tutorial:

- short sections
- one step at a time
- clear commands
- simple questions before deeper details
- measurable results before interpretation

## Planned Topics

- local serving baseline
- TTFT and inter-token latency
- prompt length effects
- output length effects
- concurrency
- batching behavior
- model comparison
- quantization comparison
- vLLM on NVIDIA GPU
- routing and distributed serving
