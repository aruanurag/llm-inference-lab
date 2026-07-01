from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterator

from fastapi import Request
from fastapi.responses import Response, StreamingResponse

from . import state
from .ssh import free_local_port, start_tunnel


@dataclass
class EndpointRuntime:
    local_port: int
    process: Any


RUNTIMES: dict[int, EndpointRuntime] = {}


def proxy_base_url(experiment_id: int) -> str:
    return f"http://127.0.0.1:8090/api/experiments/{experiment_id}/endpoint/v1"


def upstream_base_url(local_port: int) -> str:
    return f"http://127.0.0.1:{local_port}"


def extract_prompt_chars(payload: dict[str, Any]) -> int:
    messages = payload.get("messages") or []
    total = 0
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            total += sum(len(part.get("text", "")) for part in content if isinstance(part, dict))
    return total


def extract_response_text(payload: dict[str, Any]) -> str:
    parts = []
    for choice in payload.get("choices", []):
        message = choice.get("message", {}) if isinstance(choice, dict) else {}
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
    return "".join(parts)


def extract_stream_text(data: str) -> str:
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return ""
    parts = []
    for choice in payload.get("choices", []):
        delta = choice.get("delta", {}) if isinstance(choice, dict) else {}
        content = delta.get("content")
        if isinstance(content, str):
            parts.append(content)
    return "".join(parts)


def select_instance(experiment_id: int) -> dict[str, Any]:
    instances = state.list_instances_for_experiment(experiment_id)
    running = [item for item in instances if item.get("lifecycle_state") == "RUNNING"]
    candidates = running or instances
    if not candidates:
        raise RuntimeError("No instance is associated with this experiment.")
    instance = candidates[0]
    if not (instance.get("public_ip") or instance.get("private_ip")):
        raise RuntimeError("Experiment instance has no IP recorded.")
    return instance


def check_upstream(local_port: int) -> bool:
    try:
        with urllib.request.urlopen(f"{upstream_base_url(local_port)}/health", timeout=3) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def runtime_for(experiment_id: int) -> EndpointRuntime | None:
    runtime = RUNTIMES.get(experiment_id)
    if not runtime:
        return None
    if runtime.process.poll() is not None:
        RUNTIMES.pop(experiment_id, None)
        state.upsert_endpoint_session(
            experiment_id,
            status="stopped",
            proxy_url=proxy_base_url(experiment_id),
            error="SSH tunnel process exited.",
        )
        return None
    return runtime


def endpoint_status(experiment_id: int) -> dict[str, Any]:
    session = state.get_endpoint_session(experiment_id) or state.upsert_endpoint_session(
        experiment_id,
        status="stopped",
        proxy_url=proxy_base_url(experiment_id),
    )
    runtime = runtime_for(experiment_id)
    if not runtime:
        if session.get("status") == "running":
            session = state.upsert_endpoint_session(
                experiment_id,
                status="stopped",
                proxy_url=proxy_base_url(experiment_id),
                error="Endpoint tunnel is not active in this backend process.",
            )
        return {**session, "healthy": False, "analytics": state.endpoint_analytics(experiment_id)}
    healthy = check_upstream(runtime.local_port)
    session = state.upsert_endpoint_session(
        experiment_id,
        status="running" if healthy else "failed",
        local_port=runtime.local_port,
        proxy_url=proxy_base_url(experiment_id),
        error=None if healthy else "Tunnel is running but llama-server health check failed.",
    )
    return {**session, "healthy": healthy, "analytics": state.endpoint_analytics(experiment_id)}


def start_endpoint(experiment_id: int) -> dict[str, Any]:
    existing = runtime_for(experiment_id)
    if existing and check_upstream(existing.local_port):
        return endpoint_status(experiment_id)

    stop_endpoint(experiment_id)
    instance = select_instance(experiment_id)
    key = state.get_ssh_key(instance["ssh_key_id"])
    host = instance["public_ip"] or instance["private_ip"]
    local_port = free_local_port()
    process = start_tunnel(key["private_key_path"], instance["ssh_user"], host, local_port)
    RUNTIMES[experiment_id] = EndpointRuntime(local_port=local_port, process=process)
    state.upsert_endpoint_session(
        experiment_id,
        status="starting",
        local_port=local_port,
        proxy_url=proxy_base_url(experiment_id),
    )
    for _ in range(20):
        time.sleep(0.5)
        if process.poll() is not None:
            break
        if check_upstream(local_port):
            state.upsert_endpoint_session(
                experiment_id,
                status="running",
                local_port=local_port,
                proxy_url=proxy_base_url(experiment_id),
            )
            return endpoint_status(experiment_id)

    stderr = ""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except Exception:
            process.kill()
    if process.stderr:
        try:
            stderr = process.stderr.read() or ""
        except Exception:
            stderr = ""
    RUNTIMES.pop(experiment_id, None)
    state.upsert_endpoint_session(
        experiment_id,
        status="failed",
        local_port=local_port,
        proxy_url=proxy_base_url(experiment_id),
        error=stderr.strip() or "Endpoint tunnel started but llama-server did not become healthy.",
    )
    return endpoint_status(experiment_id)


def stop_endpoint(experiment_id: int) -> dict[str, Any]:
    runtime = RUNTIMES.pop(experiment_id, None)
    if runtime:
        runtime.process.terminate()
        try:
            runtime.process.wait(timeout=5)
        except Exception:
            runtime.process.kill()
    state.upsert_endpoint_session(
        experiment_id,
        status="stopped",
        proxy_url=proxy_base_url(experiment_id),
    )
    return endpoint_status(experiment_id)


def upstream_request(local_port: int, path: str, payload: bytes) -> urllib.request.Request:
    return urllib.request.Request(
        f"{upstream_base_url(local_port)}{path}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )


async def proxy_chat_completion(experiment_id: int, request: Request) -> Response | StreamingResponse:
    runtime = runtime_for(experiment_id)
    if not runtime:
        status = start_endpoint(experiment_id)
        runtime = runtime_for(experiment_id)
        if not runtime:
            raise RuntimeError(status.get("error") or "Endpoint is not running.")

    body = await request.body()
    payload = json.loads(body.decode("utf-8") or "{}")
    prompt_chars = extract_prompt_chars(payload)
    started = time.perf_counter()
    is_stream = bool(payload.get("stream"))

    if is_stream:
        return StreamingResponse(
            stream_upstream(experiment_id, runtime.local_port, body, started, prompt_chars),
            media_type="text/event-stream",
        )

    try:
        with urllib.request.urlopen(upstream_request(runtime.local_port, "/v1/chat/completions", body), timeout=600) as response:
            content = response.read()
            latency = time.perf_counter() - started
            parsed = json.loads(content.decode("utf-8"))
            output_chars = len(extract_response_text(parsed))
            state.insert_endpoint_request_log(
                experiment_id,
                status="ok",
                latency_seconds=latency,
                prompt_chars=prompt_chars,
                output_chars=output_chars,
            )
            return Response(content=content, media_type=response.headers.get("Content-Type", "application/json"), status_code=response.status)
    except Exception as exc:
        latency = time.perf_counter() - started
        state.insert_endpoint_request_log(
            experiment_id,
            status="error",
            latency_seconds=latency,
            prompt_chars=prompt_chars,
            output_chars=0,
            error=str(exc),
        )
        raise


def stream_upstream(experiment_id: int, local_port: int, body: bytes, started: float, prompt_chars: int) -> Iterator[bytes]:
    output_chars = 0
    status = "ok"
    error = None
    try:
        with urllib.request.urlopen(upstream_request(local_port, "/v1/chat/completions", body), timeout=600) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if line.startswith("data:"):
                    data = line.removeprefix("data:").strip()
                    if data != "[DONE]":
                        output_chars += len(extract_stream_text(data))
                yield raw_line
    except Exception as exc:
        status = "error"
        error = str(exc)
        yield f"data: {json.dumps({'error': error})}\n\n".encode("utf-8")
    finally:
        latency = time.perf_counter() - started
        state.insert_endpoint_request_log(
            experiment_id,
            status=status,
            latency_seconds=latency,
            prompt_chars=prompt_chars,
            output_chars=output_chars,
            error=error,
        )
