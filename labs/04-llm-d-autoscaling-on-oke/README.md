# Lab 4: LLM-D Demand-Driven Autoscaling on OKE

## Goal

Extend the Lab 3 CPU vLLM deployment with observability and demand-driven autoscaling. The experiment uses LLM-D Endpoint Picker Proxy (EPP) metrics to scale model-server pods, then relies on OKE Cluster Autoscaler to add managed-node-pool capacity only when a new model pod cannot schedule.

```text
concurrent client requests
  -> LLM-D EPP Flow Control
  -> Prometheus scrapes EPP metrics
  -> KEDA Prometheus triggers and generated HPA
  -> CPU vLLM replicas
  -> Pending replica (only when capacity is exhausted)
  -> OKE Cluster Autoscaler adds a managed node
```

## Scaling Signals

This lab intentionally does not use CPU utilization as its primary scaling signal. LLM inference can keep CPUs busy under both manageable and saturated workloads. Instead, KEDA queries Prometheus for two EPP demand metrics:

| Metric | What it shows | Why it matters |
| --- | --- | --- |
| `llm_d_epp_flow_control_queue_size` | Requests waiting because backend capacity is unavailable | Reacts to saturation and traffic bursts. |
| `llm_d_epp_request_running` | Active in-flight requests | Adds capacity proactively as concurrency grows. |

KEDA owns the generated HPA. Do not create another HPA for the CPU vLLM Deployment. With both triggers, Kubernetes uses the larger calculated desired replica count.

The first policy keeps one warm replica and uses these defaults: minimum 1, maximum 3, queue threshold 1 per replica, running-request threshold 4 per replica, 15-second polling, and 300-second scale-down stabilization.

## Prerequisites

- Complete [Lab 3](../03-llm-d-on-oci-cpu-cluster/README.md) or use the same class of existing OKE CPU cluster.
- Use a managed OKE node pool dedicated to the lab. Configure OKE Cluster Autoscaler outside the workbench with a minimum of one worker and a maximum of at least three workers.
- Size each node for the requested vLLM CPU and memory plus Kubernetes/router headroom. The model-server `requests` are the signal OKE uses when it sees an unschedulable Pending pod.
- Use `kubectl` and `helm` with enough permissions to install CRDs only when choosing the dedicated Lab 4 stack.

## OCI Inference Cloud Workflow

Create **Lab 4 · LLM-D autoscaling and observability** in OCI Inference Cloud.

1. Validate the existing kubeconfig context and CPU cluster.
2. Choose a platform mode:
   - **Dedicated Lab 4 stack** installs the `llmd` Prometheus/Grafana release in `llm-d-monitoring` and KEDA in `keda` after you review and confirm the plan.
   - **Use existing platform services** does not install cluster-wide components; it validates that the administrator-managed services are available.
3. Supply a Grafana password only for the dedicated stack. It is written directly to a Kubernetes Secret, never stored in workbench state, plan output, logs, or Git.
4. Deploy LLM-D. Lab 4 adds the upstream monitoring and EPP Flow Control router values in addition to Lab 3's CPU vLLM overlay.
5. Render and apply the KEDA policy. Review the namespace, EPP service, model, replica bounds, and PromQL selectors before applying it.
6. Run a sustained concurrent benchmark, then capture observations. Compare EPP queue depth, active requests, HPA target/current replicas, Ready/Pending model pods, node count, TTFT p95, p95 latency, and throughput.

## Grafana Access

Grafana remains a cluster-internal `ClusterIP` service. The workbench's **Open Grafana locally** button starts a local `kubectl port-forward` and shows a localhost URL. Log in with the password supplied at bootstrap; the upstream LLM-D dashboards are loaded through labeled ConfigMaps.

Equivalent manual access:

```bash
kubectl --context <context> -n llm-d-monitoring \
  port-forward service/llmd-grafana 3000:80
```

Open `http://127.0.0.1:3000`. Do not create a public ingress in this baseline lab.

## Traffic Experiments and Captured Results

Lab 4 includes repeatable traffic recipes in the **Traffic experiment recipes** section of OCI Inference Cloud. Selecting a recipe chooses its seeded CSV, locks Requests to the CSV row count, and applies the recommended concurrency and maximum output length. The CSV files are seeded locally by the workbench; uploaded prompt files and raw outputs remain outside Git.

| Recipe | Workload | Run settings | Primary question |
| --- | --- | --- | --- |
| Baseline: short unique prompts | 100 short, distinct prompts | concurrency 1, max output 128 | What is the low-load TTFT, ITL, and output-throughput reference? |
| Cold prefill: long unique prompts | 100 long contexts that differ from their first tokens | concurrency 1, max output 64 | How much does cache-cold prefill increase TTFT? |
| Warm cache: shared prefix | 100 long prompts with one identical initial context and unique suffixes | concurrency 1, max output 64 | How much does prefix reuse reduce TTFT after warm-up? |
| Decode pressure: long outputs | 50 short prompts asking for roughly 400-word responses | concurrency 1, max output 512 | How do long generations affect end-to-end latency and request rate? |
| Concurrency: sustained mixed traffic | 150 unique medium prompts | concurrency 8, max output 128 | When do queueing, KEDA scale-out, and possibly OKE node scale-out begin? |

### How to run a clean comparison

1. Start Grafana locally and set its time range to **Last 15 minutes** immediately before starting a run. A 12-hour range mixes prior traffic and is not suitable for a point-in-time comparison.
2. For a cache-cold starting point, restart the CPU vLLM Deployment and wait for it to become Ready. This resets the model-server's in-memory KV/prefix cache and its cumulative counters:

   ```bash
   kubectl --context <context> -n <namespace> \
     rollout restart deployment/optimized-baseline-cpu-vllm-decode
   kubectl --context <context> -n <namespace> \
     rollout status deployment/optimized-baseline-cpu-vllm-decode
   ```

3. Run **Baseline**, then **Cold prefill**, then **Warm cache** without another restart. Keep model, replica count, CPU, memory, KV-cache size, prefix-caching setting, concurrency, and max output tokens fixed except for the variable the recipe is designed to test.
4. Run **Decode pressure** next. It intentionally changes output length, not prompt length.
5. Run the sustained-concurrency recipe last. Use the app's scaling-observation control and Grafana to capture EPP queue depth, running requests, HPA replicas, Pending pods, and node count during the burst.

`vllm:*` dashboard metrics are emitted by the model server; the workbench summary is measured at the local OpenAI-compatible endpoint and includes router/network/streaming overhead. Do not compare the two sources as though they were the same measurement. The dashboard cache-hit counters are cumulative for the life of the model-server pod; reset the pod and use a fresh time range for a cache-cold experiment.

### Expected outcomes and analysis protocol

The recipes are designed to isolate one variable at a time. Record results locally, using the workbench export or an approved private location, rather than adding workload-specific values, dashboard captures, cluster identifiers, or benchmark artifacts to this repository.

| Comparison | Expected dashboard change | Interpretation |
| --- | --- | --- |
| Baseline short unique | Low TTFT and ITL, no meaningful cache reuse or queueing. | Low-load reference. |
| Cold long unique vs. baseline | Higher TTFT; cache-hit rate stays low; ITL is relatively stable. | Long prompt prefill affects TTFT more than decode speed. |
| Warm shared prefix vs. cold long unique | Cache-hit rate rises; TTFT falls after initial warm-up; ITL remains relatively stable. | Prefix caching avoids repeated prefill work. |
| Decode pressure vs. baseline | End-to-end request duration rises and completed requests/sec falls; ITL may stay stable at concurrency 1. | Longer outputs consume more decode time without necessarily increasing per-token latency. |
| Concurrency 4 or 8 | Running requests and/or EPP queue depth rise; p95 TTFT/latency can rise; a KEDA scale event becomes possible. | Concurrent demand is the pod-autoscaling input. |

### Experiment 5: Concurrency-8 sustained traffic and autoscaling

Run the sustained mixed-traffic recipe with concurrency 8 after applying the KEDA policy. KEDA evaluates the larger replica request from its two Prometheus triggers. For example, when the active-request trigger observes eight requests against a threshold of four requests per replica:

```text
llm_d_epp_request_running = 8
running-request threshold = 4 requests per replica
ceil(8 / 4) = 2 desired CPU vLLM replicas
```

This is pod scaling. If the second model-server pod cannot fit on current capacity, it becomes Pending; that unschedulable pod is the separate signal OKE Cluster Autoscaler uses to add a managed node. Do not delete a Pending replica while observing this stage. Watch for a new OKE node, then for the pod to advance from `Pending` to `ContainerCreating` and finally `Running`. Record timings and screenshots only in a private location.

## Interpreting the Scale Event

1. A burst causes active requests and/or EPP queue depth to cross the configured per-replica threshold.
2. KEDA queries Prometheus and updates its generated HPA.
3. Kubernetes asks for an additional CPU vLLM pod.
4. If the pod fits, it starts on an existing node. If it remains Pending because its CPU or memory request cannot fit, OKE Cluster Autoscaler may add a managed node within the configured pool bounds.
5. When the replica becomes Ready, EPP queue depth should fall. After traffic stops, the HPA returns to the one warm replica after the stabilization window. Node scale-in is intentionally slower and depends on OKE's safe-drain decision.

## Safety and Cleanup

The workbench records whether it created the dedicated platform release and only offers cleanup for that lab-owned stack. It never removes a detected existing monitoring platform. Keep kubeconfigs, cluster IDs, local app state, Grafana passwords, endpoint URLs, and raw benchmark artifacts out of Git.
