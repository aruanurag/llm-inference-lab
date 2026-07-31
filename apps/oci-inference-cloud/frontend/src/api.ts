import type { BenchmarkRecord, ClusterValidation, DeployModelOption, EndpointStatus, ExperimentRecord, InstanceRecord, KubernetesContext, LlmDAutoscalingObservation, LlmDAutoscalingPlan, LlmDBenchmarkRecord, LlmDBenchmarkResult, LlmDCheckout, LlmDEndpointStatus, LlmDGrafanaStatus, LlmDPlan, LlmDPlatformPlan, LlmDPlatformPreflight, LlmDPlatformStatus, Option, Profile, PromptSet, SshKeyRecord } from "./types";

const jsonHeaders = { "Content-Type": "application/json" };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // Keep the HTTP status text.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export const api = {
  profiles: () => request<Profile[]>("/api/profiles"),
  experiments: () => request<ExperimentRecord[]>("/api/experiments"),
  createExperiment: (payload: { name: string; description: string; kind?: string }) =>
    request<ExperimentRecord>("/api/experiments", { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  exportExperiment: (experimentId: number) => request<Record<string, unknown>>(`/api/experiments/${experimentId}/export`),
  deleteExperimentInfra: (experimentId: number) =>
    request<Record<string, unknown>>(`/api/experiments/${experimentId}/delete-infra`, { method: "POST" }),
  endpointHealth: (experimentId: number) => request<EndpointStatus>(`/api/experiments/${experimentId}/endpoint/health`),
  startEndpoint: (experimentId: number) => request<EndpointStatus>(`/api/experiments/${experimentId}/endpoint/start`, { method: "POST" }),
  stopEndpoint: (experimentId: number) => request<EndpointStatus>(`/api/experiments/${experimentId}/endpoint/stop`, { method: "POST" }),
  kubernetesContexts: () => request<KubernetesContext[]>("/api/kubernetes/contexts"),
  validateKubernetes: (payload: { context: string; namespace: string }) =>
    request<ClusterValidation>("/api/kubernetes/validate", { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  prepareLlmDCheckout: (path?: string) =>
    request<LlmDCheckout>("/api/llm-d/checkout", { method: "POST", headers: jsonHeaders, body: JSON.stringify({ path: path || null }) }),
  planLlmD: (experimentId: number, payload: Record<string, unknown>) =>
    request<LlmDPlan>(`/api/experiments/${experimentId}/llm-d/plan`, { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  deployLlmD: (experimentId: number, payload: Record<string, unknown>) =>
    request<{ status: string; log_path: string; message: string; plan: LlmDPlan }>(`/api/experiments/${experimentId}/llm-d/deploy`, { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  llmdEndpoint: (experimentId: number) => request<LlmDEndpointStatus>(`/api/experiments/${experimentId}/llm-d/endpoint`),
  startLlmDEndpoint: (experimentId: number) => request<LlmDEndpointStatus>(`/api/experiments/${experimentId}/llm-d/endpoint/start`, { method: "POST" }),
  stopLlmDEndpoint: (experimentId: number) => request<LlmDEndpointStatus>(`/api/experiments/${experimentId}/llm-d/endpoint/stop`, { method: "POST" }),
  inferLlmD: (experimentId: number, payload: { prompt: string; max_tokens: number; temperature: number }) =>
    request<Record<string, any>>(`/api/experiments/${experimentId}/llm-d/inference`, { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  benchmarkLlmD: (experimentId: number, payload: Record<string, unknown>) =>
    request<LlmDBenchmarkResult>(`/api/experiments/${experimentId}/llm-d/benchmark`, { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  llmdBenchmarks: (experimentId: number) => request<LlmDBenchmarkRecord[]>(`/api/experiments/${experimentId}/llm-d/benchmarks`),
  llmdPlatformPreflight: (experimentId: number, payload: { context: string; namespace: string; release_name: string; monitoring_namespace: string; prometheus_service: string; grafana_service: string; keda_namespace: string }) =>
    request<LlmDPlatformPreflight>(`/api/experiments/${experimentId}/llm-d/autoscaling/preflight`, { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  llmdPlatformStatus: (experimentId: number) => request<LlmDPlatformStatus>(`/api/experiments/${experimentId}/llm-d/autoscaling/platform`),
  planLlmDPlatform: (experimentId: number, payload: Record<string, unknown>) =>
    request<LlmDPlatformPlan>(`/api/experiments/${experimentId}/llm-d/autoscaling/platform/plan`, { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  bootstrapLlmDPlatform: (experimentId: number, payload: Record<string, unknown>) =>
    request<{ status: string; log_path?: string; message: string; plan: LlmDPlatformPlan }>(`/api/experiments/${experimentId}/llm-d/autoscaling/platform/bootstrap`, { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  uninstallLlmDPlatform: (experimentId: number, payload: Record<string, unknown>) =>
    request<{ status: string; log_path: string; message: string }>(`/api/experiments/${experimentId}/llm-d/autoscaling/platform/uninstall`, { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  llmdGrafana: (experimentId: number) => request<LlmDGrafanaStatus>(`/api/experiments/${experimentId}/llm-d/grafana`),
  startLlmDGrafana: (experimentId: number) => request<LlmDGrafanaStatus>(`/api/experiments/${experimentId}/llm-d/grafana/start`, { method: "POST" }),
  stopLlmDGrafana: (experimentId: number) => request<LlmDGrafanaStatus>(`/api/experiments/${experimentId}/llm-d/grafana/stop`, { method: "POST" }),
  planLlmDAutoscaling: (experimentId: number, payload: Record<string, unknown>) =>
    request<LlmDAutoscalingPlan>(`/api/experiments/${experimentId}/llm-d/autoscaling/plan`, { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  deployLlmDAutoscaling: (experimentId: number, payload: Record<string, unknown>) =>
    request<{ status: string; log_path: string; message: string; plan: LlmDAutoscalingPlan }>(`/api/experiments/${experimentId}/llm-d/autoscaling/deploy`, { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  llmdAutoscalingObservation: (experimentId: number) => request<LlmDAutoscalingObservation>(`/api/experiments/${experimentId}/llm-d/autoscaling/observation`),
  context: (payload: { profile: string; region?: string | null; compartment_id?: string | null }) =>
    request("/api/context", { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  compartments: () => request<Option[]>("/api/compartments"),
  availabilityDomains: () => request<Option[]>("/api/availability-domains"),
  shapes: (compartmentId: string, availabilityDomain?: string, includeGpuShapes = false) => {
    const params = new URLSearchParams({ compartment_id: compartmentId });
    if (availabilityDomain) params.set("availability_domain", availabilityDomain);
    if (includeGpuShapes) params.set("include_gpu_shapes", "true");
    return request<Option[]>(`/api/shapes?${params}`);
  },
  vcns: (compartmentId: string) => request<Option[]>(`/api/vcns?${new URLSearchParams({ compartment_id: compartmentId })}`),
  subnets: (compartmentId: string, vcnId: string) => request<Option[]>(`/api/subnets?${new URLSearchParams({ compartment_id: compartmentId, vcn_id: vcnId })}`),
  images: (compartmentId: string, shape: string) => request<Option[]>(`/api/images?${new URLSearchParams({ compartment_id: compartmentId, shape })}`),
  sshKeys: () => request<SshKeyRecord[]>("/api/ssh-keys"),
  createSshKey: (name: string) => request<SshKeyRecord>("/api/ssh-keys", { method: "POST", headers: jsonHeaders, body: JSON.stringify({ name }) }),
  instances: () => request<InstanceRecord[]>("/api/instances"),
  createInstance: (payload: Record<string, unknown>) => request<InstanceRecord>("/api/instances", { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  deployModels: () => request<DeployModelOption[]>("/api/deploy/models"),
  deploy: (instanceId: number, payload: Record<string, unknown>) =>
    request<{ status: string; message: string; log_path: string }>(`/api/instances/${instanceId}/deploy`, { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  prompts: () => request<PromptSet[]>("/api/prompts"),
  uploadPrompt: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<PromptSet>("/api/prompts", { method: "POST", body: form });
  },
  benchmarks: () => request<BenchmarkRecord[]>("/api/benchmarks"),
  runBenchmark: (payload: Record<string, unknown>) => request<BenchmarkRecord>("/api/benchmarks", { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) })
};
