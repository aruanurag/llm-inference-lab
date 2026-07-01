import { analytics } from "./store";

export const runtime = "nodejs";

type Provider = "cpu" | "openai";

function cpuChatUrl() {
  const base = process.env.CPU_ENDPOINT_URL;
  if (!base) throw new Error("CPU_ENDPOINT_URL is required.");
  return `${base.replace(/\/$/, "")}/chat/completions`;
}

function routeFor(prompt: string, maxTokens: number, mode: string): { provider: Provider; reason: string } {
  if (mode === "cpu") return { provider: "cpu", reason: "Manual CPU mode selected." };
  if (mode === "openai") return { provider: "openai", reason: "Manual OpenAI mode selected." };
  if (prompt.length <= 450 && maxTokens <= 256) {
    return { provider: "cpu", reason: "Short prompt and modest output budget fit the CPU endpoint." };
  }
  return { provider: "openai", reason: "Longer or higher-output request routed to OpenAI fallback." };
}

async function callCpu(prompt: string, maxTokens: number) {
  const response = await fetch(cpuChatUrl(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: "local-model",
      messages: [{ role: "user", content: prompt }],
      stream: false,
      max_tokens: maxTokens,
      temperature: 0,
    }),
  });
  const data = await response.json();
  return { ok: response.ok, text: data.choices?.[0]?.message?.content || data.error || "", raw: data };
}

async function callOpenAI(prompt: string, maxTokens: number) {
  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey) throw new Error("OPENAI_API_KEY is required for OpenAI-routed requests.");
  const response = await fetch("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model: process.env.OPENAI_MODEL || "gpt-4.1-mini",
      messages: [{ role: "user", content: prompt }],
      max_tokens: maxTokens,
      temperature: 0,
    }),
  });
  const data = await response.json();
  return { ok: response.ok, text: data.choices?.[0]?.message?.content || data.error?.message || "", raw: data };
}

export async function POST(request: Request) {
  const body = await request.json();
  const prompt = String(body.prompt || "");
  const maxTokens = Number(body.maxTokens || 256);
  const decision = routeFor(prompt, maxTokens, String(body.mode || "auto"));
  const started = performance.now();
  try {
    const result = decision.provider === "cpu" ? await callCpu(prompt, maxTokens) : await callOpenAI(prompt, maxTokens);
    analytics.record({ provider: decision.provider, reason: decision.reason, latencyMs: performance.now() - started, ok: result.ok, createdAt: new Date().toISOString() });
    return Response.json({ provider: decision.provider, reason: decision.reason, text: result.text, raw: result.raw });
  } catch (error) {
    analytics.record({ provider: decision.provider, reason: decision.reason, latencyMs: performance.now() - started, ok: false, createdAt: new Date().toISOString() });
    return Response.json({ provider: decision.provider, reason: decision.reason, error: error instanceof Error ? error.message : String(error) }, { status: 500 });
  }
}
