# Lab 2 Observations

## OCI Instance

- Date:
- Region:
- Availability domain:
- Image:
- Shape:
- OCPUs:
- RAM:
- GPU type:
- GPU memory:
- Public IP:
- Hourly cost:

## Networking

- SSH source CIDR:
- vLLM port:
- vLLM source CIDR:
- SSH tunnel used:

## vLLM Setup

- Python version:
- vLLM version:
- NVIDIA driver version:
- CUDA version from `nvidia-smi`:
- Model:
- Dtype:
- Max model length:
- Max sequences:
- Max batched tokens:

## Startup

- Command:
- Startup time:
- Health check result:
- Notes:

## GPU Monitoring

- `nvidia-smi` idle memory:
- Peak GPU utilization:
- Peak memory used:
- Peak power draw:
- Peak temperature:
- Notes during prefill:
- Notes during decode:
- Notes during concurrency:

## Cost Tracking

- Hourly cost:
- Total benchmark runtime:
- Estimated total cost:
- Approximate generated tokens:
- Approximate cost per million generated tokens:

## Experiment A: Short Prompt, Short Output

- Command:
- TTFT:
- Approximate ITL:
- End-to-end latency:
- Output throughput:
- GPU utilization notes:

## Experiment B: Long Prompt, Short Output

- Command:
- TTFT:
- Approximate ITL:
- End-to-end latency:
- Prefill observation:
- GPU utilization notes:

## Experiment C: Short Prompt, Long Output

- Command:
- TTFT:
- Approximate ITL:
- End-to-end latency:
- Decode throughput:
- GPU utilization notes:

## Experiment D: Concurrency

- Commands:
- Concurrency levels:
- Requests per second:
- p50 latency:
- p95 latency:
- GPU memory notes:
- GPU utilization notes:

## Experiment E: Batching Behavior

- Server command:
- Max model length:
- Max sequences:
- Max batched tokens:
- Requests per second:
- p95 latency:
- Throughput:
- GPU memory notes:
- Stability notes:
