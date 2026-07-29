# Setup: LLM-D CPU Cluster Lab

## 1. Verify local tools

```bash
kubectl version --client
helm version --short
kubectl config get-contexts
```

Select the intended context explicitly for every command. Avoid relying on the current context while learning.

## 2. Verify the existing CPU node pool

```bash
kubectl --context <context> get nodes -o wide
kubectl --context <context> describe nodes
```

Confirm that the nodes are Ready and that the requested CPU and memory fit after normal Kubernetes reservations. The model-server pod requests equal limits so the lab has predictable CPU capacity.

## 3. Pin the LLM-D sources

```bash
git clone https://github.com/llm-d/llm-d.git ~/src/llm-d
cd ~/src/llm-d
git rev-parse HEAD
```

Record the SHA in `observations.md`. The workbench validates that this checkout contains the current optimized-baseline CPU vLLM recipe and renders an overlay against it.

## 4. Optional Hugging Face token

The default Qwen model is public and does not need a token. If you select a gated model, provide its token in the workbench only at deployment time. It is written to a namespace-scoped Kubernetes Secret named `llm-d-hf-token`; it is not added to this repository or the workbench state database.

## 5. Namespace permissions

The user behind the kubeconfig needs permission to create resources in the lab namespace and to apply the Gateway API Inference Extension CRDs if those are not already installed. A platform administrator may need to perform the CRD installation once for a shared cluster.
