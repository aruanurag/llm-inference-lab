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

### Lab 4: LLM-D Demand-Driven Autoscaling on OKE

The fourth lab adds observability and demand-driven pod autoscaling to the Lab 3 LLM-D CPU vLLM deployment. It uses Prometheus, Grafana, KEDA, and LLM-D EPP demand metrics to show when inference load should add model-server replicas and when OKE Cluster Autoscaler may need to add managed-node capacity.

Start here:

[labs/04-llm-d-autoscaling-on-oke/README.md](labs/04-llm-d-autoscaling-on-oke/README.md)

### Lab 5: Hybrid Model Routing on OKE

The fifth lab adds an explicit model-routing layer in front of the Lab 4 deployment. A private LiteLLM router exposes one OpenAI-compatible endpoint with local aliases backed by LLM-D CPU vLLM and external aliases backed by OpenRouter, so participants can measure route split and local-versus-external behavior.

Start here:

[labs/05-hybrid-model-routing-on-oke/README.md](labs/05-hybrid-model-routing-on-oke/README.md)

## Apps

### OCI Inference Cloud

A local hackathon workbench for provisioning OCI CPU instances, deploying `llama.cpp`, exposing a private CPU inference endpoint through a local proxy, running benchmarks, and handing participants sample apps that compare direct CPU inference with rule-based routing to OpenAI.

Start here:

[apps/oci-inference-cloud/README.md](apps/oci-inference-cloud/README.md)

Follow the full lab guide:

[docs/inference-cloud-lab-guide.md](docs/inference-cloud-lab-guide.md)

Experiment types in the app:

| Experiment type | Use it when | Main comparison |
| --- | --- | --- |
| OCI CPU instance | You want one compute instance and one local endpoint. | Model, engine, prompt shape, and concurrency. |
| CPU shape comparison | You want two OCI CPU shapes with the same model and workload. | Shape-level latency and throughput. |
| Lab 3 LLM-D cluster | You already have a CPU Kubernetes cluster. | LLM-D routing, replica count, CPU/memory, and vLLM settings. |
| Lab 4 autoscaling | You want demand-driven scaling observations. | EPP queue/running-request demand, KEDA replicas, and OKE node capacity. |
| Lab 5 hybrid routing | You have a ready Lab 4 experiment and want route analytics. | Local CPU aliases versus external model aliases. |

## Examples

- [examples/direct-cpu-chat/README.md](examples/direct-cpu-chat/README.md): calls the generated CPU endpoint directly.
- [examples/router-chat/README.md](examples/router-chat/README.md): routes simple requests to CPU inference and heavier requests to OpenAI.
- [docs/cpu-inference-good-enough.md](docs/cpu-inference-good-enough.md): participant explainer for when CPU inference is enough.
- [docs/cpu-inference-hackathon-proposal.md](docs/cpu-inference-hackathon-proposal.md): leadership proposal for a CPU inference routing hackathon.
- [docs/cpu-inference-hackathon-proposal.docx](docs/cpu-inference-hackathon-proposal.docx): shareable Word version of the hackathon proposal.

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
│   ├── 03-llm-d-on-oci-cpu-cluster/
│   ├── 04-llm-d-autoscaling-on-oke/
│   ├── 05-hybrid-model-routing-on-oke/
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
