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


MODEL_CATALOG: list[dict[str, Any]] = [
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


def list_deploy_models() -> list[dict[str, Any]]:
    return MODEL_CATALOG


def _safe_filename(value: str) -> str:
    filename = Path(urlparse(value).path).name or "model.gguf"
    filename = re.sub(r"[^A-Za-z0-9._-]+", "-", filename)
    if not filename.lower().endswith(".gguf"):
        filename = f"{filename}.gguf"
    return filename.lower()


def resolve_model(config: dict[str, Any]) -> dict[str, Any]:
    model_id = config.get("model_id") or MODEL_CATALOG[0]["id"]
    if model_id == "custom":
        url = (config.get("custom_model_url") or "").strip()
        if not url.startswith(("https://", "http://")):
            raise ValueError("Custom model URL must start with https:// or http://.")
        filename = _safe_filename(url)
        return {
            "id": "custom",
            "name": (config.get("custom_model_name") or filename).strip() or filename,
            "url": url,
            "filename": filename,
        }
    for model in MODEL_CATALOG:
        if model["id"] == model_id:
            return model
    raise ValueError(f"Unknown deploy model: {model_id}")


def deployment_script(config: dict[str, Any] | None = None) -> str:
    config = config or {}
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
