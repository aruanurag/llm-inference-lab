from __future__ import annotations

import pytest

from app.deploy import list_deploy_models, resolve_model, vllm_cpu_deployment_script
from app.native_benchmark import _native_summary, native_benchmark_script, recommended_tool


def test_engine_catalogs_return_engine_specific_models() -> None:
    llama_models = list_deploy_models("llama_cpp")
    vllm_models = list_deploy_models("vllm_cpu")

    assert llama_models[0]["engine"] == "llama_cpp"
    assert llama_models[0]["filename"].endswith(".gguf")
    assert vllm_models[0]["engine"] == "vllm_cpu"
    assert vllm_models[0]["url"].startswith("Qwen/")


def test_vllm_cpu_script_uses_local_only_server_and_cpu_configuration() -> None:
    script = vllm_cpu_deployment_script(
        {"model_id": "qwen2.5-1.5b-instruct", "ctx_size": 2048, "parallel": 3, "cpu_kv_cache_gib": 12}
    )

    assert "vllm[bench,zen]" in script
    assert "VLLM_CPU_KVCACHE_SPACE=12" in script
    assert "VLLM_CPU_NUM_OF_RESERVED_CPU=1" in script
    assert "--host 127.0.0.1 --port 8080" in script
    assert "--max-model-len 2048 --max-num-seqs 3" in script


def test_native_tools_match_the_engine_and_render_without_remote_addresses() -> None:
    llama = resolve_model({"engine": "llama_cpp", "model_id": "qwen2.5-1.5b-q4_k_m"})
    vllm = resolve_model({"engine": "vllm_cpu", "model_id": "qwen2.5-1.5b-instruct"})

    assert recommended_tool("llama_cpp") == "llama_bench"
    assert recommended_tool("vllm_cpu") == "vllm_bench_serve"
    assert "llama-bench" in native_benchmark_script(tool="llama_bench", model=llama, prompt_tokens=100, max_tokens=32, requests=3, concurrency=1)
    assert "vllm\" bench serve" in native_benchmark_script(tool="vllm_bench_serve", model=vllm, prompt_tokens=100, max_tokens=32, requests=3, concurrency=2)


def test_custom_vllm_model_requires_a_safe_hugging_face_id() -> None:
    with pytest.raises(ValueError, match="Hugging Face repository ID"):
        resolve_model({"engine": "vllm_cpu", "model_id": "custom", "custom_model_url": "https://invalid.example/model"})


def test_llama_bench_json_populates_prompt_and_decode_throughput() -> None:
    output = '''login banner
[
  {"n_prompt": 512, "n_gen": 0, "avg_ts": 170.5},
  {"n_prompt": 0, "n_gen": 128, "avg_ts": 49.2}
]
'''
    summary = _native_summary(
        tool="llama_bench", engine="llama_cpp", model="test", requests=4,
        concurrency=1, max_tokens=128, prompt_count=10, prompt_tokens=512, stdout=output,
    )

    assert summary["successful_requests"] == 4
    assert summary["prompt_tokens_per_second"] == 170.5
    assert summary["decode_tokens_per_second"] == 49.2
    assert summary["approx_output_tokens_per_second"] == 49.2
