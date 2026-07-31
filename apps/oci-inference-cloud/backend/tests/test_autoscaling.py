from __future__ import annotations

import json
from pathlib import Path

from app import autoscaling


def deployment_config() -> dict[str, object]:
    return {
        "context": "oci-cpu",
        "namespace": "llm-d-lab",
        "release_name": "llm-d-lab",
        "model": "Qwen/Qwen2.5-1.5B-Instruct",
    }


def policy() -> dict[str, object]:
    return {
        "min_replicas": 1,
        "max_replicas": 3,
        "queue_threshold": 1,
        "running_request_threshold": 4,
        "polling_interval": 15,
        "cooldown_period": 300,
        "scale_down_stabilization": 300,
        "prometheus_address": None,
    }


def test_autoscaling_plan_uses_epp_demand_and_only_keda_hpa() -> None:
    plan = autoscaling.autoscaling_plan(deployment_config(), policy())
    manifest = json.loads(plan["manifest"])

    assert manifest["kind"] == "ScaledObject"
    assert manifest["spec"]["scaleTargetRef"]["name"] == autoscaling.MODEL_DEPLOYMENT
    assert manifest["spec"]["minReplicaCount"] == 1
    assert manifest["spec"]["maxReplicaCount"] == 3
    assert manifest["spec"]["advanced"]["horizontalPodAutoscalerConfig"]["name"].startswith("keda-hpa-")
    queries = [trigger["metadata"]["query"] for trigger in manifest["spec"]["triggers"]]
    assert any("llm_d_epp_flow_control_queue_size" in query for query in queries)
    assert any("llm_d_epp_request_running" in query for query in queries)
    assert all('namespace="llm-d-lab"' in query for query in queries)
    assert "HorizontalPodAutoscaler" not in plan["manifest"]


def test_platform_plan_redacts_grafana_password_and_discovers_dashboards(tmp_path: Path) -> None:
    root = tmp_path / "llm-d"
    for relative in (
        "guides/env.sh",
        "guides/recipes/router/base.values.yaml",
        "guides/optimized-baseline/router/optimized-baseline.values.yaml",
        "guides/optimized-baseline/modelserver/cpu/vllm/kustomization.yaml",
        "guides/recipes/observability/grafana/dashboards/llm-d-vllm-overview.json",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}" if path.suffix == ".json" else "# test\n", encoding="utf-8")

    plan = autoscaling.platform_plan("oci-cpu", str(root), "dedicated")

    assert "admin-password" in plan["values"]
    assert "admin:\n    existingSecret: llmd-grafana-admin" in plan["values"]
    assert "adminPassword:" not in plan["values"]
    assert "llm-d-vllm-overview" in plan["dashboards"]
    assert "Prometheus Operator CRDs" in plan["cluster_scoped_changes"]
    assert all("password" not in " ".join(command).lower() for command in plan["commands"])
