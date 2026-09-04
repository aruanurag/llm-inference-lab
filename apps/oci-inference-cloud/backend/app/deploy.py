from __future__ import annotations

import re
import shlex
import textwrap
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import LOGS_DIR
from .ssh import run_ssh
from .state import utc_now


LLAMA_CPP_MODEL_CATALOG: list[dict[str, Any]] = [
    {
        "id": "qwen2.5-1.5b-q4_k_m",
        "name": "Qwen2.5 1.5B Instruct Q4_K_M",
        "size_label": "1.5B",
        "quantization": "Q4_K_M",
        "url": "https://huggingface.co/bartowski/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf",
        "filename": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "recommended_ocpus": 4,
        "recommended_memory_gbs": 32,
        "description": "Fast smoke-test model. Good for validating deployment, but usually too small to separate similar shapes clearly.",
    },
    {
        "id": "qwen2.5-7b-q4_k_m",
        "name": "Qwen2.5 7B Instruct Q4_K_M",
        "size_label": "7B",
        "quantization": "Q4_K_M",
        "url": "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        "filename": "qwen2.5-7b-instruct-q4_k_m.gguf",
        "recommended_ocpus": 8,
        "recommended_memory_gbs": 64,
        "description": "Recommended first serious throughput comparison model across CPU shapes, OCPU counts, and deploy settings.",
    },
    {
        "id": "qwen2.5-7b-q8_0",
        "name": "Qwen2.5 7B Instruct Q8_0",
        "size_label": "7B",
        "quantization": "Q8_0",
        "url": "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q8_0.gguf",
        "filename": "qwen2.5-7b-instruct-q8_0.gguf",
        "recommended_ocpus": 8,
        "recommended_memory_gbs": 96,
        "description": "Heavier 7B variant. Useful when Q4 does not create enough separation between shapes.",
    },
    {
        "id": "qwen2.5-14b-q4_k_m",
        "name": "Qwen2.5 14B Instruct Q4_K_M",
        "size_label": "14B",
        "quantization": "Q4_K_M",
        "url": "https://huggingface.co/bartowski/Qwen2.5-14B-Instruct-GGUF/resolve/main/Qwen2.5-14B-Instruct-Q4_K_M.gguf",
        "filename": "qwen2.5-14b-instruct-q4_k_m.gguf",
        "recommended_ocpus": 16,
        "recommended_memory_gbs": 128,
        "description": "Best catalog choice for showing meaningful throughput separation across larger shapes or more aggressive deploy settings.",
    },
]

VLLM_CPU_MODEL_CATALOG: list[dict[str, Any]] = [
    {
        "id": "qwen2.5-1.5b-instruct",
        "name": "Qwen2.5 1.5B Instruct",
        "size_label": "1.5B",
        "quantization": "BF16",
        "url": "Qwen/Qwen2.5-1.5B-Instruct",
        "filename": "",
        "recommended_ocpus": 4,
        "recommended_memory_gbs": 32,
        "description": "Public Hugging Face weights for CPU vLLM. A small, practical first CPU serving and vLLM bench serve workload.",
    },
    {
        "id": "qwen2.5-7b-instruct",
        "name": "Qwen2.5 7B Instruct",
        "size_label": "7B",
        "quantization": "BF16",
        "url": "Qwen/Qwen2.5-7B-Instruct",
        "filename": "",
        "recommended_ocpus": 8,
        "recommended_memory_gbs": 64,
        "description": "Public Hugging Face weights for a more demanding CPU vLLM comparison. Use identical OCPUs, memory, and vLLM settings across shapes.",
    },
]

MODEL_CATALOGS = {
    "llama_cpp": LLAMA_CPP_MODEL_CATALOG,
    "vllm_cpu": VLLM_CPU_MODEL_CATALOG,
}


def list_deploy_models(engine: str = "llama_cpp") -> list[dict[str, Any]]:
    if engine not in MODEL_CATALOGS:
        raise ValueError(f"Unknown inference engine: {engine}")
    return [{**model, "engine": engine} for model in MODEL_CATALOGS[engine]]


def _safe_filename(value: str) -> str:
    filename = Path(urlparse(value).path).name or "model.gguf"
    filename = re.sub(r"[^A-Za-z0-9._-]+", "-", filename)
    if not filename.lower().endswith(".gguf"):
        filename = f"{filename}.gguf"
    return filename.lower()


def resolve_model(config: dict[str, Any]) -> dict[str, Any]:
    engine = config.get("engine") or "llama_cpp"
    catalog = MODEL_CATALOGS.get(engine)
    if not catalog:
        raise ValueError(f"Unknown inference engine: {engine}")
    model_id = config.get("model_id") or catalog[0]["id"]
    if model_id == "custom":
        source = (config.get("custom_model_url") or "").strip()
        if engine == "llama_cpp":
            if not source.startswith(("https://", "http://")):
                raise ValueError("Custom llama.cpp model URL must start with https:// or http://.")
            filename = _safe_filename(source)
        else:
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", source):
                raise ValueError("Custom CPU vLLM model must be a public Hugging Face repository ID such as org/model.")
            filename = ""
        return {
            "id": "custom",
            "name": (config.get("custom_model_name") or source).strip() or source,
            "url": source,
            "filename": filename,
            "engine": engine,
        }
    for model in catalog:
        if model["id"] == model_id:
            return {**model, "engine": engine}
    raise ValueError(f"Unknown deploy model: {model_id}")


def deployment_script(config: dict[str, Any] | None = None) -> str:
    config = config or {}
    engine = config.get("engine") or "llama_cpp"
    if engine == "vllm_cpu":
        return vllm_cpu_deployment_script(config)
    model = resolve_model(config)
    build_native = bool(config.get("build_native", False))
    disable_vnni = bool(config.get("disable_vnni", True))
    ctx_size = int(config.get("ctx_size") or 4096)
    parallel = int(config.get("parallel") or 4)
    batch_size = int(config.get("batch_size") or 512)
    ubatch_size = int(config.get("ubatch_size") or 128)

    if build_native:
        cmake_flags = ["-DGGML_NATIVE=ON"]
        if disable_vnni:
            cmake_flags.extend(
                [
                    "-DGGML_AVX_VNNI=OFF",
                    "-DGGML_AVX512_VNNI=OFF",
                    "-DCMAKE_C_FLAGS=-mno-avxvnni -mno-avx512vnni",
                    "-DCMAKE_CXX_FLAGS=-mno-avxvnni -mno-avx512vnni",
                ]
            )
        build_label = "native optimized CPU execution"
    else:
        cmake_flags = ["-DGGML_NATIVE=OFF", "-DGGML_AVX512=OFF", "-DGGML_AVX512_VBMI=OFF", "-DGGML_AVX512_VNNI=OFF"]
        build_label = "portable CPU execution"

    model_url = shlex.quote(model["url"])
    model_name = shlex.quote(model["name"])
    model_filename = shlex.quote(model["filename"])
    cmake_flags_text = " ".join(cmake_flags)
    cmake_flags_shell = " ".join(shlex.quote(flag) for flag in cmake_flags)
    return textwrap.dedent(
        f"""
        set -euo pipefail
        MODEL_URL={model_url}
        MODEL_NAME={model_name}
        MODEL_FILENAME={model_filename}
        MODEL_PATH="$HOME/oci-inference-cloud/models/$MODEL_FILENAME"

        echo "[1/7] Preparing remote directories"
        mkdir -p "$HOME/oci-inference-cloud/models" "$HOME/oci-inference-cloud/logs"

        echo "[2/7] Installing OS build dependencies"
        if command -v dnf >/dev/null 2>&1; then
          sudo dnf --disablerepo=ol9_ksplice install -y git cmake gcc gcc-c++ make curl || sudo dnf install -y git cmake gcc gcc-c++ make curl
        elif command -v apt-get >/dev/null 2>&1; then
          sudo apt-get update
          sudo apt-get install -y git cmake build-essential curl
        else
          echo "Unsupported Linux distribution: missing dnf and apt-get"
          exit 1
        fi

        echo "[3/7] Fetching llama.cpp source"
        cd "$HOME/oci-inference-cloud"
        if [ ! -d llama.cpp ]; then
          git clone https://github.com/ggml-org/llama.cpp.git
        fi

        echo "[4/7] Building llama.cpp for {build_label}"
        cd llama.cpp
        git pull --ff-only || true
        rm -rf build
        echo "CMake flags: {cmake_flags_text}"
        cmake -B build {cmake_flags_shell}
        cmake --build build --config Release -j"$(nproc)" || exit 1
        test -x "$HOME/oci-inference-cloud/llama.cpp/build/bin/llama-server" || {{
          echo "llama-server binary was not produced by the build"
          exit 1
        }}

        echo "[5/7] Downloading GGUF model: $MODEL_NAME"
        if [ ! -f "$MODEL_PATH" ]; then
          curl -fL "$MODEL_URL" -o "$MODEL_PATH"
        else
          echo "Model already exists at $MODEL_PATH"
        fi

        echo "[6/7] Starting llama-server on remote localhost"
        if [ -f "$HOME/oci-inference-cloud/logs/llama-server.pid" ]; then
          kill "$(cat "$HOME/oci-inference-cloud/logs/llama-server.pid")" >/dev/null 2>&1 || true
          rm -f "$HOME/oci-inference-cloud/logs/llama-server.pid"
        fi
        nohup "$HOME/oci-inference-cloud/llama.cpp/build/bin/llama-server" \
          --model "$MODEL_PATH" \
          --host 127.0.0.1 \
          --port 8080 \
          --ctx-size {ctx_size} \
          --parallel {parallel} \
          --batch-size {batch_size} \
          --ubatch-size {ubatch_size} \
          > "$HOME/oci-inference-cloud/logs/llama-server.log" 2>&1 &
        echo "$!" > "$HOME/oci-inference-cloud/logs/llama-server.pid"

        echo "[7/7] Verifying llama-server health"
        for attempt in $(seq 1 30); do
          if curl -fsS http://127.0.0.1:8080/health; then
            exit 0
          fi
          sleep 2
        done
        echo "llama-server did not become healthy. Server log follows:"
        tail -n 80 "$HOME/oci-inference-cloud/logs/llama-server.log" || true
        exit 1
        """
    ).strip()


def vllm_cpu_deployment_script(config: dict[str, Any] | None = None) -> str:
    """Render a CPU vLLM install and local-only serve script.

    This follows the vLLM CPU guidance for AMD Zen: install the CPU wheel with
    the ``zen`` extra, reserve a frontend CPU, and let vLLM select ZenDNN
    kernels when they are available. The model is an HF repository ID rather
    than a GGUF download URL.
    """
    config = {**(config or {}), "engine": "vllm_cpu"}
    model = resolve_model(config)
    ctx_size = int(config.get("ctx_size") or 4096)
    parallel = int(config.get("parallel") or 4)
    kv_cache_gib = int(config.get("cpu_kv_cache_gib") or 8)
    model_ref = shlex.quote(model["url"])
    model_name = shlex.quote(model["name"])
    return textwrap.dedent(
        f"""
        set -euo pipefail
        MODEL_REF={model_ref}
        MODEL_NAME={model_name}
        APP_DIR="$HOME/oci-inference-cloud"
        VENV_DIR="$APP_DIR/vllm-cpu-venv"
        LOG_DIR="$APP_DIR/logs"

        echo "[1/6] Installing CPU vLLM prerequisites"
        if command -v dnf >/dev/null 2>&1; then
          sudo dnf --disablerepo=ol9_ksplice install -y python3.11 python3.11-pip curl git || sudo dnf install -y python3.11 python3.11-pip curl git
        elif command -v apt-get >/dev/null 2>&1; then
          sudo apt-get update
          sudo apt-get install -y python3.11 python3.11-venv python3-pip curl git
        else
          echo "Unsupported Linux distribution: missing dnf and apt-get"
          exit 1
        fi

        PYTHON_BIN="$(command -v python3.11 || command -v python3)"
        mkdir -p "$APP_DIR" "$LOG_DIR"
        "$PYTHON_BIN" -m venv "$VENV_DIR"
        "$VENV_DIR/bin/python" -m pip install --upgrade pip uv

        echo "[2/6] Installing the vLLM CPU wheel with AMD Zen optimizations"
        VLLM_VERSION="$(curl -fsSL https://api.github.com/repos/vllm-project/vllm/releases/latest | "$VENV_DIR/bin/python" -c 'import json,sys; print(json.load(sys.stdin)["tag_name"].lstrip("v"))')"
        "$VENV_DIR/bin/uv" pip install --python "$VENV_DIR/bin/python" "vllm[bench,zen]" \\
          --extra-index-url "https://wheels.vllm.ai/${{VLLM_VERSION}}/cpu" \\
          --index-strategy first-index --torch-backend cpu

        echo "[3/6] Configuring CPU memory and thread placement"
        export VLLM_CPU_KVCACHE_SPACE={kv_cache_gib}
        export VLLM_CPU_NUM_OF_RESERVED_CPU=1
        printf 'export VLLM_CPU_KVCACHE_SPACE=%s\\nexport VLLM_CPU_NUM_OF_RESERVED_CPU=%s\\n' "$VLLM_CPU_KVCACHE_SPACE" "$VLLM_CPU_NUM_OF_RESERVED_CPU" > "$APP_DIR/vllm-cpu.env"

        echo "[4/6] Stopping an earlier CPU vLLM service"
        if [ -f "$LOG_DIR/vllm-server.pid" ]; then
          kill "$(cat "$LOG_DIR/vllm-server.pid")" >/dev/null 2>&1 || true
          rm -f "$LOG_DIR/vllm-server.pid"
        fi

        echo "[5/6] Starting CPU vLLM for $MODEL_NAME on remote localhost"
        nohup env VLLM_CPU_KVCACHE_SPACE="$VLLM_CPU_KVCACHE_SPACE" VLLM_CPU_NUM_OF_RESERVED_CPU="$VLLM_CPU_NUM_OF_RESERVED_CPU" \\
          "$VENV_DIR/bin/vllm" serve "$MODEL_REF" --host 127.0.0.1 --port 8080 \\
          --dtype bfloat16 --max-model-len {ctx_size} --max-num-seqs {parallel} \\
          > "$LOG_DIR/vllm-server.log" 2>&1 &
        echo "$!" > "$LOG_DIR/vllm-server.pid"

        echo "[6/6] Verifying the local OpenAI-compatible service"
        for attempt in $(seq 1 90); do
          if curl -fsS http://127.0.0.1:8080/health >/dev/null; then
            exit 0
          fi
          sleep 2
        done
        echo "CPU vLLM did not become healthy. Server log follows:"
        tail -n 100 "$LOG_DIR/vllm-server.log" || true
        exit 1
        """
    ).strip()


def deploy_llama_cpp(
    instance_id: int,
    private_key_path: str,
    user: str,
    host: str,
    config: dict[str, Any] | None = None,
) -> tuple[str, str]:
    config = config or {}
    model = resolve_model(config)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"deploy-{instance_id}-{utc_now().replace(':', '-')}.log"
    result = run_ssh(private_key_path, user, host, deployment_script(config), timeout=None)
    log_text = "\n".join(
        [
            f"returncode={result.returncode}",
            f"model={model['name']}",
            f"model_url={model['url']}",
            f"build_native={bool(config.get('build_native', False))}",
            f"disable_vnni={bool(config.get('disable_vnni', True))}",
            f"ctx_size={int(config.get('ctx_size') or 4096)}",
            f"parallel={int(config.get('parallel') or 4)}",
            f"batch_size={int(config.get('batch_size') or 512)}",
            f"ubatch_size={int(config.get('ubatch_size') or 128)}",
            "--- stdout ---",
            result.stdout,
            "--- stderr ---",
            result.stderr,
        ]
    )
    log_path.write_text(log_text, encoding="utf-8")
    if result.returncode != 0:
        tail = "\n".join(log_text.splitlines()[-24:])
        return str(log_path), f"Deployment failed. Last log lines:\n{tail}"
    return str(log_path), f"llama.cpp deployed {model['name']} and llama-server is responding on remote 127.0.0.1:8080."


def deploy_inference_engine(
    instance_id: int,
    private_key_path: str,
    user: str,
    host: str,
    config: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Deploy the selected CPU inference engine and retain a diagnostic log."""
    config = config or {}
    engine = config.get("engine") or "llama_cpp"
    if engine == "llama_cpp":
        return deploy_llama_cpp(instance_id, private_key_path, user, host, config)
    if engine != "vllm_cpu":
        raise ValueError(f"Unknown inference engine: {engine}")

    model = resolve_model(config)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"deploy-{instance_id}-{utc_now().replace(':', '-')}.log"
    result = run_ssh(private_key_path, user, host, deployment_script(config), timeout=None)
    log_text = "\n".join(
        [
            f"returncode={result.returncode}",
            "engine=vllm_cpu",
            f"model={model['name']}",
            f"model_ref={model['url']}",
            f"ctx_size={int(config.get('ctx_size') or 4096)}",
            f"max_num_seqs={int(config.get('parallel') or 4)}",
            f"cpu_kv_cache_gib={int(config.get('cpu_kv_cache_gib') or 8)}",
            "--- stdout ---",
            result.stdout,
            "--- stderr ---",
            result.stderr,
        ]
    )
    log_path.write_text(log_text, encoding="utf-8")
    if result.returncode != 0:
        return str(log_path), f"Deployment failed. Last log lines:\n{'\\n'.join(log_text.splitlines()[-24:])}"
    return str(log_path), f"CPU vLLM deployed {model['name']} and its OpenAI-compatible server is responding on remote 127.0.0.1:8080."
