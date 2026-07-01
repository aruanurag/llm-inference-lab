from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Profile(BaseModel):
    name: str
    region: str | None = None
    tenancy: str | None = None
    user: str | None = None


class ContextRequest(BaseModel):
    profile: str
    region: str | None = None
    compartment_id: str | None = None


class ContextState(BaseModel):
    profile: str | None = None
    region: str | None = None
    compartment_id: str | None = None


class Option(BaseModel):
    id: str
    name: str
    extra: dict[str, Any] = Field(default_factory=dict)


class SshKeyCreate(BaseModel):
    name: str


class SshKeyRecord(BaseModel):
    id: int
    name: str
    created_at: str


class ExperimentCreate(BaseModel):
    name: str
    description: str = ""


class ExperimentRecord(BaseModel):
    id: int
    name: str
    description: str = ""
    status: str
    created_at: str
    updated_at: str


class InstanceCreate(BaseModel):
    experiment_id: int | None = None
    display_name: str
    compartment_id: str
    availability_domain: str
    shape: str
    subnet_id: str
    image_id: str
    ssh_key_id: int
    ssh_user: str = "opc"
    assign_public_ip: bool = True
    boot_volume_size_gbs: int = 100
    ocpus: float | None = None
    memory_gbs: float | None = None


class InstanceRecord(BaseModel):
    id: int
    experiment_id: int | None = None
    oci_instance_id: str
    display_name: str
    lifecycle_state: str | None = None
    shape: str
    availability_domain: str
    compartment_id: str
    subnet_id: str
    image_id: str
    ssh_key_id: int
    ssh_user: str
    public_ip: str | None = None
    private_ip: str | None = None
    created_at: str
    updated_at: str


class DeployResult(BaseModel):
    instance_id: int
    status: str
    log_path: str
    message: str


class DeployModelOption(BaseModel):
    id: str
    name: str
    size_label: str
    quantization: str
    url: str
    filename: str
    recommended_ocpus: int
    recommended_memory_gbs: int
    description: str


class DeployRequest(BaseModel):
    model_id: str = "qwen2.5-1.5b-q4_k_m"
    custom_model_name: str | None = None
    custom_model_url: str | None = None
    build_native: bool = False
    disable_vnni: bool = True
    ctx_size: int = 4096
    parallel: int = 4
    batch_size: int = 512
    ubatch_size: int = 128


class PromptSet(BaseModel):
    id: int
    name: str
    description: str = ""
    path: str
    prompt_count: int
    created_at: str


class BenchmarkRequest(BaseModel):
    experiment_id: int | None = None
    instance_id: int
    name: str = "benchmark"
    preset_id: str | None = None
    preset_name: str | None = None
    preset_focus: str | None = None
    comparison_group: str | None = None
    experiment_lane: str | None = None
    prompt_set_id: int | None = None
    prompts: list[str] | None = None
    concurrency: int = 1
    requests: int = 1
    max_tokens: int = 128
    temperature: float = 0.0


class BenchmarkRecord(BaseModel):
    id: int
    instance_id: int
    name: str
    summary_path: str
    raw_path: str
    created_at: str
    summary: dict[str, Any]
