from __future__ import annotations

from pathlib import Path

from app import llmd


def make_llmd_checkout(tmp_path: Path) -> Path:
    root = tmp_path / "llm-d"
    for relative in (
        "guides/env.sh",
        "guides/recipes/router/base.values.yaml",
        "guides/optimized-baseline/router/optimized-baseline.values.yaml",
        "guides/optimized-baseline/modelserver/cpu/vllm/kustomization.yaml",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# test\n", encoding="utf-8")
    return root


def test_make_plan_renders_cpu_overlay_without_mutating_checkout(tmp_path: Path, monkeypatch) -> None:
    root = make_llmd_checkout(tmp_path)
    monkeypatch.setattr(llmd, "LLMD_DIR", tmp_path / "workbench")

    plan = llmd.make_plan(
        {
            "context": "oci-cpu",
            "namespace": "llm-d-lab",
            "llmd_repo_path": str(root),
            "release_name": "llm-d-lab",
            "model": "Qwen/Qwen2.5-1.5B-Instruct",
            "replicas": 2,
            "cpu": 16,
            "memory_gib": 32,
            "kv_cache_gib": 8,
            "max_model_len": 4096,
        },
        experiment_id=42,
    )

    assert "replicas: 2" in plan["overlay"]
    assert 'value: "8"' in plan["overlay"]
    assert "--kube-context" in plan["commands"][1]
    assert plan["commands"][2][-1].endswith("cpu-vllm-overlay")
    assert "resources:\n  - ../" in plan["overlay"]
    assert str(root) not in plan["overlay"]
    assert "includeSelectors: false" in plan["overlay"]
    assert "lab.llm-inference.ai/cpu-vendor: amd" in plan["overlay"]
    assert "llm-d.ai/accelerator-vendor: amd" not in plan["overlay"]
    assert "maxSurge: 0" in plan["overlay"]
    assert "maxUnavailable: 1" in plan["overlay"]
    assert (tmp_path / "workbench" / "experiment-42" / "cpu-vllm-overlay" / "kustomization.yaml").exists()


def test_make_plan_enables_the_upstream_monitoring_and_epp_overlays_for_lab4(tmp_path: Path, monkeypatch) -> None:
    root = make_llmd_checkout(tmp_path)
    for relative in (
        "guides/recipes/router/features/monitoring.values.yaml",
        "guides/workload-autoscaling/keda-epp/router.values.yaml",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# test\n", encoding="utf-8")
    monkeypatch.setattr(llmd, "LLMD_DIR", tmp_path / "workbench")

    plan = llmd.make_plan(
        {
            "context": "oci-cpu", "namespace": "llm-d-lab", "llmd_repo_path": str(root), "release_name": "llm-d-lab",
            "model": "Qwen/Qwen2.5-1.5B-Instruct", "replicas": 1, "cpu": 16, "memory_gib": 32,
            "kv_cache_gib": 8, "max_model_len": 4096, "enable_autoscaling": True,
        },
        experiment_id=43,
    )

    command = " ".join(plan["commands"][1])
    assert "monitoring.values.yaml" in command
    assert "workload-autoscaling/keda-epp/router.values.yaml" in command
    assert plan["monitoring_manifest"]
    assert '"kind": "ServiceMonitor"' in plan["monitoring_manifest"]
    assert '"kind": "PodMonitor"' in plan["monitoring_manifest"]
    assert '"port": "modelserver"' in plan["monitoring_manifest"]
    assert '"bearerTokenFile": "/var/run/secrets/kubernetes.io/serviceaccount/token"' in plan["monitoring_manifest"]
    assert any("monitoring.json" in " ".join(command) for command in plan["commands"])
