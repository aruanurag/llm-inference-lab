"""Managed local Grafana tunnels for Lab 4.

Grafana remains a ClusterIP service; this exposes it only on the workstation
running OCI Inference Cloud, just like the existing LLM-D endpoint tunnel.
"""

from __future__ import annotations

import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from . import state
from .autoscaling import MONITORING_NAMESPACE, PROMETHEUS_RELEASE
from .ssh import free_local_port


@dataclass
class GrafanaRuntime:
    local_port: int
    process: subprocess.Popen[str]


RUNTIMES: dict[int, GrafanaRuntime] = {}


def _url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def _runtime(experiment_id: int) -> GrafanaRuntime | None:
    runtime = RUNTIMES.get(experiment_id)
    if runtime and runtime.process.poll() is not None:
        RUNTIMES.pop(experiment_id, None)
        return None
    return runtime


def _healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"{_url(port)}/api/health", timeout=3) as response:
            return 200 <= response.status < 400
    except (urllib.error.URLError, urllib.error.HTTPError):
        return False


def _dashboard_links(port: int) -> dict[str, str]:
    base = _url(port)
    return {
        "Home": f"{base}/dashboards",
        "LLM-D vLLM overview": f"{base}/dashboards",
        "Failure and saturation": f"{base}/dashboards",
        "Performance and KV cache": f"{base}/dashboards",
    }


def status(experiment_id: int) -> dict[str, Any]:
    runtime = _runtime(experiment_id)
    if not runtime:
        return {"experiment_id": experiment_id, "status": "stopped", "endpoint_url": "", "healthy": False, "dashboards": {}}
    healthy = _healthy(runtime.local_port)
    return {
        "experiment_id": experiment_id,
        "status": "running" if healthy else "starting",
        "endpoint_url": _url(runtime.local_port),
        "healthy": healthy,
        "dashboards": _dashboard_links(runtime.local_port) if healthy else {},
    }


def start(experiment_id: int) -> dict[str, Any]:
    existing = _runtime(experiment_id)
    if existing and _healthy(existing.local_port):
        return status(experiment_id)
    if existing:
        stop(experiment_id)
    config = state.get_setting(f"lab4:{experiment_id}")
    if not config:
        raise RuntimeError("Bootstrap or validate the Lab 4 platform before opening Grafana.")
    port = free_local_port()
    command = [
        "kubectl", "--context", config["context"], "-n", config.get("monitoring_namespace", MONITORING_NAMESPACE),
        "port-forward", f"service/{config.get('grafana_service', f'{PROMETHEUS_RELEASE}-grafana')}", f"{port}:80",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    RUNTIMES[experiment_id] = GrafanaRuntime(local_port=port, process=process)
    for _ in range(80):
        time.sleep(0.25)
        if process.poll() is not None:
            break
        if _healthy(port):
            return status(experiment_id)
    stderr = process.stderr.read().strip() if process.poll() is not None and process.stderr else ""
    stop(experiment_id)
    raise RuntimeError(stderr or "Grafana did not become reachable through the local tunnel. Verify the platform bootstrap first.")


def stop(experiment_id: int) -> dict[str, Any]:
    runtime = RUNTIMES.pop(experiment_id, None)
    if runtime:
        runtime.process.terminate()
        try:
            runtime.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            runtime.process.kill()
    return status(experiment_id)
