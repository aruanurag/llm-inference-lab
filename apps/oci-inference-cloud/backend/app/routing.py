"""Pure resource rendering for the Lab 5 hybrid LLM-D routing experiment.

Lab 5 adds a small LiteLLM Proxy service *in front of* an existing LLM-D EPP
service.  It is deliberately not an LLM-D replacement: ``private`` and
``fast`` aliases stay in-cluster and pass through LLM-D, while ``coding`` and
``reasoning`` are explicit OpenRouter aliases.  This module contains no
kubectl, Helm, state, or network calls so its plans can be reviewed and tested
without modifying a cluster.

The OpenRouter credential is intentionally not rendered.  Callers that apply a
plan must create the referenced Secret from the request body directly and must
never include that Secret's contents in a plan, response, log, or persisted
setting.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import secrets
from collections.abc import Mapping
from typing import Any

from . import llmd


LAB_NAME = "lab-5"
ROUTER_NAME = "llm-d-routing"
# These are the default names only. Rendering derives every owned ConfigMap and
# Secret from ``router_name`` so two Lab 5 experiments can share a namespace.
ROUTER_CONFIG_MAP = "llm-d-routing-config"
ROUTER_SECRET = "llm-d-routing-openrouter"
ROUTER_SECRET_KEY = "OPENROUTER_API_KEY"
ROUTER_MASTER_KEY = "LITELLM_MASTER_KEY"
ROUTER_SERVICE_PORT = 80
ROUTER_CONTAINER_PORT = 4000
ROUTER_DASHBOARD = "llm-d-routing-overview"
MONITORING_NAMESPACE = "llm-d-monitoring"
PROMETHEUS_SERVICE = "llmd-kube-prometheus-stack-prometheus"

# This is the published immutable digest for LiteLLM v1.93.1.  It is not a
# mutable ``latest``/``stable`` tag, which keeps a lab run reproducible.
LITELLM_IMAGE = (
    "ghcr.io/berriai/litellm@"
    "sha256:caee7ffd8ae5ff84d4d37610a1871367eb037d5349ace155b2f9fd9e44cb5e1f"
)

LOCAL_ALIASES = ("private", "fast")
EXTERNAL_ALIASES = ("coding", "reasoning")
ALIASES = LOCAL_ALIASES + EXTERNAL_ALIASES
EXTERNAL_MAX_TOKENS = 512

_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}$")
# Match actual credential field names rather than broad substrings.  In
# particular, ``max_tokens`` is a harmless benchmark/route setting and must
# remain numeric in a redacted plan response.
_SENSITIVE_KEY_RE = re.compile(
    r"(?:secret|password|(?:api|master)[_-]?key|credential|(?:^|_)[a-z0-9_-]*token$)", re.IGNORECASE,
)


def _required_text(config: Mapping[str, Any], key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key.replace('_', ' ').capitalize()} is required.")
    value = value.strip()
    if "\n" in value or "\r" in value or "\x00" in value:
        raise ValueError(f"{key.replace('_', ' ').capitalize()} must not contain a newline or NUL byte.")
    return value


def _model_id(value: str, label: str) -> str:
    value = value.strip()
    if not _MODEL_ID_RE.fullmatch(value):
        raise ValueError(
            f"{label} must be a provider/model identifier using letters, numbers, '.', '_', '-', '/', ':', '@', or '+'."
        )
    return value


def _name(config: Mapping[str, Any], key: str, default: str | None = None) -> str:
    value = config.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key.replace('_', ' ').capitalize()} is required.")
    return llmd.checked_name(value.strip(), key.replace("_", " ").capitalize())


def _labels(router_name: str) -> dict[str, str]:
    """Return resource ownership labels; selectors intentionally use a subset."""

    return {
        "app.kubernetes.io/name": ROUTER_NAME,
        "app.kubernetes.io/instance": router_name,
        "app.kubernetes.io/managed-by": "oci-inference-cloud",
        "app.kubernetes.io/part-of": "llm-d-routing",
        "lab.llm-inference.ai": LAB_NAME,
        "lab.llm-inference.ai/owned": "true",
    }


def resource_names(config: Mapping[str, Any]) -> dict[str, str]:
    """Return collision-free Lab 5-owned resource names for a router config."""

    router_name = config["router_name"]
    return {
        "router": router_name,
        "config_map": f"{router_name}-config",
        "secret": f"{router_name}-openrouter",
        "dashboard": f"{router_name}-overview",
    }


def validate_config(config: Mapping[str, Any], *, require_openrouter_key: bool = False) -> dict[str, Any]:
    """Normalize and validate a Lab 5 configuration without exposing a secret.

    ``source_experiment_id`` is preserved as non-sensitive provenance.  The
    caller resolves it to the Lab 4 deployment values before calling this
    function; the manifests do not need to know how settings are stored.
    """

    router_name = _name(config, "router_name", ROUTER_NAME)
    # ``-openrouter`` is the longest derived suffix. Keep every generated
    # resource within Kubernetes's 63-character DNS-label limit.
    if len(router_name) > 51:
        raise ValueError("Router name must contain at most 51 characters so Lab 5-owned resource names remain valid.")
    normalized: dict[str, Any] = {
        "context": _required_text(config, "context"),
        "namespace": _name(config, "namespace"),
        "release_name": _name(config, "release_name"),
        "model": _model_id(_required_text(config, "model"), "Local LLM-D model"),
        "coding_model": _model_id(_required_text(config, "coding_model"), "OpenRouter coding model"),
        "reasoning_model": _model_id(_required_text(config, "reasoning_model"), "OpenRouter reasoning model"),
        "router_name": router_name,
        "monitoring_namespace": _name(config, "monitoring_namespace", MONITORING_NAMESPACE),
        "prometheus_service": _name(config, "prometheus_service", PROMETHEUS_SERVICE),
    }
    source_id = config.get("source_experiment_id")
    if source_id is not None:
        if not isinstance(source_id, int) or isinstance(source_id, bool) or source_id < 1:
            raise ValueError("Source experiment ID must be a positive integer.")
        normalized["source_experiment_id"] = source_id

    key = config.get("openrouter_api_key")
    if key is not None:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("OpenRouter API key must be a non-empty string when supplied.")
        if "\n" in key or "\r" in key or "\x00" in key:
            raise ValueError("OpenRouter API key must not contain a newline or NUL byte.")
        # Preserve only this deploy-only value in the normalized object that a
        # caller receives. ``routing_plan`` explicitly strips it.
        normalized["openrouter_api_key"] = key
    if require_openrouter_key and "openrouter_api_key" not in normalized:
        raise ValueError("An OpenRouter API key is required to deploy coding and reasoning routes.")
    return normalized


def alias_details(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Describe the fixed alias policy exposed by the routing endpoint."""

    safe = validate_config(config)
    return [
        {"alias": alias, "destination": "llm-d", "model": safe["model"], "max_tokens": None}
        for alias in LOCAL_ALIASES
    ] + [
        {
            "alias": alias,
            "destination": "openrouter",
            "model": safe[f"{alias}_model"],
            "max_tokens": EXTERNAL_MAX_TOKENS,
        }
        for alias in EXTERNAL_ALIASES
    ]


def validate_inference_request(alias: str, max_tokens: int) -> dict[str, Any]:
    """Apply the public alias allow-list and external output-token guardrail."""

    if alias not in ALIASES:
        raise ValueError("Model must be one of: private, fast, coding, reasoning.")
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens < 1:
        raise ValueError("max_tokens must be a positive integer.")
    if alias in EXTERNAL_ALIASES and max_tokens > EXTERNAL_MAX_TOKENS:
        raise ValueError(f"OpenRouter routes are limited to {EXTERNAL_MAX_TOKENS} max_tokens for this lab.")
    return {
        "alias": alias,
        "destination": "llm-d" if alias in LOCAL_ALIASES else "openrouter",
        "max_tokens": max_tokens,
        "external_max_tokens": EXTERNAL_MAX_TOKENS if alias in EXTERNAL_ALIASES else None,
    }


def redact(value: Any) -> Any:
    """Return a deep copy with likely credential values replaced.

    This is intentionally useful to API handlers as a final defense in depth:
    plans themselves omit secret data, but an exception/report that includes an
    original request should still be safe to return or log.
    """

    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _SENSITIVE_KEY_RE.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return copy.deepcopy(value)


def new_router_master_key() -> str:
    """Generate an ephemeral, deployment-only LiteLLM master key.

    Callers must pass it straight to :func:`secret_manifest` and then discard
    it. It is not suitable for API responses, state settings, plans, or logs.
    """

    return "sk-lab5-" + secrets.token_urlsafe(32)


def secret_manifest(config: Mapping[str, Any], router_master_key: str) -> dict[str, Any]:
    """Build the apply-time Secret manifest; never add this to a plan.

    The application layer owns the safe lifecycle: call it only during deploy,
    send the result directly to ``kubectl apply -f -``, and avoid recording the
    returned dictionary. Keeping this separate makes accidental inclusion in a
    preview materially harder.
    """

    safe = validate_config(config, require_openrouter_key=True)
    if not isinstance(router_master_key, str) or len(router_master_key) < 24:
        raise ValueError("Router master key must contain at least 24 characters.")
    if "\n" in router_master_key or "\r" in router_master_key or "\x00" in router_master_key:
        raise ValueError("Router master key must not contain a newline or NUL byte.")
    names = resource_names(safe)
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": names["secret"], "namespace": safe["namespace"], "labels": _labels(safe["router_name"])},
        "type": "Opaque",
        "stringData": {
            ROUTER_SECRET_KEY: safe["openrouter_api_key"],
            ROUTER_MASTER_KEY: router_master_key,
        },
    }


def _epp_base_url(config: Mapping[str, Any]) -> str:
    return f"http://{config['release_name']}-epp.{config['namespace']}.svc.cluster.local/v1"


def _proxy_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Render LiteLLM configuration without any credential value."""

    local = {
        "model": f"openai/{config['model']}",
        "api_base": _epp_base_url(config),
        # LLM-D's cluster-local EPP does not require a client API key. LiteLLM
        # still expects an OpenAI-compatible placeholder for this provider.
        "api_key": "not-needed",
        "num_retries": 0,
    }
    external = lambda model: {
        "model": f"openrouter/{model}",
        "api_key": f"os.environ/{ROUTER_SECRET_KEY}",
        "num_retries": 0,
        # OpenRouter gets an explicit privacy preference and must not select a
        # provider fallback. There is also no LiteLLM fallback to the local
        # model; an external failure is returned to the caller.
        "extra_body": {"provider": {"data_collection": "deny", "allow_fallbacks": False}},
    }
    return {
        "model_list": [
            {"model_name": alias, "litellm_params": copy.deepcopy(local)} for alias in LOCAL_ALIASES
        ] + [
            {"model_name": alias, "litellm_params": external(config[f"{alias}_model"])}
            for alias in EXTERNAL_ALIASES
        ],
        "router_settings": {
            "fallbacks": [],
            "context_window_fallbacks": [],
        },
        "litellm_settings": {
            "callbacks": ["prometheus"],
            "prometheus_emit_stream_label": False,
            "turn_off_message_logging": True,
            "redact_user_api_key_info": True,
            "disable_end_user_cost_tracking": True,
            "default_fallbacks": [],
            "context_window_fallbacks": [],
            "content_policy_fallbacks": [],
            # Avoid creating sensitive/high-cardinality series inside the
            # proxy in the first place. ServiceMonitor relabeling below is a
            # second defensive layer for labels future LiteLLM versions add.
            "prometheus_exclude_labels": [
                "hashed_api_key",
                "api_key_alias",
                "end_user",
                "user",
                "user_email",
                "client_ip",
                "user_agent",
                "api_base",
            ],
        },
        "general_settings": {
            "master_key": f"os.environ/{ROUTER_MASTER_KEY}",
            "disable_spend_logs": True,
        },
    }


def _config_map(config: Mapping[str, Any]) -> dict[str, Any]:
    labels = _labels(config["router_name"])
    names = resource_names(config)
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": names["config_map"], "namespace": config["namespace"], "labels": labels},
        # JSON is valid YAML, so LiteLLM's --config accepts this safely while
        # making values easy to inspect in a plan and resistant to YAML input
        # interpolation from external model names.
        "data": {"config.yaml": json.dumps(_proxy_config(config), indent=2, sort_keys=True) + "\n"},
    }


def _deployment(config: Mapping[str, Any]) -> dict[str, Any]:
    labels = _labels(config["router_name"])
    names = resource_names(config)
    selector = {"app.kubernetes.io/name": ROUTER_NAME, "app.kubernetes.io/instance": config["router_name"]}
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": config["router_name"], "namespace": config["namespace"], "labels": labels},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": selector},
            "strategy": {"type": "Recreate"},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "automountServiceAccountToken": False,
                    "containers": [{
                        "name": "litellm",
                        "image": LITELLM_IMAGE,
                        "imagePullPolicy": "IfNotPresent",
                        "args": ["--config", "/app/config/config.yaml", "--port", str(ROUTER_CONTAINER_PORT), "--num_workers", "1"],
                        "ports": [{"name": "http", "containerPort": ROUTER_CONTAINER_PORT, "protocol": "TCP"}],
                        "env": [
                            {"name": "LITELLM_LOG", "value": "ERROR"},
                            {
                                "name": ROUTER_SECRET_KEY,
                                "valueFrom": {"secretKeyRef": {"name": names["secret"], "key": ROUTER_SECRET_KEY}},
                            },
                            {
                                "name": ROUTER_MASTER_KEY,
                                "valueFrom": {"secretKeyRef": {"name": names["secret"], "key": ROUTER_MASTER_KEY}},
                            },
                        ],
                        "resources": {
                            "requests": {"cpu": "250m", "memory": "512Mi"},
                            "limits": {"cpu": "1", "memory": "1Gi"},
                        },
                        "securityContext": {
                            "allowPrivilegeEscalation": False,
                            "capabilities": {"drop": ["ALL"]},
                        },
                        "volumeMounts": [{"name": "config", "mountPath": "/app/config", "readOnly": True}],
                        "readinessProbe": {"httpGet": {"path": "/health/readiness", "port": "http"}, "initialDelaySeconds": 5, "periodSeconds": 5},
                        "livenessProbe": {"httpGet": {"path": "/health/liveliness", "port": "http"}, "initialDelaySeconds": 15, "periodSeconds": 10},
                    }],
                    "volumes": [{"name": "config", "configMap": {"name": names["config_map"]}}],
                },
            },
        },
    }


def _service(config: Mapping[str, Any]) -> dict[str, Any]:
    labels = _labels(config["router_name"])
    selector = {"app.kubernetes.io/name": ROUTER_NAME, "app.kubernetes.io/instance": config["router_name"]}
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": config["router_name"], "namespace": config["namespace"], "labels": labels},
        "spec": {
            "type": "ClusterIP",
            "selector": selector,
            "ports": [{"name": "http", "port": ROUTER_SERVICE_PORT, "targetPort": "http", "protocol": "TCP"}],
        },
    }


def _service_monitor(config: Mapping[str, Any]) -> dict[str, Any]:
    labels = _labels(config["router_name"])
    names = resource_names(config)
    selector = {"app.kubernetes.io/name": ROUTER_NAME, "app.kubernetes.io/instance": config["router_name"]}
    return {
        "apiVersion": "monitoring.coreos.com/v1",
        "kind": "ServiceMonitor",
        "metadata": {"name": config["router_name"], "namespace": config["namespace"], "labels": labels},
        "spec": {
            "selector": {"matchLabels": selector},
            "endpoints": [{
                "port": "http",
                "path": "/metrics",
                "interval": "15s",
                # LiteLLM protects /metrics by default. The generated router
                # master key stays in the Lab 5-owned Secret and is never
                # returned in a plan, endpoint status, or application log.
                "authorization": {"type": "Bearer", "credentials": {"name": names["secret"], "key": ROUTER_MASTER_KEY}},
                "metricRelabelings": [{
                    "action": "labeldrop",
                    # LiteLLM exposes rich labels. Drop direct identifiers and
                    # endpoint URLs before Prometheus stores them.
                    "regex": "(?i)^(client_ip|user_agent|hashed_api_key|api_key_alias|end_user|user|user_email|api_base|upstream.*|url|request_id|metadata.*)$",
                }],
            }],
        },
    }


def _grafana_dashboard_json(router_name: str) -> str:
    """Render a dashboard with a stable, per-router Grafana UID.

    The ConfigMap names are already isolated by ``router_name``.  Grafana uses
    the dashboard UID as its own identity, though, so a fixed UID would make a
    second Lab 5 experiment overwrite the first dashboard after discovery.
    Keep the UID short and deterministic without exposing any cluster detail.
    """

    dashboard_uid = "llmd-routing-" + hashlib.sha256(router_name.encode("utf-8")).hexdigest()[:12]
    datasource = {"type": "prometheus", "uid": "${datasource}"}
    namespace_selector = '{namespace=~"$namespace"}'
    panels = [
        {
            "id": 1, "title": "Route request rate", "type": "timeseries", "datasource": datasource, "gridPos": {"x": 0, "y": 0, "w": 12, "h": 8},
            "targets": [{"refId": "A", "expr": f"sum by (requested_model) (rate(litellm_proxy_total_requests_metric{namespace_selector}[$__rate_interval]))", "legendFormat": "{{requested_model}}"}],
        },
        {
            "id": 2, "title": "Route p95 latency", "type": "timeseries", "datasource": datasource, "gridPos": {"x": 12, "y": 0, "w": 12, "h": 8},
            "targets": [{"refId": "A", "expr": f"histogram_quantile(0.95, sum by (requested_model, le) (rate(litellm_request_total_latency_metric_bucket{namespace_selector}[$__rate_interval])))", "legendFormat": "{{requested_model}}"}],
        },
        {
            "id": 3, "title": "Route error rate", "type": "timeseries", "datasource": datasource, "gridPos": {"x": 0, "y": 8, "w": 8, "h": 8},
            "targets": [{"refId": "A", "expr": f"sum by (requested_model) (rate(litellm_proxy_failed_requests_metric{namespace_selector}[$__rate_interval]))", "legendFormat": "{{requested_model}}"}],
        },
        {
            "id": 4, "title": "Router in-flight requests", "type": "timeseries", "datasource": datasource, "gridPos": {"x": 8, "y": 8, "w": 8, "h": 8},
            "targets": [{"refId": "A", "expr": f"sum(litellm_in_flight_requests{namespace_selector})", "legendFormat": "in-flight"}],
        },
        {
            "id": 5, "title": "Route share", "type": "piechart", "datasource": datasource, "gridPos": {"x": 16, "y": 8, "w": 8, "h": 8},
            "targets": [{"refId": "A", "expr": f"sum by (requested_model) (increase(litellm_proxy_total_requests_metric{namespace_selector}[$__range]))", "legendFormat": "{{requested_model}}"}],
        },
    ]
    dashboard = {
        "annotations": {"list": []},
        "editable": True,
        "graphTooltip": 0,
        "panels": panels,
        "schemaVersion": 39,
        "tags": ["llm-d", "lab-5", "routing"],
        "templating": {"list": [
            {"name": "datasource", "type": "datasource", "query": "prometheus", "current": {"text": "Prometheus", "value": "Prometheus"}},
            {"name": "namespace", "label": "Namespace", "type": "query", "datasource": datasource, "query": "label_values(litellm_proxy_total_requests_metric, namespace)", "includeAll": True, "allValue": ".+", "current": {"text": "All", "value": "$__all"}},
        ]},
        "time": {"from": "now-1h", "to": "now"},
        "title": "Lab 5 · LLM-D hybrid routing",
        "uid": dashboard_uid,
        "version": 1,
    }
    return json.dumps(dashboard, indent=2) + "\n"


def _grafana_config_map(config: Mapping[str, Any]) -> dict[str, Any]:
    labels = _labels(config["router_name"])
    labels["grafana_dashboard"] = "1"
    names = resource_names(config)
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": names["dashboard"], "namespace": config["monitoring_namespace"], "labels": labels},
        "data": {"llm-d-routing-overview.json": _grafana_dashboard_json(config["router_name"])},
    }


def render_manifests(config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return only lab-owned resources, never an OpenRouter credential Secret."""

    safe = validate_config(config)
    return {
        "configmap": _config_map(safe),
        "deployment": _deployment(safe),
        "service": _service(safe),
        "service_monitor": _service_monitor(safe),
        "grafana_dashboard": _grafana_config_map(safe),
    }


def preflight_manifest(config: Mapping[str, Any]) -> dict[str, Any]:
    """Describe read-only checks an API handler should make before deployment."""

    safe = validate_config(config)
    names = resource_names(safe)
    return {
        "context": safe["context"],
        "namespace": safe["namespace"],
        "router_name": safe["router_name"],
        "service_name": names["router"],
        "resource_names": names,
        "epp_service_name": f"{safe['release_name']}-epp",
        "epp_url": _epp_base_url(safe),
        "monitoring_namespace": safe["monitoring_namespace"],
        "prometheus_service_name": safe["prometheus_service"],
        "checks": [
            {"kind": "Service", "namespace": safe["namespace"], "name": f"{safe['release_name']}-epp", "purpose": "LLM-D local route"},
            {"kind": "CustomResourceDefinition", "name": "servicemonitors.monitoring.coreos.com", "purpose": "LiteLLM metrics discovery"},
            {"kind": "Service", "namespace": safe["monitoring_namespace"], "name": safe["prometheus_service"], "purpose": "Grafana and ServiceMonitor platform"},
        ],
        "warnings": [
            "OpenRouter routes require cluster egress, DNS, and a valid OpenRouter API key; preflight must report failures without exposing the key.",
            "Only private and fast aliases call LLM-D and can influence Lab 4 EPP/KEDA metrics. Coding and reasoning bypass LLM-D.",
        ],
    }


def routing_plan(config: Mapping[str, Any]) -> dict[str, Any]:
    """Render a safe Lab 5 plan suitable for UI/API review."""

    safe = validate_config(config)
    names = resource_names(safe)
    manifests = render_manifests(safe)
    # A List makes the namespace-local resources easy to apply in one atomic
    # review unit. The dashboard lives in the monitoring namespace, so it is a
    # separate document/command. Neither document contains Secret data.
    namespaced_items = [
        manifests["configmap"], manifests["deployment"], manifests["service"], manifests["service_monitor"],
    ]
    namespace_manifest = {"apiVersion": "v1", "kind": "List", "items": namespaced_items}
    rendered = json.dumps(namespace_manifest, indent=2) + "\n"
    dashboard_rendered = json.dumps(manifests["grafana_dashboard"], indent=2) + "\n"
    context, namespace, router_name = safe["context"], safe["namespace"], safe["router_name"]
    return {
        "source_experiment_id": safe.get("source_experiment_id"),
        "context": context,
        "namespace": namespace,
        "router_name": router_name,
        "service_name": names["router"],
        "resource_names": names,
        "aliases": alias_details(safe),
        "manifest": rendered,
        "dashboard_manifest": dashboard_rendered,
        # Convenience preview field for API response models. Apply commands
        # remain separate because the dashboard belongs in the monitoring
        # namespace rather than the model-serving namespace.
        "manifests": rendered + "---\n" + dashboard_rendered,
        "commands": [
            llmd.kubectl(context, "-n", namespace, "apply", "-f", "-"),
            llmd.kubectl(context, "-n", safe["monitoring_namespace"], "apply", "-f", "-"),
            # A redeploy rotates the generated internal LiteLLM key. It is
            # injected as an environment variable, so make the restart an
            # explicit reviewed action rather than leaving a pod on the old
            # Secret value while Prometheus/the local proxy use the new one.
            llmd.kubectl(context, "-n", namespace, "rollout", "restart", "deployment", router_name),
            llmd.kubectl(context, "-n", namespace, "rollout", "status", "deployment", router_name, "--timeout=180s"),
            llmd.kubectl(context, "-n", namespace, "get", "service", router_name),
        ],
        # Metadata only. The actual secret is an apply-time input, deliberately
        # omitted from rendered manifests and command previews.
        "secret": {
            "name": names["secret"],
            "namespace": namespace,
            "keys": [ROUTER_SECRET_KEY, ROUTER_MASTER_KEY],
            "provided": "openrouter_api_key" in safe,
        },
        "preflight": preflight_manifest(safe),
        "warnings": [
            "The OpenRouter API key is stored only in a Lab 5-owned Kubernetes Secret and is redacted from this plan.",
            "No public ingress is created; access the ClusterIP service through the Lab 5 local tunnel.",
        ],
    }
