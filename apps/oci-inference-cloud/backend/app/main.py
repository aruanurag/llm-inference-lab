from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from . import endpoint, oci_cli, state
from .benchmark import run_benchmark, write_benchmark_result
from .config import BENCHMARKS_DIR, PROMPTS_DIR, ensure_app_dirs
from .deploy import deploy_llama_cpp, list_deploy_models
from .prompts import parse_prompt_file, read_prompt_set, seed_default_prompts
from .schemas import (
    BenchmarkRecord,
    BenchmarkRequest,
    ContextRequest,
    ContextState,
    DeployResult,
    DeployModelOption,
    DeployRequest,
    ExperimentCreate,
    ExperimentRecord,
    InstanceCreate,
    InstanceRecord,
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
    return ExperimentRecord(**state.insert_experiment(request.name.strip(), request.description.strip()))


@app.get("/api/experiments/{experiment_id}/export")
def export_experiment(experiment_id: int) -> dict[str, Any]:
    experiment = state.get_experiment(experiment_id)
    instances = state.list_instances_for_experiment(experiment_id)
    benchmarks = state.list_benchmarks_for_experiment(experiment_id)
    return {
        "experiment": experiment,
        "instances": instances,
        "benchmarks": benchmarks,
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
    prompts = parse_prompt_file(text)
    if not prompts:
        raise HTTPException(status_code=400, detail="Prompt file did not contain any prompts.")
    safe_name = "".join(char if char.isalnum() or char in ("-", "_", ".") else "-" for char in file.filename or "prompts.txt")
    path = PROMPTS_DIR / f"{int(time.time())}-{safe_name}"
    path.write_text(text, encoding="utf-8")
    return PromptSet(**state.insert_prompt_set(file.filename or safe_name, path, len(prompts), "Uploaded prompt file. Prompts are separated by blank lines."))


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
