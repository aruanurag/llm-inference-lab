# Setup

## Step 0: Pick a Low-Cost GPU Shape

Use the lowest-cost NVIDIA GPU shape available in your OCI region that has enough GPU memory for a small instruct model.

Good targets for this lab:

- NVIDIA A10 / A10G-class GPU, if available
- the smallest available OCI NVIDIA GPU shape in your region

Record in `observations.md`:

- region
- availability domain
- shape
- GPU type
- GPU memory
- OCPU count
- RAM
- hourly cost

Pricing changes by region and date, so copy the current hourly price from the OCI Console or Oracle pricing page when you create the instance.

## Step 1: Create the Instance

In the OCI Console:

1. Go to Compute > Instances.
2. Create an instance.
3. Choose an Ubuntu image.
4. Choose a GPU shape.
5. Add your SSH public key.
6. Use a VCN/subnet that can be reached from your machine.
7. Create the instance.

Security rule:

- allow SSH port `22` from your IP only
- allow vLLM port `8000` from your IP only

Do not expose port `8000` to `0.0.0.0/0` for this learning lab.

## Step 2: Connect With SSH

Replace the host and key path:

```bash
ssh -i ~/.ssh/id_rsa ubuntu@PUBLIC_IP
```

Some OCI images use `opc` instead of `ubuntu`:

```bash
ssh -i ~/.ssh/id_rsa opc@PUBLIC_IP
```

## Step 3: Verify NVIDIA Driver and GPU

Run:

```bash
nvidia-smi
```

Record:

- GPU name
- driver version
- CUDA version shown by `nvidia-smi`
- total GPU memory

If `nvidia-smi` is not found or fails, install the OCI/NVIDIA driver path recommended for the image and shape you chose. Some OCI GPU images already include drivers; some base Ubuntu images require driver setup.

## Step 4: Install System Packages

First check which Linux distribution you are using:

```bash
cat /etc/os-release
```

If the instance uses Ubuntu or Debian:

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip git curl jq
```

If the instance uses Oracle Linux, use `dnf`:

```bash
sudo dnf install -y python3 python3-pip git curl jq
```

If `dnf` fails on an optional repository such as `ol9_ksplice`, disable that repository for this install:

```bash
sudo dnf --disablerepo=ol9_ksplice install -y python3 python3-pip git curl jq
```

If `dnf` is not available but `yum` is:

```bash
sudo yum install -y python3 python3-pip git curl jq
```

On Oracle Linux, the Python `venv` module is usually included with Python 3. If `python3 -m venv .venv` fails in the next step, install the matching Python venv package for your image or use a Conda/Mambaforge environment.

If package metadata downloads time out, confirm the instance has outbound HTTPS access:

```bash
curl -I https://yum.us-ashburn-1.oci.oraclecloud.com/
curl -I https://github.com/
```

If those commands time out, check the subnet route table and security rules. A private subnet needs a NAT gateway or service gateway. A public subnet needs an internet gateway, a route to it, and outbound security rules that allow TCP `443`.

## Step 5: Create a Python Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

## Step 6: Install vLLM

For NVIDIA CUDA, start with:

```bash
pip install vllm --extra-index-url https://download.pytorch.org/whl/cu129
```

The vLLM GPU install docs also document `uv pip install vllm --torch-backend=auto`. If the `pip` command fails because of Python, CUDA, or wheel compatibility, check the current official vLLM GPU install page and use the wheel path matching your environment.

Verify:

```bash
python -c "import vllm; print(vllm.__version__)"
vllm serve --help
```

If `vllm serve` is not available, try:

```bash
c
```

## Step 7: Copy This Lab to the Instance

From your local machine, copy the lab folder:

```bash
scp -r labs/02-vllm-on-oci ubuntu@PUBLIC_IP:~/02-vllm-on-oci
```

Or clone the repository on the instance:

```bash
git clone https://github.com/aruanurag/llm-inference-lab.git
cd llm-inference-lab/labs/02-vllm-on-oci
```

## Step 8: Start vLLM

From the lab directory on the OCI instance:

```bash
source .venv/bin/activate
./run_vllm.sh
```

Defaults:

```text
MODEL=Qwen/Qwen2.5-1.5B-Instruct
HOST=0.0.0.0
PORT=8000
DTYPE=auto
```

Optional batching-related settings:

```bash
MAX_MODEL_LEN=4096 \
MAX_NUM_SEQS=16 \
MAX_NUM_BATCHED_TOKENS=4096 \
./run_vllm.sh
```

## Step 9: Verify Locally on the Instance

```bash
curl http://127.0.0.1:8000/health
```

```bash
curl http://127.0.0.1:8000/v1/models
```

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-1.5B-Instruct",
    "messages": [
      {
        "role": "user",
        "content": "Explain vLLM continuous batching in one paragraph."
      }
    ],
    "max_tokens": 128,
    "temperature": 0
  }'
```

## Step 10: Optional Remote Access From Your Laptop

The safer path is an SSH tunnel:

```bash
ssh -i ~/.ssh/id_rsa -L 8000:127.0.0.1:8000 ubuntu@PUBLIC_IP
```

Then your laptop can use:

```text
http://127.0.0.1:8000
```

If you use a public ingress rule instead, restrict source CIDR to your own IP.

## References

- vLLM GPU installation docs: https://docs.vllm.ai/en/latest/getting_started/installation/gpu/
- vLLM OpenAI-compatible server docs: https://docs.vllm.ai/en/latest/serving/openai_compatible_server/
- OCI Compute pricing: https://www.oracle.com/cloud/compute/pricing/
