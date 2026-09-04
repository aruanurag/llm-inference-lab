export type Profile = {
  name: string;
  region?: string | null;
  tenancy?: string | null;
  user?: string | null;
};

export type Option = {
  id: string;
  name: string;
  extra: Record<string, unknown>;
};

export type SshKeyRecord = {
  id: number;
  name: string;
  created_at: string;
};

export type ExperimentRecord = {
  id: number;
  name: string;
  description: string;
  kind: "cpu-instance" | "llm-d-cluster" | "llm-d-autoscaling" | string;
  source_experiment_id?: number | null;
  status: string;
  created_at: string;
  updated_at: string;
};

export type KubernetesContext = { name: string };

export type ClusterValidation = {
  context: string;
  namespace: string;
  kubectl_version?: string | null;
  helm_version?: string | null;
  ready_nodes: number;
  total_nodes: number;
  cpu_cores: number;
  memory_kib: number;
  architectures: string[];
  warnings: string[];
};

export type LlmDCheckout = {
  path: string;
  revision: string;
  status: "cloned" | "existing" | string;
};

export type LlmDPlan = {
  context: string;
  namespace: string;
  release_name: string;
  overlay_path: string;
  overlay: string;
  monitoring_path?: string | null;
  monitoring_manifest?: string | null;
  commands: string[][];
};

export type LlmDEndpointStatus = {
  experiment_id: number;
  status: "stopped" | "starting" | "running" | string;
  endpoint_url: string;
  healthy: boolean;
};

export type LlmDBenchmarkResult = {
  endpoint_url: string;
  raw_path: string;
  summary_path: string;
  summary: Record<string, any>;
};

export type LlmDBenchmarkRecord = {
  id: number;
  experiment_id: number;
  name: string;
  raw_path: string;
  summary_path: string;
  created_at: string;
  summary: Record<string, any>;
};

export type LlmDPlatformPreflight = {
  context: string;
  namespace: string;
  monitoring_namespace: string;
  keda_namespace: string;
  service_monitor_crd: boolean;
  scaled_object_crd: boolean;
  prometheus_service: boolean;
  grafana_service: boolean;
  keda_ready: boolean;
  epp_service: boolean;
  epp_service_monitor: boolean;
  model_deployment: boolean;
  node_count: number;
  conflicting_releases: { name: string; namespace: string; chart: string }[];
  competing_hpas: string[];
  warnings: string[];
};

export type LlmDPlatformPlan = {
  mode: string;
  commands: string[][];
  values: string;
  dashboards: string[];
  cluster_scoped_changes: string[];
};

export type LlmDPlatformStatus = {
  configured: boolean;
  mode?: string | null;
  owned: boolean;
  context?: string | null;
  monitoring_namespace?: string | null;
  prometheus_service_name?: string | null;
  grafana_service_name?: string | null;
  keda_namespace?: string | null;
  preflight?: LlmDPlatformPreflight | null;
};

export type LlmDGrafanaStatus = {
  experiment_id: number;
  status: string;
  endpoint_url: string;
  healthy: boolean;
  dashboards: Record<string, string>;
};

export type LlmDAutoscalingPlan = {
  context: string;
  namespace: string;
  target_deployment: string;
  manifest: string;
  commands: string[][];
};

export type LlmDAutoscalingObservation = {
  captured_at: string;
  queue_depth?: number | null;
  running_requests?: number | null;
  desired_replicas?: number | null;
  ready_replicas: number;
  hpa_desired_replicas?: number | null;
  hpa_current_replicas?: number | null;
  scaled_object_ready: string;
  pending_pods: string[];
  node_count: number;
  policy: Record<string, number>;
};

/**
 * Lab 5 accepts only these stable, user-facing model aliases.  The router
 * resolves an alias to either the source Lab 4 LLM-D endpoint or OpenRouter;
 * callers never send an arbitrary upstream model or URL.
 */
export type LlmDRoutingAlias = "private" | "fast" | "coding" | "reasoning";

export type LlmDRoutingDestinationType = "llm-d" | "openrouter";

/** A route exposed by the router plan/status response. */
export type LlmDRoutingAliasRoute = {
  alias: LlmDRoutingAlias;
  destination: LlmDRoutingDestinationType;
  model: string;
  /** External aliases are capped at 512 tokens; local aliases are uncapped. */
  max_tokens: number | null;
};

/** Preflight needs the same non-secret configuration used to render a plan. */
export type LlmDRoutingPreflightRequest = LlmDRoutingConfiguration;

export type LlmDRoutingPreflight = {
  source_experiment_id: number;
  context: string;
  namespace: string;
  source_experiment_ready: boolean;
  epp_service: string | null;
  epp_ready: boolean;
  prometheus_available: boolean;
  grafana_available: boolean;
  service_monitor_crd: boolean;
  egress_ready: boolean | null;
  conflicting_releases: { name: string; namespace: string; chart: string }[];
  warnings: string[];
};

/** Shared, non-secret routing configuration used for plan, status, and UI state. */
export type LlmDRoutingConfiguration = {
  source_experiment_id: number;
  context: string;
  namespace: string;
  release_name: string;
  model: string;
  coding_model: string;
  reasoning_model: string;
  router_name?: string;
};

export type LlmDRoutingPlanRequest = LlmDRoutingConfiguration;

/**
 * The OpenRouter key is write-only: it is accepted only while deploying and
 * must not appear in plan, status, result, or benchmark types.
 */
export type LlmDRoutingDeployRequest = LlmDRoutingConfiguration & {
  openrouter_api_key: string;
  confirm: boolean;
};

export type LlmDRoutingPlan = {
  source_experiment_id: number;
  context: string;
  namespace: string;
  router_name: string;
  service_name: string;
  manifests: string;
  commands: string[][];
  aliases: LlmDRoutingAliasRoute[];
  warnings: string[];
};

export type LlmDRoutingDeployResult = {
  status: string;
  log_path?: string | null;
  message: string;
  plan: LlmDRoutingPlan;
};

/** Deliberately sanitized: this response contains no API key, endpoint host, or raw provider config. */
export type LlmDRoutingStatus = {
  experiment_id: number;
  configured: boolean;
  owned: boolean;
  ready: boolean;
  source_experiment_id?: number | null;
  context?: string | null;
  namespace?: string | null;
  router_name?: string | null;
  service_name?: string | null;
  aliases: LlmDRoutingAliasRoute[];
  message?: string | null;
};

export type LlmDRoutingEndpointStatus = {
  experiment_id: number;
  status: "stopped" | "starting" | "running" | "failed" | string;
  endpoint_url: string;
  healthy: boolean;
  available_models: LlmDRoutingAlias[];
  message?: string | null;
};

export type LlmDRoutingInferenceRequest = {
  model: LlmDRoutingAlias;
  prompt?: string;
  messages?: Array<{
    role: "system" | "user" | "assistant";
    content: string;
  }>;
  max_tokens: number;
  temperature: number;
  stream?: boolean;
};

export type LlmDRoutingInferenceResult = {
  model: LlmDRoutingAlias;
  destination: LlmDRoutingDestinationType;
  response: Record<string, unknown>;
  usage?: Record<string, number> | null;
};

export type LlmDRoutingBenchmarkRequest = {
  name: string;
  model: LlmDRoutingAlias;
  prompt?: string;
  prompt_set_id?: number | null;
  concurrency: number;
  requests: number;
  max_tokens: number;
  temperature: number;
};

export type LlmDRoutingBenchmarkResult = {
  endpoint_url: string;
  raw_path: string;
  summary_path: string;
  summary: Record<string, unknown>;
  model: LlmDRoutingAlias;
  destination: LlmDRoutingDestinationType;
};

export type LlmDRoutingBenchmarkRecord = {
  id: number;
  experiment_id: number;
  name: string;
  model: LlmDRoutingAlias;
  destination: LlmDRoutingDestinationType;
  raw_path: string;
  summary_path: string;
  created_at: string;
  summary: Record<string, unknown>;
};

export type LlmDRoutingUninstallResult = {
  status: string;
  log_path?: string | null;
  message: string;
};

export type InstanceRecord = {
  id: number;
  experiment_id?: number | null;
  oci_instance_id: string;
  display_name: string;
  lifecycle_state?: string | null;
  shape: string;
  availability_domain: string;
  compartment_id: string;
  subnet_id: string;
  image_id: string;
  ssh_key_id: number;
  ssh_user: string;
  public_ip?: string | null;
  private_ip?: string | null;
  inference_engine?: string | null;
  deployed_model_id?: string | null;
  deployed_model_name?: string | null;
  deployed_model_source?: string | null;
  created_at: string;
  updated_at: string;
};

export type DeployModelOption = {
  id: string;
  name: string;
  size_label: string;
  quantization: string;
  url: string;
  filename: string;
  recommended_ocpus: number;
  recommended_memory_gbs: number;
  description: string;
  engine: string;
};

export type PromptSet = {
  id: number;
  name: string;
  description: string;
  path: string;
  prompt_count: number;
  created_at: string;
};

export type BenchmarkRecord = {
  id: number;
  instance_id: number;
  name: string;
  summary_path: string;
  raw_path: string;
  created_at: string;
  summary: Record<string, any>;
};

export type EndpointStatus = {
  experiment_id: number;
  status: "stopped" | "starting" | "running" | "failed" | string;
  local_port?: number | null;
  model_name: string;
  proxy_url: string;
  started_at?: string | null;
  stopped_at?: string | null;
  updated_at: string;
  error?: string | null;
  healthy?: boolean;
  analytics?: Record<string, any>;
};
