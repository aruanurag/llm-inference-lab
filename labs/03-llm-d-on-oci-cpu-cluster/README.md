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

## OCI Inference Cloud Experiment Type

In the app, create:

```text
Lab 3 · LLM-D on existing CPU cluster
```

Use this experiment type when you already have a CPU Kubernetes cluster and want to deploy the LLM-D EPP router plus a CPU vLLM model-server pool. The app does not create or delete the cluster. It only validates the selected kubeconfig context, renders a reviewable overlay from a pinned LLM-D checkout, applies the lab-owned namespace resources after confirmation, and keeps overlays, logs, endpoint state, and benchmark JSON outside Git.

Choose Lab 4 instead when the question is autoscaling and observability. Choose Lab 5 only after a Lab 4 experiment is ready and the question is local-versus-external model routing.

## Optional: Provision an OKE Cluster for This Lab

This lab deliberately deploys to an *existing* cluster. If you need a dedicated environment, provision an Oracle Kubernetes Engine (OKE) cluster first, then return to the lab workflow. The workbench will not create or delete that cluster for you.

### Choose the OKE shape of the experiment

For the first CPU vLLM run, choose an OKE cluster with a **managed node pool**, not virtual nodes. Managed nodes let you choose the CPU and memory shape and observe the capacity that a CPU model-server pod consumes. Start with one managed CPU worker node that has enough *allocatable* capacity for the baseline model-server request plus Kubernetes and router headroom. The baseline in this lab requests 16 CPUs and 32 GiB per replica, so do not size the node exactly at those values.

To demonstrate replica scale-out, plan for a second worker node or enough unused CPU and memory for the second model-server pod. A one-node cluster is still useful for baseline, parameter, and prefix-cache experiments, but a model-server redeploy briefly replaces the pod rather than running old and new versions simultaneously.

### Create the cluster in OCI Console

1. In the OCI Console, open **Developer Services → Kubernetes Clusters (OKE)** and select **Create cluster**.
2. Choose **Quick Create** when OCI can create the VCN and default networking for a disposable lab. Choose **Custom Create** when you need an existing VCN, private API endpoint, specific subnets, or organization-standard network controls.
3. Choose **Managed** as the node type. Select a current OKE worker-node image and a CPU shape with the capacity described above.
4. Prefer **private worker nodes**. A public Kubernetes API endpoint is convenient for a local hands-on lab only when its ingress is tightly restricted. A private endpoint requires network access through an approved path such as VPN, FastConnect, or a bastion.
5. Wait for the cluster and node-pool work requests to finish, then confirm the worker node is Ready.

Oracle references:

- [Create an OKE cluster](https://docs.oracle.com/en-us/iaas/Content/ContEng/Tasks/contengcreatingclusterusingoke_topic-Using_the_API.htm)
- [Quick Create workflow](https://docs.oracle.com/en-us/iaas/Content/ContEng/Tasks/contengcreatingclusterusingoke_topic-Using_the_Console_to_create_a_Quick_Cluster_with_Default_Settings.htm)
- [Custom Create workflow](https://docs.oracle.com/en-us/iaas/Content/ContEng/Tasks/contengcreatingclusterusingoke_topic-Using_the_Console_to_create_a_Custom_Cluster_with_Explicitly_Defined_Settings.htm)
- [Managed nodes and capacity responsibilities](https://docs.oracle.com/en-us/iaas/Content/ContEng/Tasks/contengworkingwithmanagednodes.htm)
- [Create or add a managed node pool](https://docs.oracle.com/en-us/iaas/Content/ContEng/Tasks/create-node-pool.htm)

### Configure local cluster access

Keep the cluster OCID and kubeconfig on your workstation; neither belongs in this repository. Generate a kubeconfig with your own placeholders, then validate access:

```bash
mkdir -p "$HOME/.kube"

oci ce cluster create-kubeconfig \
  --cluster-id <cluster-ocid> \
  --file "$HOME/.kube/config" \
  --region <region> \
  --token-version 2.0.0 \
  --kube-endpoint PUBLIC_ENDPOINT

kubectl config get-contexts
kubectl get nodes -o wide
```

Use `PRIVATE_ENDPOINT` instead of `PUBLIC_ENDPOINT` only when your machine has a permitted private network path to the Kubernetes API. The OCI CLI identity needs the appropriate IAM permissions to create or manage the cluster and to generate access credentials. See the [OKE documentation home](https://docs.oracle.com/en-us/iaas/Content/ContEng/) for current IAM, networking, and access guidance.

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
