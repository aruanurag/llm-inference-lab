# Setup

## Step 0: Confirm Your Machine

Run:

```bash
uname -m
sw_vers
sysctl -n machdep.cpu.brand_string
```

Expected Apple Silicon architecture:

```text
arm64
```

Write the output in `results/observations.md`.

## Step 1: Install llama.cpp

The easiest path is Homebrew:

```bash
brew install llama.cpp
```

Verify:

```bash
llama-server --help
```

If the command is not found, try:

```bash
llama-server --version
```

## Step 2: Choose a Small GGUF Model

Start small. The first lab should run reliably before it tries to be impressive.

Good first choices:

- Qwen2.5 1.5B Instruct GGUF, Q4 or Q5
- Llama 3.2 1B or 3B Instruct GGUF, Q4 or Q5
- Phi 3 Mini GGUF, Q4, if memory allows

Create a model directory:

```bash
mkdir -p models
```

Download one GGUF file into `models/`.

For the first run, use Qwen2.5 1.5B Instruct with Q4_K_M quantization:

```bash
curl -L \
  "https://huggingface.co/bartowski/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf" \
  -o models/qwen2.5-1.5b-instruct-q4_k_m.gguf
```

This file is about 986 MB.

Final path:

```text
models/qwen2.5-1.5b-instruct-q4_k_m.gguf
```

## Step 3: Start the Server

From this lab directory:

```bash
./run.sh models/qwen2.5-1.5b-instruct-q4_k_m.gguf
```

The script starts `llama-server` on:

```text
http://127.0.0.1:8080
```

The server script also accepts tuning through environment variables:

```bash
CTX_SIZE=4096 \
PARALLEL=4 \
BATCH_SIZE=512 \
UBATCH_SIZE=128 \
GPU_LAYERS=auto \
./run.sh models/qwen2.5-1.5b-instruct-q4_k_m.gguf
```

Use these later in the lab. For the first run, keep the defaults.

`GPU_LAYERS` controls llama.cpp model offload:

```bash
GPU_LAYERS=0 ./run.sh models/qwen2.5-1.5b-instruct-q4_k_m.gguf
```

Runs CPU-only.

```bash
GPU_LAYERS=auto ./run.sh models/qwen2.5-1.5b-instruct-q4_k_m.gguf
```

Lets llama.cpp decide how much to offload to Metal.

```bash
GPU_LAYERS=all ./run.sh models/qwen2.5-1.5b-instruct-q4_k_m.gguf
```

Attempts to offload all possible layers to the GPU.

## Step 4: Verify the Server

In another terminal:

```bash
curl http://127.0.0.1:8080/health
```

Then send one OpenAI-compatible request:

```bash
curl http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "local-model",
    "messages": [
      {
        "role": "user",
        "content": "Explain TTFT in one sentence."
      }
    ],
    "stream": true,
    "max_tokens": 64
  }'
```

## Step 5: Run the First Benchmark

```bash
python3 benchmark.py \
  --url http://127.0.0.1:8080/v1/chat/completions \
  --experiment single-short \
  --prompt "Explain KV cache in two sentences." \
  --max-tokens 64 \
  --concurrency 1
```

## If Setup Fails

Keep the failure as part of the lab.

Record:

- exact command
- exact error
- machine type
- model file
- what you tried next

The first useful result may be: this model/runtime/configuration does not work on this machine.
