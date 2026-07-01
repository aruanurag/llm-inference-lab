"use client";

import { useEffect, useState } from "react";

type Analytics = {
  totalRequests: number;
  cpuRequests: number;
  openaiRequests: number;
  cpuPercent: number;
  openaiPercent: number;
  averageLatencyMsByProvider: { cpu: number; openai: number };
  latestRouteReason: string;
};

export default function Page() {
  const [prompt, setPrompt] = useState("Summarize why CPU inference can be useful for hackathon prototypes.");
  const [mode, setMode] = useState("auto");
  const [maxTokens, setMaxTokens] = useState(256);
  const [answer, setAnswer] = useState("");
  const [provider, setProvider] = useState("");
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(false);
  const [analytics, setAnalytics] = useState<Analytics | null>(null);

  async function refreshAnalytics() {
    const response = await fetch("/api/analytics");
    setAnalytics(await response.json());
  }

  async function send() {
    setLoading(true);
    setAnswer("");
    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, maxTokens, mode }),
      });
      const data = await response.json();
      setProvider(data.provider || "");
      setReason(data.reason || "");
      setAnswer(data.text || data.error || "No response");
      await refreshAnalytics();
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refreshAnalytics();
  }, []);

  const cpuPercent = analytics?.cpuPercent || 0;
  const openaiPercent = analytics?.openaiPercent || 0;

  return (
    <main>
      <section className="toolbar">
        <div>
          <h1>Router Chat</h1>
          <p>Routes simple requests to CPU inference and escalates heavier requests to OpenAI.</p>
        </div>
      </section>
      <section className="grid">
        <div className="panel chat">
          <div className="controls">
            <label>Mode<select value={mode} onChange={(event) => setMode(event.target.value)}><option value="auto">Auto rule-based</option><option value="cpu">Force CPU</option><option value="openai">Force OpenAI</option></select></label>
            <label>Max tokens<input type="number" value={maxTokens} onChange={(event) => setMaxTokens(Number(event.target.value))} /></label>
          </div>
          <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} />
          <button onClick={send} disabled={loading}>{loading ? "Routing..." : "Send"}</button>
          <div className="decision"><strong>{provider || "No route yet"}</strong><span>{reason}</span></div>
          <pre>{answer}</pre>
        </div>
        <div className="panel">
          <h2>Route Analytics</h2>
          <Metric label="Total requests" value={analytics?.totalRequests || 0} />
          <Metric label="CPU handled" value={`${analytics?.cpuRequests || 0} (${cpuPercent.toFixed(0)}%)`} />
          <Metric label="OpenAI handled" value={`${analytics?.openaiRequests || 0} (${openaiPercent.toFixed(0)}%)`} />
          <Metric label="CPU avg latency" value={`${(analytics?.averageLatencyMsByProvider.cpu || 0).toFixed(0)} ms`} />
          <Metric label="OpenAI avg latency" value={`${(analytics?.averageLatencyMsByProvider.openai || 0).toFixed(0)} ms`} />
          <div className="bar"><span style={{ width: `${cpuPercent}%` }}>CPU</span><span style={{ width: `${openaiPercent}%` }}>OpenAI</span></div>
          <p>{analytics?.latestRouteReason}</p>
        </div>
      </section>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong></div>;
}
