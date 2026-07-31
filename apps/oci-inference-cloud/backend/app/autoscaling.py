"""Lab 4 platform bootstrap, KEDA policy, and observation helpers.

This module deliberately separates cluster-scoped platform work (Prometheus
Operator CRDs and KEDA) from namespace-scoped LLM-D autoscaling resources.  A
participant must review a plan and explicitly confirm before the former runs.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from . import llmd
from .config import LLMD_DIR, LOGS_DIR
from .ssh import free_local_port


MONITORING_NAMESPACE = "llm-d-monitoring"
KEDA_NAMESPACE = "keda"
PROMETHEUS_RELEASE = "llmd"
KEDA_RELEASE = "keda"
PROMETHEUS_CHART = "prometheus-community/kube-prometheus-stack"
KEDA_CHART = "kedacore/keda"
# Pin versions so a lab result remains reproducible. Bump them only after
# validating the complete bootstrap flow against the supported OKE version.
PROMETHEUS_CHART_VERSION = "77.11.0"
KEDA_CHART_VERSION = "2.20.0"
GRAFANA_SECRET = "llmd-grafana-admin"
MODEL_DEPLOYMENT = "optimized-baseline-cpu-vllm-decode"


def _run(command: list[str], *, input_text: str | None = None, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return llmd.command_output(command, input_text=input_text, timeout=timeout)


def _json(command: list[str]) -> dict[str, Any]:
    result = _run(command)
    if result.returncode:
        return {}
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return {}


def _exists(context: str, *args: str) -> bool:
    return _run(llmd.kubectl(context, *args)).returncode == 0


def _helm_releases(context: str) -> list[dict[str, Any]]:
    result = _run(["helm", "list", "--all-namespaces", "--kube-context", context, "-o", "json"])
    if result.returncode:
        return []
    try:
        parsed = json.loads(result.stdout or "[]")
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def _matching_releases(releases: list[dict[str, Any]], names: set[str]) -> list[dict[str, str]]:
    return [
        {"name": str(item.get("name", "")), "namespace": str(item.get("namespace", "")), "chart": str(item.get("chart", ""))}
        for item in releases
        if str(item.get("name", "")) in names
        or any(token in str(item.get("chart", "")).lower() for token in ("kube-prometheus-stack", "keda"))
    ]


def preflight(
    context: str,
    namespace: str,
    release_name: str,
    monitoring_namespace: str = MONITORING_NAMESPACE,
    prometheus_service_name: str = f"{PROMETHEUS_RELEASE}-kube-prometheus-stack-prometheus",
    grafana_service_name: str = f"{PROMETHEUS_RELEASE}-grafana",
    keda_namespace: str = KEDA_NAMESPACE,
) -> dict[str, Any]:
    """Read-only diagnostics for the Lab 4 platform and target workload."""

    llmd.require_tool("kubectl")
    llmd.checked_name(namespace, "Namespace")
    llmd.checked_name(release_name, "Release name")
    warnings: list[str] = []
    if not _exists(context, "get", "nodes"):
        warnings.append("The selected kubeconfig context is not reachable.")
    if not shutil.which("helm"):
        warnings.append("Helm is required to bootstrap the dedicated platform stack.")

    releases = _helm_releases(context)
    conflicts = _matching_releases(releases, {PROMETHEUS_RELEASE, KEDA_RELEASE})
    service_monitor = _exists(context, "get", "crd", "servicemonitors.monitoring.coreos.com")
    scaled_object = _exists(context, "get", "crd", "scaledobjects.keda.sh")
    prometheus_service = _exists(context, "-n", monitoring_namespace, "get", "service", prometheus_service_name)
    grafana_service = _exists(context, "-n", monitoring_namespace, "get", "service", grafana_service_name)
    keda_ready = _exists(context, "-n", keda_namespace, "get", "deployment", "keda-operator")
    epp_service = _exists(context, "-n", namespace, "get", "service", f"{release_name}-epp")
    epp_monitor = _exists(context, "-n", namespace, "get", "servicemonitor") if service_monitor else False
    model_deployment = _exists(context, "-n", namespace, "get", "deployment", MODEL_DEPLOYMENT)
    hpas = _json(llmd.kubectl(context, "-n", namespace, "get", "hpa", "-o", "json")).get("items", [])
    competing_hpas = [
        item.get("metadata", {}).get("name", "unknown") for item in hpas
        if item.get("spec", {}).get("scaleTargetRef", {}).get("name") == MODEL_DEPLOYMENT
        and not str(item.get("metadata", {}).get("name", "")).startswith("keda-hpa-")
    ]
    nodes = _json(llmd.kubectl(context, "get", "nodes", "-o", "json")).get("items", [])
    if not nodes:
        warnings.append("No nodes were returned. OKE Cluster Autoscaler cannot be validated from an empty cluster.")
    warnings.append(
        "OKE Cluster Autoscaler is administrator-managed. Confirm the selected managed node pool has min/max bounds and can add a node for this pod's CPU and memory requests."
    )
    if competing_hpas:
        warnings.append("A non-KEDA HPA already targets the CPU vLLM Deployment. Remove or retarget it before applying the KEDA ScaledObject.")
    return {
        "context": context,
        "namespace": namespace,
        "monitoring_namespace": monitoring_namespace,
        "keda_namespace": keda_namespace,
        "service_monitor_crd": service_monitor,
        "scaled_object_crd": scaled_object,
        "prometheus_service": prometheus_service,
        "grafana_service": grafana_service,
        "keda_ready": keda_ready,
        "epp_service": epp_service,
        "epp_service_monitor": epp_monitor,
        "model_deployment": model_deployment,
        "node_count": len(nodes),
        "conflicting_releases": conflicts,
        "competing_hpas": competing_hpas,
        "warnings": warnings,
    }


def _platform_values() -> str:
    # The Grafana Secret is created separately. It is intentionally absent from
    # this file and every rendered plan/API response.
    return f'''grafana:
  admin:
    existingSecret: {GRAFANA_SECRET}
    userKey: admin-user
    passwordKey: admin-password
  service:
    type: ClusterIP
  sidecar:
    dashboards:
      enabled: true
      searchNamespace: {MONITORING_NAMESPACE}
      label: grafana_dashboard
    datasources:
      defaultDatasourceEnabled: false
  datasources:
    datasources.yaml:
      apiVersion: 1
      datasources:
        - name: Prometheus
          type: prometheus
          url: http://{PROMETHEUS_RELEASE}-kube-prometheus-stack-prometheus.{MONITORING_NAMESPACE}.svc.cluster.local:9090
          access: proxy
          isDefault: true
prometheus:
  service:
    type: ClusterIP
  prometheusSpec:
    serviceMonitorSelectorNilUsesHelmValues: false
    serviceMonitorSelector: {{}}
    serviceMonitorNamespaceSelector: {{}}
    podMonitorSelectorNilUsesHelmValues: false
    podMonitorSelector: {{}}
    podMonitorNamespaceSelector: {{}}
    ruleSelectorNilUsesHelmValues: false
    ruleSelector: {{}}
    ruleNamespaceSelector: {{}}
'''


def _dashboard_manifests(llmd_repo_path: str) -> tuple[dict[str, Any], list[str]]:
    root = llmd.repo_root(llmd_repo_path)
    directory = root / "guides" / "recipes" / "observability" / "grafana" / "dashboards"
    if not directory.is_dir():
        raise RuntimeError("The LLM-D checkout does not contain the upstream Grafana dashboards.")
    items: list[dict[str, Any]] = []
    names: list[str] = []
    for dashboard in sorted(directory.glob("*.json")):
        name = dashboard.stem
        names.append(name)
        items.append({
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": name, "namespace": MONITORING_NAMESPACE, "labels": {"grafana_dashboard": "1", "app.kubernetes.io/managed-by": "oci-inference-cloud"}},
            "data": {dashboard.name: dashboard.read_text(encoding="utf-8")},
        })
    if not items:
        raise RuntimeError("No LLM-D Grafana dashboards were found in the pinned checkout.")
    return {"apiVersion": "v1", "kind": "List", "items": items}, names


def platform_plan(context: str, llmd_repo_path: str, mode: str) -> dict[str, Any]:
    if mode not in {"dedicated", "existing"}:
        raise ValueError("Platform mode must be either 'dedicated' or 'existing'.")
    if mode == "existing":
        return {
            "mode": mode,
            "commands": [llmd.kubectl(context, "get", "crd", "servicemonitors.monitoring.coreos.com"), llmd.kubectl(context, "get", "crd", "scaledobjects.keda.sh")],
            "values": "No platform resources will be installed. The app will validate the existing Prometheus and KEDA services.",
            "dashboards": [],
            "cluster_scoped_changes": [],
        }
    _, dashboards = _dashboard_manifests(llmd_repo_path)
    values_path = str(LLMD_DIR / "lab4" / "platform-values.yaml")
    return {
        "mode": mode,
        "commands": [
            ["helm", "repo", "add", "--force-update", "prometheus-community", "https://prometheus-community.github.io/helm-charts"],
            ["helm", "repo", "add", "--force-update", "kedacore", "https://kedacore.github.io/charts"],
            ["helm", "repo", "update"],
            ["helm", "upgrade", "--install", PROMETHEUS_RELEASE, PROMETHEUS_CHART, "--namespace", MONITORING_NAMESPACE, "--create-namespace", "--kube-context", context, "--version", PROMETHEUS_CHART_VERSION, "-f", values_path],
            ["helm", "upgrade", "--install", KEDA_RELEASE, KEDA_CHART, "--namespace", KEDA_NAMESPACE, "--create-namespace", "--kube-context", context, "--version", KEDA_CHART_VERSION],
        ],
        "values": _platform_values(),
        "dashboards": dashboards,
        "cluster_scoped_changes": ["Prometheus Operator CRDs", "KEDA CRDs", "KEDA external metrics API service"],
    }


def _execute(entries: list[str], command: list[str], *, input_text: str | None = None, timeout: int = 600) -> None:
    entries.append("$ " + " ".join(command))
    result = _run(command, input_text=input_text, timeout=timeout)
    entries.extend(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"Command failed with exit code {result.returncode}.")


def bootstrap(context: str, llmd_repo_path: str, mode: str, grafana_admin_password: str) -> tuple[dict[str, Any], Path]:
    """Install only the dedicated stack; no secret is written to the log."""

    llmd.require_tool("kubectl")
    llmd.require_tool("helm")
    plan = platform_plan(context, llmd_repo_path, mode)
    if mode == "existing":
        return plan, LOGS_DIR / "lab4-existing-platform.log"
    secret_exists = _run(llmd.kubectl(context, "-n", MONITORING_NAMESPACE, "get", "secret", GRAFANA_SECRET)).returncode == 0
    if len(grafana_admin_password) < 12 and not secret_exists:
        raise ValueError("Grafana admin password must contain at least 12 characters.")
    log_path = LOGS_DIR / f"lab4-platform-{int(time.time())}.log"
    entries: list[str] = []
    values_dir = LLMD_DIR / "lab4"
    values_dir.mkdir(parents=True, exist_ok=True)
    values_path = values_dir / "platform-values.yaml"
    values_path.write_text(_platform_values(), encoding="utf-8")
    try:
        _execute(entries, ["helm", "repo", "add", "--force-update", "prometheus-community", "https://prometheus-community.github.io/helm-charts"])
        _execute(entries, ["helm", "repo", "add", "--force-update", "kedacore", "https://kedacore.github.io/charts"])
        _execute(entries, ["helm", "repo", "update"])
        # The Grafana chart consumes an existing Secret. Create the namespace
        # first; Helm's --create-namespace only runs later during chart
        # installation and cannot make this secret apply succeed.
        namespace_manifest = _run(llmd.kubectl(context, "create", "namespace", MONITORING_NAMESPACE, "--dry-run=client", "-o", "json"))
        if namespace_manifest.returncode:
            raise RuntimeError(namespace_manifest.stderr.strip() or "Could not render the monitoring namespace manifest.")
        _execute(entries, llmd.kubectl(context, "apply", "-f", "-"), input_text=namespace_manifest.stdout)
        if grafana_admin_password:
            secret = {
                "apiVersion": "v1", "kind": "Secret", "metadata": {"name": GRAFANA_SECRET, "namespace": MONITORING_NAMESPACE, "labels": {"app.kubernetes.io/managed-by": "oci-inference-cloud"}},
                "type": "Opaque", "stringData": {"admin-user": "admin", "admin-password": grafana_admin_password},
            }
            # Do not add the secret manifest to entries: it contains the password.
            result = _run(llmd.kubectl(context, "apply", "-f", "-"), input_text=json.dumps(secret), timeout=180)
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or "Could not create the Grafana credential Secret.")
        else:
            entries.append("Reusing the existing Grafana credential Secret; no password was read or logged.")
        _execute(entries, plan["commands"][3] + ["-f", str(values_path)])
        _execute(entries, plan["commands"][4])
        dashboards, _ = _dashboard_manifests(llmd_repo_path)
        _execute(entries, llmd.kubectl(context, "apply", "-f", "-"), input_text=json.dumps(dashboards))
        _execute(entries, llmd.kubectl(context, "-n", MONITORING_NAMESPACE, "rollout", "status", "deployment", f"{PROMETHEUS_RELEASE}-grafana", "--timeout=300s"), timeout=330)
        _execute(entries, llmd.kubectl(context, "-n", KEDA_NAMESPACE, "rollout", "status", "deployment", "keda-operator", "--timeout=300s"), timeout=330)
    except Exception:
        log_path.write_text("\n".join(entries) + "\n", encoding="utf-8")
        raise
    log_path.write_text("\n".join(entries) + "\n", encoding="utf-8")
    return plan, log_path


def _scaled_object(config: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    namespace, release, model = config["namespace"], config["release_name"], config["model"]
    llmd.checked_name(namespace, "Namespace")
    prometheus = policy.get("prometheus_address") or f"http://{PROMETHEUS_RELEASE}-kube-prometheus-stack-prometheus.{MONITORING_NAMESPACE}.svc.cluster.local:9090"
    common = f'namespace="{namespace}",service="{release}-epp",model_name="{model}"'
    spec: dict[str, Any] = {
        "scaleTargetRef": {"name": MODEL_DEPLOYMENT},
        "pollingInterval": policy["polling_interval"],
        "cooldownPeriod": policy["cooldown_period"],
        "minReplicaCount": policy["min_replicas"],
        "maxReplicaCount": policy["max_replicas"],
        "advanced": {"horizontalPodAutoscalerConfig": {"name": "keda-hpa-llm-d-epp-demand", "behavior": {"scaleDown": {"stabilizationWindowSeconds": policy["scale_down_stabilization"], "policies": [{"type": "Percent", "value": 100, "periodSeconds": 60}]}}}},
        "triggers": [
            {"type": "prometheus", "metadata": {"serverAddress": prometheus, "metricName": "llmd_epp_queue_size", "threshold": str(policy["queue_threshold"]), "query": f"sum(llm_d_epp_flow_control_queue_size{{{common}}})"}},
            {"type": "prometheus", "metadata": {"serverAddress": prometheus, "metricName": "llmd_epp_request_running", "threshold": str(policy["running_request_threshold"]), "query": f"sum(llm_d_epp_request_running{{{common}}})"}},
        ],
    }
    auth_name = policy.get("prometheus_trigger_authentication")
    if auth_name:
        for trigger in spec["triggers"]:
            trigger["authenticationRef"] = {"name": str(auth_name)}
    return {
        "apiVersion": "keda.sh/v1alpha1",
        "kind": "ScaledObject",
        "metadata": {"name": "llm-d-epp-demand", "namespace": namespace, "labels": {"app.kubernetes.io/managed-by": "oci-inference-cloud", "lab.llm-inference.ai": "lab-4"}},
        "spec": spec,
    }


def autoscaling_plan(config: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    manifest = _scaled_object(config, policy)
    return {
        "context": config["context"], "namespace": config["namespace"], "target_deployment": MODEL_DEPLOYMENT,
        "manifest": json.dumps(manifest, indent=2),
        "commands": [llmd.kubectl(config["context"], "-n", config["namespace"], "apply", "-f", "-"), llmd.kubectl(config["context"], "-n", config["namespace"], "get", "scaledobject", "llm-d-epp-demand"), llmd.kubectl(config["context"], "-n", config["namespace"], "get", "hpa", "keda-hpa-llm-d-epp-demand")],
    }


def apply_autoscaling(config: dict[str, Any], policy: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    plan = autoscaling_plan(config, policy)
    existing = _json(llmd.kubectl(config["context"], "-n", config["namespace"], "get", "hpa", "-o", "json")).get("items", [])
    competing = [item.get("metadata", {}).get("name", "unknown") for item in existing if item.get("spec", {}).get("scaleTargetRef", {}).get("name") == MODEL_DEPLOYMENT and not str(item.get("metadata", {}).get("name", "")).startswith("keda-hpa-")]
    if competing:
        raise RuntimeError("A non-KEDA HPA already targets the CPU vLLM Deployment: " + ", ".join(competing))
    log_path = LOGS_DIR / f"lab4-autoscaling-{int(time.time())}.log"
    result = _run(plan["commands"][0], input_text=plan["manifest"], timeout=180)
    log_path.write_text("$ " + " ".join(plan["commands"][0]) + "\n" + result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Could not apply the KEDA ScaledObject.")
    return plan, log_path


def _prometheus_query(context: str, query: str, monitoring_namespace: str = MONITORING_NAMESPACE, prometheus_service: str = f"{PROMETHEUS_RELEASE}-kube-prometheus-stack-prometheus") -> float | None:
    port = free_local_port()
    command = llmd.kubectl(context, "-n", monitoring_namespace, "port-forward", f"service/{prometheus_service}", f"{port}:9090")
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(24):
            if process.poll() is not None:
                return None
            try:
                url = f"http://127.0.0.1:{port}/api/v1/query?" + urllib.parse.urlencode({"query": query})
                with urllib.request.urlopen(url, timeout=1) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    result = payload.get("data", {}).get("result", [])
                    return float(result[0]["value"][1]) if result else None
            except Exception:
                time.sleep(0.25)
        return None
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()


def observation(config: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    context, namespace, release, model = config["context"], config["namespace"], config["release_name"], config["model"]
    deployment = _json(llmd.kubectl(context, "-n", namespace, "get", "deployment", MODEL_DEPLOYMENT, "-o", "json"))
    pods = _json(llmd.kubectl(context, "-n", namespace, "get", "pods", "-o", "json")).get("items", [])
    hpa = _json(llmd.kubectl(context, "-n", namespace, "get", "hpa", "keda-hpa-llm-d-epp-demand", "-o", "json"))
    scaled = _json(llmd.kubectl(context, "-n", namespace, "get", "scaledobject", "llm-d-epp-demand", "-o", "json"))
    selector = f'namespace="{namespace}",service="{release}-epp",model_name="{model}"'
    relevant = [pod for pod in pods if MODEL_DEPLOYMENT.replace("-decode", "") in pod.get("metadata", {}).get("name", "")]
    monitoring_namespace = str(policy.get("monitoring_namespace") or MONITORING_NAMESPACE)
    prometheus_service = str(policy.get("prometheus_service") or f"{PROMETHEUS_RELEASE}-kube-prometheus-stack-prometheus")
    return {
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "queue_depth": _prometheus_query(context, f"sum(llm_d_epp_flow_control_queue_size{{{selector}}})", monitoring_namespace, prometheus_service),
        "running_requests": _prometheus_query(context, f"sum(llm_d_epp_request_running{{{selector}}})", monitoring_namespace, prometheus_service),
        "desired_replicas": deployment.get("spec", {}).get("replicas"),
        "ready_replicas": deployment.get("status", {}).get("readyReplicas", 0),
        "hpa_desired_replicas": hpa.get("status", {}).get("desiredReplicas"),
        "hpa_current_replicas": hpa.get("status", {}).get("currentReplicas"),
        "scaled_object_ready": next((item.get("status") for item in scaled.get("status", {}).get("conditions", []) if item.get("type") == "Ready"), "Unknown"),
        "pending_pods": [pod.get("metadata", {}).get("name") for pod in relevant if pod.get("status", {}).get("phase") == "Pending"],
        "node_count": len(_json(llmd.kubectl(context, "get", "nodes", "-o", "json")).get("items", [])),
        "policy": {key: policy[key] for key in ("min_replicas", "max_replicas", "queue_threshold", "running_request_threshold")},
    }


def uninstall_platform(context: str) -> Path:
    """Remove only the Lab 4-owned releases. Caller authorizes this explicitly."""
    log_path = LOGS_DIR / f"lab4-platform-uninstall-{int(time.time())}.log"
    entries: list[str] = []
    for command in (["helm", "uninstall", KEDA_RELEASE, "--namespace", KEDA_NAMESPACE, "--kube-context", context], ["helm", "uninstall", PROMETHEUS_RELEASE, "--namespace", MONITORING_NAMESPACE, "--kube-context", context]):
        result = _run(command)
        entries.append("$ " + " ".join(command))
        entries.extend(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
        if result.returncode and "release: not found" not in result.stderr.lower():
            log_path.write_text("\n".join(entries) + "\n", encoding="utf-8")
            raise RuntimeError(result.stderr.strip() or "Helm uninstall failed.")
    for namespace in (KEDA_NAMESPACE, MONITORING_NAMESPACE):
        command = llmd.kubectl(context, "delete", "namespace", namespace, "--ignore-not-found")
        result = _run(command)
        entries.append("$ " + " ".join(command))
        entries.extend(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
        if result.returncode:
            log_path.write_text("\n".join(entries) + "\n", encoding="utf-8")
            raise RuntimeError(result.stderr.strip() or "Namespace cleanup failed.")
    log_path.write_text("\n".join(entries) + "\n", encoding="utf-8")
    return log_path
