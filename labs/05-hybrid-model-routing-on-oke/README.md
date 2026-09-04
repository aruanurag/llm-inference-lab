# Lab 5: Hybrid Model Routing with LLM-D and OpenRouter on OKE

## Goal

Add an explicit model-routing layer to the Lab 4 LLM-D deployment. A private LiteLLM Proxy in OKE exposes one OpenAI-compatible endpoint and routes each request by its selected model alias:

```text
client / benchmark
  -> local-only kubectl port-forward
  -> LiteLLM Router (OKE, ClusterIP)
     -> private or fast     -> LLM-D EPP -> local CPU vLLM pods
     -> coding or reasoning -> HTTPS -> OpenRouter -> selected external model
```

This is deliberately a two-stage decision:

1. **LiteLLM Router** chooses the destination from the explicit model alias.
2. **LLM-D EPP** chooses a healthy local CPU vLLM backend only for traffic routed to the local destination.

OpenRouter is an external hosted API gateway. It is **not** deployed in the OKE cluster. The new in-cluster component is LiteLLM Router.

## What You Will Learn

- Route one OpenAI-compatible API to local and external model destinations.
- Keep locally served traffic on LLM-D while routing selected workloads to OpenRouter.
- Compare route-level latency, throughput, errors, and destination share in Grafana.
- Understand why only local traffic can drive the Lab 4 EPP/KEDA autoscaling policy.
- Deploy, access, and clean up a lab-owned router without exposing a public endpoint or committing secrets.

## Prerequisites

- Complete [Lab 4](../04-llm-d-autoscaling-on-oke/README.md) and keep its LLM-D EPP, CPU vLLM deployment, and monitoring stack healthy.
- A Kubernetes context that can create namespace-scoped resources and a local `kubectl` installation.
- Outbound HTTPS, DNS, and account access required to call OpenRouter from the router pod.
- An OpenRouter API key and two permitted external model IDs: one for `coding`, one for `reasoning`.

Do not add the API key, kubeconfig, cluster identifier, endpoint URL, prompt data, or benchmark outputs to Git.

## OCI Inference Cloud Experiment Type

In the app, create:

```text
Lab 5 · Hybrid LLM-D model routing
```

Use this experiment type only after a Lab 4 autoscaling experiment is deployed and healthy. Lab 5 links to that source experiment. It does not recreate the LLM-D EPP service, CPU vLLM pods, Prometheus, Grafana, KEDA, node pools, or cluster. Its ownership boundary is only the Lab 5 LiteLLM router resources, its private Service, ServiceMonitor, Grafana dashboard ConfigMap, and Kubernetes Secret.

This lab is for route-level questions:

- Which requests stay on local CPU inference?
- Which requests route to the configured external model aliases?
- What latency, error, and throughput difference appears by route?
- Which fraction of traffic is eligible to drive Lab 4 EPP/KEDA autoscaling?

## Route Contract

The client chooses a route by setting the OpenAI `model` field to one of four aliases. There is no hidden prompt classifier in this lab and no automatic content-based routing.

| Alias | Destination | Intended use | Can affect LLM-D/KEDA? |
| --- | --- | --- | --- |
| `private` | Existing LLM-D EPP and local CPU vLLM deployment | Workloads that must remain inside the cluster | Yes |
| `fast` | Existing LLM-D EPP and local CPU vLLM deployment | Low-latency local baseline | Yes |
| `coding` | OpenRouter over HTTPS | Code-generation comparison | No |
| `reasoning` | OpenRouter over HTTPS | Reasoning-model comparison | No |

`private` is a hard local-only route. `coding` and `reasoning` fail clearly if OpenRouter is unavailable; they must not silently fall back to a local model or another external model. The router accepts only the aliases above, so clients cannot bypass the intended policy with an arbitrary upstream model name.

## Components and Boundaries

| Component | Location | Responsibility |
| --- | --- | --- |
| LiteLLM Router | Lab-owned Deployment and `ClusterIP` Service in the Lab 4 namespace | Alias policy, OpenAI-compatible endpoint, upstream calls, route metrics |
| LLM-D EPP | Existing Lab 4 service | Selects healthy local CPU vLLM replicas for `private` and `fast` |
| CPU vLLM deployment | Existing Lab 4 namespace | Serves the local model |
| OpenRouter | External service | Serves configured `coding` and `reasoning` model IDs |
| Prometheus and Grafana | Existing Lab 4 monitoring stack | Scrapes router, EPP, and model-server metrics; visualizes results |

The router is one replica for this lab. Do not add an HPA or KEDA policy to it. The purpose is to observe model-route behavior without introducing a second autoscaling control loop.

## Deployment Workflow in OCI Inference Cloud

Create **Lab 5 · Hybrid model routing** and select a ready Lab 4 experiment as the source.

1. **Preflight** — validate the selected Kubernetes context, namespace, local LLM-D EPP service, and Prometheus/Grafana availability. It reports the HTTPS/DNS egress requirement for OpenRouter without sending a credential-bearing test request.
2. **Configure routes** — enter the two external model IDs and supply the OpenRouter API key. The `private` and `fast` aliases are bound to the selected Lab 4 EPP service.
3. **Render plan** — review the namespace, owned release name, `ClusterIP` Service, ServiceMonitor, dashboard ConfigMap, local EPP target, aliases, and external model IDs. The plan redacts the API key.
4. **Confirm and deploy** — create the LiteLLM Deployment, ConfigMap, Secret, Service, ServiceMonitor, and Lab 5 dashboard resources. The key is sent directly to a Lab 5-owned Kubernetes Secret.
5. **Verify** — use the health/status view and `/v1/models` through a local tunnel. Confirm that all four aliases are listed and that local aliases can reach EPP.
6. **Run experiments** — send text or CSV traffic through an alias and compare route metrics with the Lab 4 LLM-D metrics.

The workbench must record ownership only for resources it creates. It may remove those resources during Lab 5 cleanup, but it must not remove Lab 4's LLM-D, KEDA, Prometheus, Grafana, node pools, or administrator-managed platform services.

Each Lab 5 experiment starts with a router name derived from its experiment ID, so independently created routing experiments do not share Kubernetes resource names or a Grafana dashboard UID. Once deployed, keep that router name unchanged; changing it requires first using Lab 5 cleanup so ownership remains unambiguous. A redeploy with the same name deliberately restarts the router after updating its generated internal credential, then requires a fresh local endpoint tunnel.

## Local Endpoint Access

The router remains cluster-internal. The workbench's endpoint control starts a local `kubectl port-forward` plus a loopback-only companion proxy and displays the localhost URL; no public ingress is created. The companion proxy injects the internally generated LiteLLM credential only in local process memory, so a normal OpenAI-compatible client can use the displayed `/v1/...` URL without the credential being shown, saved, or copied into shell history.

The UI endpoint is the supported client path. A raw manual port-forward is useful only for diagnostics and requires the internal router credential, so do not copy that credential out of its Lab 5-owned Kubernetes Secret:

```bash
kubectl --context <context> -n <namespace> \
  port-forward service/<lab5-router-service> 4000:80
```

Use one of the four aliases in a standard OpenAI-compatible chat-completion request at the UI-displayed localhost URL. For example, the client supplies `"model": "private"` to retain the request inside the local LLM-D path. Keep API keys, prompts, responses, and endpoint URLs in local tooling rather than shell history or source files.

## Observability and Autoscaling

LiteLLM exports router metrics to Prometheus through a Lab 5 ServiceMonitor. The Lab 5 Grafana dashboard should show:

- request rate, p95 latency, in-flight requests, errors, and traffic share by alias/destination;
- local-route behavior next to Lab 4 EPP queue depth, active requests, Ready/Pending vLLM pods, TTFT, and throughput;
- no prompt text, completion text, client IP, API-key identifier, upstream URL, or cost/spend labels.

### What Scales What

```text
private / fast traffic
  -> LiteLLM Router
  -> LLM-D EPP demand metrics
  -> Prometheus
  -> existing KEDA ScaledObject
  -> local CPU vLLM replicas
  -> Pending model pod, if capacity is exhausted
  -> OKE Cluster Autoscaler may add a node

coding / reasoning traffic
  -> LiteLLM Router
  -> OpenRouter
  -> no EPP demand and no local vLLM/KEDA scale-out
```

KEDA remains the sole owner of the generated HPA for the CPU vLLM Deployment. Its Lab 4 EPP-demand signals, `llm_d_epp_flow_control_queue_size` and `llm_d_epp_request_running`, describe only local LLM-D traffic. External-route traffic should be excluded from conclusions about local model capacity or node autoscaling.

## Repeatable Experiments

Use the same prompt set, concurrency, output limit, and time window for each comparable route. Start Grafana locally before the run and use a fresh, narrow time range.

| Experiment | Route(s) | Question to answer |
| --- | --- | --- |
| Local baseline | `private` | What do local EPP, TTFT, ITL, and CPU vLLM metrics look like at low load? |
| Local fast baseline | `fast` | Does the alternate local alias preserve the same EPP path and behavior? |
| External coding | `coding` | What are the route-level latency and error characteristics of the selected OpenRouter coding model? |
| External reasoning | `reasoning` | How does a reasoning-model route differ under the same prompt and output budget? |
| Mixed route comparison | all aliases | How does traffic split across local and external destinations, and which fraction is eligible to scale local capacity? |
| Local autoscaling control | `private` / `fast` only | Does sustained local concurrency increase EPP demand and trigger the existing KEDA policy? |

For a clean local autoscaling observation, send the concurrent workload only to `private` or `fast`. A mixed run is useful for route accounting, but external requests must not be counted as LLM-D demand.

## Failure Guidance

| Symptom | Likely cause | Response |
| --- | --- | --- |
| Local alias fails | EPP service or CPU vLLM pods are not Ready | Resolve the Lab 4 endpoint/readiness issue before comparing routes. |
| External alias fails | Invalid API key, unavailable external model, DNS/egress issue, or provider error | Show the sanitized route failure; do not fall back to another model. |
| No route metrics in Grafana | ServiceMonitor discovery or Prometheus scrape issue | Check the lab-owned ServiceMonitor and the router `/metrics` endpoint; do not expose it publicly. |
| KEDA does not scale during external traffic | Expected behavior | Only EPP metrics from local LLM-D traffic feed the Lab 4 KEDA policy. |
| A local scale-out pod is Pending | Insufficient CPU or memory on current nodes | Preserve the pod while observing; OKE Cluster Autoscaler can act only if the managed node pool has valid capacity and bounds. |

## Secret, Privacy, and Cleanup Rules

- The OpenRouter API key is accepted only during deployment and written directly to a Lab 5-owned Kubernetes Secret.
- Redact the key from plans, status APIs, frontend state, logs, error messages, screenshots, exports, and Git.
- Store no prompt or completion content in router metrics, Grafana labels, or repository files.
- Keep Kubernetes contexts, cluster identifiers, private endpoint addresses, local port-forward state, and raw benchmark artifacts outside this repository.
- The workbench's **Uninstall Lab 5** control removes only the router resources and Secret it recorded as Lab 5-owned. It never deletes OpenRouter resources, because OpenRouter is external, and it never deletes Lab 4 platform resources.

## Success Criteria

1. The local endpoint lists exactly `private`, `fast`, `coding`, and `reasoning`.
2. `private` and `fast` reach LLM-D EPP and appear in EPP/CPU vLLM metrics.
3. `coding` and `reasoning` reach only their configured OpenRouter destinations and appear in route metrics.
4. An external-route failure is clear and sanitized, with no automatic fallback.
5. A local-only concurrency run can still trigger the existing KEDA/OKE scale path.
6. Cleanup removes Lab 5-owned resources while leaving Lab 4 functional.
