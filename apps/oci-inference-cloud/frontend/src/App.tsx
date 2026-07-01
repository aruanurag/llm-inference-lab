import { useEffect, useMemo, useState } from "react";
import { Activity, AlertCircle, CheckCircle2, Circle, Cloud, Info, KeyRound, Loader2, Play, RefreshCcw, Rocket, Server, Upload } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import { api } from "./api";
import type { BenchmarkRecord, DeployModelOption, EndpointStatus, ExperimentRecord, InstanceRecord, Option, Profile, PromptSet, SshKeyRecord } from "./types";

type Status = { kind: "idle" | "loading" | "error" | "ok"; message: string };
type ActiveAction = "idle" | "load" | "provision" | "deploy" | "benchmark" | "endpoint";
type View = "setup" | "benchmarks" | "hackathon";
type BenchmarkPreset = {
  id: string;
  name: string;
  focus: "latency" | "prefill" | "decode" | "throughput" | "concurrency";
  primaryMetric: string;
  description: string;
  concurrency: number;
  requests: number;
  maxTokens: number;
  benchmarkName: string;
  promptHint: string;
  comparisonGroup: string;
};

const emptyStatus: Status = { kind: "idle", message: "Ready." };

const BENCHMARK_PRESETS: BenchmarkPreset[] = [
  {
    id: "throughput-comparison",
    name: "Throughput comparison",
    focus: "throughput",
    primaryMetric: "Approx tokens/sec and output chars/sec",
    description: "Run this unchanged across different models, shapes, or deploy settings. The comparison view highlights relative throughput.",
    concurrency: 8,
    requests: 32,
    maxTokens: 256,
    benchmarkName: "throughput-comparison",
    promptHint: "Throughput comparison prompts",
    comparisonGroup: "model-shape-throughput",
  },
  {
    id: "latency",
    name: "Latency check",
    focus: "latency",
    primaryMetric: "Latency p95 and TTFT p95",
    description: "Single-request style run for clean latency, TTFT, and ITL measurements. Good first benchmark after deployment.",
    concurrency: 1,
    requests: 8,
    maxTokens: 128,
    benchmarkName: "latency-check",
    promptHint: "Latency smoke prompts",
    comparisonGroup: "latency-check",
  },
  {
    id: "prefill",
    name: "Long prompt prefill",
    focus: "prefill",
    primaryMetric: "TTFT p95",
    description: "Uses longer prompts with short-to-medium output to expose prompt processing cost and TTFT changes.",
    concurrency: 1,
    requests: 6,
    maxTokens: 128,
    benchmarkName: "long-prefill",
    promptHint: "Long context prefill prompts",
    comparisonGroup: "prefill-pressure",
  },
  {
    id: "decode",
    name: "Long decode throughput",
    focus: "decode",
    primaryMetric: "Approx tokens/sec",
    description: "Requests longer completions to stress decode speed and output throughput.",
    concurrency: 1,
    requests: 4,
    maxTokens: 512,
    benchmarkName: "long-decode",
    promptHint: "Long decode prompts",
    comparisonGroup: "decode-throughput",
  },
  {
    id: "concurrency",
    name: "Concurrency throughput",
    focus: "concurrency",
    primaryMetric: "Requests/sec, p95 latency, and approx tokens/sec",
    description: "Runs a mixed workload with concurrency to show batching, queueing, p95 latency, and throughput tradeoffs.",
    concurrency: 4,
    requests: 16,
    maxTokens: 256,
    benchmarkName: "throughput-concurrency-4",
    promptHint: "Concurrency mixed workload",
    comparisonGroup: "concurrency-scaling",
  },
];

const LANE_OPTIONS = [
  { id: "primary", name: "Primary run", description: "Use this for the first model, shape, or deploy setting in a comparison." },
  { id: "comparison", name: "Comparison run", description: "Use this for the second model, shape, or deploy setting." },
  { id: "custom", name: "Custom", description: "Use when the run needs its own label." },
];

type ShapeFamily = "cpu" | "gpu" | "all";

function formatSeconds(value: unknown) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "n/a";
  if (value < 1) return `${(value * 1000).toFixed(1)} ms`;
  return `${value.toFixed(2)} s`;
}

function formatNumber(value: unknown) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "n/a";
  return value.toFixed(2);
}

function metric(summary: Record<string, any>, path: string): number | null {
  return path.split(".").reduce<any>((current, key) => current?.[key], summary) ?? null;
}

function numberFromExtra(extra: Record<string, unknown>, path: string): number | null {
  const value = path.split(".").reduce<unknown>((current, key) => {
    if (!current || typeof current !== "object") return undefined;
    return (current as Record<string, unknown>)[key];
  }, extra);
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function flexDefaults(option?: Option) {
  const minOcpus = option ? numberFromExtra(option.extra, "ocpu-options.min") : null;
  const defaultMemoryPerOcpu = option ? numberFromExtra(option.extra, "memory-options.default-per-ocpu-in-gbs") : null;
  const minMemory = option ? numberFromExtra(option.extra, "memory-options.min-in-gbs") : null;
  const defaultOcpus = Math.max(minOcpus || 0, 4);
  const defaultMemory = Math.max(minMemory || 0, defaultOcpus * (defaultMemoryPerOcpu || 8), 32);
  return { ocpus: String(defaultOcpus), memoryGbs: String(defaultMemory) };
}

function shapeClass(shapeName?: string | null) {
  const upper = (shapeName || "").toUpperCase();
  if (upper.includes("GPU")) return "gpu";
  if (upper.includes("HPC") || upper.includes("OPTIMIZED")) return "hpc";
  return "cpu";
}

function optionShapeClass(option: Option) {
  const value = option.extra?.llm_inference_shape_class;
  if (value === "accelerator") return "gpu";
  return typeof value === "string" ? value : shapeClass(option.id);
}

function filterShapesForFamily(options: Option[], family: ShapeFamily) {
  if (family === "gpu") return options.filter((item) => optionShapeClass(item) === "gpu");
  if (family === "cpu") return options.filter((item) => optionShapeClass(item) !== "gpu");
  return options;
}

function laneLabel(value?: string | null) {
  if (value === "baseline-cpu") return "Primary run";
  if (value === "oci-accelerator") return "Comparison run";
  return LANE_OPTIONS.find((item) => item.id === value)?.name || value || "Unlabeled";
}

function cleanBenchmarkName(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "benchmark";
}

export function App() {
  const [status, setStatus] = useState<Status>(emptyStatus);
  const [activeAction, setActiveAction] = useState<ActiveAction>("idle");
  const [deployedInstanceIds, setDeployedInstanceIds] = useState<number[]>([]);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [experiments, setExperiments] = useState<ExperimentRecord[]>([]);
  const [compartments, setCompartments] = useState<Option[]>([]);
  const [availabilityDomains, setAvailabilityDomains] = useState<Option[]>([]);
  const [shapes, setShapes] = useState<Option[]>([]);
  const [vcns, setVcns] = useState<Option[]>([]);
  const [subnets, setSubnets] = useState<Option[]>([]);
  const [images, setImages] = useState<Option[]>([]);
  const [sshKeys, setSshKeys] = useState<SshKeyRecord[]>([]);
  const [instances, setInstances] = useState<InstanceRecord[]>([]);
  const [deployModels, setDeployModels] = useState<DeployModelOption[]>([]);
  const [promptSets, setPromptSets] = useState<PromptSet[]>([]);
  const [benchmarks, setBenchmarks] = useState<BenchmarkRecord[]>([]);
  const [endpointStatus, setEndpointStatus] = useState<EndpointStatus | null>(null);

  const [profile, setProfile] = useState("");
  const [region, setRegion] = useState("");
  const [compartmentId, setCompartmentId] = useState("");
  const [availabilityDomain, setAvailabilityDomain] = useState("");
  const [shapeFamily, setShapeFamily] = useState<ShapeFamily>("cpu");
  const [shape, setShape] = useState("");
  const [vcnId, setVcnId] = useState("");
  const [subnetId, setSubnetId] = useState("");
  const [imageId, setImageId] = useState("");
  const [sshKeyId, setSshKeyId] = useState("");
  const [newKeyName, setNewKeyName] = useState(`oci-inference-${Date.now()}`);
  const [displayName, setDisplayName] = useState("oci-inference-cpu");
  const [sshUser, setSshUser] = useState("opc");
  const [ocpus, setOcpus] = useState("");
  const [memoryGbs, setMemoryGbs] = useState("");
  const [selectedInstanceId, setSelectedInstanceId] = useState("");
  const [selectedDeployModelId, setSelectedDeployModelId] = useState("qwen2.5-1.5b-q4_k_m");
  const [customModelName, setCustomModelName] = useState("");
  const [customModelUrl, setCustomModelUrl] = useState("");
  const [showDeployAdvanced, setShowDeployAdvanced] = useState(false);
  const [buildNative, setBuildNative] = useState(false);
  const [disableVnni, setDisableVnni] = useState(true);
  const [deployCtxSize, setDeployCtxSize] = useState(4096);
  const [deployParallel, setDeployParallel] = useState(4);
  const [deployBatchSize, setDeployBatchSize] = useState(512);
  const [deployUbatchSize, setDeployUbatchSize] = useState(128);
  const [selectedPromptSetId, setSelectedPromptSetId] = useState("");
  const [benchmarkName, setBenchmarkName] = useState("throughput-comparison-primary");
  const [experimentLane, setExperimentLane] = useState("primary");
  const [concurrency, setConcurrency] = useState(1);
  const [requests, setRequests] = useState(4);
  const [maxTokens, setMaxTokens] = useState(128);
  const [selectedPresetId, setSelectedPresetId] = useState("throughput-comparison");
  const [view, setView] = useState<View>("setup");
  const [experimentName, setExperimentName] = useState(`Inference throughput research ${new Date().toLocaleDateString()}`);
  const [experimentDescription, setExperimentDescription] = useState("Compare models, shapes, and deploy settings using repeatable benchmark presets.");
  const [selectedExperimentId, setSelectedExperimentId] = useState("");

  const activeExperiment = useMemo(
    () => experiments.find((item) => String(item.id) === selectedExperimentId),
    [experiments, selectedExperimentId]
  );
  const experimentInstances = useMemo(
    () => selectedExperimentId ? instances.filter((item) => String(item.experiment_id || "") === selectedExperimentId) : instances,
    [instances, selectedExperimentId]
  );
  const experimentBenchmarks = useMemo(
    () => selectedExperimentId ? benchmarks.filter((item) => String(item.summary.experiment_id || "") === selectedExperimentId || experimentInstances.some((instance) => instance.id === item.instance_id)) : benchmarks,
    [benchmarks, experimentInstances, selectedExperimentId]
  );
  const selectedInstance = useMemo(
    () => experimentInstances.find((item) => String(item.id) === selectedInstanceId) || experimentInstances[0],
    [experimentInstances, selectedInstanceId]
  );
  const selectedPromptSet = useMemo(
    () => promptSets.find((item) => String(item.id) === selectedPromptSetId),
    [promptSets, selectedPromptSetId]
  );
  const selectedPreset = useMemo(
    () => BENCHMARK_PRESETS.find((item) => item.id === selectedPresetId),
    [selectedPresetId]
  );
  const selectedDeployModel = useMemo(
    () => deployModels.find((item) => item.id === selectedDeployModelId),
    [deployModels, selectedDeployModelId]
  );
  const selectedLane = useMemo(
    () => LANE_OPTIONS.find((item) => item.id === experimentLane),
    [experimentLane]
  );
  const selectedShapeClass = shapeClass(selectedInstance?.shape || shape);
  const isBusy = activeAction !== "idle";
  const hasOciContext = Boolean(compartmentId && availabilityDomains.length && vcns.length);
  const hasExperiment = Boolean(activeExperiment);
  const hasProvisionedInstance = experimentInstances.length > 0;
  const selectedInstanceReady = Boolean(selectedInstance && selectedInstance.lifecycle_state === "RUNNING" && (selectedInstance.public_ip || selectedInstance.private_ip));
  const hasDeployed = Boolean(
    activeExperiment?.status === "deployed" ||
    activeExperiment?.status === "benchmarked" ||
    (selectedInstance && deployedInstanceIds.includes(selectedInstance.id))
  );
  const hasBenchmarks = experimentBenchmarks.length > 0;
  const endpointRunning = endpointStatus?.status === "running" && endpointStatus?.healthy;
  const endpointUrl = endpointStatus?.proxy_url || (activeExperiment ? `http://127.0.0.1:8090/api/experiments/${activeExperiment.id}/endpoint/v1` : "");
  const endpointAnalytics = endpointStatus?.analytics || {};
  const workflowSteps = [
    {
      title: "Load OCI",
      detail: hasExperiment ? activeExperiment?.name || "Experiment selected" : "Create or select experiment",
      state: hasExperiment ? "done" : "todo"
    },
    {
      title: "Setup",
      detail: hasOciContext ? `${compartments.find((item) => item.id === compartmentId)?.name || "Compartment"} loaded` : "Load OCI and choose infra",
      state: activeAction === "load" ? "active" : hasOciContext ? "done" : hasExperiment ? "ready" : "todo"
    },
    {
      title: "Provision",
      detail: hasProvisionedInstance ? `${experimentInstances[0].display_name} · ${experimentInstances[0].lifecycle_state || "unknown"}` : "Create experiment instance",
      state: activeAction === "provision" ? "active" : hasProvisionedInstance ? "done" : hasOciContext ? "ready" : "todo"
    },
    {
      title: "Deploy",
      detail: hasDeployed ? "llama-server deployed" : selectedInstanceReady ? "Instance ready for SSH deploy" : "Wait for RUNNING instance with IP",
      state: activeAction === "deploy" ? "active" : hasDeployed ? "done" : selectedInstanceReady ? "ready" : "todo"
    },
    {
      title: "Benchmark",
      detail: hasBenchmarks ? `${experimentBenchmarks.length} benchmark run${experimentBenchmarks.length === 1 ? "" : "s"}` : "Run prompts through SSH tunnel",
      state: activeAction === "benchmark" ? "active" : hasBenchmarks ? "done" : hasDeployed ? "ready" : "todo"
    },
    {
      title: "Endpoint",
      detail: endpointRunning ? "Participant endpoint running" : "Start local proxy for sample apps",
      state: activeAction === "endpoint" ? "active" : endpointRunning ? "done" : hasDeployed ? "ready" : "todo"
    }
  ];

  async function loadInitial() {
    setActiveAction("load");
    setStatus({ kind: "loading", message: "Loading local app state." });
    try {
      const [profileList, experimentList, keyList, instanceList, promptList, benchmarkList, deployModelList] = await Promise.all([
        api.profiles(),
        api.experiments(),
        api.sshKeys(),
        api.instances(),
        api.prompts(),
        api.benchmarks(),
        api.deployModels()
      ]);
      setProfiles(profileList);
      setExperiments(experimentList);
      setSshKeys(keyList);
      setInstances(instanceList);
      setPromptSets(promptList);
      setBenchmarks(benchmarkList);
      setDeployModels(deployModelList);
      if (!profile && profileList[0]) {
        setProfile(profileList[0].name);
        setRegion(profileList[0].region || "");
      }
      if (!sshKeyId && keyList[0]) setSshKeyId(String(keyList[0].id));
      if (!selectedInstanceId && instanceList[0]) setSelectedInstanceId(String(instanceList[0].id));
      if (!selectedPromptSetId) {
        const presetPrompt = promptList.find((item) => item.name === BENCHMARK_PRESETS[0].promptHint);
        setSelectedPromptSetId(String((presetPrompt || promptList[0])?.id || ""));
      }
      if (!selectedDeployModelId && deployModelList[0]) setSelectedDeployModelId(deployModelList[0].id);
      setStatus({ kind: "ok", message: "State loaded." });
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setActiveAction("idle");
    }
  }

  async function createExperiment() {
    setActiveAction("load");
    setStatus({ kind: "loading", message: "Creating experiment." });
    try {
      const experiment = await api.createExperiment({ name: experimentName, description: experimentDescription });
      const experimentList = await api.experiments();
      setExperiments(experimentList);
      setSelectedExperimentId(String(experiment.id));
      setView("setup");
      setStatus({ kind: "ok", message: `Experiment created: ${experiment.name}. Continue with OCI setup.` });
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setActiveAction("idle");
    }
  }

  async function exportActiveExperiment() {
    if (!activeExperiment) return;
    setStatus({ kind: "loading", message: "Preparing experiment export." });
    try {
      const payload = await api.exportExperiment(activeExperiment.id);
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${activeExperiment.name.toLowerCase().replace(/[^a-z0-9]+/g, "-") || "experiment"}-export.json`;
      link.click();
      URL.revokeObjectURL(url);
      setStatus({ kind: "ok", message: "Experiment export downloaded." });
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    }
  }

  async function deleteInfra() {
    if (!activeExperiment) return;
    setActiveAction("provision");
    setStatus({ kind: "loading", message: "Terminating OCI infrastructure for this experiment." });
    try {
      await api.deleteExperimentInfra(activeExperiment.id);
      const [experimentList, instanceList] = await Promise.all([api.experiments(), api.instances()]);
      setExperiments(experimentList);
      setInstances(instanceList);
      setStatus({ kind: "ok", message: "Infra deletion requested. OCI instances are moving to TERMINATING." });
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setActiveAction("idle");
    }
  }

  useEffect(() => {
    loadInitial();
  }, []);

  useEffect(() => {
    if (!activeExperiment) return;
    if (activeExperiment.status === "deployed" || activeExperiment.status === "benchmarked") {
      setView("benchmarks");
    } else {
      setView("setup");
    }
  }, [activeExperiment?.id, activeExperiment?.status]);

  useEffect(() => {
    if (!activeExperiment) {
      setEndpointStatus(null);
      return;
    }
    refreshEndpoint(false);
  }, [activeExperiment?.id]);

  async function refreshEndpoint(showStatus = true) {
    if (!activeExperiment) return;
    if (showStatus) setStatus({ kind: "loading", message: "Refreshing endpoint status." });
    try {
      const result = await api.endpointHealth(activeExperiment.id);
      setEndpointStatus(result);
      if (showStatus) setStatus({ kind: "ok", message: "Endpoint status refreshed." });
    } catch (error) {
      if (showStatus) setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    }
  }

  async function startEndpoint() {
    if (!activeExperiment) return;
    setActiveAction("endpoint");
    setStatus({ kind: "loading", message: "Starting local endpoint proxy and SSH tunnel." });
    try {
      const result = await api.startEndpoint(activeExperiment.id);
      setEndpointStatus(result);
      setView("hackathon");
      setStatus({ kind: result.status === "running" ? "ok" : "error", message: result.status === "running" ? "Endpoint is running." : (result.error || "Endpoint failed to start.") });
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setActiveAction("idle");
    }
  }

  async function stopEndpoint() {
    if (!activeExperiment) return;
    setActiveAction("endpoint");
    setStatus({ kind: "loading", message: "Stopping local endpoint proxy tunnel." });
    try {
      const result = await api.stopEndpoint(activeExperiment.id);
      setEndpointStatus(result);
      setStatus({ kind: "ok", message: "Endpoint stopped." });
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setActiveAction("idle");
    }
  }

  async function copyText(text: string, label: string) {
    await navigator.clipboard.writeText(text);
    setStatus({ kind: "ok", message: `${label} copied.` });
  }

  async function applyContext() {
    setActiveAction("load");
    setStatus({ kind: "loading", message: "Applying OCI context and loading infrastructure." });
    try {
      await api.context({ profile, region, compartment_id: compartmentId || null });
      const compartmentList = await api.compartments();
      setCompartments(compartmentList);
      const activeCompartment = compartmentId || compartmentList[0]?.id || "";
      setCompartmentId(activeCompartment);
      const [adList, vcnList] = await Promise.all([
        api.availabilityDomains(),
        api.vcns(activeCompartment)
      ]);
      setAvailabilityDomains(adList);
      setVcns(vcnList);
      setAvailabilityDomain(adList[0]?.id || "");
      setVpcDefaults(vcnList);
      setStatus({ kind: "ok", message: "OCI context loaded." });
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setActiveAction("idle");
    }
  }

  function setVpcDefaults(vcnList: Option[]) {
    const nextVpc = vcnList[0]?.id || "";
    setVcnId(nextVpc);
  }

  async function changeCompartment(nextCompartmentId: string) {
    setCompartmentId(nextCompartmentId);
    setVcns([]);
    setVcnId("");
    setSubnets([]);
    setSubnetId("");
    setShapes([]);
    setShape("");
    setImages([]);
    setImageId("");
    if (!nextCompartmentId) return;

    setActiveAction("load");
    setStatus({ kind: "loading", message: "Loading VCNs and shapes for selected compartment." });
    try {
      await api.context({ profile, region, compartment_id: nextCompartmentId });
      const [vcnList, rawShapeList] = await Promise.all([
        api.vcns(nextCompartmentId),
        api.shapes(nextCompartmentId, availabilityDomain, shapeFamily !== "cpu")
      ]);
      const shapeList = filterShapesForFamily(rawShapeList, shapeFamily);
      const nextVpc = vcnList[0]?.id || "";
      const nextShape = shapeList[0]?.id || "";
      setVcns(vcnList);
      setVcnId(nextVpc);
      setShapes(shapeList);
      setShape(nextShape);
      if (nextShape.includes(".Flex") && (!ocpus || !memoryGbs)) {
        const defaults = flexDefaults(shapeList.find((item) => item.id === nextShape));
        if (!ocpus) setOcpus(defaults.ocpus);
        if (!memoryGbs) setMemoryGbs(defaults.memoryGbs);
      }

      const [subnetList, imageList] = await Promise.all([
        nextVpc ? api.subnets(nextCompartmentId, nextVpc) : Promise.resolve([]),
        nextShape ? api.images(nextCompartmentId, nextShape) : Promise.resolve([])
      ]);
      setSubnets(subnetList);
      setSubnetId(subnetList[0]?.id || "");
      setImages(imageList);
      setImageId(imageList[0]?.id || "");
      setStatus({ kind: "ok", message: "Compartment infrastructure loaded." });
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setActiveAction("idle");
    }
  }

  async function changeShapeFamily(nextFamily: ShapeFamily) {
    setShapeFamily(nextFamily);
    setShapes([]);
    setShape("");
    setImages([]);
    setImageId("");
    if (!compartmentId) return;

    setActiveAction("load");
    setStatus({ kind: "loading", message: `Loading ${nextFamily === "gpu" ? "GPU" : nextFamily === "cpu" ? "CPU/HPC" : "all"} shapes.` });
    try {
      const rawShapeList = await api.shapes(compartmentId, availabilityDomain, nextFamily !== "cpu");
      const shapeList = filterShapesForFamily(rawShapeList, nextFamily);
      const nextShape = shapeList[0]?.id || "";
      setShapes(shapeList);
      setShape(nextShape);
      if (nextShape.includes(".Flex")) {
        const defaults = flexDefaults(shapeList.find((item) => item.id === nextShape));
        setOcpus(defaults.ocpus);
        setMemoryGbs(defaults.memoryGbs);
      }
      const imageList = nextShape ? await api.images(compartmentId, nextShape) : [];
      setImages(imageList);
      setImageId(imageList[0]?.id || "");
      const familyLabel = nextFamily === "gpu" ? "GPU" : nextFamily === "cpu" ? "CPU/HPC" : "all";
      setStatus({ kind: "ok", message: `${shapeList.length} shape${shapeList.length === 1 ? "" : "s"} loaded for ${familyLabel}.` });
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setActiveAction("idle");
    }
  }

  async function changeVpc(nextVpcId: string) {
    setVcnId(nextVpcId);
    setSubnets([]);
    setSubnetId("");
    if (!compartmentId || !nextVpcId) return;

    setActiveAction("load");
    setStatus({ kind: "loading", message: "Loading subnets for selected VCN." });
    try {
      const subnetList = await api.subnets(compartmentId, nextVpcId);
      setSubnets(subnetList);
      setSubnetId(subnetList[0]?.id || "");
      setStatus({ kind: "ok", message: "VCN subnets loaded." });
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setActiveAction("idle");
    }
  }

  async function changeShape(nextShape: string) {
    setShape(nextShape);
    setImages([]);
    setImageId("");
    if (nextShape.includes(".Flex") && (!ocpus || !memoryGbs)) {
      const defaults = flexDefaults(shapes.find((item) => item.id === nextShape));
      if (!ocpus) setOcpus(defaults.ocpus);
      if (!memoryGbs) setMemoryGbs(defaults.memoryGbs);
    }
    if (!compartmentId || !nextShape) return;

    setActiveAction("load");
    setStatus({ kind: "loading", message: "Loading images for selected shape." });
    try {
      const imageList = await api.images(compartmentId, nextShape);
      setImages(imageList);
      setImageId(imageList[0]?.id || "");
      setStatus({ kind: "ok", message: "Shape images loaded." });
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setActiveAction("idle");
    }
  }

  async function refreshInfra() {
    if (!compartmentId) return;
    setActiveAction("load");
    setStatus({ kind: "loading", message: "Refreshing shapes, subnets, and images." });
    try {
      const [rawShapeList, subnetList] = await Promise.all([
        api.shapes(compartmentId, availabilityDomain, shapeFamily !== "cpu"),
        vcnId ? api.subnets(compartmentId, vcnId) : Promise.resolve([])
      ]);
      const shapeList = filterShapesForFamily(rawShapeList, shapeFamily);
      setShapes(shapeList);
      setSubnets(subnetList);
      const nextShape = shape || shapeList[0]?.id || "";
      setShape(nextShape);
      setSubnetId(subnetId || subnetList[0]?.id || "");
      if (nextShape.includes(".Flex") && (!ocpus || !memoryGbs)) {
        const defaults = flexDefaults(shapeList.find((item) => item.id === nextShape));
        if (!ocpus) setOcpus(defaults.ocpus);
        if (!memoryGbs) setMemoryGbs(defaults.memoryGbs);
      }
      if (nextShape) {
        const imageList = await api.images(compartmentId, nextShape);
        setImages(imageList);
        setImageId(imageId || imageList[0]?.id || "");
      }
      setStatus({ kind: "ok", message: "Infrastructure options refreshed." });
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setActiveAction("idle");
    }
  }

  async function createKey() {
    setActiveAction("provision");
    setStatus({ kind: "loading", message: "Generating SSH key." });
    try {
      const key = await api.createSshKey(newKeyName);
      const keyList = await api.sshKeys();
      setSshKeys(keyList);
      setSshKeyId(String(key.id));
      setStatus({ kind: "ok", message: `Generated key ${key.name}.` });
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setActiveAction("idle");
    }
  }

  async function createInstance() {
    let nextOcpus = ocpus;
    let nextMemoryGbs = memoryGbs;
    if (shape.includes(".Flex") && (!nextOcpus || !nextMemoryGbs)) {
      const defaults = flexDefaults(shapes.find((item) => item.id === shape));
      nextOcpus = nextOcpus || defaults.ocpus;
      nextMemoryGbs = nextMemoryGbs || defaults.memoryGbs;
      setOcpus(nextOcpus);
      setMemoryGbs(nextMemoryGbs);
    }

    const missing = [
      ["experiment", activeExperiment?.id],
      ["compartment", compartmentId],
      ["availability domain", availabilityDomain],
      ["shape", shape],
      ["subnet", subnetId],
      ["image", imageId],
      ["SSH key", sshKeyId],
      ["instance name", displayName],
      ...(shape.includes(".Flex") ? [["OCPUs", nextOcpus], ["Memory GB", nextMemoryGbs]] : [])
    ].filter(([, value]) => !String(value || "").trim()).map(([label]) => label);
    if (missing.length) {
      setStatus({ kind: "error", message: `Select ${missing.join(", ")} before provisioning.` });
      return;
    }

    setActiveAction("provision");
    setStatus({ kind: "loading", message: "Provisioning OCI instance." });
    try {
      const payload: Record<string, unknown> = {
        experiment_id: activeExperiment?.id,
        display_name: displayName,
        compartment_id: compartmentId,
        availability_domain: availabilityDomain,
        shape,
        subnet_id: subnetId,
        image_id: imageId,
        ssh_key_id: Number(sshKeyId),
        ssh_user: sshUser,
        assign_public_ip: true,
        boot_volume_size_gbs: 100
      };
      if (nextOcpus && nextMemoryGbs) {
        payload.ocpus = Number(nextOcpus);
        payload.memory_gbs = Number(nextMemoryGbs);
      }
      const instance = await api.createInstance(payload);
      const instanceList = await api.instances();
      setInstances(instanceList);
      setSelectedInstanceId(String(instance.id));
      setStatus({ kind: "ok", message: `Provisioned ${instance.display_name}.` });
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setActiveAction("idle");
    }
  }

  async function deploySelected() {
    const instanceId = Number(selectedInstanceId || selectedInstance?.id);
    if (!instanceId) return;
    setActiveAction("deploy");
    setStatus({ kind: "loading", message: `Deploying llama.cpp over SSH with ${selectedDeployModel?.name || selectedDeployModelId}. This can take several minutes.` });
    try {
      const result = await api.deploy(instanceId, {
        model_id: selectedDeployModelId,
        custom_model_name: customModelName || null,
        custom_model_url: customModelUrl || null,
        build_native: buildNative,
        disable_vnni: disableVnni,
        ctx_size: deployCtxSize,
        parallel: deployParallel,
        batch_size: deployBatchSize,
        ubatch_size: deployUbatchSize,
      });
      if (result.status === "ok") {
        setDeployedInstanceIds((current) => Array.from(new Set([...current, instanceId])));
        const [experimentList, instanceList] = await Promise.all([api.experiments(), api.instances()]);
        setExperiments(experimentList);
        setInstances(instanceList);
        setView("benchmarks");
        setStatus({ kind: "ok", message: `${result.message} Log: ${result.log_path}` });
      } else {
        setStatus({ kind: "error", message: `${result.message}\nLog: ${result.log_path}` });
      }
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setActiveAction("idle");
    }
  }

  function changeDeployModel(nextModelId: string) {
    setSelectedDeployModelId(nextModelId);
    const model = deployModels.find((item) => item.id === nextModelId);
    if (model) {
      if (!ocpus || Number(ocpus) < model.recommended_ocpus) setOcpus(String(model.recommended_ocpus));
      if (!memoryGbs || Number(memoryGbs) < model.recommended_memory_gbs) setMemoryGbs(String(model.recommended_memory_gbs));
    }
  }

  async function uploadPrompt(file?: File) {
    if (!file) return;
    setStatus({ kind: "loading", message: "Uploading prompt set." });
    try {
      const prompt = await api.uploadPrompt(file);
      const promptList = await api.prompts();
      setPromptSets(promptList);
      setSelectedPromptSetId(String(prompt.id));
      setStatus({ kind: "ok", message: `Uploaded ${prompt.name}.` });
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    }
  }

  function applyPreset(presetId: string) {
    setSelectedPresetId(presetId);
    const preset = BENCHMARK_PRESETS.find((item) => item.id === presetId);
    if (!preset) return;
    setConcurrency(preset.concurrency);
    setRequests(preset.requests);
    setMaxTokens(preset.maxTokens);
    setBenchmarkName(cleanBenchmarkName(`${preset.benchmarkName}-${experimentLane}`));
    const matchingPrompt = promptSets.find((item) => item.name === preset.promptHint);
    if (matchingPrompt) setSelectedPromptSetId(String(matchingPrompt.id));
  }

  function changeExperimentLane(nextLane: string) {
    setExperimentLane(nextLane);
    if (selectedPreset) {
      setBenchmarkName(cleanBenchmarkName(`${selectedPreset.benchmarkName}-${nextLane}`));
    }
  }

  async function runBenchmark() {
    if (!activeExperiment) {
      setStatus({ kind: "error", message: "Create or select an experiment before running benchmarks." });
      return;
    }
    if (!Number(selectedInstanceId || selectedInstance?.id)) {
      setStatus({ kind: "error", message: "Select a deployed instance before running benchmarks." });
      return;
    }
    setActiveAction("benchmark");
    setStatus({ kind: "loading", message: "Running benchmark through SSH tunnel." });
    try {
      const record = await api.runBenchmark({
        experiment_id: activeExperiment?.id,
        instance_id: Number(selectedInstanceId || selectedInstance?.id),
        name: benchmarkName,
        preset_id: selectedPreset?.id,
        preset_name: selectedPreset?.name,
        preset_focus: selectedPreset?.focus,
        comparison_group: selectedPreset?.comparisonGroup,
        experiment_lane: experimentLane,
        prompt_set_id: Number(selectedPromptSetId),
        concurrency,
        requests,
        max_tokens: maxTokens,
        temperature: 0
      });
      const benchmarkList = await api.benchmarks();
      const experimentList = await api.experiments();
      setBenchmarks(benchmarkList);
      setExperiments(experimentList);
      setStatus({ kind: "ok", message: `Benchmark complete: ${record.name}.` });
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setActiveAction("idle");
    }
  }

  const chartRows = useMemo(() => {
    return experimentBenchmarks.map((benchmark) => ({
      name: benchmark.name,
      preset: benchmark.summary.preset_name || benchmark.summary.preset_id || "Unlabeled",
      lane: laneLabel(benchmark.summary.experiment_lane),
      shape: benchmark.summary.shape || instances.find((item) => item.id === benchmark.instance_id)?.shape || "unknown",
      shapeClass: benchmark.summary.shape_class || shapeClass(instances.find((item) => item.id === benchmark.instance_id)?.shape),
      latency: metric(benchmark.summary, "latency_seconds.p95"),
      ttft: metric(benchmark.summary, "ttft_seconds.p95"),
      itl: metric(benchmark.summary, "approx_itl_seconds.p95"),
      rps: benchmark.summary.requests_per_second,
      output: benchmark.summary.output_chars_per_second,
      wall: benchmark.summary.wall_seconds,
      chars: benchmark.summary.output_chars,
      approxTokensPerSecond: benchmark.summary.approx_output_tokens_per_second
    }));
  }, [experimentBenchmarks, instances]);

  const comparisonRows = useMemo(() => {
    const group = selectedPreset?.comparisonGroup || selectedPreset?.id;
    const matching = benchmarks.filter((benchmark) => {
      if (benchmark.summary.comparison_group) return benchmark.summary.comparison_group === group;
      return benchmark.summary.preset_id === selectedPreset?.id || benchmark.name.includes(selectedPreset?.benchmarkName || "");
    });
    const primaryReference = Math.max(
      ...matching
        .filter((benchmark) => {
          const lane = benchmark.summary.experiment_lane;
          return lane === "primary" || lane === "baseline-cpu";
        })
        .map((benchmark) => Number(benchmark.summary.approx_output_tokens_per_second || 0)),
      0
    );
    return matching.map((benchmark) => {
      const instance = instances.find((item) => item.id === benchmark.instance_id);
      const tokPerSecond = Number(benchmark.summary.approx_output_tokens_per_second || 0);
      return {
        name: benchmark.name,
        experimentId: benchmark.summary.experiment_id,
        lane: laneLabel(benchmark.summary.experiment_lane),
        shape: benchmark.summary.shape || instance?.shape || "unknown",
        shapeClass: benchmark.summary.shape_class || shapeClass(instance?.shape),
        rps: benchmark.summary.requests_per_second,
        output: benchmark.summary.output_chars_per_second,
        approxTokensPerSecond: tokPerSecond,
        latency: metric(benchmark.summary, "latency_seconds.p95"),
        ttft: metric(benchmark.summary, "ttft_seconds.p95"),
        ratio: primaryReference > 0 && tokPerSecond > 0 ? tokPerSecond / primaryReference : null,
      };
    });
  }, [benchmarks, instances, selectedPreset]);

  if (!activeExperiment) {
    return (
      <main className="entry-page">
        <section className="entry-card">
          <div>
            <div className="brand standalone"><Cloud size={22} /> OCI Inference Cloud</div>
            <h1>Create or select an experiment</h1>
            <p className="muted">Each experiment keeps its OCI setup, deployment state, benchmark runs, raw result paths, and export bundle.</p>
          </div>
          <div className={`status ${status.kind}`}><StatusIcon kind={status.kind} /> <span>{status.message}</span></div>
          <div className="entry-grid">
            <label>Existing experiment<select value={selectedExperimentId} onChange={(event) => setSelectedExperimentId(event.target.value)}>
              <option value="">Select experiment</option>
              {experiments.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.status}</option>)}
            </select></label>
            <div className="divider-label">or create a new one</div>
            <label>Name<input value={experimentName} onChange={(event) => setExperimentName(event.target.value)} /></label>
            <label>Description<input value={experimentDescription} onChange={(event) => setExperimentDescription(event.target.value)} /></label>
            <button className="primary" onClick={createExperiment} disabled={isBusy}><Cloud size={16} /> Create experiment</button>
          </div>
        </section>
      </main>
    );
  }

  return (
    <div className="workspace">
      <header className="topbar">
        <div className="topbar-left">
          <div className="brand"><Cloud size={20} /> OCI Inference Cloud</div>
          <label className="experiment-switcher">Experiment<select value={selectedExperimentId} onChange={(event) => setSelectedExperimentId(event.target.value)}>
            {experiments.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.status}</option>)}
          </select></label>
        </div>
        <div className="topbar-actions">
          <button onClick={() => setSelectedExperimentId("")}>Switch / create</button>
          <button onClick={exportActiveExperiment}>Export JSON</button>
          <button className="danger" onClick={deleteInfra} disabled={!hasProvisionedInstance || isBusy}>Delete infra</button>
          <button className="icon-button" onClick={loadInitial} disabled={isBusy} title="Refresh state"><RefreshCcw size={17} /></button>
        </div>
      </header>
      <main className="workspace-main">
        <section className="experiment-heading">
          <div>
            <h1>{activeExperiment.name}</h1>
            <p>{activeExperiment.description || "No description"}</p>
          </div>
          <div className="phase-pill">{activeExperiment.status}</div>
        </section>

        <StepRail steps={workflowSteps} />
        <div className={`status ${status.kind}`}><StatusIcon kind={status.kind} /> <span>{status.message}</span></div>

        <div className="view-tabs">
          <button className={view === "setup" ? "selected" : ""} onClick={() => setView("setup")}>Setup</button>
          <button className={view === "benchmarks" ? "selected" : ""} onClick={() => setView("benchmarks")} disabled={!hasProvisionedInstance}>Benchmarks</button>
          <button className={view === "hackathon" ? "selected" : ""} onClick={() => setView("hackathon")} disabled={!hasDeployed}>Hackathon</button>
        </div>

        {view === "setup" && <>
        <section id="context" className="panel">
          <h2><KeyRound size={18} /> OCI context</h2>
          <div className="form-grid">
            <label>Profile<select value={profile} onChange={(event) => {
              setProfile(event.target.value);
              const selected = profiles.find((item) => item.name === event.target.value);
              setRegion(selected?.region || "");
            }}>{profiles.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}</select></label>
            <label>Region<input value={region} onChange={(event) => setRegion(event.target.value)} placeholder="us-ashburn-1" /></label>
            <label>Compartment<select value={compartmentId} onChange={(event) => changeCompartment(event.target.value)}><option value="">Load compartments first</option>{compartments.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
            <button onClick={applyContext} disabled={isBusy}><RefreshCcw size={16} /> {activeAction === "load" ? "Loading" : "Load OCI"}</button>
          </div>
        </section>

        <section id="provision" className="panel">
          <h2><Server size={18} /> Provision experiment instance</h2>
          <div className="form-grid">
            <label>Availability domain<select value={availabilityDomain} onChange={(event) => setAvailabilityDomain(event.target.value)}>{availabilityDomains.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
            <label>VCN<select value={vcnId} onChange={(event) => changeVpc(event.target.value)}>{vcns.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
            <label>Subnet<select value={subnetId} onChange={(event) => setSubnetId(event.target.value)}>{subnets.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
            <button onClick={refreshInfra} disabled={isBusy}><RefreshCcw size={16} /> Refresh infra</button>
            <label>Shape family<select value={shapeFamily} onChange={(event) => changeShapeFamily(event.target.value as ShapeFamily)}>
              <option value="cpu">CPU/HPC shapes</option>
              <option value="gpu">GPU shapes</option>
              <option value="all">All shapes</option>
            </select></label>
            <label>Shape<select value={shape} onChange={(event) => changeShape(event.target.value)}>{shapes.map((item) => <option key={item.id} value={item.id}>{item.name} · {optionShapeClass(item)}</option>)}</select></label>
            <label>Image<select value={imageId} onChange={(event) => setImageId(event.target.value)}>{images.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
            <label>OCPUs<input value={ocpus} onChange={(event) => setOcpus(event.target.value)} placeholder="optional for Flex shapes" /></label>
            <label>Memory GB<input value={memoryGbs} onChange={(event) => setMemoryGbs(event.target.value)} placeholder="optional for Flex shapes" /></label>
            <label>SSH user<select value={sshUser} onChange={(event) => setSshUser(event.target.value)}><option value="opc">opc</option><option value="ubuntu">ubuntu</option></select></label>
            <label>SSH key<select value={sshKeyId} onChange={(event) => setSshKeyId(event.target.value)}>{sshKeys.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
            <label>New key name<input value={newKeyName} onChange={(event) => setNewKeyName(event.target.value)} /></label>
            <button onClick={createKey} disabled={isBusy}><KeyRound size={16} /> Generate key</button>
            <label>Instance name<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></label>
            <button className="primary" onClick={createInstance} disabled={isBusy}><Rocket size={16} /> {activeAction === "provision" ? "Provisioning" : "Provision"}</button>
          </div>
        </section>

        <section id="deploy" className="panel">
          <h2><Rocket size={18} /> Deploy llama.cpp</h2>
          <div className="info-grid">
            <div className="info-box">
              <Info size={16} />
              <div>
                <strong>{selectedDeployModel?.name || "Custom GGUF model"}</strong>
                <span>{selectedDeployModel?.description || "Provide a direct GGUF download URL. The remote instance must be able to download it."}</span>
                {selectedDeployModel && <em>Recommended: {selectedDeployModel.recommended_ocpus} OCPU / {selectedDeployModel.recommended_memory_gbs} GB</em>}
              </div>
            </div>
            <div className="info-box">
              <Info size={16} />
              <div>
                <strong>{buildNative ? "Native optimized llama.cpp build" : "Portable llama.cpp build"}</strong>
                <span>{buildNative ? "Uses -DGGML_NATIVE=ON so llama.cpp can use CPU features available on the selected shape." : "Uses portable flags and disables AVX512 variants for compatibility across shapes."}</span>
                <em>{buildNative ? (disableVnni ? "Native build with VNNI disabled for Oracle Linux toolchain compatibility" : "Aggressive native build; may fail if the toolchain rejects VNNI instructions") : "Best for safe first deploys"}</em>
              </div>
            </div>
          </div>
          <div className="form-grid">
            <label>Instance<select value={selectedInstanceId || String(selectedInstance?.id || "")} onChange={(event) => setSelectedInstanceId(event.target.value)}>{experimentInstances.map((item) => <option key={item.id} value={item.id}>{item.display_name} · {item.lifecycle_state || "unknown"} · {item.public_ip || item.private_ip}</option>)}</select></label>
            <label>Model<select value={selectedDeployModelId} onChange={(event) => changeDeployModel(event.target.value)}>
              {deployModels.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.size_label} · {item.quantization}</option>)}
              <option value="custom">Custom GGUF URL</option>
            </select></label>
            {selectedDeployModelId === "custom" && <>
              <label>Custom model name<input value={customModelName} onChange={(event) => setCustomModelName(event.target.value)} placeholder="My GGUF model" /></label>
              <label>Custom model URL<input value={customModelUrl} onChange={(event) => setCustomModelUrl(event.target.value)} placeholder="https://.../model.gguf" /></label>
            </>}
            <label className="checkbox-row"><input type="checkbox" checked={showDeployAdvanced} onChange={(event) => setShowDeployAdvanced(event.target.checked)} /> Advanced settings</label>
            <button className="primary" onClick={deploySelected} disabled={isBusy || !selectedInstanceReady}><Play size={16} /> {activeAction === "deploy" ? "Deploying" : "Deploy"}</button>
          </div>
          {showDeployAdvanced && <div className="advanced-grid">
            <label className="checkbox-row"><input type="checkbox" checked={buildNative} onChange={(event) => setBuildNative(event.target.checked)} /> Build with `-DGGML_NATIVE=ON`</label>
            <label className="checkbox-row"><input type="checkbox" checked={disableVnni} onChange={(event) => setDisableVnni(event.target.checked)} /> Disable VNNI instructions</label>
            <label>Context size<input type="number" min={512} value={deployCtxSize} onChange={(event) => setDeployCtxSize(Number(event.target.value))} /></label>
            <label>Parallel slots<input type="number" min={1} value={deployParallel} onChange={(event) => setDeployParallel(Number(event.target.value))} /></label>
            <label>Batch size<input type="number" min={1} value={deployBatchSize} onChange={(event) => setDeployBatchSize(Number(event.target.value))} /></label>
            <label>Micro-batch size<input type="number" min={1} value={deployUbatchSize} onChange={(event) => setDeployUbatchSize(Number(event.target.value))} /></label>
          </div>}
          <div className="hint-row">
            <span>Current instance: {selectedInstance ? `${selectedInstance.lifecycle_state || "unknown"} · ${selectedInstance.public_ip || selectedInstance.private_ip || "waiting for IP"}` : "none selected"}</span>
          </div>
          <InstanceTable instances={experimentInstances} />
        </section>
        </>}

        {view === "benchmarks" && <>
        <section id="benchmark" className="panel">
          <h2><Activity size={18} /> Benchmark presets</h2>
          <div className="info-grid">
            <div className="info-box">
              <Info size={16} />
              <div><strong>{selectedPreset?.name || "Preset"}</strong><span>{selectedPreset?.description || "Choose a preset to configure request shape."}</span><em>Primary metric: {selectedPreset?.primaryMetric || "n/a"}</em></div>
            </div>
            <div className="info-box">
              <Info size={16} />
              <div><strong>{selectedPromptSet?.name || "Prompt set"}</strong><span>{selectedPromptSet?.description || "Choose a prompt set to see what it is designed to test."}</span></div>
            </div>
            <div className="info-box">
              <Info size={16} />
              <div><strong>{selectedLane?.name || "Comparison lane"}</strong><span>{selectedLane?.description || "Label this run for later comparison."}</span><em>Selected shape class: {selectedShapeClass}</em></div>
            </div>
          </div>
          <div className="form-grid">
            <label>Preset<select value={selectedPresetId} onChange={(event) => applyPreset(event.target.value)}>
              {BENCHMARK_PRESETS.map((preset) => <option key={preset.id} value={preset.id}>{preset.name}</option>)}
            </select></label>
            <label>Compare as<select value={experimentLane} onChange={(event) => changeExperimentLane(event.target.value)}>
              {LANE_OPTIONS.map((lane) => <option key={lane.id} value={lane.id}>{lane.name}</option>)}
            </select></label>
            <label>Prompt set<select value={selectedPromptSetId} onChange={(event) => setSelectedPromptSetId(event.target.value)}>{promptSets.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.prompt_count} prompts</option>)}</select></label>
            <label>Name<input value={benchmarkName} onChange={(event) => setBenchmarkName(event.target.value)} /></label>
            <label>Concurrency<input type="number" min={1} value={concurrency} onChange={(event) => setConcurrency(Number(event.target.value))} /></label>
            <label>Requests<input type="number" min={1} value={requests} onChange={(event) => setRequests(Number(event.target.value))} /></label>
            <label>Max tokens<input type="number" min={1} value={maxTokens} onChange={(event) => setMaxTokens(Number(event.target.value))} /></label>
            <label>Upload prompts<input type="file" accept=".txt,.md" onChange={(event) => uploadPrompt(event.target.files?.[0])} /></label>
            <button className="primary" onClick={runBenchmark} disabled={isBusy || !selectedInstanceReady}><Upload size={16} /> {activeAction === "benchmark" ? "Running" : "Run benchmark"}</button>
          </div>
        </section>

        <section id="results" className="panel">
          <h2><Activity size={18} /> Results</h2>
          <div className="metrics">
            <Metric title="Benchmarks" value={experimentBenchmarks.length} />
            <Metric title="Best latency p95" value={formatSeconds(Math.min(...chartRows.map((row) => row.latency ?? Infinity)))} />
            <Metric title="Best TTFT p95" value={formatSeconds(Math.min(...chartRows.map((row) => row.ttft ?? Infinity)))} />
            <Metric title="Best req/s" value={formatNumber(Math.max(...chartRows.map((row) => row.rps ?? 0)))} />
            <Metric title="Best output chars/s" value={formatNumber(Math.max(...chartRows.map((row) => row.output ?? 0)))} />
            <Metric title="Best approx tok/s" value={formatNumber(Math.max(...chartRows.map((row) => row.approxTokensPerSecond ?? 0)))} />
          </div>
          <div className="charts">
            <Chart title="Latency p95" dataKey="latency" rows={chartRows} />
            <Chart title="TTFT p95" dataKey="ttft" rows={chartRows} />
            <Chart title="Approx ITL p95" dataKey="itl" rows={chartRows} />
            <Chart title="Requests/sec" dataKey="rps" rows={chartRows} />
            <Chart title="Output chars/sec" dataKey="output" rows={chartRows} />
            <Chart title="Approx tokens/sec" dataKey="approxTokensPerSecond" rows={chartRows} />
            <Chart title="Wall seconds" dataKey="wall" rows={chartRows} />
          </div>
          <div className="comparison-panel">
            <div>
              <h3>Preset comparison: {selectedPreset?.name}</h3>
              <p className="muted">Run the same preset across multiple experiments, models, shapes, or deploy settings. Relative throughput is calculated against the best Primary run approximate tokens/sec in this preset group.</p>
            </div>
            <div className="charts">
              <Chart title="Approx tokens/sec by lane" dataKey="approxTokensPerSecond" rows={comparisonRows} />
              <Chart title="Output chars/sec by lane" dataKey="output" rows={comparisonRows} />
              <Chart title="Requests/sec by lane" dataKey="rps" rows={comparisonRows} />
              <Chart title="Latency p95 by lane" dataKey="latency" rows={comparisonRows} />
            </div>
            <ComparisonTable rows={comparisonRows} />
          </div>
          <BenchmarkTable benchmarks={experimentBenchmarks} />
        </section>
        </>}

        {view === "hackathon" && <>
        <section className="panel">
          <h2><Cloud size={18} /> Hackathon endpoint</h2>
          <div className="readiness-grid">
            <ReadinessItem label="Infrastructure" ready={hasProvisionedInstance} detail={selectedInstance ? `${selectedInstance.shape} · ${selectedInstance.lifecycle_state}` : "No instance"} />
            <ReadinessItem label="llama.cpp" ready={hasDeployed} detail={hasDeployed ? "Deployed on remote CPU instance" : "Deploy before starting endpoint"} />
            <ReadinessItem label="Local endpoint" ready={Boolean(endpointRunning)} detail={endpointRunning ? endpointUrl : endpointStatus?.status || "stopped"} />
            <ReadinessItem label="Benchmarks" ready={hasBenchmarks} detail={`${experimentBenchmarks.length} run${experimentBenchmarks.length === 1 ? "" : "s"}`} />
          </div>
          <div className="endpoint-card">
            <div>
              <span className={`endpoint-dot ${endpointRunning ? "running" : endpointStatus?.status === "failed" ? "failed" : ""}`} />
              <strong>{endpointRunning ? "Endpoint running" : `Endpoint ${endpointStatus?.status || "stopped"}`}</strong>
              <p>{endpointStatus?.error || "Local proxy forwards OpenAI-compatible requests through an SSH tunnel to remote llama-server."}</p>
            </div>
            <div className="endpoint-actions">
              <button className="primary" onClick={startEndpoint} disabled={isBusy || !hasDeployed}>{activeAction === "endpoint" ? "Starting" : "Start endpoint"}</button>
              <button onClick={() => refreshEndpoint()} disabled={isBusy}>Refresh</button>
              <button onClick={stopEndpoint} disabled={isBusy || !endpointStatus}>Stop</button>
            </div>
          </div>
        </section>

        <section className="panel">
          <h2><Info size={18} /> Participant handoff</h2>
          <div className="handoff-grid">
            <EnvBlock
              title="Direct CPU chat sample"
              description="Use this when participants should call the CPU inference endpoint directly."
              text={`CPU_ENDPOINT_URL=${endpointUrl}\nCPU_ENDPOINT_API_KEY=\nPORT=3001`}
              onCopy={() => copyText(`CPU_ENDPOINT_URL=${endpointUrl}\nCPU_ENDPOINT_API_KEY=\nPORT=3001`, "Direct sample env")}
            />
            <EnvBlock
              title="Router chat sample"
              description="Use this to compare transparent CPU routing against OpenAI fallback routing."
              text={`CPU_ENDPOINT_URL=${endpointUrl}\nOPENAI_API_KEY=replace-with-your-key\nOPENAI_MODEL=gpt-4.1-mini\nPORT=3002`}
              onCopy={() => copyText(`CPU_ENDPOINT_URL=${endpointUrl}\nOPENAI_API_KEY=replace-with-your-key\nOPENAI_MODEL=gpt-4.1-mini\nPORT=3002`, "Router sample env")}
            />
          </div>
          <div className="hint-row">
            <span>Examples live in <strong>examples/direct-cpu-chat</strong> and <strong>examples/router-chat</strong>. Start the endpoint first, then run the sample apps with the copied env values.</span>
          </div>
        </section>

        <section className="panel">
          <h2><Activity size={18} /> Endpoint usage analytics</h2>
          <div className="metrics">
            <Metric title="Proxy requests" value={endpointAnalytics.total_requests ?? 0} />
            <Metric title="Successful" value={endpointAnalytics.successful_requests ?? 0} />
            <Metric title="Failed" value={endpointAnalytics.failed_requests ?? 0} />
            <Metric title="Latency p50" value={formatSeconds(endpointAnalytics.latency_seconds?.p50)} />
            <Metric title="Latency p95" value={formatSeconds(endpointAnalytics.latency_seconds?.p95)} />
            <Metric title="Approx tok/s" value={formatNumber(endpointAnalytics.approx_output_tokens_per_second)} />
          </div>
        </section>
        </>}
      </main>
    </div>
  );
}

function StatusIcon({ kind }: { kind: Status["kind"] }) {
  if (kind === "loading") return <Loader2 className="spin" size={16} />;
  if (kind === "error") return <AlertCircle size={16} />;
  if (kind === "ok") return <CheckCircle2 size={16} />;
  return <Circle size={16} />;
}

function StepRail({ steps }: { steps: { title: string; detail: string; state: string }[] }) {
  return (
    <div className="step-rail">
      {steps.map((step, index) => (
        <div className={`step-card ${step.state}`} key={step.title}>
          <div className="step-index">{step.state === "done" ? <CheckCircle2 size={16} /> : index + 1}</div>
          <div>
            <strong>{step.title}</strong>
            <span>{step.detail}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function Metric({ title, value }: { title: string; value: string | number }) {
  return <div className="metric"><span>{title}</span><strong>{String(value).replace("Infinity", "n/a")}</strong></div>;
}

function ReadinessItem({ label, ready, detail }: { label: string; ready: boolean; detail: string }) {
  return (
    <div className={`readiness-item ${ready ? "ready" : ""}`}>
      {ready ? <CheckCircle2 size={17} /> : <Circle size={17} />}
      <div><strong>{label}</strong><span>{detail}</span></div>
    </div>
  );
}

function EnvBlock({ title, description, text, onCopy }: { title: string; description: string; text: string; onCopy: () => void }) {
  return (
    <div className="env-block">
      <div>
        <strong>{title}</strong>
        <span>{description}</span>
      </div>
      <pre>{text}</pre>
      <button onClick={onCopy}>Copy env</button>
    </div>
  );
}

function Chart({ title, dataKey, rows }: { title: string; dataKey: string; rows: Record<string, any>[] }) {
  return (
    <div className="chart">
      <h3>{title}</h3>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={rows}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="name" hide />
          <YAxis />
          <Tooltip formatter={(value) => typeof value === "number" ? value.toFixed(3) : value} />
          <Bar dataKey={dataKey} fill="#2f6f9f" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function InstanceTable({ instances }: { instances: InstanceRecord[] }) {
  if (!instances.length) return <p className="muted">No app-created instances yet.</p>;
  return (
    <table>
      <thead><tr><th>Name</th><th>Shape</th><th>State</th><th>Public IP</th><th>SSH user</th></tr></thead>
      <tbody>{instances.map((item) => <tr key={item.id}><td>{item.display_name}</td><td>{item.shape}</td><td>{item.lifecycle_state}</td><td>{item.public_ip || "n/a"}</td><td>{item.ssh_user}</td></tr>)}</tbody>
    </table>
  );
}

function BenchmarkTable({ benchmarks }: { benchmarks: BenchmarkRecord[] }) {
  if (!benchmarks.length) return <p className="muted">No benchmarks yet.</p>;
  return (
    <table>
      <thead><tr><th>Name</th><th>Preset</th><th>Lane</th><th>Shape</th><th>Concurrency</th><th>Requests</th><th>Latency p95</th><th>TTFT p95</th><th>Req/s</th><th>Approx tok/s</th><th>Raw file</th></tr></thead>
      <tbody>{benchmarks.map((item) => <tr key={item.id}><td>{item.name}</td><td>{item.summary.preset_name || "n/a"}</td><td>{laneLabel(item.summary.experiment_lane)}</td><td>{item.summary.shape || "n/a"}</td><td>{item.summary.concurrency}</td><td>{item.summary.requests}</td><td>{formatSeconds(metric(item.summary, "latency_seconds.p95"))}</td><td>{formatSeconds(metric(item.summary, "ttft_seconds.p95"))}</td><td>{formatNumber(item.summary.requests_per_second)}</td><td>{formatNumber(item.summary.approx_output_tokens_per_second)}</td><td>{item.raw_path}</td></tr>)}</tbody>
    </table>
  );
}

function ComparisonTable({ rows }: { rows: Array<Record<string, any>> }) {
  if (!rows.length) return <p className="muted">No runs yet for this preset comparison group.</p>;
  return (
    <table>
      <thead><tr><th>Run</th><th>Experiment</th><th>Lane</th><th>Shape</th><th>Shape class</th><th>Approx tok/s</th><th>Output chars/s</th><th>Req/s</th><th>Latency p95</th><th>TTFT p95</th><th>Relative throughput</th></tr></thead>
      <tbody>{rows.map((row) => <tr key={`${row.experimentId}-${row.name}-${row.lane}`}>
        <td>{row.name}</td>
        <td>{row.experimentId || "n/a"}</td>
        <td>{row.lane}</td>
        <td>{row.shape}</td>
        <td>{row.shapeClass}</td>
        <td>{formatNumber(row.approxTokensPerSecond)}</td>
        <td>{formatNumber(row.output)}</td>
        <td>{formatNumber(row.rps)}</td>
        <td>{formatSeconds(row.latency)}</td>
        <td>{formatSeconds(row.ttft)}</td>
        <td>{typeof row.ratio === "number" ? `${row.ratio.toFixed(2)}x` : "n/a"}</td>
      </tr>)}</tbody>
    </table>
  );
}
