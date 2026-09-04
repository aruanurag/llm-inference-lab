"""Local-only endpoint sessions for a Lab 5 LiteLLM router.

The router remains a ClusterIP Service inside the selected OKE namespace.  A
short-lived local ``kubectl port-forward`` is the only way this workbench
exposes it to the participant; neither credentials nor provider URLs are
persisted in the session state.
"""

from __future__ import annotations

import base64
import binascii
import json
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from . import llmd, routing, state
from .ssh import free_local_port


ALIASES = ("private", "fast", "coding", "reasoning")


@dataclass
class EndpointRuntime:
    tunnel_port: int
    local_port: int
    process: subprocess.Popen[str]
    proxy: ThreadingHTTPServer
    proxy_thread: threading.Thread


RUNTIMES: dict[int, EndpointRuntime] = {}


def endpoint_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def _master_key(config: dict[str, Any]) -> str:
    """Read the generated internal LiteLLM key only into process memory.

    The value is never written to SQLite, an API response, a log, or the
    browser.  A localhost companion proxy below injects it for standard
    OpenAI-compatible clients while the actual router remains private.
    """

    secret_name = str(config.get("secret_name") or routing.ROUTER_SECRET)
    command = llmd.kubectl(
        str(config["context"]), "-n", str(config["namespace"]), "get", "secret", secret_name,
        "-o", f"jsonpath={{.data.{routing.ROUTER_MASTER_KEY}}}",
    )
    result = llmd.command_output(command, timeout=30)
    if result.returncode or not result.stdout.strip():
        raise RuntimeError("The Lab 5 router credential Secret is unavailable. Redeploy the Lab 5 router before starting its endpoint.")
    try:
        return base64.b64decode(result.stdout.strip()).decode("utf-8")
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise RuntimeError("The Lab 5 router credential Secret has an invalid internal key.") from exc


def _proxy_handler(upstream_port: int, master_key: str) -> type[BaseHTTPRequestHandler]:
    """Create a loopback-only transparent proxy that injects router auth."""

    class LocalRouterProxy(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *_args: Any) -> None:
            # Default HTTP server logging includes request paths; keep local
            # test prompts and provider metadata out of application logs.
            return

        def _forward(self) -> None:
            # The injected credential is a LiteLLM master key.  Expose only
            # the intended OpenAI-compatible inference and health surfaces on
            # the participant's loopback endpoint, never LiteLLM admin paths.
            if not (self.path.startswith("/v1/") or self.path.startswith("/health")):
                self.send_error(404, "Only /v1 and /health routes are available through the local endpoint.")
                return
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(length) if length else None
            headers = {
                key: value for key, value in self.headers.items()
                if key.lower() not in {"host", "connection", "authorization", "content-length"}
            }
            headers["Authorization"] = f"Bearer {master_key}"
            if body is not None:
                headers["Content-Length"] = str(len(body))
            request = urllib.request.Request(
                f"{endpoint_url(upstream_port)}{self.path}", data=body, headers=headers, method=self.command,
            )
            try:
                response = urllib.request.urlopen(request, timeout=610)
            except urllib.error.HTTPError as error:
                response = error
            except urllib.error.URLError:
                self.send_error(502, "The local router tunnel is unavailable.")
                return
            try:
                self.send_response(response.status)
                for key, value in response.headers.items():
                    if key.lower() not in {"connection", "transfer-encoding", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "upgrade"}:
                        self.send_header(key, value)
                self.end_headers()
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            finally:
                response.close()

        do_GET = _forward
        do_POST = _forward
        do_PUT = _forward
        do_PATCH = _forward
        do_DELETE = _forward
        do_OPTIONS = _forward

    return LocalRouterProxy


def deployment_config(experiment_id: int) -> dict[str, Any]:
    config = state.get_setting(f"llmd-routing:{experiment_id}")
    if not config or not config.get("owned"):
        raise RuntimeError("Deploy the Lab 5 LiteLLM router before starting its local endpoint.")
    return config


def runtime_for(experiment_id: int) -> EndpointRuntime | None:
    runtime = RUNTIMES.get(experiment_id)
    if runtime and runtime.process.poll() is not None:
        RUNTIMES.pop(experiment_id, None)
        return None
    return runtime


def _healthy(port: int) -> bool:
    # LiteLLM has used both health paths across releases.  Check the OpenAI
    # models endpoint as the final, user-visible contract.
    for path in ("/health/liveliness", "/health", "/v1/models"):
        try:
            with urllib.request.urlopen(f"{endpoint_url(port)}{path}", timeout=4) as response:
                if 200 <= response.status < 300:
                    return True
        except (urllib.error.URLError, urllib.error.HTTPError):
            continue
    return False


def status(experiment_id: int) -> dict[str, Any]:
    runtime = runtime_for(experiment_id)
    if not runtime:
        return {
            "experiment_id": experiment_id,
            "status": "stopped",
            "endpoint_url": "",
            "healthy": False,
            "available_models": [],
        }
    healthy = _healthy(runtime.local_port)
    return {
        "experiment_id": experiment_id,
        "status": "running" if healthy else "starting",
        "endpoint_url": endpoint_url(runtime.local_port),
        "healthy": healthy,
        "available_models": list(ALIASES) if healthy else [],
    }


def start(experiment_id: int) -> dict[str, Any]:
    existing = runtime_for(experiment_id)
    if existing and _healthy(existing.local_port):
        return status(experiment_id)
    if existing:
        stop(experiment_id)

    config = deployment_config(experiment_id)
    master_key = _master_key(config)
    tunnel_port = free_local_port()
    local_port = free_local_port()
    service_name = str(config.get("service_name") or config.get("router_name") or "llm-d-routing")
    command = [
        "kubectl", "--context", config["context"], "-n", config["namespace"],
        "port-forward", f"service/{service_name}", f"{tunnel_port}:80",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    proxy = ThreadingHTTPServer(("127.0.0.1", local_port), _proxy_handler(tunnel_port, master_key))
    proxy_thread = threading.Thread(target=proxy.serve_forever, name=f"llmd-routing-{experiment_id}", daemon=True)
    proxy_thread.start()
    RUNTIMES[experiment_id] = EndpointRuntime(
        tunnel_port=tunnel_port, local_port=local_port, process=process, proxy=proxy, proxy_thread=proxy_thread,
    )
    for _ in range(80):
        time.sleep(0.25)
        if process.poll() is not None:
            break
        if _healthy(local_port):
            return status(experiment_id)
    stderr = process.stderr.read().strip() if process.poll() is not None and process.stderr else ""
    stop(experiment_id)
    raise RuntimeError(
        stderr or "LiteLLM router did not become reachable through the local tunnel. "
        "Verify the Lab 5 router Deployment and Service are Ready, then start the tunnel again."
    )


def stop(experiment_id: int) -> dict[str, Any]:
    runtime = RUNTIMES.pop(experiment_id, None)
    if runtime:
        runtime.proxy.shutdown()
        runtime.proxy.server_close()
        runtime.proxy_thread.join(timeout=2)
        runtime.process.terminate()
        try:
            runtime.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            runtime.process.kill()
    return status(experiment_id)


def route_descriptor(alias: str, max_tokens: int) -> dict[str, Any]:
    return routing.validate_inference_request(alias, max_tokens)


def chat(
    experiment_id: int,
    *,
    alias: str,
    prompt: str | None,
    messages: list[dict[str, str]] | None,
    max_tokens: int,
    temperature: float,
    stream: bool = False,
) -> dict[str, Any]:
    """Submit a non-streaming UI request through the selected explicit alias.

    Streaming remains available for standard clients hitting the returned local
    OpenAI-compatible endpoint directly.  The workbench UI uses non-streaming
    responses so it never proxies provider output or credentials through its
    own API.
    """

    if stream:
        raise RuntimeError("Streaming is available at the local router endpoint. Use its /v1/chat/completions API directly with stream=true.")
    route = route_descriptor(alias, max_tokens)
    if not messages:
        if not prompt or not prompt.strip():
            raise ValueError("Provide a text prompt or at least one chat message.")
        messages = [{"role": "user", "content": prompt.strip()}]

    runtime = runtime_for(experiment_id)
    if not runtime:
        start(experiment_id)
        runtime = runtime_for(experiment_id)
    if not runtime:
        raise RuntimeError("Unable to start the local LiteLLM router tunnel.")

    payload = json.dumps({
        "model": alias,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{endpoint_url(runtime.local_port)}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            body = json.loads(response.read().decode("utf-8"))
            usage = body.get("usage") if isinstance(body, dict) else None
            return {"model": alias, "destination": route["destination"], "response": body, "usage": usage}
    except urllib.error.HTTPError as exc:
        # Provider error bodies can include implementation details.  Return the
        # status only, never a raw error that might contain a URL or key.
        raise RuntimeError(
            f"The {route['destination']} route returned HTTP {exc.code}. "
            "The selected route has no automatic fallback; check its availability and try again."
        ) from exc
