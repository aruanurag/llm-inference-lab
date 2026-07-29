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
  kind: "cpu-instance" | "llm-d-cluster" | string;
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
