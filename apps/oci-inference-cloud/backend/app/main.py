from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from . import autoscaling, endpoint, grafana_endpoint, llmd, llmd_endpoint, oci_cli, state
from .benchmark import run_benchmark, write_benchmark_result
from .config import BENCHMARKS_DIR, PROMPTS_DIR, ensure_app_dirs
from .deploy import deploy_llama_cpp, list_deploy_models
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
    return ExperimentRecord(**state.insert_experiment(request.name.strip(), request.description.strip(), request.kind))


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
def deploy_models() -> list[DeployModelOption]:
    return [DeployModelOption(**item) for item in list_deploy_models()]


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
        log_path, message = deploy_llama_cpp(instance_id, key["private_key_path"], instance["ssh_user"], host, deploy_config)
        status = "failed" if message.startswith("Deployment failed") else "ok"
        if status == "ok" and instance.get("experiment_id"):
            state.update_experiment(instance["experiment_id"], status="deployed")
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
            )
        finally:
            tunnel.terminate()
            try:
                tunnel.wait(timeout=5)
            except Exception:
                tunnel.kill()

        experiment_id = request.experiment_id or instance.get("experiment_id")
        result["summary"]["name"] = request.name
        result["summary"]["instance_id"] = request.instance_id
        result["summary"]["experiment_id"] = experiment_id
        result["summary"]["instance_display_name"] = instance["display_name"]
        result["summary"]["shape"] = instance["shape"]
        result["summary"]["shape_class"] = oci_cli.shape_class(instance["shape"])
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
