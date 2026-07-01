type RequestLog = {
  provider: "cpu";
  latencyMs: number;
  outputChars: number;
  ok: boolean;
  createdAt: string;
};

const logs: RequestLog[] = [];

export const analytics = {
  record(log: RequestLog) {
    logs.unshift(log);
    logs.splice(100);
  },
  snapshot() {
    const total = logs.length;
    const successful = logs.filter((log) => log.ok);
    const latencyTotal = successful.reduce((sum, log) => sum + log.latencyMs, 0);
    const outputChars = successful.reduce((sum, log) => sum + log.outputChars, 0);
    const elapsedSeconds = latencyTotal / 1000;
    return {
      totalRequests: total,
      cpuRequests: total,
      averageLatencyMs: successful.length ? latencyTotal / successful.length : 0,
      lastLatencyMs: logs[0]?.latencyMs || 0,
      outputCharsPerSecond: elapsedSeconds > 0 ? outputChars / elapsedSeconds : 0,
      recent: logs.slice(0, 10),
    };
  },
};
