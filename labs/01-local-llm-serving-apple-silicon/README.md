# Lab 1: Local LLM Serving on Apple Silicon

## Goal

Start a local LLM server on a Mac mini, send real requests to it, and measure basic inference metrics.

By the end of this lab, you should be able to answer:

- Can I start a local model server on this machine?
- What model can realistically run here?
- How long does the server take to start?
- What is time to first token?
- How fast do output tokens stream?
- How does concurrency change latency and throughput?
- What changes when prompts get longer?
- What changes when outputs get longer?
- What changes when server batching knobs are adjusted?

## Runtime Choice

This lab uses `llama.cpp` first.

Why?

- It works well on Apple Silicon.
- It supports Metal acceleration.
- It runs quantized GGUF models.
- It exposes an OpenAI-compatible HTTP API.
- It is simple enough for a first reproducible lab.

vLLM is still useful later, especially on NVIDIA GPUs. For this first Mac mini lab, `llama.cpp` is the lower-friction way to observe inference behavior.

## What You Will Measure

Core latency:

- TTFT: time to first token
- approximate ITL: time between non-empty streamed text chunks
- end-to-end latency

Throughput:

- output tokens per second
- requests per second
- approximate total tokens per second

System behavior:

- startup time
- CPU and memory usage
- GPU / Metal offload mode
- concurrency level
- batch size and micro-batch size
- p50 / p95 / p99 latency

## Lab Flow

### Step 1: Set up the runtime

Follow [setup.md](setup.md).

At the end of setup, you should have a local server responding at:

```text
http://127.0.0.1:8080
```

When the server starts, read the printed command and the startup log under `results/logs/`. The `GPU layers` value tells you the intended offload mode:

- `GPU_LAYERS=0`: CPU-only
- `GPU_LAYERS=auto`: llama.cpp decides Metal offload automatically
- `GPU_LAYERS=all`: try to offload all possible layers to Metal

### Step 2: Run one short request

This establishes the baseline.

```bash
python3 benchmark.py \
  --url http://127.0.0.1:8080/v1/chat/completions \
  --experiment single-short \
  --prompt "Explain KV cache in two sentences." \
  --max-tokens 64 \
  --concurrency 1
```

Question to answer:

What is the first-token delay before generation starts?

Also look at `approx_itl_seconds` in the benchmark output. This estimates how quickly generated chunks arrive after the first chunk.

### Step 3: Observe CPU and GPU usage

Keep `llama-server` running and run these commands in another terminal.

Find the server process:

```bash
pgrep -fl llama-server
```

Watch CPU and memory for the process:

```bash
top -pid $(pgrep -n llama-server)
```

Take a one-shot process snapshot:

```bash
ps -o pid,%cpu,%mem,rss,command -p $(pgrep -n llama-server)
```

Open Activity Monitor for a visual check:

```bash
open -a "Activity Monitor"
```

In Activity Monitor:

- CPU tab shows CPU usage for `llama-server`.
- Memory tab shows RAM usage.
- Window > GPU History shows Apple GPU activity.

For command-line GPU sampling on macOS, use `powermetrics`:

```bash
sudo powermetrics --samplers gpu_power -i 1000
```

If that sampler is not available on your macOS version, try:

```bash
sudo powermetrics -i 1000
```

What to record:

- `GPU_LAYERS` value from `run.sh` output
- whether startup logs mention Metal
- CPU usage during the benchmark
- memory usage during the benchmark
- whether GPU History moves during generation

### Step 4: Increase prompt length

This isolates prefill cost.

```bash
python3 benchmark.py \
  --url http://127.0.0.1:8080/v1/chat/completions \
  --experiment long-prompt-short-output \
  --prompt-file prompts/long_prompt.txt \
  --max-tokens 64 \
  --concurrency 1
```

Question to answer:

Does TTFT increase when the prompt gets longer?

### Step 5: Increase output length

This isolates decode cost.

```bash
python3 benchmark.py \
  --url http://127.0.0.1:8080/v1/chat/completions \
  --experiment short-prompt-long-output \
  --prompt "Write a compact tutorial on continuous batching." \
  --max-tokens 256 \
  --concurrency 1
```

Question to answer:

Does end-to-end latency increase mostly because more tokens are decoded?

### Step 6: Add concurrency

This shows how serving behavior changes under load.

```bash
python3 benchmark.py \
  --url http://127.0.0.1:8080/v1/chat/completions \
  --experiment concurrent-short \
  --prompt "Explain why batching helps inference throughput." \
  --max-tokens 128 \
  --concurrency 4 \
  --requests 12
```

Question to answer:

Does throughput improve, and what happens to p95 latency?

### Step 7: Change batching settings

This shows how server-side batching knobs affect prompt processing and concurrent work.

`llama.cpp` exposes two useful knobs:

- `BATCH_SIZE`: logical batch size. This affects how much prompt work the server tries to process together.
- `UBATCH_SIZE`: physical micro-batch size. This controls how that work is split into smaller chunks.

The exact best values depend on model size, context size, memory, and hardware. In this step, keep the benchmark the same and only restart the server with different values.

Stop the currently running server.

If `llama-server` is running in your current terminal, press:

```text
Ctrl+C
```

If it is running in another terminal and you need a command, use:

```bash
pkill -f "llama-server"
```

Then start a conservative baseline:

```bash
BATCH_SIZE=256 UBATCH_SIZE=64 ./run.sh models/qwen2.5-1.5b-instruct-q4_k_m.gguf
```

Check the startup output. It should include:

```text
Batch size: 256
Micro-batch size: 64
```

If the benchmark still appears to use the old settings, an older server is probably still running. Stop it with `pkill -f "llama-server"` and start again.

Run:

```bash
python3 benchmark.py \
  --url http://127.0.0.1:8080/v1/chat/completions \
  --experiment batch-256-ubatch-64 \
  --prompt-file prompts/long_prompt.txt \
  --max-tokens 128 \
  --concurrency 4 \
  --requests 12
```

Stop the server again:

```text
Ctrl+C
```

Or, from another terminal:

```bash
pkill -f "llama-server"
```

Then try a larger setting:

```bash
BATCH_SIZE=1024 UBATCH_SIZE=256 ./run.sh models/qwen2.5-1.5b-instruct-q4_k_m.gguf
```

Run the same benchmark:

```bash
python3 benchmark.py \
  --url http://127.0.0.1:8080/v1/chat/completions \
  --experiment batch-1024-ubatch-256 \
  --prompt-file prompts/long_prompt.txt \
  --max-tokens 128 \
  --concurrency 4 \
  --requests 12
```

Questions to answer:

- Did TTFT improve or get worse?
- Did p95 latency improve or get worse?
- Did throughput improve?
- Did memory usage change?
- Did either setting make the server unstable?

### Step 8: Summarize results

```bash
python3 collect_metrics.py --input results/raw --output results/summary.json
```

Open the summary and compare experiments.

### Step 9: Visualize results

Open the dashboard in your browser:

[results_dashboard.html](results_dashboard.html)

Use the file picker to select one or more JSON files from:

```text
results/raw/
```

The dashboard compares:

- latency p95
- TTFT p95
- approximate ITL p95
- requests per second
- output characters per second
- concurrency and request counts

## Result Files

Benchmark output is written under:

```text
results/raw/
```

Summaries are written under:

```text
results/summary.json
results/summary.csv
```

## Notes While Running

Record observations in:

```text
results/observations.md
```

Keep notes practical:

- model used
- quantization used
- machine specs
- startup time
- surprising latency changes
- resource usage
- anything that failed
