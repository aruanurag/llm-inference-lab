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
    kind: str = "cpu-instance"


class ExperimentRecord(BaseModel):
    id: int
    name: str
    description: str = ""
    kind: str = "cpu-instance"
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


class KubernetesContext(BaseModel):
    name: str


class ClusterAccessRequest(BaseModel):
    context: str
    namespace: str = "llm-d-lab"


class ClusterValidation(BaseModel):
    context: str
    namespace: str
    kubectl_version: str | None = None
    helm_version: str | None = None
    ready_nodes: int
    total_nodes: int
    cpu_cores: float
    memory_kib: int
    architectures: list[str]
    warnings: list[str] = Field(default_factory=list)


class LlmDDeploymentRequest(ClusterAccessRequest):
    llmd_repo_path: str
    release_name: str = "llm-d-lab"
    model: str = "Qwen/Qwen2.5-1.5B-Instruct"
    replicas: int = Field(default=1, ge=1, le=20)
    cpu: int = Field(default=16, ge=1, le=512)
    memory_gib: int = Field(default=32, ge=4, le=2048)
    kv_cache_gib: int = Field(default=8, ge=1, le=1024)
    max_model_len: int = Field(default=4096, ge=256, le=131072)
    max_num_seqs: int = Field(default=8, ge=1, le=1024)
    max_num_batched_tokens: int = Field(default=2048, ge=256, le=131072)
    cpu_threads_bind: str | None = None
    reserved_cpu: int = Field(default=1, ge=0, le=128)
    enable_prefix_caching: bool = True
    enable_autoscaling: bool = False
    hf_token: str | None = None


class LlmDCheckoutRequest(BaseModel):
    path: str | None = None


class LlmDCheckout(BaseModel):
    path: str
    revision: str
    status: str


class LlmDPlan(BaseModel):
    context: str
    namespace: str
    release_name: str
    overlay_path: str
    commands: list[list[str]]
    overlay: str
    monitoring_path: str | None = None
    monitoring_manifest: str | None = None


class LlmDDeployResult(BaseModel):
    status: str
    log_path: str
    message: str
    plan: LlmDPlan


class LlmDEndpointStatus(BaseModel):
    experiment_id: int
    status: str
    endpoint_url: str
    healthy: bool


class LlmDInferenceRequest(BaseModel):
    prompt: str
    max_tokens: int = Field(default=128, ge=1, le=4096)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)


class LlmDBenchmarkRequest(BaseModel):
    name: str = "llmd-cpu-baseline"
    prompt: str = "Explain why an LLM-aware router uses queue depth and cache state."
    prompt_set_id: int | None = None
    concurrency: int = Field(default=1, ge=1, le=128)
    requests: int = Field(default=8, ge=1, le=1000)
    max_tokens: int = Field(default=128, ge=1, le=4096)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)


class LlmDBenchmarkResult(BaseModel):
    endpoint_url: str
    raw_path: str
    summary_path: str
    summary: dict[str, Any]


class LlmDBenchmarkRecord(BaseModel):
    id: int
    experiment_id: int
    name: str
    raw_path: str
    summary_path: str
    created_at: str
    summary: dict[str, Any]


class LlmDPlatformPreflightRequest(ClusterAccessRequest):
    release_name: str = "llm-d-lab"
    monitoring_namespace: str = "llm-d-monitoring"
    prometheus_service: str = "llmd-kube-prometheus-stack-prometheus"
    grafana_service: str = "llmd-grafana"
    keda_namespace: str = "keda"


class LlmDPlatformBootstrapRequest(BaseModel):
    context: str
    llmd_repo_path: str
    namespace: str = "llm-d-lab"
    release_name: str = "llm-d-lab"
    monitoring_namespace: str = "llm-d-monitoring"
    prometheus_service: str = "llmd-kube-prometheus-stack-prometheus"
    grafana_service: str = "llmd-grafana"
    keda_namespace: str = "keda"
    mode: str = "dedicated"
    grafana_admin_password: str | None = None
    confirm_cluster_changes: bool = False


class LlmDPlatformPlan(BaseModel):
    mode: str
    commands: list[list[str]]
    values: str
    dashboards: list[str]
    cluster_scoped_changes: list[str]


class LlmDPlatformResult(BaseModel):
    status: str
    log_path: str | None = None
    message: str
    plan: LlmDPlatformPlan


class LlmDPlatformStatus(BaseModel):
    configured: bool
    mode: str | None = None
    owned: bool = False
    context: str | None = None
    monitoring_namespace: str | None = None
    prometheus_service_name: str | None = None
    grafana_service_name: str | None = None
    keda_namespace: str | None = None
    preflight: dict[str, Any] | None = None


class LlmDGrafanaStatus(BaseModel):
    experiment_id: int
    status: str
    endpoint_url: str
    healthy: bool
    dashboards: dict[str, str] = Field(default_factory=dict)


class LlmDAutoscalingRequest(BaseModel):
    min_replicas: int = Field(default=1, ge=1, le=20)
    max_replicas: int = Field(default=3, ge=1, le=50)
    queue_threshold: int = Field(default=1, ge=1, le=1000)
    running_request_threshold: int = Field(default=4, ge=1, le=1000)
    polling_interval: int = Field(default=15, ge=5, le=300)
    cooldown_period: int = Field(default=300, ge=60, le=3600)
    scale_down_stabilization: int = Field(default=300, ge=0, le=3600)
    prometheus_address: str | None = None
    prometheus_trigger_authentication: str | None = None


class LlmDAutoscalingPlan(BaseModel):
    context: str
    namespace: str
    target_deployment: str
    manifest: str
    commands: list[list[str]]


class LlmDAutoscalingResult(BaseModel):
    status: str
    log_path: str
    message: str
    plan: LlmDAutoscalingPlan


class LlmDAutoscalingObservation(BaseModel):
    captured_at: str
    queue_depth: float | None = None
    running_requests: float | None = None
    desired_replicas: int | None = None
    ready_replicas: int = 0
    hpa_desired_replicas: int | None = None
    hpa_current_replicas: int | None = None
    scaled_object_ready: str
    pending_pods: list[str] = Field(default_factory=list)
    node_count: int = 0
    policy: dict[str, int]
