type Provider = "cpu" | "openai";

type RequestLog = {
  provider: Provider;
  reason: string;
  latencyMs: number;
  ok: boolean;
  createdAt: string;
};

const logs: RequestLog[] = [];

function average(values: number[]) {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}

export const analytics = {
  record(log: RequestLog) {
    logs.unshift(log);
    logs.splice(200);
  },
  snapshot() {
    const total = logs.length;
    const cpu = logs.filter((log) => log.provider === "cpu");
    const openai = logs.filter((log) => log.provider === "openai");
    return {
      totalRequests: total,
      cpuRequests: cpu.length,
      openaiRequests: openai.length,
      cpuPercent: total ? (cpu.length / total) * 100 : 0,
      openaiPercent: total ? (openai.length / total) * 100 : 0,
      averageLatencyMsByProvider: {
        cpu: average(cpu.filter((log) => log.ok).map((log) => log.latencyMs)),
        openai: average(openai.filter((log) => log.ok).map((log) => log.latencyMs)),
      },
      latestRouteReason: logs[0]?.reason || "No requests yet.",
      recent: logs.slice(0, 10),
    };
  },
};
