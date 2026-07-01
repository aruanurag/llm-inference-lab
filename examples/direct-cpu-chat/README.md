# Direct CPU Chat

This sample calls the CPU inference endpoint created by `apps/oci-inference-cloud`.

## Run

```bash
cd examples/direct-cpu-chat
npm install
CPU_ENDPOINT_URL=http://127.0.0.1:8090/api/experiments/1/endpoint/v1 PORT=3001 npm run dev
```

Open `http://127.0.0.1:3001`.

The app keeps simple in-memory analytics for request count, CPU usage, latency, and output throughput.
