# OCI Inference Cloud

A local hackathon workbench for provisioning OCI inference experiments, deploying CPU inference endpoints, running repeatable benchmarks, and giving participants sample apps that can call or route to those endpoints.

The app is intentionally opinionated: generated keys, state, overlays, prompt uploads, logs, and benchmark outputs live outside this repository, while the repository keeps only reusable source, documentation, and empty result placeholders.

Full tutorial guide:

[../../docs/inference-cloud-lab-guide.md](../../docs/inference-cloud-lab-guide.md)

This app is intentionally local-first:

- uses your existing OCI CLI profiles
- does not store OCI API keys
- generates SSH keys under `~/.llm-inference-cloud/`
- keeps benchmark results outside this Git repo
- uses SSH tunnels instead of exposing `llama-server` publicly
- can terminate app-created OCI infrastructure from an experiment

## Which Experiment Type Should I Use?

| Experiment type | Choose it when | What it deploys | What to compare |
| --- | --- | --- | --- |
| **OCI CPU instance** | You want the simplest path from OCI compute to a local OpenAI-compatible endpoint. | One OCI CPU/HPC instance with `llama.cpp` or CPU `vLLM`, reachable through SSH tunnel/local proxy. | Model size, quantization, engine, prompt shape, concurrency, and deploy settings. |
| **CPU shape comparison** | You want to compare two OCI CPU shapes under the same workload. | Two OCI CPU instances with the same model and serving settings. | Shape-level latency, TTFT, approximate ITL, requests/sec, and approximate tokens/sec. |
| **Lab 3 · LLM-D on existing CPU cluster** | You already have an OCI Kubernetes cluster and want Kubernetes-native inference routing. | LLM-D EPP plus CPU vLLM model-server replicas in a selected namespace. | Replica count, CPU/memory per replica, KV cache, model length, prefix caching, and vLLM scheduler settings. |
| **Lab 4 · LLM-D autoscaling and observability** | You want to observe demand-driven scale-out and dashboards. | Lab 3 deployment plus optional lab-owned Prometheus/Grafana/KEDA or validation of existing platform services. | EPP queue depth, running requests, KEDA desired replicas, Ready/Pending pods, node count, TTFT, and throughput. |
| **Lab 5 · Hybrid LLM-D model routing** | You have a ready Lab 4 experiment and want explicit local-versus-external model routing. | Lab 5-owned LiteLLM router as a private `ClusterIP` Service linked to the Lab 4 EPP path and OpenRouter. | Route split, local CPU alias behavior, external alias latency/errors, and which traffic can drive local autoscaling. |

## Benchmark Methods

Use the method that matches the question:

| Method | Available for | Measures | Use for |
| --- | --- | --- | --- |
| HTTP streaming end-to-end | `llama.cpp`, CPU `vLLM`, LLM-D, and routing endpoints | Client-observed TTFT, approximate ITL, latency, requests/sec, and approximate output tokens/sec. | Fair user-path comparisons across engines, shapes, and routes. |
| `llama-bench` | `llama.cpp` | Native prompt/decode throughput inside the engine. | Isolating local engine throughput without HTTP/proxy overhead. |
| `vllm bench serve` | CPU `vLLM` | vLLM serving throughput, TTFT, and TPOT-style measurements. | Comparing vLLM scheduler/server behavior with its own tool. |
| Lab 4 traffic recipes | LLM-D autoscaling | Workload-specific latency plus EPP/KEDA/Grafana observations. | Prefix cache, long prefill, decode pressure, and sustained concurrency. |
| Lab 5 route benchmarks | Hybrid routing | Alias-level route behavior and local/external split. | Showing how many requests stay on CPU versus route elsewhere. |

Do not rank native tool results and HTTP streaming results as if they measure the same boundary. The UI labels the method in the result table so comparisons stay honest.

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
2. Select the experiment type that matches your goal.
3. Complete the setup panel for that type:
   - OCI CPU instance and CPU shape comparison use OCI CLI profile, compartment, VCN, subnet, image, shape, and SSH key.
   - Lab 3, Lab 4, and Lab 5 use an existing kubeconfig context and namespace.
4. Deploy the inference path.
5. Run the matching benchmark method or recipe.
6. Start the local endpoint when the experiment type supports one.
7. Give participants the generated local endpoint value.
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

## CPU Engines, Models, and Benchmark Methods

The CPU deploy panel makes the serving engine an explicit experiment variable:

- **llama.cpp · GGUF**: downloads the selected GGUF model, builds `llama-server`, and serves it only on `127.0.0.1:8080` on the instance. It supports the existing portable/native build controls.
- **vLLM · CPU**: downloads a public Hugging Face model, installs the vLLM CPU wheel with the AMD Zen extra, reserves one CPU for the serving framework, and serves an OpenAI-compatible API only on `127.0.0.1:8080`. CPU vLLM uses `bfloat16`, configurable max model length, max concurrent sequences, and CPU KV-cache capacity.

Both engines retain the same local proxy and **HTTP streaming · end-to-end** benchmark. This is the appropriate like-for-like method for comparing TTFT, approximate ITL, p95 latency, requests/sec, and approximate output tokens/sec across engines or OCI shapes.

The Benchmarks panel also provides an engine-native option after deployment:

- **llama-bench** for `llama.cpp`: isolated prompt/decode microbenchmark. It reports engine token-throughput measurements and deliberately does **not** represent networked TTFT.
- **vLLM bench serve** for CPU `vLLM`: runs vLLM's serving benchmark against the private loopback service and reports serving throughput, TTFT, and TPOT (a serving-side inter-token-latency approximation).

Do not place native-tool results and HTTP-streaming results in the same performance ranking: they measure different boundaries. The result table labels the method and keeps every raw result outside Git for inspection.

## Deploy Models and Build Mode

For `llama.cpp`, the deploy panel supports a model catalog:

- Qwen2.5 1.5B Instruct Q4_K_M
- Qwen2.5 7B Instruct Q4_K_M
- Qwen2.5 7B Instruct Q8_0
- Qwen2.5 14B Instruct Q4_K_M
- Custom directly downloadable GGUF URL

For CPU `vLLM`, it includes public Qwen2.5 1.5B and 7B Instruct models plus a custom public Hugging Face repository ID. It does not require a Hugging Face token for the catalog models; gated models are intentionally not offered in the baseline lab.

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

For single-instance CPU experiments, the app exposes a local OpenAI-compatible endpoint:

```text
POST http://127.0.0.1:8090/api/experiments/{experiment_id}/endpoint/v1/chat/completions
```

The remote inference server remains bound to `127.0.0.1:8080` on the OCI instance. The local backend reaches it through an SSH tunnel.

Lab 3 and Lab 4 use local `kubectl port-forward` endpoints to the LLM-D EPP service. Lab 5 exposes a local route endpoint through a port-forward plus a loopback-only companion proxy that injects the internal LiteLLM credential in memory.

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

Keep these out of Git:

- `~/.llm-inference-cloud/`
- kubeconfig files and cluster OCIDs
- OpenRouter or provider API keys
- model files such as `.gguf`, `.safetensors`, `.bin`, `.pt`, `.pth`, and `.onnx`
- generated benchmark JSON/CSV/log files
- screenshots or local notes that contain endpoint URLs, prompts, responses, public IPs, or customer data

The `.gitignore` is configured for those generated artifacts, but still review `git status --short --untracked-files=all` before committing.
