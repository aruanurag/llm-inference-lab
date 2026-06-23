# Lab 2: Running vLLM on OCI GPU

## Goal

Provision an OCI GPU instance, deploy vLLM, expose an OpenAI-compatible endpoint, and measure real inference behavior on a GPU.

By the end of this lab, you should be able to answer:

- How do I provision a GPU instance on OCI?
- Which OCI GPU shape is suitable for low-cost inference experiments?
- How do I install and run vLLM?
- How do I expose an OpenAI-compatible endpoint?
- What are TTFT, approximate ITL, latency, throughput, and concurrency metrics on a GPU-backed deployment?
- How does batching affect performance?
- How do I monitor GPU utilization and memory consumption?
- What is the approximate cost of running the experiment?

## What Changes From Lab 1

Lab 1 used `llama.cpp` locally on Apple Silicon.

Lab 2 moves to a GPU-backed server:

- runtime: `vLLM`
- hardware: OCI GPU instance
- API: OpenAI-compatible `/v1/chat/completions`
- monitoring: `nvidia-smi`
- cost: hourly GPU instance cost

## What You Will Measure

Core latency:

- TTFT: time to first token
- approximate ITL: time between non-empty streamed text chunks
- end-to-end latency

Throughput:

- requests per second
- output characters per second
- approximate generated tokens per second

GPU behavior:

- GPU utilization
- GPU memory usage
- power draw
- temperature

Cost:

- benchmark wall time
- cost per experiment
- approximate cost per million generated tokens

## Lab Flow

### Step 1: Provision the OCI GPU instance

Follow [setup.md](setup.md).

Record the instance details in [observations.md](observations.md):

- region
- availability domain
- shape
- GPU type
- GPU memory
- image
- hourly cost
- public IP

### Step 2: Install and verify vLLM

On the OCI instance, create a Python environment and install vLLM.

The setup guide uses the Python package path first. If you prefer Docker later, keep that as a future lab.

Verify:

```bash
python -c "import vllm; print(vllm.__version__)"
vllm serve --help
```

### Step 3: Start the vLLM server

From this lab directory on the OCI instance:

```bash
./run_vllm.sh
```

The default model is:

```text
Qwen/Qwen2.5-1.5B-Instruct
```

The default endpoint is:

```text
http://0.0.0.0:8000
```

The script prints and logs the exact `vllm serve` command.

### Step 4: Verify the endpoint

From the OCI instance:

```bash
curl http://127.0.0.1:8000/health
```

Send one test request:

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-1.5B-Instruct",
    "messages": [
      {
        "role": "user",
        "content": "Explain TTFT in one sentence."
      }
    ],
    "max_tokens": 64,
    "temperature": 0
  }'
```

Question to answer:

How long did vLLM take to load the model and become ready?

### Step 5: Monitor GPU usage

Run these in another SSH session while benchmarks are running.

Watch a live summary:

```bash
watch -n 1 nvidia-smi
```

Watch device metrics:

```bash
nvidia-smi dmon
```

Capture utilization, memory, power, and temperature:

```bash
nvidia-smi \
  --query-gpu=timestamp,name,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw,temperature.gpu \
  --format=csv \
  -l 1
```

Record observations:

- Did GPU utilization spike during prefill?
- Did memory usage change with concurrency?
- Did power draw rise during long output generation?
- Did temperature stabilize?

### Step 6: Experiment A, short prompt and short output

```bash
python3 benchmark.py \
  --url http://127.0.0.1:8000/v1/chat/completions \
  --model Qwen/Qwen2.5-1.5B-Instruct \
  --experiment a-short-prompt-short-output \
  --prompt "Explain KV cache in two sentences." \
  --max-tokens 64 \
  --concurrency 1
```

Question to answer:

What is the GPU-backed baseline TTFT and approximate ITL?

### Step 7: Experiment B, long prompt and short output

```bash
python3 benchmark.py \
  --url http://127.0.0.1:8000/v1/chat/completions \
  --model Qwen/Qwen2.5-1.5B-Instruct \
  --experiment b-long-prompt-short-output \
  --prompt-file prompts/long_prompt.txt \
  --max-tokens 64 \
  --concurrency 1
```

Question to answer:

How much does the longer prompt affect TTFT?

### Step 8: Experiment C, short prompt and long output

```bash
python3 benchmark.py \
  --url http://127.0.0.1:8000/v1/chat/completions \
  --model Qwen/Qwen2.5-1.5B-Instruct \
  --experiment c-short-prompt-long-output \
  --prompt "Write a compact tutorial on continuous batching in vLLM." \
  --max-tokens 256 \
  --concurrency 1
```

Question to answer:

How does decode length affect end-to-end latency and output throughput?

### Step 9: Experiment D, concurrency

Run the same workload at concurrency 1, 4, 8, and 16.

```bash
python3 benchmark.py \
  --url http://127.0.0.1:8000/v1/chat/completions \
  --model Qwen/Qwen2.5-1.5B-Instruct \
  --experiment d-concurrency-1 \
  --prompt "Explain why batching improves LLM serving throughput." \
  --max-tokens 128 \
  --concurrency 1 \
  --requests 8
```

```bash
python3 benchmark.py \
  --url http://127.0.0.1:8000/v1/chat/completions \
  --model Qwen/Qwen2.5-1.5B-Instruct \
  --experiment d-concurrency-4 \
  --prompt "Explain why batching improves LLM serving throughput." \
  --max-tokens 128 \
  --concurrency 4 \
  --requests 16
```

```bash
python3 benchmark.py \
  --url http://127.0.0.1:8000/v1/chat/completions \
  --model Qwen/Qwen2.5-1.5B-Instruct \
  --experiment d-concurrency-8 \
  --prompt "Explain why batching improves LLM serving throughput." \
  --max-tokens 128 \
  --concurrency 8 \
  --requests 32
```

```bash
python3 benchmark.py \
  --url http://127.0.0.1:8000/v1/chat/completions \
  --model Qwen/Qwen2.5-1.5B-Instruct \
  --experiment d-concurrency-16 \
  --prompt "Explain why batching improves LLM serving throughput." \
  --max-tokens 128 \
  --concurrency 16 \
  --requests 64
```

Questions to answer:

- Does requests/sec increase?
- What happens to p95 latency?
- Does GPU memory usage change?
- Does GPU utilization become steadier?

### Step 10: Experiment E, batching behavior

Stop the server:

```text
Ctrl+C
```

Or from another SSH session:

```bash
pkill -f "vllm serve"
```

Restart with explicit batching-related limits:

```bash
MAX_NUM_SEQS=16 \
MAX_NUM_BATCHED_TOKENS=4096 \
MAX_MODEL_LEN=4096 \
./run_vllm.sh
```

Run the concurrency workload again:

```bash
python3 benchmark.py \
  --url http://127.0.0.1:8000/v1/chat/completions \
  --model Qwen/Qwen2.5-1.5B-Instruct \
  --experiment e-batching-limits \
  --prompt-file prompts/long_prompt.txt \
  --max-tokens 128 \
  --concurrency 8 \
  --requests 32
```

Questions to answer:

- Did p95 latency improve or get worse?
- Did requests/sec change?
- Did GPU memory usage change?
- Did the server reject or queue more work?

### Step 11: Summarize results

If you know the hourly OCI instance cost, pass it here:

```bash
python3 collect_metrics.py \
  --input results/raw \
  --output results/summary.json \
  --csv-output results/summary.csv \
  --hourly-cost-usd 1.25
```

If you do not know the cost yet:

```bash
python3 collect_metrics.py --input results/raw --output results/summary.json
```

### Step 12: Visualize results

Open the dashboard:

[results_dashboard.html](results_dashboard.html)

Select JSON files from:

```text
results/raw/
```

You can also select:

```text
results/summary.json
```

Enter the hourly OCI instance cost in the dashboard if the loaded files do not already include cost fields.

The dashboard compares:

- latency p95
- TTFT p95
- approximate ITL p95
- requests/sec
- generated token estimate
- estimated cost per run
- estimated cost per million generated tokens

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

Server logs are written under:

```text
results/logs/
```

## Notes While Running

Record observations in:

```text
observations.md
```

Keep notes practical:

- instance shape and GPU
- hourly cost
- vLLM version
- model
- startup time
- GPU utilization
- GPU memory
- latency and throughput changes
- failures or quota limits
