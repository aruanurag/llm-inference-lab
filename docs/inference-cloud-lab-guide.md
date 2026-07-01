# Inference Cloud Lab Guide

This guide walks through using the local **OCI Inference Cloud** app to provision OCI infrastructure, deploy an inference endpoint with `llama.cpp`, run benchmark presets, and compare models, shapes, and deploy settings.

The app runs on your laptop. It uses your local OCI CLI profile, provisions OCI instances into existing networking, and keeps generated SSH keys, logs, prompts, and benchmark results outside the repo.

## What You Will Build

By the end of this lab you will have:

- a local web app running at `http://127.0.0.1:5173`
- a FastAPI backend running at `http://127.0.0.1:8090`
- one OCI experiment with a CPU/HPC instance
- `llama.cpp` deployed on that instance
- a private `llama-server` endpoint reached through an SSH tunnel
- benchmark results for latency, TTFT, throughput, and concurrency
- a local OpenAI-compatible endpoint for sample hackathon apps

## Architecture

```text
Browser UI
  |
  | http://127.0.0.1:5173
  v
Local FastAPI backend
  |
  | OCI CLI
  v
OCI Compute instance

Local FastAPI backend
  |
  | SSH tunnel
  v
remote 127.0.0.1:8080 llama-server
```

The inference server is not exposed publicly. The app connects to it through SSH.

## Prerequisites

Install these locally:

- Python 3.10 or newer
- Node.js 20 or newer
- Git
- OCI CLI
- An OCI tenancy, compartment, VCN, subnet, and permissions to create Compute instances

The lab assumes you already have OCI networking. The app does not create VCNs, subnets, route tables, gateways, or security lists in v1.

## Step 1: Install OCI CLI

On macOS with Homebrew:

```bash
brew install oci-cli
```

Or use Oracle's installer:

```bash
bash -c "$(curl -L https://raw.githubusercontent.com/oracle/oci-cli/master/scripts/install/install.sh)"
```

Verify:

```bash
oci --version
```

## Step 2: Configure OCI CLI

Run:

```bash
oci setup config
```

You will be asked for:

- user OCID
- tenancy OCID
- region, such as `us-ashburn-1`
- private key location
- public key upload confirmation

The OCI CLI writes profiles to:

```text
~/.oci/config
```

Typical profile shape:

```ini
[DEFAULT]
user=ocid1.user.oc1...
fingerprint=...
tenancy=ocid1.tenancy.oc1...
region=us-ashburn-1
key_file=/Users/you/.oci/oci_api_key.pem
```

Test the profile:

```bash
oci iam region list
```

If you use multiple profiles, test the one you plan to use:

```bash
oci iam region list --profile DEFAULT
```

## Step 3: Confirm OCI Access

Confirm you can list compartments:

```bash
oci iam compartment list --compartment-id-in-subtree true
```

Confirm you can list compute shapes in your compartment:

```bash
oci compute shape list \
  --compartment-id <your_compartment_ocid> \
  --all
```

Confirm you have an existing VCN and subnet:

```bash
oci network vcn list --compartment-id <your_compartment_ocid>
```

```bash
oci network subnet list --compartment-id <your_compartment_ocid>
```

For the first CPU lab, the subnet should allow SSH from your machine. If you use a private subnet, you need a path to SSH into the instance, such as a bastion or VPN.

## Step 4: Start the Inference Cloud App

From the repo root:

```bash
cd apps/oci-inference-cloud/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8090
```

In another terminal:

```bash
cd apps/oci-inference-cloud/frontend
npm install
npm run dev -- --host 127.0.0.1
```

Open:

```text
http://127.0.0.1:5173
```

## Step 5: Create an Experiment

On the landing page:

1. Create a new experiment.
2. Use a name like `Qwen 7B throughput on 8 OCPU`.
3. Use a description that records the intent, such as `Primary throughput run for model and shape comparison`.

Each experiment keeps its own infrastructure, deployment state, benchmark runs, endpoint logs, and export bundle.

## Step 6: Load OCI Context

In **OCI context**:

1. Select your OCI CLI profile.
2. Confirm the region.
3. Click **Load OCI**.
4. Select the compartment where the instance should be created.

The app reads local OCI CLI profiles. It does not store OCI API keys.

## Step 7: Provision the Experiment Instance

In **Provision experiment instance**:

1. Select an availability domain.
2. Select an existing VCN.
3. Select a subnet.
4. Set **Shape family** to `CPU/HPC shapes`.
5. Choose a shape.
6. For flexible shapes, start with:

```text
OCPUs: 4
Memory GB: 32
```

7. Select an Oracle Linux image.
8. Select or generate an SSH key.
9. Click **Provision**.

Wait until the instance state becomes `RUNNING` and it has an IP address.

## Step 8: Deploy llama.cpp

In **Deploy llama.cpp**:

1. Select the running instance.
2. Select a model.
3. For deploy-setting comparison runs, open **Advanced settings** and optionally enable `-DGGML_NATIVE=ON`.
4. Keep **Disable VNNI instructions** enabled unless you have verified the remote compiler and assembler support VNNI instructions.
5. Click **Deploy**.

The app connects over SSH and runs a remote install script. It:

- installs build tools
- clones `llama.cpp`
- builds `llama-server`
- downloads the default GGUF model
- starts `llama-server` on remote `127.0.0.1:8080`

The default model is:

```text
Qwen2.5-1.5B-Instruct-Q4_K_M.gguf
```

For stronger throughput experiments, choose a larger model:

| Model | Suggested shape size | Use when |
|---|---:|---|
| Qwen2.5 1.5B Instruct Q4_K_M | 4 OCPU / 32 GB | Smoke test and fast validation |
| Qwen2.5 7B Instruct Q4_K_M | 8 OCPU / 64 GB | First serious model/shape throughput comparison |
| Qwen2.5 7B Instruct Q8_0 | 8 OCPU / 96 GB | Heavier 7B run when Q4 is too easy |
| Qwen2.5 14B Instruct Q4_K_M | 16 OCPU / 128 GB | Best catalog option for showing separation across larger shapes |
| Custom GGUF URL | Depends on model | Bring your own directly downloadable GGUF |
 
The native build option changes the llama.cpp CMake flags:

```bash
-DGGML_NATIVE=ON
```

When native build is off, the app uses portable CPU flags for compatibility:

```bash
-DGGML_NATIVE=OFF
-DGGML_AVX512=OFF
-DGGML_AVX512_VBMI=OFF
-DGGML_AVX512_VNNI=OFF
```

Use portable mode for first deploys. Use native mode when comparing the same shape with different llama.cpp build settings.

If native mode fails with an error like:

```text
unsupported instruction `vpdpbusd`
```

retry with **Disable VNNI instructions** enabled. This keeps the native build path but adds:

```bash
-DGGML_AVX_VNNI=OFF
-DGGML_AVX512_VNNI=OFF
-DCMAKE_C_FLAGS="-mno-avxvnni -mno-avx512vnni"
-DCMAKE_CXX_FLAGS="-mno-avxvnni -mno-avx512vnni"
```

Remote model path:

```text
$HOME/oci-inference-cloud/models/qwen2.5-1.5b-instruct-q4_k_m.gguf
```

The server runs with:

```bash
--ctx-size 4096
--parallel 4
--batch-size 512
--ubatch-size 128
```

## Step 9: Run Benchmark Presets

Open the **Benchmarks** view.

Start with **Throughput comparison**:

1. Preset: `Throughput comparison`
2. Compare as: `Primary run`
3. Prompt set: `Throughput comparison prompts`
4. Keep the default concurrency, request count, and max tokens for the first run.
5. Click **Run benchmark**.

The benchmark records:

- requests/sec
- output chars/sec
- approximate output tokens/sec
- TTFT p50/p95/p99
- latency p50/p95/p99
- approximate inter-token latency
- wall seconds
- shape and comparison lane metadata

Approximate tokens use:

```text
approx_output_tokens = output_chars / 4
```

This is intentionally approximate because tokenizer-level counting is not part of v1.

## Step 10: Compare Models, Shapes, and Deploy Settings

For a controlled comparison:

1. Create a second experiment, such as `Qwen 14B throughput on 16 OCPU`.
2. Change one variable: model, shape, OCPU count, memory, or deploy advanced settings.
3. Use the same prompt set, max tokens, request count, and concurrency as the first run.
4. Keep the benchmark preset unchanged.
5. In Benchmarks, use:

```text
Preset: Throughput comparison
Compare as: Comparison run
```

The comparison panel shows:

- approximate tokens/sec by lane
- output chars/sec by lane
- requests/sec by lane
- p95 latency by lane
- relative throughput versus the best Primary run

## Step 11: Start the Local Endpoint

Open the **Hackathon** view and click **Start endpoint**.

The app creates a local proxy endpoint:

```text
http://127.0.0.1:8090/api/experiments/<experiment_id>/endpoint/v1
```

Chat completions endpoint:

```text
POST http://127.0.0.1:8090/api/experiments/<experiment_id>/endpoint/v1/chat/completions
```

The remote `llama-server` stays private on the instance.

## Step 12: Try the Sample Apps

Direct CPU endpoint chat:

```bash
cd examples/direct-cpu-chat
npm install
CPU_ENDPOINT_URL=http://127.0.0.1:8090/api/experiments/<experiment_id>/endpoint/v1 \
PORT=3001 \
npm run dev
```

Open:

```text
http://127.0.0.1:3001
```

Router chat:

```bash
cd examples/router-chat
npm install
CPU_ENDPOINT_URL=http://127.0.0.1:8090/api/experiments/<experiment_id>/endpoint/v1 \
OPENAI_API_KEY=<your_openai_key> \
OPENAI_MODEL=gpt-4.1-mini \
PORT=3002 \
npm run dev
```

Open:

```text
http://127.0.0.1:3002
```

The router sample sends simple requests to the CPU endpoint and heavier requests to OpenAI. Its analytics panel shows CPU versus external LLM usage.

## Step 13: Export Results

Use **Export JSON** from the selected experiment.

The export includes:

- experiment metadata
- infrastructure records
- benchmark summaries
- endpoint status
- endpoint usage analytics

Generated state is stored outside the repo:

```text
~/.llm-inference-cloud/
├── state.db
├── keys/
├── prompts/
├── benchmarks/
└── logs/
```

## Step 14: Clean Up Infrastructure

When finished, use **Delete infra** from the selected experiment.

Then verify in OCI Console or CLI:

```bash
oci compute instance list \
  --compartment-id <your_compartment_ocid> \
  --lifecycle-state RUNNING
```

Do not leave benchmark instances running after the lab unless you intend to keep paying for them.

## Troubleshooting

If `Load OCI` fails:

- run `oci iam region list`
- confirm the selected profile exists in `~/.oci/config`
- confirm the profile has the right region
- confirm the user has access to the compartment

If provisioning fails:

- confirm you selected a subnet in the same compartment/region
- confirm the shape is available in the selected availability domain
- for flexible shapes, provide OCPUs and memory
- confirm your tenancy has quota for the shape

If deploy fails:

- open the deploy log shown in the UI
- confirm SSH works to the instance
- confirm the instance can reach package repositories and Hugging Face
- confirm there is enough disk space for build artifacts and the model

If benchmarks fail:

- confirm the instance is `RUNNING`
- confirm deploy completed successfully
- confirm `llama-server` is healthy on remote `127.0.0.1:8080`
- confirm the SSH key still exists under the app data directory

## Key Learning Questions

After running the lab, you should be able to answer:

- What throughput can a small quantized model deliver on a CPU shape?
- How does concurrency affect p95 latency and aggregate throughput?
- When does CPU inference look good enough?
- Which prompts stress prefill versus decode?
- How much relative throughput does a different model, shape, or deploy setting provide for the same workload?
- Which endpoint should a hackathon app use by default, and when should it route elsewhere?
