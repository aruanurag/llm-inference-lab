import type { BenchmarkRecord, DeployModelOption, EndpointStatus, ExperimentRecord, InstanceRecord, Option, Profile, PromptSet, SshKeyRecord } from "./types";

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
  createExperiment: (payload: { name: string; description: string }) =>
    request<ExperimentRecord>("/api/experiments", { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  exportExperiment: (experimentId: number) => request<Record<string, unknown>>(`/api/experiments/${experimentId}/export`),
  deleteExperimentInfra: (experimentId: number) =>
    request<Record<string, unknown>>(`/api/experiments/${experimentId}/delete-infra`, { method: "POST" }),
  endpointHealth: (experimentId: number) => request<EndpointStatus>(`/api/experiments/${experimentId}/endpoint/health`),
  startEndpoint: (experimentId: number) => request<EndpointStatus>(`/api/experiments/${experimentId}/endpoint/start`, { method: "POST" }),
  stopEndpoint: (experimentId: number) => request<EndpointStatus>(`/api/experiments/${experimentId}/endpoint/stop`, { method: "POST" }),
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
