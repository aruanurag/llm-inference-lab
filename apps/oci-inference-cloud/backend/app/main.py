from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from . import autoscaling, endpoint, grafana_endpoint, llmd, llmd_endpoint, oci_cli, routing, routing_endpoint, state
from .benchmark import run_benchmark, write_benchmark_result
from .config import BENCHMARKS_DIR, LOGS_DIR, PROMPTS_DIR, ensure_app_dirs
from .deploy import deploy_inference_engine, list_deploy_models, resolve_model
from .native_benchmark import BENCHMARK_TOOLS, run_native_benchmark
from .prompts import parse_prompt_file, read_prompt_set, seed_default_prompts
from .schemas import (
    BenchmarkRecord,
    BenchmarkRequest,
    ClusterAccessRequest,
    ClusterValidation,
    ContextRequest,
    ContextState,
    DeployResult,
    DeployModelOption,
    DeployRequest,
    ExperimentCreate,
    ExperimentRecord,
    InstanceCreate,
    InstanceRecord,
    KubernetesContext,
    LlmDDeployResult,
    LlmDCheckout,
    LlmDCheckoutRequest,
    LlmDBenchmarkRequest,
    LlmDBenchmarkResult,
    LlmDBenchmarkRecord,
    LlmDDeploymentRequest,
    LlmDEndpointStatus,
    LlmDAutoscalingObservation,
    LlmDAutoscalingPlan,
    LlmDAutoscalingRequest,
    LlmDAutoscalingResult,
    LlmDGrafanaStatus,
    LlmDInferenceRequest,
    LlmDPlatformBootstrapRequest,
    LlmDPlatformPlan,
    LlmDPlatformPreflightRequest,
    LlmDPlatformResult,
    LlmDPlatformStatus,
    LlmDPlan,
    LlmDRoutingBenchmarkRecord,
    LlmDRoutingBenchmarkRequest,
    LlmDRoutingBenchmarkResult,
    LlmDRoutingConfiguration,
    LlmDRoutingDeployRequest,
    LlmDRoutingDeployResult,
    LlmDRoutingEndpointStatus,
    LlmDRoutingInferenceRequest,
    LlmDRoutingInferenceResult,
    LlmDRoutingPlan,
    LlmDRoutingPreflightRequest,
    LlmDRoutingStatus,
    LlmDRoutingUninstallResult,
    Option,
    Profile,
    PromptSet,
    SshKeyCreate,
    SshKeyRecord,
)
from .ssh import free_local_port, generate_ed25519_key, start_tunnel


app = FastAPI(title="OCI Inference Cloud")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:3001",
        "http://localhost:3001",
        "http://127.0.0.1:3002",
        "http://localhost:3002",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    ensure_app_dirs()
    state.init_db()
    seed_default_prompts()


def api_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/profiles", response_model=list[Profile])
def profiles() -> list[Profile]:
    return oci_cli.parse_profiles()


@app.get("/api/experiments", response_model=list[ExperimentRecord])
def experiments() -> list[ExperimentRecord]:
    return [ExperimentRecord(**item) for item in state.list_experiments()]


@app.post("/api/experiments", response_model=ExperimentRecord)
def create_experiment(request: ExperimentCreate) -> ExperimentRecord:
    if not request.name.strip():
        raise HTTPException(status_code=400, detail="Experiment name is required.")
    if request.kind == "llm-d-routing":
        if not request.source_experiment_id:
            raise HTTPException(status_code=400, detail="A Lab 5 routing experiment must link to a Lab 4 source experiment.")
        source = state.get_experiment(request.source_experiment_id)
        if source.get("kind") != "llm-d-autoscaling":
            raise HTTPException(status_code=400, detail="Lab 5 can only link to a Lab 4 LLM-D autoscaling experiment.")
    return ExperimentRecord(**state.insert_experiment(
        request.name.strip(), request.description.strip(), request.kind, request.source_experiment_id,
    ))


@app.get("/api/kubernetes/contexts", response_model=list[KubernetesContext])
def kubernetes_contexts() -> list[KubernetesContext]:
    try:
        return [KubernetesContext(name=name) for name in llmd.list_contexts()]
    except Exception as exc:
        raise api_error(exc) from exc


@app.post("/api/kubernetes/validate", response_model=ClusterValidation)
def validate_kubernetes_cluster(request: ClusterAccessRequest) -> ClusterValidation:
    try:
        return ClusterValidation(**llmd.validate_cluster(request.context, request.namespace))
    except Exception as exc:
        raise api_error(exc) from exc


@app.post("/api/llm-d/checkout", response_model=LlmDCheckout)
def prepare_llmd_checkout(request: LlmDCheckoutRequest) -> LlmDCheckout:
    try:
        return LlmDCheckout(**llmd.prepare_checkout(request.path))
    except Exception as exc:
        raise api_error(exc) from exc


@app.post("/api/experiments/{experiment_id}/llm-d/plan", response_model=LlmDPlan)
def plan_llmd_deployment(experiment_id: int, request: LlmDDeploymentRequest) -> LlmDPlan:
    try:
        state.get_experiment(experiment_id)
        safe_config = request.model_dump(exclude={"hf_token"})
        state.set_setting(f"llmd:{experiment_id}", safe_config)
        return LlmDPlan(**llmd.make_plan(request.model_dump(), experiment_id))
    except Exception as exc:
        raise api_error(exc) from exc


@app.post("/api/experiments/{experiment_id}/llm-d/deploy", response_model=LlmDDeployResult)
def deploy_llmd(experiment_id: int, request: LlmDDeploymentRequest) -> LlmDDeployResult:
    try:
        state.get_experiment(experiment_id)
        safe_config = request.model_dump(exclude={"hf_token"})
        # Record the selected target before applying. If Kubernetes reports a
        # recoverable rollout issue, endpoint and diagnostics must still refer
        # to the cluster the participant just chose—not an earlier experiment.
        state.set_setting(f"llmd:{experiment_id}", safe_config)
        plan, log_path, message = llmd.deploy(request.model_dump(), experiment_id)
        state.update_experiment(experiment_id, status="llm-d-deployed")
        return LlmDDeployResult(status="ok", log_path=str(log_path), message=message, plan=LlmDPlan(**plan))
    except Exception as exc:
        raise api_error(exc) from exc


@app.post("/api/experiments/{experiment_id}/llm-d/autoscaling/preflight")
def llmd_autoscaling_preflight(experiment_id: int, request: LlmDPlatformPreflightRequest) -> dict[str, Any]:
    try:
        state.get_experiment(experiment_id)
        return autoscaling.preflight(
            request.context, request.namespace, request.release_name,
            request.monitoring_namespace, request.prometheus_service, request.grafana_service, request.keda_namespace,
        )
    except Exception as exc:
        raise api_error(exc) from exc


@app.post("/api/experiments/{experiment_id}/llm-d/autoscaling/platform/plan", response_model=LlmDPlatformPlan)
def plan_llmd_platform(experiment_id: int, request: LlmDPlatformBootstrapRequest) -> LlmDPlatformPlan:
    try:
        state.get_experiment(experiment_id)
        return LlmDPlatformPlan(**autoscaling.platform_plan(request.context, request.llmd_repo_path, request.mode))
    except Exception as exc:
        raise api_error(exc) from exc


@app.post("/api/experiments/{experiment_id}/llm-d/autoscaling/platform/bootstrap", response_model=LlmDPlatformResult)
def bootstrap_llmd_platform(experiment_id: int, request: LlmDPlatformBootstrapRequest) -> LlmDPlatformResult:
    try:
        state.get_experiment(experiment_id)
        if not request.confirm_cluster_changes:
            raise ValueError("Confirm the cluster-scoped changes after reviewing the platform plan before bootstrapping.")
        existing_platform = state.get_setting(f"lab4:{experiment_id}")
        if request.mode == "dedicated" and not request.grafana_admin_password and not existing_platform.get("owned"):
            raise ValueError("A Grafana admin password is required for a dedicated Lab 4 platform stack.")
        preflight = autoscaling.preflight(
            request.context, request.namespace, request.release_name,
            request.monitoring_namespace, request.prometheus_service, request.grafana_service, request.keda_namespace,
        )
        if request.mode == "dedicated" and preflight["conflicting_releases"] and not existing_platform.get("owned"):
            raise ValueError(
                "A Prometheus/Grafana or KEDA Helm release is already present in this cluster. "
                "Choose 'Use existing platform services' rather than taking ownership of it."
            )
        if request.mode == "existing" and not (preflight["service_monitor_crd"] and preflight["scaled_object_crd"] and preflight["prometheus_service"] and preflight["keda_ready"]):
            raise ValueError(
                "The existing platform is incomplete for Lab 4. It must provide the ServiceMonitor CRD, KEDA ScaledObject CRD, a reachable Prometheus service, and a ready KEDA operator."
            )
        plan, log_path = autoscaling.bootstrap(request.context, request.llmd_repo_path, request.mode, request.grafana_admin_password or "")
        # Never persist the password. The mode and context are enough to
        # restart the local Grafana tunnel and to guard uninstall actions.
        state.set_setting(f"lab4:{experiment_id}", {
            "context": request.context, "mode": request.mode, "llmd_repo_path": request.llmd_repo_path, "owned": request.mode == "dedicated",
            "monitoring_namespace": request.monitoring_namespace, "prometheus_service": request.prometheus_service,
            "grafana_service": request.grafana_service, "keda_namespace": request.keda_namespace,
        })
        state.update_experiment(experiment_id, status="lab4-platform-ready")
        return LlmDPlatformResult(status="ok", log_path=str(log_path), message="Lab 4 platform is ready. Deploy the monitored LLM-D router, then apply the KEDA policy.", plan=LlmDPlatformPlan(**plan))
    except Exception as exc:
        raise api_error(exc) from exc


@app.get("/api/experiments/{experiment_id}/llm-d/autoscaling/platform", response_model=LlmDPlatformStatus)
def llmd_platform_status(experiment_id: int) -> LlmDPlatformStatus:
    try:
        state.get_experiment(experiment_id)
        config = state.get_setting(f"lab4:{experiment_id}")
        if not config:
            return LlmDPlatformStatus(configured=False)
        deployment = state.get_setting(f"llmd:{experiment_id}")
        preflight = autoscaling.preflight(
            config["context"], deployment.get("namespace", "llm-d-lab"), deployment.get("release_name", "llm-d-lab"),
            config.get("monitoring_namespace", autoscaling.MONITORING_NAMESPACE),
            config.get("prometheus_service", f"{autoscaling.PROMETHEUS_RELEASE}-kube-prometheus-stack-prometheus"),
            config.get("grafana_service", f"{autoscaling.PROMETHEUS_RELEASE}-grafana"),
            config.get("keda_namespace", autoscaling.KEDA_NAMESPACE),
        )
        return LlmDPlatformStatus(
            configured=True, mode=config.get("mode"), owned=bool(config.get("owned")), context=config.get("context"),
            monitoring_namespace=config.get("monitoring_namespace"), prometheus_service_name=config.get("prometheus_service"),
            grafana_service_name=config.get("grafana_service"), keda_namespace=config.get("keda_namespace"), preflight=preflight,
        )
    except Exception as exc:
        raise api_error(exc) from exc


@app.post("/api/experiments/{experiment_id}/llm-d/autoscaling/platform/uninstall")
def uninstall_llmd_platform(experiment_id: int, request: LlmDPlatformBootstrapRequest) -> dict[str, str]:
    try:
        platform = state.get_setting(f"lab4:{experiment_id}")
        if not request.confirm_cluster_changes:
            raise ValueError("Confirm that you want to remove the Lab 4-owned platform releases.")
        if not platform.get("owned") or platform.get("mode") != "dedicated":
            raise ValueError("This experiment did not create a dedicated Lab 4 platform stack, so it cannot remove platform services.")
        if platform.get("context") != request.context:
            raise ValueError("The selected context does not match the Lab 4-owned platform stack.")
        log_path = autoscaling.uninstall_platform(request.context)
        state.set_setting(f"lab4:{experiment_id}", {"context": request.context, "mode": "dedicated", "owned": False})
        return {"status": "ok", "log_path": str(log_path), "message": "Removed the Lab 4-owned Prometheus, Grafana, and KEDA releases."}
    except Exception as exc:
        raise api_error(exc) from exc


@app.get("/api/experiments/{experiment_id}/llm-d/grafana", response_model=LlmDGrafanaStatus)
def llmd_grafana_status(experiment_id: int) -> LlmDGrafanaStatus:
    state.get_experiment(experiment_id)
    return LlmDGrafanaStatus(**grafana_endpoint.status(experiment_id))


@app.post("/api/experiments/{experiment_id}/llm-d/grafana/start", response_model=LlmDGrafanaStatus)
def start_llmd_grafana(experiment_id: int) -> LlmDGrafanaStatus:
    try:
        state.get_experiment(experiment_id)
        return LlmDGrafanaStatus(**grafana_endpoint.start(experiment_id))
    except Exception as exc:
        raise api_error(exc) from exc


@app.post("/api/experiments/{experiment_id}/llm-d/grafana/stop", response_model=LlmDGrafanaStatus)
def stop_llmd_grafana(experiment_id: int) -> LlmDGrafanaStatus:
    state.get_experiment(experiment_id)
    return LlmDGrafanaStatus(**grafana_endpoint.stop(experiment_id))


def deployed_llmd_config(experiment_id: int) -> dict[str, Any]:
    config = state.get_setting(f"llmd:{experiment_id}")
    if not config:
        raise RuntimeError("Deploy the monitored LLM-D CPU vLLM pool before configuring autoscaling.")
    if not config.get("enable_autoscaling"):
        raise RuntimeError("Redeploy LLM-D with Lab 4 monitoring and EPP Flow Control enabled before configuring autoscaling.")
    return config


@app.post("/api/experiments/{experiment_id}/llm-d/autoscaling/plan", response_model=LlmDAutoscalingPlan)
def plan_llmd_autoscaling(experiment_id: int, request: LlmDAutoscalingRequest) -> LlmDAutoscalingPlan:
    try:
        state.get_experiment(experiment_id)
        config = deployed_llmd_config(experiment_id)
        return LlmDAutoscalingPlan(**autoscaling.autoscaling_plan(config, request.model_dump()))
    except Exception as exc:
        raise api_error(exc) from exc


@app.post("/api/experiments/{experiment_id}/llm-d/autoscaling/deploy", response_model=LlmDAutoscalingResult)
def deploy_llmd_autoscaling(experiment_id: int, request: LlmDAutoscalingRequest) -> LlmDAutoscalingResult:
    try:
        state.get_experiment(experiment_id)
        config = deployed_llmd_config(experiment_id)
        policy = request.model_dump()
        platform = state.get_setting(f"lab4:{experiment_id}")
        policy.update({key: platform.get(key) for key in ("monitoring_namespace", "prometheus_service") if platform.get(key)})
        plan, log_path = autoscaling.apply_autoscaling(config, policy)
        state.set_setting(f"lab4-policy:{experiment_id}", policy)
        state.update_experiment(experiment_id, status="lab4-autoscaling-ready")
        return LlmDAutoscalingResult(status="ok", log_path=str(log_path), message="KEDA now owns the HPA for the CPU vLLM Deployment. Generate sustained traffic and observe the demand metrics.", plan=LlmDAutoscalingPlan(**plan))
    except Exception as exc:
        raise api_error(exc) from exc


@app.get("/api/experiments/{experiment_id}/llm-d/autoscaling/observation", response_model=LlmDAutoscalingObservation)
def llmd_autoscaling_observation(experiment_id: int) -> LlmDAutoscalingObservation:
    try:
        config = deployed_llmd_config(experiment_id)
        policy = state.get_setting(f"lab4-policy:{experiment_id}")
        if not policy:
            raise RuntimeError("Apply a Lab 4 KEDA policy before collecting observations.")
        snapshot = autoscaling.observation(config, policy)
        timeline = state.get_setting(f"lab4-timeline:{experiment_id}", {"items": []})
        state.set_setting(f"lab4-timeline:{experiment_id}", {"items": (timeline.get("items", []) + [snapshot])[-100:]})
        return LlmDAutoscalingObservation(**snapshot)
    except Exception as exc:
        raise api_error(exc) from exc


@app.get("/api/experiments/{experiment_id}/llm-d/endpoint", response_model=LlmDEndpointStatus)
def llmd_endpoint_status(experiment_id: int) -> LlmDEndpointStatus:
    state.get_experiment(experiment_id)
    return LlmDEndpointStatus(**llmd_endpoint.status(experiment_id))


@app.post("/api/experiments/{experiment_id}/llm-d/endpoint/start", response_model=LlmDEndpointStatus)
def start_llmd_endpoint(experiment_id: int) -> LlmDEndpointStatus:
    try:
        state.get_experiment(experiment_id)
        return LlmDEndpointStatus(**llmd_endpoint.start(experiment_id))
    except Exception as exc:
        raise api_error(exc) from exc


@app.post("/api/experiments/{experiment_id}/llm-d/endpoint/stop", response_model=LlmDEndpointStatus)
def stop_llmd_endpoint(experiment_id: int) -> LlmDEndpointStatus:
    state.get_experiment(experiment_id)
    return LlmDEndpointStatus(**llmd_endpoint.stop(experiment_id))


@app.post("/api/experiments/{experiment_id}/llm-d/inference")
def llmd_inference(experiment_id: int, request: LlmDInferenceRequest) -> dict[str, Any]:
    try:
        state.get_experiment(experiment_id)
        return llmd_endpoint.chat(experiment_id, request.prompt, request.max_tokens, request.temperature)
    except Exception as exc:
        raise api_error(exc) from exc


@app.post("/api/experiments/{experiment_id}/llm-d/benchmark", response_model=LlmDBenchmarkResult)
async def benchmark_llmd(experiment_id: int, request: LlmDBenchmarkRequest) -> LlmDBenchmarkResult:
    try:
        state.get_experiment(experiment_id)
        endpoint_state = llmd_endpoint.start(experiment_id)
        config = llmd_endpoint.deployment_config(experiment_id)
        prompt_set = state.get_prompt_set(request.prompt_set_id) if request.prompt_set_id else None
        prompts = read_prompt_set(prompt_set["path"]) if prompt_set else [request.prompt]
        prompts = [prompt.strip() for prompt in prompts if prompt.strip()]
        if not prompts:
            raise RuntimeError("Provide a prompt or select a CSV prompt set with at least one prompt.")
        result = await run_benchmark(
            url=f"{endpoint_state['endpoint_url']}/v1/chat/completions",
            model=config["model"],
            prompts=prompts,
            concurrency=request.concurrency,
            requests=request.requests,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
        )
        result["summary"].update({
            "name": request.name,
            "experiment_id": experiment_id,
            "deployment": "llm-d-cpu-vllm",
            "model": config["model"],
            "namespace": config["namespace"],
            "release_name": config["release_name"],
            "prompt_set_id": request.prompt_set_id,
            "prompt_set_name": prompt_set["name"] if prompt_set else "Custom prompt",
        })
        output_dir = BENCHMARKS_DIR / "llm-d" / str(experiment_id)
        raw_path, summary_path = write_benchmark_result(output_dir, request.name, result)
        state.insert_llmd_benchmark(experiment_id, request.name, summary_path, raw_path, result["summary"])
        successful_requests = result["summary"]["successful_requests"]
        if successful_requests == 0:
            raise RuntimeError(
                f"Benchmark could not reach the LLM-D endpoint: 0/{result['summary']['requests']} requests succeeded. "
                "The failed attempt was saved in benchmark history for troubleshooting."
            )
        state.update_experiment(experiment_id, status="llm-d-benchmarked")
        return LlmDBenchmarkResult(
            endpoint_url=endpoint_state["endpoint_url"], raw_path=str(raw_path), summary_path=str(summary_path), summary=result["summary"],
        )
    except Exception as exc:
        raise api_error(exc) from exc


@app.get("/api/experiments/{experiment_id}/llm-d/benchmarks", response_model=list[LlmDBenchmarkRecord])
def list_llmd_benchmark_runs(experiment_id: int) -> list[LlmDBenchmarkRecord]:
    state.get_experiment(experiment_id)
    return [LlmDBenchmarkRecord(**item) for item in state.list_llmd_benchmarks(experiment_id)]


# ---------------------------------------------------------------------------
# Lab 5: hybrid LiteLLM routing.  These handlers intentionally use a linked
# Lab 4 experiment as their immutable source of local EPP details; Lab 5 never
# recreates, changes, or deletes the source model servers, KEDA policy, or
# platform stack.

def _routing_source_config(experiment_id: int, request_config: dict[str, Any]) -> dict[str, Any]:
    experiment = state.get_experiment(experiment_id)
    if experiment.get("kind") != "llm-d-routing":
        raise RuntimeError("Create a Lab 5 hybrid routing experiment before configuring its router.")
    stored_source_id = experiment.get("source_experiment_id")
    requested_source_id = request_config.get("source_experiment_id")
    if not stored_source_id:
        raise RuntimeError("This Lab 5 experiment is not linked to a Lab 4 source experiment.")
    if requested_source_id and requested_source_id != stored_source_id:
        raise RuntimeError("The selected source does not match the Lab 4 experiment linked when this Lab 5 experiment was created.")

    source = state.get_experiment(int(stored_source_id))
    if source.get("kind") != "llm-d-autoscaling":
        raise RuntimeError("The linked source is not a Lab 4 LLM-D autoscaling experiment.")
    source_deployment = state.get_setting(f"llmd:{stored_source_id}")
    if not source_deployment:
        raise RuntimeError("The linked Lab 4 experiment has no deployed LLM-D configuration.")
    if not source_deployment.get("enable_autoscaling"):
        raise RuntimeError("Redeploy the linked Lab 4 LLM-D workload with monitoring and EPP Flow Control enabled before adding Lab 5 routing.")
    platform = state.get_setting(f"lab4:{stored_source_id}")
    if not platform:
        raise RuntimeError("Bootstrap or attach the Lab 4 observability platform before adding Lab 5 routing.")

    # Bound the router's private targets to the selected source.  We ignore
    # client-supplied context/service/model values rather than letting a Lab 5
    # UI field point a router at another workload.
    config = dict(request_config)
    # Preflight intentionally accepts a smaller payload than the plan/deploy
    # forms. Alias model IDs do not affect source-cluster readiness, so use the
    # same public defaults when they are absent.
    config.setdefault("coding_model", "openai/gpt-4.1-mini")
    config.setdefault("reasoning_model", "deepseek/deepseek-r1")
    if not config.get("router_name"):
        config["router_name"] = f"{routing.ROUTER_NAME}-{experiment_id}"
    config.update({
        "source_experiment_id": int(stored_source_id),
        "context": source_deployment["context"],
        "namespace": source_deployment["namespace"],
        "release_name": source_deployment["release_name"],
        "model": source_deployment["model"],
        "monitoring_namespace": platform.get("monitoring_namespace", routing.MONITORING_NAMESPACE),
        "prometheus_service": platform.get("prometheus_service", routing.PROMETHEUS_SERVICE),
    })
    return routing.validate_config(config, require_openrouter_key=bool(config.get("openrouter_api_key")))


def _routing_kubectl_exists(config: dict[str, Any], *args: str) -> bool:
    try:
        result = llmd.command_output(llmd.kubectl(config["context"], *args), timeout=45)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _routing_epp_ready(config: dict[str, Any]) -> bool:
    try:
        result = llmd.command_output(
            llmd.kubectl(config["context"], "-n", config["namespace"], "get", "endpoints", f"{config['release_name']}-epp", "-o", "json"),
            timeout=45,
        )
        if result.returncode:
            return False
        endpoints = json.loads(result.stdout or "{}")
        for subset in endpoints.get("subsets", []):
            if subset.get("addresses"):
                return True
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        pass
    return False


def _routing_preflight(experiment_id: int, config: dict[str, Any]) -> dict[str, Any]:
    source = state.get_experiment(config["source_experiment_id"])
    source_deployment = state.get_setting(f"llmd:{config['source_experiment_id']}")
    platform = state.get_setting(f"lab4:{config['source_experiment_id']}")
    warnings = list(routing.preflight_manifest(config)["warnings"])
    llmd.require_tool("kubectl")

    epp_service_name = f"{config['release_name']}-epp"
    epp_service = _routing_kubectl_exists(config, "-n", config["namespace"], "get", "service", epp_service_name)
    epp_ready = _routing_epp_ready(config) if epp_service else False
    service_monitor_crd = _routing_kubectl_exists(config, "get", "crd", "servicemonitors.monitoring.coreos.com")
    prometheus_available = _routing_kubectl_exists(
        config, "-n", config["monitoring_namespace"], "get", "service", config["prometheus_service"],
    )
    grafana_service = platform.get("grafana_service", "llmd-grafana") if platform else "llmd-grafana"
    grafana_available = _routing_kubectl_exists(
        config, "-n", config["monitoring_namespace"], "get", "service", grafana_service,
    )
    conflicts: list[dict[str, str]] = []
    try:
        platform_preflight = autoscaling.preflight(
            config["context"], config["namespace"], config["release_name"], config["monitoring_namespace"],
            config["prometheus_service"], grafana_service, platform.get("keda_namespace", autoscaling.KEDA_NAMESPACE) if platform else autoscaling.KEDA_NAMESPACE,
        )
        conflicts = platform_preflight.get("conflicting_releases", [])
    except Exception:
        # The route prerequisites above are specific, and useful even if Helm
        # is not installed locally to inspect existing releases.
        warnings.append("Could not inspect Helm releases for platform conflicts. No Helm resources will be installed by Lab 5.")

    source_ready = bool(
        source.get("kind") == "llm-d-autoscaling"
        and source_deployment.get("enable_autoscaling")
        and platform
    )
    if not source_ready:
        warnings.append("The selected source does not have a complete Lab 4 monitored/autoscaling configuration.")
    if not epp_service:
        warnings.append(f"The linked Lab 4 EPP Service {epp_service_name!r} was not found in {config['namespace']!r}.")
    elif not epp_ready:
        warnings.append("The linked EPP Service has no ready endpoints yet. Wait for the LLM-D router and model pods to become Ready.")
    if not service_monitor_crd:
        warnings.append("The ServiceMonitor CRD is absent, so Prometheus cannot discover Lab 5 router metrics.")
    if not prometheus_available:
        warnings.append("The selected Lab 4 Prometheus Service is unavailable, so routing metrics and Grafana panels will be empty.")
    if not grafana_available:
        warnings.append("Grafana was not detected. The router can run, but the Lab 5 dashboard ConfigMap will not be visible until Grafana is available.")
    warnings.append("External egress is not actively probed because that would require sending a credential. Coding and reasoning routes need cluster DNS and HTTPS egress to OpenRouter.")
    return {
        "source_experiment_id": config["source_experiment_id"],
        "context": config["context"],
        "namespace": config["namespace"],
        "source_experiment_ready": source_ready,
        "epp_service": epp_service_name if epp_service else None,
        "epp_ready": epp_ready,
        "prometheus_available": prometheus_available,
        "grafana_available": grafana_available,
        "service_monitor_crd": service_monitor_crd,
        "egress_ready": None,
        "conflicting_releases": conflicts,
        "warnings": warnings,
    }


def _routing_plan_model(config: dict[str, Any]) -> LlmDRoutingPlan:
    plan = routing.routing_plan(config)
    # ``routing_plan`` is designed to be safe by construction; redact again at
    # the boundary so a future renderer cannot accidentally leak an input key.
    return LlmDRoutingPlan(**routing.redact({
        "source_experiment_id": plan["source_experiment_id"],
        "context": plan["context"],
        "namespace": plan["namespace"],
        "router_name": plan["router_name"],
        "service_name": plan["service_name"],
        "manifests": plan["manifests"],
        "commands": plan["commands"],
        "aliases": plan["aliases"],
        "warnings": plan["warnings"],
    }))


def _routing_apply_command(
    entries: list[str], command: list[str], *, input_text: str | None = None, hide_output: bool = False, timeout: int = 300,
) -> None:
    entries.append("$ " + " ".join(command))
    result = llmd.command_output(command, input_text=input_text, timeout=timeout)
    if result.returncode:
        # Do not return kube API output for a Secret apply. It normally lacks
        # data, but a generic failure is safer than treating that as a contract.
        if hide_output:
            raise RuntimeError("Could not apply the Lab 5 credential Secret.")
        raise RuntimeError(result.stderr.strip() or f"Command failed with exit code {result.returncode}.")
    if not hide_output:
        entries.extend(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
    else:
        entries.append("Applied Lab 5 credential Secret (contents redacted).")


@app.post("/api/experiments/{experiment_id}/llm-d/routing/preflight")
def llmd_routing_preflight(experiment_id: int, request: LlmDRoutingPreflightRequest) -> dict[str, Any]:
    try:
        config = _routing_source_config(experiment_id, request.model_dump())
        return _routing_preflight(experiment_id, config)
    except Exception as exc:
        raise api_error(exc) from exc


@app.post("/api/experiments/{experiment_id}/llm-d/routing/plan", response_model=LlmDRoutingPlan)
def plan_llmd_routing(experiment_id: int, request: LlmDRoutingConfiguration) -> LlmDRoutingPlan:
    try:
        config = _routing_source_config(experiment_id, request.model_dump())
        return _routing_plan_model(config)
    except Exception as exc:
        raise api_error(exc) from exc


@app.post("/api/experiments/{experiment_id}/llm-d/routing/deploy", response_model=LlmDRoutingDeployResult)
def deploy_llmd_routing(experiment_id: int, request: LlmDRoutingDeployRequest) -> LlmDRoutingDeployResult:
    try:
        if not request.confirm:
            raise ValueError("Review the non-secret Lab 5 plan and confirm the Lab 5-owned changes before deploying.")
        config = _routing_source_config(experiment_id, request.model_dump())
        existing_config = state.get_setting(f"llmd-routing:{experiment_id}")
        if (
            existing_config
            and existing_config.get("owned")
            and existing_config.get("router_name") != config["router_name"]
        ):
            raise ValueError(
                "Router name cannot change after this Lab 5 router is deployed. "
                "Remove the existing Lab 5 router first, then deploy a new router name."
            )
        preflight = _routing_preflight(experiment_id, config)
        missing = [
            label for label, ready in (
                ("the linked Lab 4 source", preflight["source_experiment_ready"]),
                ("the LLM-D EPP Service", preflight["epp_ready"]),
                ("the ServiceMonitor CRD", preflight["service_monitor_crd"]),
                ("the Prometheus Service", preflight["prometheus_available"]),
            ) if not ready
        ]
        if missing:
            raise RuntimeError("Cannot deploy Lab 5 routing until " + ", ".join(missing) + " is ready. Review routing preflight for remediation.")

        # A previously started companion proxy has the old in-memory master
        # key. Stop it before rotating credentials; the user can start a fresh
        # local-only endpoint after the rollout is Ready.
        routing_endpoint.stop(experiment_id)
        plan = routing.routing_plan(config)
        master_key = routing.new_router_master_key()
        secret = routing.secret_manifest(config, master_key)
        # From this point the only configuration written to local state has the
        # OpenRouter and internal master keys removed.
        safe_config = routing.redact({key: value for key, value in config.items() if key != "openrouter_api_key"})
        safe_config.update({
            "owned": True,
            "service_name": plan["service_name"],
            "secret_name": plan["resource_names"]["secret"],
            "dashboard_name": plan["resource_names"]["dashboard"],
        })

        log_path = LOGS_DIR / f"lab5-routing-{int(time.time())}.log"
        entries: list[str] = []
        try:
            # Apply the Secret directly and never add its manifest or kubectl
            # response to the plan/result/log. The next manifests contain only
            # a Secret reference and are safe to render and retain.
            _routing_apply_command(entries, plan["commands"][0], input_text=json.dumps(secret), hide_output=True)
            _routing_apply_command(entries, plan["commands"][0], input_text=plan["manifest"])
            _routing_apply_command(entries, plan["commands"][1], input_text=plan["dashboard_manifest"])
            _routing_apply_command(entries, plan["commands"][2])
            _routing_apply_command(entries, plan["commands"][3], timeout=240)
            _routing_apply_command(entries, plan["commands"][4])
        finally:
            # ``secret`` and ``master_key`` are deliberately local variables;
            # no log/setting/response below references either value.
            log_path.write_text("\n".join(entries) + "\n", encoding="utf-8")
        state.set_setting(f"llmd-routing:{experiment_id}", safe_config)
        state.update_experiment(experiment_id, status="lab5-routing-ready")
        message = "Lab 5 router is Ready. Start the local endpoint to send explicit aliases through LiteLLM."
        return LlmDRoutingDeployResult(status="ok", log_path=str(log_path), message=message, plan=_routing_plan_model(safe_config))
    except Exception as exc:
        raise api_error(exc) from exc


@app.get("/api/experiments/{experiment_id}/llm-d/routing", response_model=LlmDRoutingStatus)
def llmd_routing_status(experiment_id: int) -> LlmDRoutingStatus:
    try:
        state.get_experiment(experiment_id)
        config = state.get_setting(f"llmd-routing:{experiment_id}")
        if not config or not config.get("owned"):
            return LlmDRoutingStatus(experiment_id=experiment_id, configured=False, owned=False, ready=False)
        plan = routing.routing_plan(config)
        deployment_ready = False
        service_ready = _routing_kubectl_exists(config, "-n", config["namespace"], "get", "service", plan["service_name"])
        try:
            result = llmd.command_output(
                llmd.kubectl(config["context"], "-n", config["namespace"], "get", "deployment", plan["router_name"], "-o", "json"), timeout=45,
            )
            if result.returncode == 0:
                deployment_ready = int(json.loads(result.stdout or "{}").get("status", {}).get("readyReplicas") or 0) >= 1
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            pass
        message = None if deployment_ready and service_ready else "The Lab 5 router is recorded as owned but its Deployment or private Service is not Ready. Refresh or inspect the cluster before starting an endpoint."
        return LlmDRoutingStatus(
            experiment_id=experiment_id, configured=True, owned=True, ready=deployment_ready and service_ready,
            source_experiment_id=config.get("source_experiment_id"), context=config.get("context"), namespace=config.get("namespace"),
            router_name=plan["router_name"], service_name=plan["service_name"], aliases=plan["aliases"], message=message,
        )
    except Exception as exc:
        raise api_error(exc) from exc


@app.get("/api/experiments/{experiment_id}/llm-d/routing/endpoint", response_model=LlmDRoutingEndpointStatus)
def llmd_routing_endpoint_status(experiment_id: int) -> LlmDRoutingEndpointStatus:
    state.get_experiment(experiment_id)
    return LlmDRoutingEndpointStatus(**routing_endpoint.status(experiment_id))


@app.post("/api/experiments/{experiment_id}/llm-d/routing/endpoint/start", response_model=LlmDRoutingEndpointStatus)
def start_llmd_routing_endpoint(experiment_id: int) -> LlmDRoutingEndpointStatus:
    try:
        state.get_experiment(experiment_id)
        return LlmDRoutingEndpointStatus(**routing_endpoint.start(experiment_id))
    except Exception as exc:
        raise api_error(exc) from exc


@app.post("/api/experiments/{experiment_id}/llm-d/routing/endpoint/stop", response_model=LlmDRoutingEndpointStatus)
def stop_llmd_routing_endpoint(experiment_id: int) -> LlmDRoutingEndpointStatus:
    state.get_experiment(experiment_id)
    return LlmDRoutingEndpointStatus(**routing_endpoint.stop(experiment_id))


@app.post("/api/experiments/{experiment_id}/llm-d/routing/inference", response_model=LlmDRoutingInferenceResult)
def llmd_routing_inference(experiment_id: int, request: LlmDRoutingInferenceRequest) -> LlmDRoutingInferenceResult:
    try:
        state.get_experiment(experiment_id)
        return LlmDRoutingInferenceResult(**routing_endpoint.chat(
            experiment_id, alias=request.model, prompt=request.prompt, messages=request.messages,
            max_tokens=request.max_tokens, temperature=request.temperature, stream=request.stream,
        ))
    except Exception as exc:
        raise api_error(exc) from exc


@app.post("/api/experiments/{experiment_id}/llm-d/routing/benchmark", response_model=LlmDRoutingBenchmarkResult)
async def benchmark_llmd_routing(experiment_id: int, request: LlmDRoutingBenchmarkRequest) -> LlmDRoutingBenchmarkResult:
    try:
        state.get_experiment(experiment_id)
        route = routing.validate_inference_request(request.model, request.max_tokens)
        endpoint_state = routing_endpoint.start(experiment_id)
        prompt_set = state.get_prompt_set(request.prompt_set_id) if request.prompt_set_id else None
        prompts = read_prompt_set(prompt_set["path"]) if prompt_set else [request.prompt]
        prompts = [prompt.strip() for prompt in prompts if prompt.strip()]
        if not prompts:
            raise RuntimeError("Provide a prompt or select a CSV prompt set with at least one prompt.")
        result = await run_benchmark(
            url=f"{endpoint_state['endpoint_url']}/v1/chat/completions", model=request.model, prompts=prompts,
            concurrency=request.concurrency, requests=request.requests, max_tokens=request.max_tokens, temperature=request.temperature,
        )
        config = routing_endpoint.deployment_config(experiment_id)
        result["summary"].update({
            "name": request.name,
            "experiment_id": experiment_id,
            "source_experiment_id": config.get("source_experiment_id"),
            "deployment": "lab5-hybrid-routing",
            "model": request.model,
            "destination": route["destination"],
            "namespace": config.get("namespace"),
            "router_name": config.get("router_name"),
            "prompt_set_id": request.prompt_set_id,
            "prompt_set_name": prompt_set["name"] if prompt_set else "Custom prompt",
        })
        output_dir = BENCHMARKS_DIR / "llm-d-routing" / str(experiment_id)
        raw_path, summary_path = write_benchmark_result(output_dir, request.name, result)
        state.insert_llmd_routing_benchmark(
            experiment_id, request.name, request.model, route["destination"], summary_path, raw_path, result["summary"],
        )
        if result["summary"]["successful_requests"] == 0:
            raise RuntimeError("The routing benchmark reached no successful requests. The local result is retained outside Git for troubleshooting.")
        state.update_experiment(experiment_id, status="lab5-routing-benchmarked")
        return LlmDRoutingBenchmarkResult(
            endpoint_url=endpoint_state["endpoint_url"], raw_path=str(raw_path), summary_path=str(summary_path), summary=result["summary"],
            model=request.model, destination=route["destination"],
        )
    except Exception as exc:
        raise api_error(exc) from exc


@app.get("/api/experiments/{experiment_id}/llm-d/routing/benchmarks", response_model=list[LlmDRoutingBenchmarkRecord])
def list_llmd_routing_benchmarks(experiment_id: int) -> list[LlmDRoutingBenchmarkRecord]:
    state.get_experiment(experiment_id)
    return [LlmDRoutingBenchmarkRecord(**item) for item in state.list_llmd_routing_benchmarks(experiment_id)]


@app.post("/api/experiments/{experiment_id}/llm-d/routing/uninstall", response_model=LlmDRoutingUninstallResult)
def uninstall_llmd_routing(experiment_id: int) -> LlmDRoutingUninstallResult:
    try:
        state.get_experiment(experiment_id)
        config = state.get_setting(f"llmd-routing:{experiment_id}")
        if not config or not config.get("owned"):
            raise RuntimeError("This experiment did not create a Lab 5-owned router, so it cannot remove routing resources.")
        routing_endpoint.stop(experiment_id)
        names = routing.resource_names(config)
        log_path = LOGS_DIR / f"lab5-routing-uninstall-{int(time.time())}.log"
        entries: list[str] = []
        commands = [
            llmd.kubectl(config["context"], "-n", config["namespace"], "delete", "deployment", names["router"], "--ignore-not-found"),
            llmd.kubectl(config["context"], "-n", config["namespace"], "delete", "service", names["router"], "--ignore-not-found"),
            llmd.kubectl(config["context"], "-n", config["namespace"], "delete", "servicemonitor", names["router"], "--ignore-not-found"),
            llmd.kubectl(config["context"], "-n", config["namespace"], "delete", "configmap", names["config_map"], "--ignore-not-found"),
            llmd.kubectl(config["context"], "-n", config["monitoring_namespace"], "delete", "configmap", names["dashboard"], "--ignore-not-found"),
            llmd.kubectl(config["context"], "-n", config["namespace"], "delete", "secret", names["secret"], "--ignore-not-found"),
        ]
        try:
            for command in commands:
                _routing_apply_command(entries, command)
        finally:
            log_path.write_text("\n".join(entries) + "\n", encoding="utf-8")
        state.set_setting(f"llmd-routing:{experiment_id}", {
            "source_experiment_id": config.get("source_experiment_id"), "owned": False,
        })
        state.update_experiment(experiment_id, status="lab5-routing-removed")
        return LlmDRoutingUninstallResult(
            status="ok", log_path=str(log_path),
            message="Removed only Lab 5-owned LiteLLM routing resources, its dashboard ConfigMap, and its credential Secret. The linked Lab 4 deployment was left intact.",
        )
    except Exception as exc:
        raise api_error(exc) from exc


@app.get("/api/experiments/{experiment_id}/export")
def export_experiment(experiment_id: int) -> dict[str, Any]:
    experiment = state.get_experiment(experiment_id)
    instances = state.list_instances_for_experiment(experiment_id)
    benchmarks = state.list_benchmarks_for_experiment(experiment_id)
    return {
        "experiment": experiment,
        "instances": instances,
        "benchmarks": benchmarks,
        "llmd_benchmarks": state.list_llmd_benchmarks(experiment_id),
        # Route benchmark metadata contains aggregate timings and local file
        # paths only. It never exports router settings, prompt bodies,
        # provider responses, or either credential.
        "llmd_routing_benchmarks": state.list_llmd_routing_benchmarks(experiment_id),
        "endpoint": state.get_endpoint_session(experiment_id),
        "endpoint_analytics": state.endpoint_analytics(experiment_id),
        "exported_at": state.utc_now(),
    }


@app.post("/api/experiments/{experiment_id}/delete-infra")
def delete_experiment_infra(experiment_id: int) -> dict[str, Any]:
    state.get_experiment(experiment_id)
    results = []
    for instance in state.list_instances_for_experiment(experiment_id):
        if instance.get("lifecycle_state") in {"TERMINATED", "TERMINATING"}:
            results.append({"id": instance["id"], "status": instance.get("lifecycle_state")})
            continue
        try:
            oci_cli.terminate_instance(instance["oci_instance_id"])
            updated = state.update_instance(instance["id"], lifecycle_state="TERMINATING")
            results.append({"id": updated["id"], "status": "TERMINATING"})
        except Exception as exc:
            results.append({"id": instance["id"], "status": "error", "message": str(exc)})
    state.update_experiment(experiment_id, status="infra-deleted")
    return {"experiment_id": experiment_id, "instances": results}


@app.post("/api/experiments/{experiment_id}/adopt-unassigned")
def adopt_unassigned(experiment_id: int) -> dict[str, Any]:
    adopted = state.adopt_unassigned_resources(experiment_id)
    return {"experiment_id": experiment_id, "adopted": adopted}


@app.get("/api/experiments/{experiment_id}/endpoint/health")
def endpoint_health(experiment_id: int) -> dict[str, Any]:
    state.get_experiment(experiment_id)
    return endpoint.endpoint_status(experiment_id)


@app.post("/api/experiments/{experiment_id}/endpoint/start")
def start_experiment_endpoint(experiment_id: int) -> dict[str, Any]:
    try:
        state.get_experiment(experiment_id)
        return endpoint.start_endpoint(experiment_id)
    except Exception as exc:
        raise api_error(exc) from exc


@app.post("/api/experiments/{experiment_id}/endpoint/stop")
def stop_experiment_endpoint(experiment_id: int) -> dict[str, Any]:
    state.get_experiment(experiment_id)
    return endpoint.stop_endpoint(experiment_id)


@app.post("/api/experiments/{experiment_id}/endpoint/v1/chat/completions", response_model=None)
async def experiment_endpoint_chat_completions(experiment_id: int, request: Request):
    try:
        state.get_experiment(experiment_id)
        return await endpoint.proxy_chat_completion(experiment_id, request)
    except Exception as exc:
        raise api_error(exc) from exc


@app.get("/api/context", response_model=ContextState)
def get_context() -> ContextState:
    return ContextState(**state.get_setting("context", {}))


@app.post("/api/context", response_model=ContextState)
def set_context(request: ContextRequest) -> ContextState:
    profile = oci_cli.profile_by_name(request.profile)
    if not profile:
        raise HTTPException(status_code=404, detail=f"OCI profile not found: {request.profile}")
    payload = {
        "profile": request.profile,
        "region": request.region or profile.region,
        "compartment_id": request.compartment_id,
    }
    state.set_setting("context", payload)
    return ContextState(**payload)


@app.get("/api/compartments", response_model=list[Option])
def compartments() -> list[Option]:
    try:
        return [Option(**item) for item in oci_cli.list_compartments()]
    except Exception as exc:
        raise api_error(exc) from exc


@app.get("/api/availability-domains", response_model=list[Option])
def availability_domains() -> list[Option]:
    try:
        return [Option(**item) for item in oci_cli.list_availability_domains()]
    except Exception as exc:
        raise api_error(exc) from exc


@app.get("/api/shapes", response_model=list[Option])
def shapes(
    compartment_id: str | None = None,
    availability_domain: str | None = None,
    include_gpu_shapes: bool = False,
) -> list[Option]:
    try:
        return [Option(**item) for item in oci_cli.list_shapes(compartment_id, availability_domain, include_gpu_shapes)]
    except Exception as exc:
        raise api_error(exc) from exc


@app.get("/api/vcns", response_model=list[Option])
def vcns(compartment_id: str | None = None) -> list[Option]:
    try:
        return [Option(**item) for item in oci_cli.list_vcns(compartment_id)]
    except Exception as exc:
        raise api_error(exc) from exc


@app.get("/api/subnets", response_model=list[Option])
def subnets(compartment_id: str | None = None, vcn_id: str | None = None) -> list[Option]:
    try:
        return [Option(**item) for item in oci_cli.list_subnets(compartment_id, vcn_id)]
    except Exception as exc:
        raise api_error(exc) from exc


@app.get("/api/images", response_model=list[Option])
def images(compartment_id: str | None = None, shape: str | None = None) -> list[Option]:
    try:
        return [Option(**item) for item in oci_cli.list_images(compartment_id, shape)]
    except Exception as exc:
        raise api_error(exc) from exc


@app.get("/api/ssh-keys", response_model=list[SshKeyRecord])
def ssh_keys() -> list[SshKeyRecord]:
    return [SshKeyRecord(**item) for item in state.list_ssh_keys()]


@app.post("/api/ssh-keys", response_model=SshKeyRecord)
def create_ssh_key(request: SshKeyCreate) -> SshKeyRecord:
    try:
        private_path, public_path, public_key = generate_ed25519_key(request.name)
        return SshKeyRecord(**state.insert_ssh_key(request.name, private_path, public_path, public_key))
    except Exception as exc:
        raise api_error(exc) from exc


@app.post("/api/instances", response_model=InstanceRecord)
def create_instance(request: InstanceCreate) -> InstanceRecord:
    try:
        ssh_key = state.get_ssh_key(request.ssh_key_id)
        launched = oci_cli.launch_instance(request.model_dump(), ssh_key["public_key"])
        vnic = oci_cli.get_instance_vnic(request.compartment_id, launched["id"])
        record = state.insert_instance(
            {
                "oci_instance_id": launched["id"],
                "display_name": request.display_name,
                "lifecycle_state": launched.get("lifecycle-state"),
                "shape": request.shape,
                "availability_domain": request.availability_domain,
                "compartment_id": request.compartment_id,
                "subnet_id": request.subnet_id,
                "image_id": request.image_id,
                "ssh_key_id": request.ssh_key_id,
                "ssh_user": request.ssh_user,
                "public_ip": vnic.get("public-ip"),
                "private_ip": vnic.get("private-ip"),
                "experiment_id": request.experiment_id,
            }
        )
        if request.experiment_id:
            state.update_experiment(request.experiment_id, status="provisioned")
        return InstanceRecord(**record)
    except Exception as exc:
        raise api_error(exc) from exc


def refresh_instance_record(instance: dict[str, Any]) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    remote = oci_cli.get_instance(instance["oci_instance_id"])
    if remote.get("lifecycle-state"):
        changes["lifecycle_state"] = remote["lifecycle-state"]

    if not instance.get("public_ip") and not instance.get("private_ip"):
        vnic = oci_cli.get_instance_vnic(instance["compartment_id"], instance["oci_instance_id"])
        if vnic.get("public-ip"):
            changes["public_ip"] = vnic["public-ip"]
        if vnic.get("private-ip"):
            changes["private_ip"] = vnic["private-ip"]

    if changes:
        return state.update_instance(instance["id"], **changes)
    return instance


@app.get("/api/instances", response_model=list[InstanceRecord])
def instances() -> list[InstanceRecord]:
    records = []
    for item in state.list_instances():
        try:
            item = refresh_instance_record(item)
        except Exception:
            pass
        records.append(InstanceRecord(**item))
    return records


@app.get("/api/deploy/models", response_model=list[DeployModelOption])
def deploy_models(engine: str = "llama_cpp") -> list[DeployModelOption]:
    return [DeployModelOption(**item) for item in list_deploy_models(engine)]


@app.post("/api/instances/{instance_id}/deploy", response_model=DeployResult)
def deploy(instance_id: int, request: DeployRequest | None = None) -> DeployResult:
    try:
        instance = refresh_instance_record(state.get_instance(instance_id))
        key = state.get_ssh_key(instance["ssh_key_id"])
        host = instance["public_ip"] or instance["private_ip"]
        if not host:
            state_text = instance.get("lifecycle_state") or "unknown"
            raise RuntimeError(
                f"Instance is {state_text} and has no IP yet. Wait until it is RUNNING, then refresh state and deploy again."
            )
        deploy_config = (request or DeployRequest()).model_dump()
        model = resolve_model(deploy_config)
        log_path, message = deploy_inference_engine(instance_id, key["private_key_path"], instance["ssh_user"], host, deploy_config)
        status = "failed" if message.startswith("Deployment failed") else "ok"
        if status == "ok" and instance.get("experiment_id"):
            state.update_experiment(instance["experiment_id"], status="deployed")
        if status == "ok":
            state.update_instance(
                instance_id,
                inference_engine=deploy_config.get("engine") or "llama_cpp",
                deployed_model_id=model["id"],
                deployed_model_name=model["name"],
                deployed_model_source=model["url"],
            )
        return DeployResult(instance_id=instance_id, status=status, log_path=log_path, message=message)
    except Exception as exc:
        raise api_error(exc) from exc


@app.get("/api/prompts", response_model=list[PromptSet])
def prompt_sets() -> list[PromptSet]:
    return [PromptSet(**item) for item in state.list_prompt_sets()]


@app.post("/api/prompts", response_model=PromptSet)
async def upload_prompt(file: UploadFile = File(...)) -> PromptSet:
    text = (await file.read()).decode("utf-8")
    filename = file.filename or "prompts.txt"
    prompts = parse_prompt_file(text, filename)
    if not prompts:
        raise HTTPException(status_code=400, detail="Prompt file did not contain any prompts.")
    safe_name = "".join(char if char.isalnum() or char in ("-", "_", ".") else "-" for char in filename)
    path = PROMPTS_DIR / f"{int(time.time())}-{safe_name}"
    path.write_text(text, encoding="utf-8")
    description = "Uploaded CSV prompt set." if Path(filename).suffix.lower() == ".csv" else "Uploaded prompt file. Prompts are separated by blank lines."
    return PromptSet(**state.insert_prompt_set(filename, path, len(prompts), description))


@app.post("/api/benchmarks", response_model=BenchmarkRecord)
async def create_benchmark(request: BenchmarkRequest) -> BenchmarkRecord:
    try:
        instance = refresh_instance_record(state.get_instance(request.instance_id))
        key = state.get_ssh_key(instance["ssh_key_id"])
        prompts = request.prompts or []
        if request.prompt_set_id:
            prompt_set = state.get_prompt_set(request.prompt_set_id)
            prompts.extend(read_prompt_set(prompt_set["path"]))
        prompts = [prompt.strip() for prompt in prompts if prompt.strip()]
        if not prompts:
            raise RuntimeError("Provide prompts or select a prompt set.")

        host = instance["public_ip"] or instance["private_ip"]
        if not host:
            state_text = instance.get("lifecycle_state") or "unknown"
            raise RuntimeError(f"Instance is {state_text} and has no IP yet. Wait until it is RUNNING before benchmarking.")

        if request.benchmark_tool == "http_streaming":
            # This request-level setting is supported by llama.cpp.  It lets a
            # benchmark keep model weights warm while preventing old prompt KV
            # state from affecting a cold-prefill/TTFT trial.
            cache_prompt = False if request.disable_prompt_cache and instance.get("inference_engine") == "llama_cpp" else None
            local_port = free_local_port()
            tunnel = start_tunnel(key["private_key_path"], instance["ssh_user"], host, local_port)
            try:
                await asyncio.sleep(1.5)
                result = await run_benchmark(
                    url=f"http://127.0.0.1:{local_port}/v1/chat/completions",
                    prompts=prompts,
                    concurrency=request.concurrency,
                    requests=request.requests,
                    max_tokens=request.max_tokens,
                    temperature=request.temperature,
                    cache_prompt=cache_prompt,
                )
            finally:
                tunnel.terminate()
                try:
                    tunnel.wait(timeout=5)
                except Exception:
                    tunnel.kill()
        else:
            cache_prompt = None
            if request.benchmark_tool not in BENCHMARK_TOOLS:
                raise RuntimeError(f"Unknown benchmark tool: {request.benchmark_tool}")
            engine = instance.get("inference_engine")
            if not engine:
                raise RuntimeError("This instance has no recorded inference engine. Redeploy it from the engine-aware Deploy step before running a native benchmark.")
            model_config = {"engine": engine, "model_id": instance.get("deployed_model_id")}
            if instance.get("deployed_model_id") == "custom":
                model_config.update({"custom_model_name": instance.get("deployed_model_name"), "custom_model_url": instance.get("deployed_model_source")})
            model = resolve_model(model_config)
            result = await asyncio.to_thread(
                run_native_benchmark,
                private_key_path=key["private_key_path"],
                user=instance["ssh_user"],
                host=host,
                tool=request.benchmark_tool,
                engine=engine,
                model=model,
                prompts=prompts,
                requests=request.requests,
                concurrency=request.concurrency,
                max_tokens=request.max_tokens,
            )

        experiment_id = request.experiment_id or instance.get("experiment_id")
        result["summary"]["name"] = request.name
        result["summary"]["instance_id"] = request.instance_id
        result["summary"]["experiment_id"] = experiment_id
        result["summary"]["instance_display_name"] = instance["display_name"]
        result["summary"]["shape"] = instance["shape"]
        result["summary"]["shape_class"] = oci_cli.shape_class(instance["shape"])
        result["summary"]["inference_engine"] = instance.get("inference_engine") or "llama_cpp"
        result["summary"]["benchmark_tool"] = request.benchmark_tool
        result["summary"]["benchmark_tool_label"] = BENCHMARK_TOOLS.get(request.benchmark_tool, "HTTP streaming")
        result["summary"]["prompt_cache_mode"] = (
            "disabled" if cache_prompt is False else "server default" if request.benchmark_tool == "http_streaming" and instance.get("inference_engine") == "llama_cpp" else "n/a"
        )
        result["summary"]["preset_id"] = request.preset_id
        result["summary"]["preset_name"] = request.preset_name
        result["summary"]["preset_focus"] = request.preset_focus
        result["summary"]["comparison_group"] = request.comparison_group or request.preset_id or request.name
        result["summary"]["experiment_lane"] = request.experiment_lane or result["summary"]["shape_class"]
        if request.prompt_set_id:
            result["summary"]["prompt_set_id"] = request.prompt_set_id
            result["summary"]["prompt_set_name"] = prompt_set["name"]
        output_dir = BENCHMARKS_DIR / str(request.instance_id)
        raw_path, summary_path = write_benchmark_result(output_dir, request.name, result)
        record = state.insert_benchmark(request.instance_id, request.name, summary_path, raw_path, result["summary"], experiment_id)
        if experiment_id:
            state.update_experiment(experiment_id, status="benchmarked")
        return BenchmarkRecord(**record)
    except Exception as exc:
        raise api_error(exc) from exc


@app.get("/api/benchmarks", response_model=list[BenchmarkRecord])
def benchmarks() -> list[BenchmarkRecord]:
    return [BenchmarkRecord(**item) for item in state.list_benchmarks()]
