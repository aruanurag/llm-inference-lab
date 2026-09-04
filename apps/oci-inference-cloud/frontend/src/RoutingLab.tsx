import { useEffect, useMemo, useState } from "react";
import { Activity, AlertCircle, CheckCircle2, Circle, Copy, Info, KeyRound, Loader2, Play, RefreshCcw, Rocket, ShieldCheck, Square, Trash2 } from "lucide-react";
import { api } from "./api";
import type {
  ExperimentRecord,
  LlmDRoutingAlias,
  LlmDRoutingAliasRoute,
  LlmDRoutingBenchmarkRecord,
  LlmDRoutingBenchmarkResult,
  LlmDRoutingConfiguration,
  LlmDRoutingDeployRequest,
  LlmDRoutingEndpointStatus,
  LlmDRoutingInferenceResult,
  LlmDRoutingPlan,
  LlmDRoutingPreflight,
  LlmDRoutingStatus,
} from "./types";

type Notice = { kind: "idle" | "loading" | "ok" | "error"; message: string };

export type RoutingLabProps = {
  /** The Lab 5 experiment that owns only the router resources. */
  experiment: ExperimentRecord;
  /** Eligible Lab 4 experiments; the source deployment is never recreated here. */
  lab4Experiments: ExperimentRecord[];
  /** Lets the parent refresh the experiment picker after a deploy or cleanup. */
  onRefreshExperiments?: () => Promise<void> | void;
};

const ALIASES: Array<{
  alias: LlmDRoutingAlias;
  title: string;
  destination: "llm-d" | "openrouter";
  description: string;
}> = [
  {
    alias: "private",
    title: "Private model",
    destination: "llm-d",
    description: "Stays in the cluster and reaches the source Lab 4 LLM-D EPP endpoint.",
  },
  {
    alias: "fast",
    title: "Fast private model",
    destination: "llm-d",
    description: "A second stable local alias for the same private LLM-D serving path.",
  },
  {
    alias: "coding",
    title: "Coding model",
    destination: "openrouter",
    description: "Uses the selected OpenRouter coding model. Provider data collection is denied.",
  },
  {
    alias: "reasoning",
    title: "Reasoning model",
    destination: "openrouter",
    description: "Uses the selected OpenRouter reasoning model. Provider data collection is denied.",
  },
];

const emptyNotice: Notice = { kind: "idle", message: "Choose a linked Lab 4 experiment, validate it, then render a non-secret deployment plan." };

function defaultConfiguration(
  lab4Experiments: ExperimentRecord[],
  linkedSourceId?: number | null,
  experimentId?: number,
): LlmDRoutingConfiguration {
  return {
    source_experiment_id: linkedSourceId || lab4Experiments[0]?.id || 0,
    context: "",
    namespace: "",
    release_name: "",
    model: "",
    coding_model: "openai/gpt-4.1-mini",
    reasoning_model: "deepseek/deepseek-r1",
    router_name: experimentId ? `llm-d-routing-${experimentId}` : "",
  };
}

function isExternalAlias(alias: LlmDRoutingAlias) {
  return alias === "coding" || alias === "reasoning";
}

function boundedTokens(alias: LlmDRoutingAlias, value: number) {
  return isExternalAlias(alias) ? Math.min(512, Math.max(1, value)) : Math.max(1, value);
}

function formatSeconds(value: unknown) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "n/a";
  return value < 1 ? `${(value * 1000).toFixed(1)} ms` : `${value.toFixed(2)} s`;
}

function formatNumber(value: unknown) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "n/a";
  return value.toFixed(2);
}

function summaryMetric(summary: Record<string, unknown>, path: string): unknown {
  return path.split(".").reduce<unknown>((current, key) => {
    if (!current || typeof current !== "object") return undefined;
    return (current as Record<string, unknown>)[key];
  }, summary);
}

function routeFor(alias: LlmDRoutingAlias, routes: LlmDRoutingAliasRoute[]) {
  return routes.find((route) => route.alias === alias);
}

function assistantText(response: Record<string, unknown>) {
  const choices = response.choices;
  if (!Array.isArray(choices)) return null;
  const first = choices[0];
  if (!first || typeof first !== "object") return null;
  const message = (first as Record<string, unknown>).message;
  if (!message || typeof message !== "object") return null;
  const content = (message as Record<string, unknown>).content;
  return typeof content === "string" ? content : null;
}

function NoticeIcon({ kind }: { kind: Notice["kind"] }) {
  if (kind === "loading") return <Loader2 className="spin" size={16} />;
  if (kind === "ok") return <CheckCircle2 size={16} />;
  if (kind === "error") return <AlertCircle size={16} />;
  return <Circle size={16} />;
}

function Metric({ title, value }: { title: string; value: string | number }) {
  return <div className="metric"><span>{title}</span><strong>{value}</strong></div>;
}

/**
 * Lab 5's in-cluster LiteLLM routing workflow. This component deliberately
 * owns no source Lab 4 resources and never reads, displays, or persists an
 * OpenRouter key after the deploy request has completed.
 */
export function RoutingLab({ experiment, lab4Experiments, onRefreshExperiments }: RoutingLabProps) {
  const [config, setConfig] = useState<LlmDRoutingConfiguration>(() => defaultConfiguration(lab4Experiments, experiment.source_experiment_id, experiment.id));
  const [notice, setNotice] = useState<Notice>(emptyNotice);
  const [busy, setBusy] = useState(false);
  const [preflight, setPreflight] = useState<LlmDRoutingPreflight | null>(null);
  const [plan, setPlan] = useState<LlmDRoutingPlan | null>(null);
  const [routerStatus, setRouterStatus] = useState<LlmDRoutingStatus | null>(null);
  const [endpoint, setEndpoint] = useState<LlmDRoutingEndpointStatus | null>(null);
  const [history, setHistory] = useState<LlmDRoutingBenchmarkRecord[]>([]);
  const [openRouterKey, setOpenRouterKey] = useState("");
  const [deployConfirmed, setDeployConfirmed] = useState(false);
  const [cleanupConfirmed, setCleanupConfirmed] = useState(false);
  const [selectedAlias, setSelectedAlias] = useState<LlmDRoutingAlias>("private");
  const [prompt, setPrompt] = useState("Explain, in two short paragraphs, how cache-aware routing can improve LLM inference efficiency.");
  const [maxTokens, setMaxTokens] = useState(128);
  const [temperature, setTemperature] = useState(0);
  const [inference, setInference] = useState<LlmDRoutingInferenceResult | null>(null);
  const [benchmarkName, setBenchmarkName] = useState("hybrid-routing-baseline");
  const [benchmarkConcurrency, setBenchmarkConcurrency] = useState(1);
  const [benchmarkRequests, setBenchmarkRequests] = useState(8);
  const [benchmarkResult, setBenchmarkResult] = useState<LlmDRoutingBenchmarkResult | null>(null);

  const sourceExperiment = useMemo(
    () => lab4Experiments.find((item) => item.id === config.source_experiment_id) || null,
    [config.source_experiment_id, lab4Experiments],
  );
  const routes = routerStatus?.aliases.length ? routerStatus.aliases : plan?.aliases.length ? plan.aliases : [];
  const effectiveMaxTokens = boundedTokens(selectedAlias, maxTokens);
  // Context, namespace, release, and local model are resolved server-side
  // from the immutable Lab 4 link. Participants configure only Lab 5-owned
  // router details here, so a blank client-side context cannot block a plan.
  const canRenderPlan = Boolean(config.source_experiment_id && config.coding_model.trim() && config.reasoning_model.trim() && config.router_name?.trim());
  const endpointRunning = Boolean(endpoint?.healthy && endpoint.status === "running");

  function updateConfig(patch: Partial<LlmDRoutingConfiguration>) {
    setConfig((current) => ({
      ...current,
      ...patch,
      ...(patch.source_experiment_id !== undefined && patch.source_experiment_id !== current.source_experiment_id
        ? { context: "", namespace: "", release_name: "", model: "" }
        : {}),
    }));
    setPlan(null);
    setDeployConfirmed(false);
  }

  function hydrateFromStatus(nextStatus: LlmDRoutingStatus) {
    if (!nextStatus.configured) return;
    setConfig((current) => {
      const coding = routeFor("coding", nextStatus.aliases)?.model;
      const reasoning = routeFor("reasoning", nextStatus.aliases)?.model;
      return {
        ...current,
        source_experiment_id: nextStatus.source_experiment_id || current.source_experiment_id,
        context: nextStatus.context || current.context,
        namespace: nextStatus.namespace || current.namespace,
        router_name: nextStatus.router_name || current.router_name,
        coding_model: coding || current.coding_model,
        reasoning_model: reasoning || current.reasoning_model,
      };
    });
  }

  async function refreshState(showNotice = false) {
    try {
      const status = await api.llmdRoutingStatus(experiment.id);
      setRouterStatus(status);
      hydrateFromStatus(status);
      try {
        setEndpoint(await api.llmdRoutingEndpoint(experiment.id));
      } catch {
        // A tunnel is optional; the router status remains useful without one.
      }
      try {
        setHistory(await api.llmdRoutingBenchmarks(experiment.id));
      } catch {
        // Benchmark history does not prevent the main routing workflow.
      }
      if (showNotice) setNotice({ kind: "ok", message: "Router state refreshed." });
    } catch (error) {
      if (showNotice) setNotice({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    }
  }

  useEffect(() => {
    setConfig(defaultConfiguration(lab4Experiments, experiment.source_experiment_id, experiment.id));
    setPreflight(null);
    setPlan(null);
    setRouterStatus(null);
    setEndpoint(null);
    setHistory([]);
    setInference(null);
    setBenchmarkResult(null);
    setOpenRouterKey("");
    setDeployConfirmed(false);
    setCleanupConfirmed(false);
    setNotice(emptyNotice);
    void refreshState(false);
    // The active Lab 5 experiment is the ownership boundary.  A later source
    // list update is handled below without erasing a loaded router config.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [experiment.id]);

  useEffect(() => {
    if (!lab4Experiments.length) return;
    setConfig((current) => {
      if (lab4Experiments.some((item) => item.id === current.source_experiment_id)) return current;
      return { ...current, source_experiment_id: lab4Experiments[0].id };
    });
  }, [lab4Experiments]);

  async function runPreflight() {
    if (!canRenderPlan) return;
    setBusy(true);
    setNotice({ kind: "loading", message: "Checking the selected Lab 4 LLM-D source, Prometheus discovery, and router prerequisites." });
    try {
      const result = await api.llmdRoutingPreflight(experiment.id, config);
      setPreflight(result);
      setConfig((current) => ({ ...current, context: result.context, namespace: result.namespace }));
      setNotice({ kind: "ok", message: "Routing preflight completed. Review warnings before rendering the plan." });
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  }

  async function renderPlan() {
    if (!canRenderPlan) return;
    setBusy(true);
    setNotice({ kind: "loading", message: "Rendering the router, ServiceMonitor, dashboard, and Secret references. The OpenRouter key is not part of this plan." });
    try {
      const result = await api.planLlmDRouting(experiment.id, config);
      setPlan(result);
      setConfig((current) => ({
        ...current,
        context: result.context,
        namespace: result.namespace,
        router_name: result.router_name,
        model: routeFor("private", result.aliases)?.model || current.model,
      }));
      setDeployConfirmed(false);
      setNotice({ kind: "ok", message: "Plan rendered. Confirm it and provide a write-only OpenRouter key to deploy." });
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  }

  async function deployRouter() {
    if (!plan || !deployConfirmed || !openRouterKey.trim()) return;
    setBusy(true);
    setNotice({ kind: "loading", message: "Deploying the Lab 5-owned in-cluster router. The OpenRouter key is write-only and will be cleared from this form." });
    try {
      const payload = {
        ...config,
        openrouter_api_key: openRouterKey.trim(),
        confirm: true,
      } satisfies LlmDRoutingDeployRequest;
      const result = await api.deployLlmDRouting(experiment.id, payload);
      setPlan(result.plan);
      await refreshState(false);
      await onRefreshExperiments?.();
      setNotice({ kind: "ok", message: result.message || "Router deployed. Start a local tunnel when it reports Ready." });
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setOpenRouterKey("");
      setBusy(false);
    }
  }

  async function startEndpoint() {
    setBusy(true);
    setNotice({ kind: "loading", message: "Starting a local-only kubectl port-forward to the router service." });
    try {
      const nextEndpoint = await api.startLlmDRoutingEndpoint(experiment.id);
      setEndpoint(nextEndpoint);
      setNotice({ kind: nextEndpoint.healthy ? "ok" : "error", message: nextEndpoint.message || (nextEndpoint.healthy ? "Local router endpoint is running." : "The local router endpoint did not become healthy.") });
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  }

  async function stopEndpoint() {
    setBusy(true);
    setNotice({ kind: "loading", message: "Stopping the local router tunnel." });
    try {
      setEndpoint(await api.stopLlmDRoutingEndpoint(experiment.id));
      setNotice({ kind: "ok", message: "Local router tunnel stopped." });
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  }

  async function copyEndpoint() {
    if (!endpoint?.endpoint_url) return;
    try {
      await navigator.clipboard.writeText(endpoint.endpoint_url);
      setNotice({ kind: "ok", message: "Router endpoint copied." });
    } catch {
      setNotice({ kind: "error", message: "Could not copy the endpoint. Copy it from the address shown below." });
    }
  }

  async function runInference() {
    if (!endpointRunning || !prompt.trim()) return;
    setBusy(true);
    setNotice({ kind: "loading", message: `Sending a test request through the ${selectedAlias} route.` });
    try {
      const result = await api.inferLlmDRouting(experiment.id, {
        model: selectedAlias,
        prompt: prompt.trim(),
        max_tokens: effectiveMaxTokens,
        temperature,
        stream: false,
      });
      setInference(result);
      setNotice({ kind: "ok", message: `Inference completed through ${result.destination}.` });
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  }

  async function runBenchmark() {
    if (!endpointRunning || !prompt.trim()) return;
    setBusy(true);
    setNotice({ kind: "loading", message: `Running a ${selectedAlias} routing benchmark. Metrics will appear in the Lab 4 Prometheus and Grafana stack when it is available.` });
    try {
      const result = await api.benchmarkLlmDRouting(experiment.id, {
        name: benchmarkName.trim() || "hybrid-routing-benchmark",
        model: selectedAlias,
        prompt: prompt.trim(),
        concurrency: Math.max(1, benchmarkConcurrency),
        requests: Math.max(1, benchmarkRequests),
        max_tokens: effectiveMaxTokens,
        temperature,
      });
      setBenchmarkResult(result);
      setHistory(await api.llmdRoutingBenchmarks(experiment.id));
      setNotice({ kind: "ok", message: `Benchmark completed through ${result.destination}. Raw output remains outside Git.` });
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  }

  async function uninstallRouter() {
    if (!cleanupConfirmed) return;
    setBusy(true);
    setNotice({ kind: "loading", message: "Removing only Lab 5-owned router resources and its OpenRouter Secret." });
    try {
      const result = await api.uninstallLlmDRouting(experiment.id);
      setPlan(null);
      setInference(null);
      setBenchmarkResult(null);
      setCleanupConfirmed(false);
      await refreshState(false);
      await onRefreshExperiments?.();
      setNotice({ kind: "ok", message: result.message || "Lab 5-owned router resources were removed. The linked Lab 4 deployment was left intact." });
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <section className="panel">
        <div className="section-heading">
          <div>
            <h2><Rocket size={18} /> Lab 5 · Hybrid model routing</h2>
            <p className="muted">Deploy a private, in-cluster LiteLLM router that sends explicit aliases to the linked Lab 4 LLM-D endpoint or to OpenRouter. This lab never recreates the source Lab 4 LLM-D deployment.</p>
          </div>
          <button onClick={() => void refreshState(true)} disabled={busy}><RefreshCcw size={16} /> Refresh router</button>
        </div>
        <div className={`status ${notice.kind}`}><NoticeIcon kind={notice.kind} /><span>{notice.message}</span></div>
      </section>

      <section className="panel">
        <h2><KeyRound size={18} /> 1. Link and validate a Lab 4 source</h2>
        <p className="muted">The router uses the selected Lab 4 EPP service for <code>private</code> and <code>fast</code>. It validates the service and observability prerequisites before it can be deployed.</p>
        <div className="form-grid">
          <label>Linked Lab 4 experiment<select value={config.source_experiment_id || ""} disabled>
            <option value="">No Lab 4 source linked</option>
            {lab4Experiments.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.status}</option>)}
          </select></label>
          <label>Cluster target<input value={config.context || "Resolved from linked Lab 4 source"} disabled /></label>
          <label>Namespace<input value={config.namespace || "Resolved from linked Lab 4 source"} disabled /></label>
          <label>Router name<input value={config.router_name || ""} onChange={(event) => updateConfig({ router_name: event.target.value })} disabled={Boolean(routerStatus?.owned)} /></label>
          <button onClick={runPreflight} disabled={busy || !canRenderPlan || !sourceExperiment}><RefreshCcw size={16} /> Validate routing prerequisites</button>
        </div>
        {!lab4Experiments.length && <div className="hint-row"><span>Create or select a ready Lab 4 autoscaling experiment first. Lab 5 only attaches a router to it.</span></div>}
        {sourceExperiment && <div className="hint-row"><span><strong>Linked source:</strong> {sourceExperiment.name}. It remains independently owned by Lab 4; cleanup here cannot remove its LLM-D EPP service, model servers, KEDA policy, or observability stack.</span></div>}
        {preflight && <>
          <div className="metrics">
            <Metric title="Lab 4 source" value={preflight.source_experiment_ready ? "Ready" : "Not ready"} />
            <Metric title="LLM-D EPP" value={preflight.epp_ready ? "Ready" : "Not ready"} />
            <Metric title="Prometheus" value={preflight.prometheus_available ? "Detected" : "Missing"} />
            <Metric title="Grafana" value={preflight.grafana_available ? "Detected" : "Optional / missing"} />
            <Metric title="ServiceMonitor CRD" value={preflight.service_monitor_crd ? "Installed" : "Missing"} />
            <Metric title="External egress" value={preflight.egress_ready === null ? "Not verified" : preflight.egress_ready ? "Available" : "Blocked"} />
          </div>
          {preflight.conflicting_releases.length > 0 && <div className="hint-row"><span><strong>Existing releases:</strong> {preflight.conflicting_releases.map((release) => `${release.name} (${release.namespace})`).join(", ")}. The router creates only Lab 5-owned resources.</span></div>}
          {preflight.warnings.map((warning) => <p className="muted" key={warning}>Warning: {warning}</p>)}
        </>}
      </section>

      <section className="panel">
        <h2><ShieldCheck size={18} /> 2. Configure aliases and review the plan</h2>
        <div className="info-grid">
          <div className="info-box"><Info size={16} /><div><strong>Explicit routing only</strong><span>The caller selects a stable alias. This lab does not classify prompts or silently fall back between providers.</span></div></div>
          <div className="info-box"><ShieldCheck size={16} /><div><strong>Private by default</strong><span><code>private</code> and <code>fast</code> stay within the OKE cluster and use the existing LLM-D EPP endpoint.</span></div></div>
          <div className="info-box"><KeyRound size={16} /><div><strong>External safety boundary</strong><span>OpenRouter aliases deny provider data collection and are hard-capped at 512 generated tokens.</span></div></div>
        </div>
        <div className="form-grid">
          <label>OpenRouter coding model<input value={config.coding_model} onChange={(event) => updateConfig({ coding_model: event.target.value })} placeholder="openai/gpt-4.1-mini" /></label>
          <label>OpenRouter reasoning model<input value={config.reasoning_model} onChange={(event) => updateConfig({ reasoning_model: event.target.value })} placeholder="deepseek/deepseek-r1" /></label>
          <button onClick={renderPlan} disabled={busy || !canRenderPlan}><Info size={16} /> Render router plan</button>
        </div>
        <div className="readiness-grid">
          {ALIASES.map((route) => {
            const configured = routeFor(route.alias, routes);
            const model = configured?.model || (route.alias === "coding" ? config.coding_model : route.alias === "reasoning" ? config.reasoning_model : config.model);
            return <div className={`readiness-item ${configured ? "ready" : ""}`} key={route.alias}>
              {configured ? <CheckCircle2 size={17} /> : <Circle size={17} />}
              <div><strong><code>{route.alias}</code> · {route.title}</strong><span>{route.description}</span><span>Target: {model}{route.destination === "openrouter" ? " · max 512 output tokens" : ""}</span></div>
            </div>;
          })}
        </div>
        {plan && <details open>
          <summary>Lab 5 router plan preview</summary>
          <p className="muted">This preview deliberately excludes the OpenRouter API key. It creates a Lab 5-owned ConfigMap, Secret reference, Deployment, private Service, ServiceMonitor, and Grafana dashboard ConfigMap.</p>
          <pre className="command-preview">{plan.commands.map((command) => `$ ${command.join(" ")}`).join("\n\n")}</pre>
          <details><summary>Rendered manifests (credential values excluded)</summary><pre className="command-preview">{plan.manifests}</pre></details>
          {plan.warnings.map((warning) => <p className="muted" key={warning}>Warning: {warning}</p>)}
        </details>}
      </section>

      <section className="panel">
        <h2><Play size={18} /> 3. Deploy the private router</h2>
        <p className="muted">The OpenRouter API key is sent only with this deploy action, stored in a Kubernetes Secret, and cleared from the form immediately. It is never included in plans, status, logs, exports, or Git.</p>
        <div className="form-grid">
          <label>OpenRouter API key<input type="password" autoComplete="off" value={openRouterKey} onChange={(event) => setOpenRouterKey(event.target.value)} placeholder="sk-or-v1-…" /></label>
          <label className="checkbox-row"><input type="checkbox" checked={deployConfirmed} onChange={(event) => setDeployConfirmed(event.target.checked)} /> I reviewed the non-secret plan and authorize these Lab 5-owned changes.</label>
          <button className="primary" onClick={deployRouter} disabled={busy || !plan || !deployConfirmed || !openRouterKey.trim()}><Rocket size={16} /> Deploy router</button>
        </div>
        {routerStatus && <div className="metrics">
          <Metric title="Router resources" value={routerStatus.configured ? routerStatus.owned ? "Lab 5-owned" : "Detected" : "Not deployed"} />
          <Metric title="Deployment" value={routerStatus.ready ? "Ready" : "Not ready"} />
          <Metric title="Service" value={routerStatus.service_name || "n/a"} />
          <Metric title="Routes" value={routerStatus.aliases.length} />
        </div>}
        {routerStatus?.message && <div className="hint-row"><span>{routerStatus.message}</span></div>}
      </section>

      <section className="panel">
        <h2><Activity size={18} /> 4. Local OpenAI-compatible endpoint</h2>
        <p className="muted">The router is private in Kubernetes. Start a local <code>kubectl port-forward</code>-backed loopback endpoint to use the OpenAI-compatible <code>/v1/chat/completions</code> and <code>/v1/models</code> endpoints; the workbench keeps the router credential out of the browser and no public ingress is created.</p>
        <div className="endpoint-card">
          <div>
            <span className={`endpoint-dot ${endpointRunning ? "running" : endpoint?.status === "failed" ? "failed" : ""}`} />
            <strong>{endpointRunning ? "Local router endpoint running" : `Local router endpoint ${endpoint?.status || "stopped"}`}</strong>
            <p>{endpoint?.message || endpoint?.endpoint_url || "Start the tunnel after the router deployment is Ready."}</p>
          </div>
          <div className="endpoint-actions">
            <button className="primary" onClick={startEndpoint} disabled={busy || !routerStatus?.configured || !routerStatus.ready}><Play size={16} /> Start endpoint</button>
            <button onClick={() => void refreshState(true)} disabled={busy}><RefreshCcw size={16} /> Refresh</button>
            <button onClick={stopEndpoint} disabled={busy || !endpoint}><Square size={15} /> Stop</button>
          </div>
        </div>
        {endpoint?.endpoint_url && <div className="hint-row"><span><strong>Endpoint:</strong> <code>{endpoint.endpoint_url}</code> · models: {endpoint.available_models.join(", ") || "private, fast, coding, reasoning"} <button onClick={copyEndpoint} disabled={busy}><Copy size={14} /> Copy</button></span></div>}
      </section>

      <section className="panel">
        <h2><Activity size={18} /> 5. Route a request and benchmark it</h2>
        <p className="muted">Choose the route intentionally. Coding and reasoning requests cannot exceed 512 output tokens, and any external-route failure is returned clearly instead of falling back to the private model.</p>
        <div className="form-grid">
          <label>Route alias<select value={selectedAlias} onChange={(event) => setSelectedAlias(event.target.value as LlmDRoutingAlias)}>{ALIASES.map((route) => <option key={route.alias} value={route.alias}>{route.alias} · {route.destination}</option>)}</select></label>
          <label>Max output tokens<input type="number" min={1} max={isExternalAlias(selectedAlias) ? 512 : 4096} value={effectiveMaxTokens} onChange={(event) => setMaxTokens(boundedTokens(selectedAlias, Number(event.target.value)))} /></label>
          <label>Temperature<input type="number" min={0} max={2} step={0.1} value={temperature} onChange={(event) => setTemperature(Number(event.target.value))} /></label>
          <button className="primary" onClick={runInference} disabled={busy || !endpointRunning || !prompt.trim()}><Play size={16} /> Send test request</button>
        </div>
        {isExternalAlias(selectedAlias) && <div className="hint-row"><span><strong>External route:</strong> max output tokens is enforced at 512. Request data is sent to OpenRouter only for this explicitly selected alias.</span></div>}
        <label>Prompt<textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={5} placeholder="Type a safe prompt to route…" /></label>
        {inference && <div className="comparison-panel">
          <h3>Latest response · <code>{inference.model}</code> → {inference.destination}</h3>
          {assistantText(inference.response) ? <p>{assistantText(inference.response)}</p> : <p className="muted">The provider returned a response without a displayable chat message. Inspect the sanitized response body below.</p>}
          {inference.usage && <p className="muted">Usage: {Object.entries(inference.usage).map(([key, value]) => `${key}: ${value}`).join(", ")}</p>}
          <details><summary>Response body</summary><pre className="command-preview">{JSON.stringify(inference.response, null, 2)}</pre></details>
        </div>}
        <div className="form-grid">
          <label>Benchmark name<input value={benchmarkName} onChange={(event) => setBenchmarkName(event.target.value)} /></label>
          <label>Concurrency<input type="number" min={1} max={128} value={benchmarkConcurrency} onChange={(event) => setBenchmarkConcurrency(Math.max(1, Number(event.target.value)))} /></label>
          <label>Requests<input type="number" min={1} max={1000} value={benchmarkRequests} onChange={(event) => setBenchmarkRequests(Math.max(1, Number(event.target.value)))} /></label>
          <button className="primary" onClick={runBenchmark} disabled={busy || !endpointRunning || !prompt.trim()}><Activity size={16} /> Run route benchmark</button>
        </div>
        {benchmarkResult && <div className="metrics">
          <Metric title="Route" value={`${benchmarkResult.model} → ${benchmarkResult.destination}`} />
          <Metric title="Latency p95" value={formatSeconds(summaryMetric(benchmarkResult.summary, "latency_seconds.p95"))} />
          <Metric title="TTFT p95" value={formatSeconds(summaryMetric(benchmarkResult.summary, "ttft_seconds.p95"))} />
          <Metric title="Requests/sec" value={formatNumber(summaryMetric(benchmarkResult.summary, "requests_per_second"))} />
          <Metric title="Approx tokens/sec" value={formatNumber(summaryMetric(benchmarkResult.summary, "approx_output_tokens_per_second"))} />
          <Metric title="Saved" value="Outside Git" />
        </div>}
      </section>

      <section className="panel">
        <div className="section-heading">
          <div>
            <h2><Activity size={18} /> Routing benchmark history</h2>
            <p className="muted">Compare aliases under the same request shape. Route labels are kept; prompts, provider credentials, and spend data are not retained here.</p>
          </div>
          <button onClick={() => void refreshState(true)} disabled={busy}><RefreshCcw size={16} /> Refresh history</button>
        </div>
        {!history.length ? <p className="muted">No Lab 5 route benchmarks yet.</p> : <table>
          <thead><tr><th>Run</th><th>Alias</th><th>Destination</th><th>Concurrency</th><th>Requests</th><th>Latency p95</th><th>TTFT p95</th><th>Req/s</th><th>Saved</th></tr></thead>
          <tbody>{history.map((item) => <tr key={item.id}>
            <td>{item.name}</td>
            <td><code>{item.model}</code></td>
            <td>{item.destination}</td>
            <td>{String(summaryMetric(item.summary, "concurrency") ?? "n/a")}</td>
            <td>{String(summaryMetric(item.summary, "requests") ?? "n/a")}</td>
            <td>{formatSeconds(summaryMetric(item.summary, "latency_seconds.p95"))}</td>
            <td>{formatSeconds(summaryMetric(item.summary, "ttft_seconds.p95"))}</td>
            <td>{formatNumber(summaryMetric(item.summary, "requests_per_second"))}</td>
            <td>{new Date(item.created_at).toLocaleString()}</td>
          </tr>)}</tbody>
        </table>}
      </section>

      {routerStatus?.configured && routerStatus.owned && <section className="panel">
        <h2><Trash2 size={18} /> Remove Lab 5 router</h2>
        <p className="muted">This removes only resources recorded as Lab 5-owned, including the router Deployment, private Service, metrics resources, dashboard ConfigMap, and OpenRouter Secret. The linked Lab 4 LLM-D deployment is not touched.</p>
        <div className="form-grid">
          <label className="checkbox-row"><input type="checkbox" checked={cleanupConfirmed} onChange={(event) => setCleanupConfirmed(event.target.checked)} /> I understand this removes the Lab 5 router only.</label>
          <button className="danger" onClick={uninstallRouter} disabled={busy || !cleanupConfirmed}><Trash2 size={16} /> Remove Lab 5 router</button>
        </div>
      </section>}
    </>
  );
}
