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

## Labs

### Lab 1: Local LLM Serving on Apple Silicon

The first lab uses `llama.cpp` as the default runtime for Mac mini / Apple Silicon.

vLLM is still an important serving system to study, but Apple Silicon support is more limited than the CUDA path used in most vLLM examples. For the first lab, `llama.cpp` gives us a simpler local server, Metal acceleration, GGUF model support, streaming responses, and an OpenAI-compatible API surface.

Start here:

[labs/01-local-llm-serving-apple-silicon/README.md](labs/01-local-llm-serving-apple-silicon/README.md)

### Lab 2: Running vLLM on OCI GPU

The second lab moves from local inference to a GPU-backed vLLM deployment on OCI. It covers provisioning a GPU instance, installing vLLM, exposing an OpenAI-compatible endpoint, measuring GPU-backed inference behavior, monitoring `nvidia-smi`, and estimating experiment cost.

Start here:

[labs/02-vllm-on-oci/README.md](labs/02-vllm-on-oci/README.md)

### Lab 3: LLM-D on an Existing OCI CPU Kubernetes Cluster

The third lab introduces Kubernetes-native distributed inference. It deploys the LLM-D routing stack with a CPU vLLM model-server pool on an existing cluster, then measures configuration and replica scale-out tradeoffs with the same streaming benchmark approach.

Start here:

[labs/03-llm-d-on-oci-cpu-cluster/README.md](labs/03-llm-d-on-oci-cpu-cluster/README.md)

## Apps

### OCI Inference Cloud

A local hackathon workbench for provisioning OCI CPU instances, deploying `llama.cpp`, exposing a private CPU inference endpoint through a local proxy, running benchmarks, and handing participants sample apps that compare direct CPU inference with rule-based routing to OpenAI.

Start here:

[apps/oci-inference-cloud/README.md](apps/oci-inference-cloud/README.md)

Follow the full lab guide:

[docs/inference-cloud-lab-guide.md](docs/inference-cloud-lab-guide.md)

## Examples

- [examples/direct-cpu-chat/README.md](examples/direct-cpu-chat/README.md): calls the generated CPU endpoint directly.
- [examples/router-chat/README.md](examples/router-chat/README.md): routes simple requests to CPU inference and heavier requests to OpenAI.
- [docs/cpu-inference-good-enough.md](docs/cpu-inference-good-enough.md): participant explainer for when CPU inference is enough.

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
│   ├── 02-vllm-on-oci/
│   │   ├── README.md
│   │   ├── setup.md
│   │   ├── run_vllm.sh
│   │   ├── benchmark.py
│   │   ├── collect_metrics.py
│   │   ├── observations.md
│   │   ├── results_dashboard.html
│   │   └── results/
│   └── templates/
├── notes/
├── results/
├── apps/
│   └── oci-inference-cloud/
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
