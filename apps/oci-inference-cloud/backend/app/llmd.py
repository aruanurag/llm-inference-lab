"""Local-kubeconfig integration for the LLM-D CPU lab.

The workbench deliberately uses a user-provided LLM-D checkout.  Its guides and
charts evolve quickly; pinning the checkout makes every generated overlay and
Helm command reviewable and reproducible for a lab participant.
"""

from __future__ import annotations

import json
import base64
import re
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .config import LLMD_DIR, LOGS_DIR


GAIE_VERSION = "v1.5.0"
ROUTER_CHART = "oci://ghcr.io/llm-d/charts/llm-d-router-standalone"
ROUTER_CHART_VERSION = "v0"
LLMD_REPOSITORY = "https://github.com/llm-d/llm-d.git"
NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


def command_output(command: list[str], *, input_text: str | None = None, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, input=input_text, capture_output=True, text=True, timeout=timeout, check=False)


def require_tool(name: str) -> None:
    if not shutil.which(name):
        raise RuntimeError(f"{name} is required. Install it locally, then reload this page.")


def checked_name(value: str, label: str) -> str:
    if not NAME_RE.fullmatch(value):
        raise ValueError(f"{label} must be a Kubernetes DNS label (lowercase letters, numbers, and hyphens).")
    return value


def yaml_scalar(value: str, label: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError(f"{label} must not contain a newline.")
    return value.replace('"', '\\"')


def kubectl(context: str, *args: str) -> list[str]:
    return ["kubectl", "--context", context, *args]


def list_contexts() -> list[str]:
    require_tool("kubectl")
    result = command_output(["kubectl", "config", "get-contexts", "-o", "name"])
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Unable to read kubeconfig contexts.")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def validate_cluster(context: str, namespace: str) -> dict[str, Any]:
    require_tool("kubectl")
    checked_name(namespace, "Namespace")
    version = command_output(kubectl(context, "version", "-o", "json"))
    if version.returncode:
        raise RuntimeError(version.stderr.strip() or f"Unable to contact Kubernetes context {context!r}.")
    nodes_result = command_output(kubectl(context, "get", "nodes", "-o", "json"))
    if nodes_result.returncode:
        raise RuntimeError(nodes_result.stderr.strip() or "Unable to read cluster nodes.")

    nodes = json.loads(nodes_result.stdout).get("items", [])
    ready_nodes = 0
    cpu_millicores = 0
    memory_kib = 0
    architectures: set[str] = set()
    warnings: list[str] = []
    for node in nodes:
        status = {item.get("type"): item.get("status") for item in node.get("status", {}).get("conditions", [])}
        if status.get("Ready") == "True":
            ready_nodes += 1
        capacity = node.get("status", {}).get("allocatable", {})
        cpu = str(capacity.get("cpu", "0"))
        try:
            cpu_millicores += int(cpu.removesuffix("m")) if cpu.endswith("m") else int(float(cpu) * 1000)
        except ValueError:
            warnings.append(f"Could not read CPU capacity for node {node.get('metadata', {}).get('name', 'unknown')}.")
        memory = str(capacity.get("memory", "0Ki"))
        try:
            memory_kib += int(memory.removesuffix("Ki"))
        except ValueError:
            warnings.append(f"Could not read memory capacity for node {node.get('metadata', {}).get('name', 'unknown')}.")
        architecture = node.get("status", {}).get("nodeInfo", {}).get("architecture")
        if architecture:
            architectures.add(architecture)
    if not nodes:
        warnings.append("No nodes were returned by this context.")
    if ready_nodes == 0:
        warnings.append("No Ready nodes found. Do not deploy until the CPU node pool is healthy.")
    if not shutil.which("helm"):
        warnings.append("Helm is not installed; router deployment will be unavailable until it is installed.")
        helm_version = None
    else:
        helm_result = command_output(["helm", "version", "--short"])
        helm_version = helm_result.stdout.strip() if helm_result.returncode == 0 else None
        if not helm_version:
            warnings.append("Helm is installed but did not return a version.")
    parsed_version = json.loads(version.stdout)
    return {
        "context": context,
        "namespace": namespace,
        "kubectl_version": parsed_version.get("serverVersion", {}).get("gitVersion"),
        "helm_version": helm_version,
        "ready_nodes": ready_nodes,
        "total_nodes": len(nodes),
        "cpu_cores": cpu_millicores / 1000,
        "memory_kib": memory_kib,
        "architectures": sorted(architectures),
        "warnings": warnings,
    }


def repo_root(repo_path: str) -> Path:
    root = Path(repo_path).expanduser().resolve()
    required = [
        root / "guides" / "env.sh",
        root / "guides" / "recipes" / "router" / "base.values.yaml",
        root / "guides" / "optimized-baseline" / "router" / "optimized-baseline.values.yaml",
        root / "guides" / "optimized-baseline" / "modelserver" / "cpu" / "vllm",
    ]
    missing = [str(path.relative_to(root)) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(f"This is not a compatible LLM-D checkout. Missing: {', '.join(missing)}")
    return root


def default_checkout_path() -> Path:
    return LLMD_DIR / "source"


def prepare_checkout(repo_path: str | None = None) -> dict[str, str]:
    """Clone the official source once, or validate an existing pinned checkout."""

    require_tool("git")
    root = Path(repo_path).expanduser().resolve() if repo_path else default_checkout_path()
    if root.exists():
        repo_root(str(root))
        status = "existing"
    else:
        root.parent.mkdir(parents=True, exist_ok=True)
        result = command_output(["git", "clone", "--depth", "1", LLMD_REPOSITORY, str(root)], timeout=600)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "Could not clone the official LLM-D repository.")
        repo_root(str(root))
        status = "cloned"
    revision = command_output(["git", "-C", str(root), "rev-parse", "HEAD"])
    if revision.returncode:
        raise RuntimeError(revision.stderr.strip() or "Could not determine the LLM-D checkout revision.")
    return {"path": str(root), "revision": revision.stdout.strip(), "status": status}


def render_overlay(config: dict[str, Any], experiment_id: int) -> tuple[Path, str]:
    root = repo_root(config["llmd_repo_path"])
    checked_name(config["namespace"], "Namespace")
    checked_name(config["release_name"], "Release name")
    overlay_dir = LLMD_DIR / f"experiment-{experiment_id}" / "cpu-vllm-overlay"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    modelserver_recipe = root / "guides" / "optimized-baseline" / "modelserver" / "cpu" / "vllm"
    relative_recipe = os.path.relpath(modelserver_recipe, overlay_dir)
    cpu = str(config["cpu"])
    memory = f"{config['memory_gib']}Gi"
    model = yaml_scalar(config["model"], "Model")
    cpu_threads_bind = yaml_scalar(config.get("cpu_threads_bind") or "", "CPU thread binding")
    vllm_args = [
        f'                  - "--max_model_len={config["max_model_len"]}"',
        f'                  - "--max_num_seqs={config.get("max_num_seqs", 8)}"',
        f'                  - "--max_num_batched_tokens={config.get("max_num_batched_tokens", 2048)}"',
    ]
    if config.get("enable_prefix_caching", True):
        vllm_args.append('                  - "--enable-prefix-caching"')
    thread_bind_env = f'''\n                  - name: VLLM_CPU_OMP_THREADS_BIND\n                    value: "{cpu_threads_bind}"''' if cpu_threads_bind else ""
    overlay = f'''apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - {relative_recipe}
labels:
  - pairs:
      lab.llm-inference.ai/cpu-architecture: amd64
      lab.llm-inference.ai/cpu-vendor: amd
    # The upstream recipe owns llm-d.ai/* labels, including the immutable
    # Deployment selector. Keep lab metadata on the workload and pod template
    # under separate keys so a benchmark redeploy never changes its identity.
    includeSelectors: false
    includeTemplates: true
patches:
  - target:
      kind: Deployment
      name: decode
    patch: |-
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: decode
      spec:
        # A one-node CPU cluster cannot schedule the old and new 16-core
        # modelserver pods at once. Release the old pod before creating the
        # replacement so parameter changes do not leave a rollout Pending.
        strategy:
          type: RollingUpdate
          rollingUpdate:
            maxSurge: 0
            maxUnavailable: 1
        replicas: {config['replicas']}
        template:
          spec:
            containers:
              - name: modelserver
                args:
                  - "{model}"
                  - "--disable-access-log-for-endpoints=/health,/metrics,/v1/models"
                  - "--disable-hybrid-kv-cache-manager"
{chr(10).join(vllm_args)}
                env:
                  # Public models run without this Secret. It is only required
                  # for gated Hugging Face models selected by the participant.
                  - name: HF_TOKEN
                    valueFrom:
                      secretKeyRef:
                        name: llm-d-hf-token
                        key: HF_TOKEN
                        optional: true
{thread_bind_env}
                  - name: VLLM_CPU_NUM_OF_RESERVED_CPU
                    value: "{config.get('reserved_cpu', 1)}"
                  - name: VLLM_CPU_KVCACHE_SPACE
                    value: "{config['kv_cache_gib']}"
                resources:
                  requests:
                    cpu: "{cpu}"
                    memory: {memory}
                  limits:
                    cpu: "{cpu}"
                    memory: {memory}
'''
    overlay_path = overlay_dir / "kustomization.yaml"
    overlay_path.write_text(overlay, encoding="utf-8")
    return overlay_path, overlay


def make_plan(config: dict[str, Any], experiment_id: int) -> dict[str, Any]:
    root = repo_root(config["llmd_repo_path"])
    overlay_path, overlay = render_overlay(config, experiment_id)
    context, namespace, release = config["context"], config["namespace"], config["release_name"]
    return {
        "context": context,
        "namespace": namespace,
        "release_name": release,
        "overlay_path": str(overlay_path),
        "overlay": overlay,
        "commands": [
            kubectl(context, "apply", "-f", f"https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/{GAIE_VERSION}/v1-manifests.yaml"),
            ["helm", "upgrade", "--install", release, ROUTER_CHART, "-f", str(root / "guides" / "recipes" / "router" / "base.values.yaml"), "-f", str(root / "guides" / "optimized-baseline" / "router" / "optimized-baseline.values.yaml"), "--namespace", namespace, "--kube-context", context, "--create-namespace", "--version", ROUTER_CHART_VERSION],
            ["kubectl", "kustomize", "--load-restrictor", "LoadRestrictionsNone", str(overlay_path.parent)],
            kubectl(context, "-n", namespace, "get", "pods", "-l", "llm-d.ai/guide=optimized-baseline"),
        ],
    }


def deploy(config: dict[str, Any], experiment_id: int) -> tuple[dict[str, Any], Path, str]:
    require_tool("kubectl")
    require_tool("helm")
    plan = make_plan(config, experiment_id)
    context, namespace = config["context"], config["namespace"]
    log_path = LOGS_DIR / f"llm-d-{experiment_id}.log"
    entries: list[str] = []

    def execute(command: list[str], *, input_text: str | None = None, timeout: int = 600) -> None:
        entries.append("$ " + " ".join(command))
        result = command_output(command, input_text=input_text, timeout=timeout)
        entries.extend(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
        if result.returncode:
            log_path.write_text("\n".join(entries) + "\n", encoding="utf-8")
            raise RuntimeError(result.stderr.strip() or f"Command failed with exit code {result.returncode}. See {log_path}")

    namespace_manifest = command_output(kubectl(context, "create", "namespace", namespace, "--dry-run=client", "-o", "yaml"))
    if namespace_manifest.returncode:
        raise RuntimeError(namespace_manifest.stderr.strip() or "Could not render namespace manifest.")
    execute(kubectl(context, "apply", "-f", "-"), input_text=namespace_manifest.stdout)
    if config.get("hf_token"):
        encoded_token = base64.b64encode(config["hf_token"].encode("utf-8")).decode("ascii")
        secret_manifest = f"""apiVersion: v1
kind: Secret
metadata:
  name: llm-d-hf-token
  namespace: {namespace}
type: Opaque
data:
  HF_TOKEN: {encoded_token}
"""
        execute(kubectl(context, "apply", "-f", "-"), input_text=secret_manifest)
    execute(plan["commands"][0])
    execute(plan["commands"][1])
    rendered = command_output(plan["commands"][2])
    if rendered.returncode:
        raise RuntimeError(rendered.stderr.strip() or "Could not render the CPU vLLM overlay.")
    execute(kubectl(context, "-n", namespace, "apply", "-f", "-"), input_text=rendered.stdout)
    log_path.write_text("\n".join(entries) + "\n", encoding="utf-8")
    return plan, log_path, "LLM-D router and CPU vLLM overlay submitted. Wait for model pods to become Ready before benchmarking."
