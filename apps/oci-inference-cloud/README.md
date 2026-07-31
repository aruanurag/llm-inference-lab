# OCI Inference Cloud

A local hackathon workbench for provisioning OCI inference experiments, deploying `llama.cpp`, exposing a private OpenAI-compatible endpoint through a local proxy, running inference benchmarks, and handing participants sample apps.

It also includes an **LLM-D on existing CPU cluster** experiment type. That flow validates a local kubeconfig context, renders a reviewable overlay against a pinned LLM-D checkout, installs the LLM-D router and CPU vLLM model-server pool only after the user confirms deployment, and preserves the generated overlay and command log outside the repository.

The **Lab 4 · LLM-D autoscaling and observability** experiment adds an opt-in dedicated Prometheus/Grafana/KEDA stack or validates existing platform services. It enables upstream EPP Flow Control and monitoring values, renders a KEDA `ScaledObject` from EPP queue depth and running-request metrics, provides a local-only Grafana tunnel, and records pod/node scaling observations. Grafana credentials are passed directly into a Kubernetes Secret and are never saved by the app.

Full tutorial guide:

[../../docs/inference-cloud-lab-guide.md](../../docs/inference-cloud-lab-guide.md)

This app is intentionally local-first:

- uses your existing OCI CLI profiles
- does not store OCI API keys
- generates SSH keys under `~/.llm-inference-cloud/`
- keeps benchmark results outside this Git repo
- uses SSH tunnels instead of exposing `llama-server` publicly
- can terminate app-created OCI infrastructure from an experiment

## Structure

```text
apps/oci-inference-cloud/
├── backend/
│   ├── app/
│   ├── tests/
│   └── requirements.txt
└── frontend/
    ├── src/
    └── package.json
```

## Run Backend

```bash
cd apps/oci-inference-cloud/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8090
```

## Run Frontend

```bash
cd apps/oci-inference-cloud/frontend
npm install
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

## Hackathon Flow

1. Create or select an experiment.
2. Load OCI context and select existing networking.
3. Provision a CPU/HPC instance for the experiment.
4. Deploy `llama.cpp` with a selected GGUF model.
5. Run benchmark presets to understand latency, TTFT, concurrency, and output throughput.
6. Open the Hackathon view and start the local endpoint proxy.
7. Give participants the generated `CPU_ENDPOINT_URL`.

For the LLM-D cluster lab, create an `LLM-D on existing CPU cluster` experiment instead. For demand-driven scaling, select `Lab 4 · LLM-D autoscaling and observability`. The app does not create or delete the Kubernetes cluster; it operates only on the selected context and namespace. OKE Cluster Autoscaler remains administrator-managed because it owns the managed node pool.
8. Run one of the sample apps:

```bash
cd examples/direct-cpu-chat
npm install
CPU_ENDPOINT_URL=http://127.0.0.1:8090/api/experiments/1/endpoint/v1 PORT=3001 npm run dev
```

```bash
cd examples/router-chat
npm install
CPU_ENDPOINT_URL=http://127.0.0.1:8090/api/experiments/1/endpoint/v1 \
OPENAI_API_KEY=replace-with-your-key \
OPENAI_MODEL=gpt-4.1-mini \
PORT=3002 \
npm run dev
```

## Deploy Models and Build Mode

The deploy panel supports a model catalog:

- Qwen2.5 1.5B Instruct Q4_K_M
- Qwen2.5 7B Instruct Q4_K_M
- Qwen2.5 7B Instruct Q8_0
- Qwen2.5 14B Instruct Q4_K_M
- Custom directly downloadable GGUF URL

Open **Advanced settings** during deploy to switch from the portable llama.cpp build to a native optimized build:

```bash
-DGGML_NATIVE=ON
```

Use this when you want llama.cpp to compile for the selected shape's available CPU features. The portable default is safer for first deploys across different shapes.

If native mode fails with `unsupported instruction 'vpdpbusd'`, keep native mode enabled but also enable **Disable VNNI instructions** in Advanced settings.

## Benchmark Comparison Presets

The Benchmarks view includes a **Throughput comparison** preset for repeatable model, shape, and deploy-setting experiments.

Recommended flow:

1. Create experiment 1 for the first model, shape, or deploy setting.
2. Deploy `llama.cpp` and run the **Throughput comparison** preset as **Primary run**.
3. Create experiment 2 with one variable changed, such as model size, OCPU count, memory, shape, or native build mode.
4. Use the same prompt set, max tokens, request count, and concurrency.
5. Run the same **Throughput comparison** preset as **Comparison run** and review the cross-experiment comparison table.

The comparison focuses on:

- approximate output tokens/sec
- output characters/sec
- requests/sec
- p95 latency
- p95 TTFT
- relative throughput versus the best Primary run

## Endpoint Proxy

The app exposes a local OpenAI-compatible endpoint:

```text
POST http://127.0.0.1:8090/api/experiments/{experiment_id}/endpoint/v1/chat/completions
```

The remote `llama-server` remains bound to `127.0.0.1:8080` on the OCI instance. The local backend reaches it through an SSH tunnel.

## App Data

Generated state is stored outside the repo:

```text
~/.llm-inference-cloud/
├── state.db
├── keys/
├── prompts/
├── benchmarks/
└── logs/
```

## Safety Notes

Use **Delete infra** from the selected experiment when the hackathon exercise is done.

The deployment path starts `llama-server` on the remote instance bound to `127.0.0.1:8080`. Benchmarks reach it through an SSH tunnel.
