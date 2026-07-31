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
