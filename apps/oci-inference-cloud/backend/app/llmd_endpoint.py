"""Local port-forward and inference helpers for an LLM-D experiment."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from . import state
from .ssh import free_local_port


@dataclass
class EndpointRuntime:
    local_port: int
    process: subprocess.Popen[str]


RUNTIMES: dict[int, EndpointRuntime] = {}


def endpoint_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def deployment_config(experiment_id: int) -> dict[str, Any]:
    config = state.get_setting(f"llmd:{experiment_id}")
    if not config:
        raise RuntimeError("Deploy LLM-D before starting its local endpoint.")
    return config


def runtime_for(experiment_id: int) -> EndpointRuntime | None:
    runtime = RUNTIMES.get(experiment_id)
    if runtime and runtime.process.poll() is not None:
        RUNTIMES.pop(experiment_id, None)
        return None
    return runtime


def upstream_healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"{endpoint_url(port)}/v1/models", timeout=4) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def status(experiment_id: int) -> dict[str, Any]:
    runtime = runtime_for(experiment_id)
    if not runtime:
        return {"experiment_id": experiment_id, "status": "stopped", "endpoint_url": "", "healthy": False}
    healthy = upstream_healthy(runtime.local_port)
    return {
        "experiment_id": experiment_id,
        "status": "running" if healthy else "starting",
        "endpoint_url": endpoint_url(runtime.local_port),
        "healthy": healthy,
    }


def start(experiment_id: int) -> dict[str, Any]:
    existing = runtime_for(experiment_id)
    if existing:
        existing_status = status(experiment_id)
        if existing_status["healthy"]:
            return existing_status
        # A port-forward process can remain alive while its local listener or
        # upstream service is unavailable. Do not hand that stale tunnel to a
        # benchmark: replace it and verify the new one below.
        stop(experiment_id)
    config = deployment_config(experiment_id)
    local_port = free_local_port()
    command = [
        "kubectl", "--context", config["context"], "-n", config["namespace"],
        "port-forward", f"service/{config['release_name']}-epp", f"{local_port}:80",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    RUNTIMES[experiment_id] = EndpointRuntime(local_port=local_port, process=process)
    # CPU model servers may need several seconds to accept the first routed
    # request even after Kubernetes reports their pods as Running.
    for _ in range(80):
        time.sleep(0.25)
        if process.poll() is not None:
            break
        if upstream_healthy(local_port):
            return status(experiment_id)
    if process.poll() is not None:
        stderr = process.stderr.read().strip() if process.stderr else ""
        RUNTIMES.pop(experiment_id, None)
        raise RuntimeError(stderr or "kubectl port-forward exited before the LLM-D endpoint became available.")
    # A running process alone is not enough. Benchmarking a tunnel before it
    # accepts requests produces misleading zero-duration / zero-response data.
    stop(experiment_id)
    raise RuntimeError("LLM-D endpoint did not become healthy within 20 seconds. Verify the router and CPU vLLM pods are Ready, then start the endpoint again.")


def stop(experiment_id: int) -> dict[str, Any]:
    runtime = RUNTIMES.pop(experiment_id, None)
    if runtime:
        runtime.process.terminate()
        try:
            runtime.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            runtime.process.kill()
    return status(experiment_id)


def chat(experiment_id: int, prompt: str, max_tokens: int, temperature: float) -> dict[str, Any]:
    runtime = runtime_for(experiment_id)
    if not runtime:
        start(experiment_id)
        runtime = runtime_for(experiment_id)
    if not runtime:
        raise RuntimeError("Unable to start the LLM-D endpoint.")
    config = deployment_config(experiment_id)
    payload = json.dumps({
        "model": config["model"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{endpoint_url(runtime.local_port)}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM-D endpoint returned HTTP {exc.code}: {detail}") from exc
