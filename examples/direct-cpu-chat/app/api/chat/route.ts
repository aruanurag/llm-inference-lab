import { analytics } from "./store";

export const runtime = "nodejs";

function chatUrl() {
  const base = process.env.CPU_ENDPOINT_URL;
  if (!base) throw new Error("CPU_ENDPOINT_URL is required.");
  return `${base.replace(/\/$/, "")}/chat/completions`;
}

export async function POST(request: Request) {
  const body = await request.json();
  const started = performance.now();
  let outputChars = 0;
  try {
    const response = await fetch(chatUrl(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "local-model",
        messages: [{ role: "user", content: body.prompt }],
        stream: false,
        max_tokens: Number(body.maxTokens || 256),
        temperature: 0,
      }),
    });
    const data = await response.json();
    const text = data.choices?.[0]?.message?.content || "";
    outputChars = text.length;
    analytics.record({ provider: "cpu", latencyMs: performance.now() - started, outputChars, ok: response.ok, createdAt: new Date().toISOString() });
    return Response.json({ provider: "cpu", text, raw: data });
  } catch (error) {
    analytics.record({ provider: "cpu", latencyMs: performance.now() - started, outputChars, ok: false, createdAt: new Date().toISOString() });
    return Response.json({ error: error instanceof Error ? error.message : String(error) }, { status: 500 });
  }
}
