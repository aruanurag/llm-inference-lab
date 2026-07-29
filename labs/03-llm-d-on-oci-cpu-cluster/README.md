# Lab 3: LLM-D on an Existing OCI CPU Kubernetes Cluster

## Goal

Deploy LLM-D's routing stack and a CPU vLLM model-server pool to an existing Kubernetes cluster, then measure how replica count and serving parameters change behavior.

This is an incremental lab. It keeps the OpenAI-compatible API and streaming measurements from Lab 2, but changes the topology from one model server to a Kubernetes-native inference pool:

```text
benchmark client
  -> LLM-D standalone router / Endpoint Picker Proxy
  -> InferencePool-selected CPU vLLM replicas
```

LLM-D routes to supported model servers such as vLLM. The previous direct `llama.cpp` CPU experiment remains a useful baseline, but is intentionally not placed behind LLM-D in this lab.

## What You Will Learn

- Verify access to an existing OCI Kubernetes cluster without creating or deleting it.
- Install the Gateway API Inference Extension and LLM-D standalone router.
- Deploy the upstream LLM-D CPU vLLM recipe using a local, pinned LLM-D checkout.
- Tune replica count, CPU/memory requests, CPU KV cache space, and model length.
- Measure TTFT, approximate ITL, p95 latency, request throughput, and output throughput.
- Compare a shared-prefix workload with prefix caching enabled and disabled.
- Trigger a controlled scale-out and scale-in event when the cluster has capacity.

## Prerequisites

- An existing Kubernetes cluster with one or more ready CPU nodes.
- `kubectl`, `helm`, and a kubeconfig context that can create namespace-scoped resources.
- A local checkout of [llm-d/llm-d](https://github.com/llm-d/llm-d). Keep its commit or tag in your observations.
- Enough allocatable CPU and memory for the model. Start small and use one replica.
- No Hugging Face token is needed for the default public Qwen model. A token is only needed for a gated model.

Follow [setup.md](setup.md) before deploying.

## Recommended First Configuration

Use the upstream CPU vLLM recipe as the baseline and reduce it to fit the available CPU pool:

| Setting | First run | Why |
| --- | ---: | --- |
| Model | `Qwen/Qwen2.5-1.5B-Instruct` | Public, small enough for the first CPU run. |
| Replicas | 1 | Establish a clean baseline. |
| CPU per replica | 16 | Adjust to your CPU node size. |
| Memory per replica | 32 GiB | Leave headroom for the runtime and model. |
| CPU KV cache | 8 GiB | Small, safe starting point for concurrency experiments. |
| Max model length | 4096 | Bounds memory use while preserving a meaningful prompt test. |

The workbench's **LLM-D cluster lab** experiment type renders these values into an experiment-local Kustomize overlay. It displays the commands before deployment and runs them only after you click **Deploy LLM-D**. The overlay, logs, local endpoint state, and benchmark JSON remain outside this repository.

## Lab Flow

### 1. Connect the cluster

In OCI Inference Cloud, create an **LLM-D on existing CPU cluster** experiment.

1. Choose the local Kubernetes context.
2. Choose a dedicated namespace, such as `llm-d-lab`.
3. Click **Validate cluster**.

Record ready nodes, allocatable CPU and memory, architecture, Kubernetes server version, and Helm version. The app does not provision a cluster and the lab cleanup only targets its namespace and Helm release.

### 2. Render and review the deployment

Set the path to the checked-out `llm-d` repository and the initial model-server parameters. Click **Render plan**.

Review three things:

- Gateway API Inference Extension CRDs are installed before the router.
- The LLM-D standalone router uses the upstream base and optimized-baseline values from the selected checkout.
- The generated overlay applies only the model, replica, CPU, memory, KV-cache, and max-model-length adjustments to the upstream CPU vLLM recipe.

### 3. Deploy and verify

Click **Deploy LLM-D**. The model image can take several minutes to pull and load. After it is Ready, the workbench starts a local `kubectl port-forward` and displays an OpenAI-compatible endpoint for the test prompt and benchmark workflow. Check readiness with:

```bash
kubectl --context <context> -n llm-d-lab get pods -w
kubectl --context <context> -n llm-d-lab get pods -l llm-d.ai/guide=optimized-baseline
kubectl --context <context> -n llm-d-lab get service
```

The LLM-D quickstart calls the standalone router service `<release>-epp`. Port-forward it for local benchmarking:

```bash
kubectl --context <context> -n llm-d-lab \
  port-forward service/llm-d-lab-epp 8000:80
```

Use the service name shown by `kubectl get service` if the chart names it differently.

### 4. Baseline benchmark

From `labs/02-vllm-on-oci`, point the existing streaming benchmark at the port-forwarded LLM-D endpoint:

```bash
python3 benchmark.py \
  --url http://127.0.0.1:8000/v1/chat/completions \
  --model Qwen/Qwen2.5-1.5B-Instruct \
  --experiment llmd-cpu-baseline-r1 \
  --prompt "Explain why an LLM-aware router needs queue depth and cache state." \
  --max-tokens 128 \
  --concurrency 1 \
  --requests 8
```

Copy the raw JSON file to this lab's `results/raw/` directory, or preserve it in the shared workbench export.

The app also keeps a benchmark-history table. A run with zero successful responses is a failed connectivity result, not a performance measurement; resolve the endpoint issue before comparing it with successful runs.

### 5. Tune one variable at a time

Create a named run for each change. Do not mix changes.

| Experiment | Change | Question |
| --- | --- | --- |
| `kv-cache-16g` | KV cache: 8 -> 16 GiB | Does more cache reduce queueing or improve repeated-prefix behavior? |
| `max-len-8192` | Max model length: 4096 -> 8192 | What capacity and TTFT tradeoff appears? |
| `replicas-2` | Replicas: 1 -> 2 | Does aggregate request throughput improve at concurrency? |
| `cpu-32` | CPU per replica: 16 -> 32 | Is decode speed or TTFT CPU-bound? |
| `prefix-cache-on` / `prefix-cache-off` | Enable or disable prefix caching | Does a repeated long prompt prefix improve prefill and TTFT? |

Each parameter change creates a fresh overlay. Re-render, review, deploy, wait for readiness, then run the same benchmark preset.

### 6. Prefix-cache comparison

Prefix caching affects prompt prefill, not the steady-state decode rate. A short prompt followed by a long answer is therefore a poor cache experiment. Use a shared 2k–4k token system prompt or document prefix, append a small different question to each request, and set a short output limit such as 16–32 tokens.

Run at least 30 requests with the same concurrency in each configuration:

1. Enable prefix caching, deploy, let the model become Ready, then run the shared-prefix workload.
2. Disable prefix caching, redeploy, wait for readiness, then repeat the exact workload.
3. Compare TTFT p95 and requests/sec. Decode tokens/sec may remain almost unchanged because caching does not make generated tokens decode faster.

### 7. Scale out under load

Start with one replica and run a concurrency workload. In a second terminal, change only replicas to two in the workbench and click **Deploy LLM-D** again. This requires enough unallocated CPU and memory for a second model-server pod. Record:

- time from deployment update to the second pod becoming Ready
- request distribution and any queueing during startup
- requests/sec, TTFT p95, and latency p95 before and after
- CPU/memory utilization for each pod

For the scale-in observation, return to one replica while the workload is low. Verify that active requests complete and the remaining replica continues serving.

On a one-node cluster where one modelserver consumes most available CPU, a parameter redeploy cannot run old and new pods simultaneously. The workbench uses `maxSurge: 0` and `maxUnavailable: 1` for the CPU vLLM Deployment: it briefly replaces the old decoder pod so the new pod can schedule. The router Service and cluster remain intact, but inference is briefly unavailable during the replacement.

### 8. Cleanup

Remove only lab resources:

```bash
helm --kube-context <context> uninstall llm-d-lab -n llm-d-lab
kubectl --context <context> delete namespace llm-d-lab
```

Do not delete the cluster or its node pool from this lab.

## Observations

Use [observations.md](observations.md) to capture the LLM-D checkout revision, cluster shape, node architecture, all parameter values, scale timestamps, and benchmark results.

## Safe Sharing

Do not commit kubeconfig files, cluster identifiers, public IPs, local checkout paths, Hugging Face tokens, endpoint URLs, or raw benchmark exports. This repository ignores local workbench state and generated raw result files. Keep reusable observations in [observations.md](observations.md) using placeholders or anonymized capacity values.
