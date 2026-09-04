from __future__ import annotations

import pytest

from app import main, routing_endpoint, state
from app.schemas import LlmDRoutingConfiguration


@pytest.fixture()
def isolated_state(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep source-link and plan tests out of a participant's real state DB."""

    monkeypatch.setattr(state, "STATE_DB", tmp_path / "state.db")
    monkeypatch.setattr(state, "ensure_app_dirs", lambda: None)
    state.init_db()


def source_lab4() -> dict[str, object]:
    return state.insert_experiment("Lab 4 source", kind="llm-d-autoscaling")


def test_lab5_plan_uses_the_linked_lab4_target_and_redacts_credentials(isolated_state: None) -> None:
    source = source_lab4()
    source_id = int(source["id"])
    state.set_setting(f"llmd:{source_id}", {
        "context": "oke-cpu", "namespace": "llm-d-lab", "release_name": "llm-d-lab",
        "model": "Qwen/Qwen2.5-1.5B-Instruct", "enable_autoscaling": True,
    })
    state.set_setting(f"lab4:{source_id}", {
        "context": "oke-cpu", "owned": True, "monitoring_namespace": "llm-d-monitoring",
        "prometheus_service": "llmd-kube-prometheus-stack-prometheus",
    })
    lab5 = state.insert_experiment("Lab 5 router", kind="llm-d-routing", source_experiment_id=source_id)

    # Values that would redirect a router are deliberately ignored in favor of
    # the linked source deployment. A credential is not part of the plan type.
    request = LlmDRoutingConfiguration(
        source_experiment_id=source_id,
        context="untrusted-context",
        namespace="other-namespace",
        release_name="other-release",
        model="Other/model",
        coding_model="openai/gpt-4.1-mini",
        reasoning_model="deepseek/deepseek-r1",
        router_name="lab5-router",
    )
    plan = main.plan_llmd_routing(int(lab5["id"]), request)

    assert plan.context == "oke-cpu"
    assert plan.namespace == "llm-d-lab"
    assert "llm-d-lab-epp.llm-d-lab.svc.cluster.local" in plan.manifests
    assert "untrusted-context" not in plan.manifests
    assert "openrouter_api_key" not in plan.model_dump()
    assert "LITELLM_MASTER_KEY" in plan.manifests  # reference only, no value


def test_lab5_plan_rejects_a_different_source_than_the_recorded_link(isolated_state: None) -> None:
    source = source_lab4()
    other_source = source_lab4()
    source_id = int(source["id"])
    state.set_setting(f"llmd:{source_id}", {
        "context": "oke-cpu", "namespace": "llm-d-lab", "release_name": "llm-d-lab",
        "model": "Qwen/Qwen2.5-1.5B-Instruct", "enable_autoscaling": True,
    })
    state.set_setting(f"lab4:{source_id}", {"context": "oke-cpu"})
    lab5 = state.insert_experiment("Lab 5 router", kind="llm-d-routing", source_experiment_id=source_id)
    request = LlmDRoutingConfiguration(
        source_experiment_id=int(other_source["id"]), context="oke-cpu", namespace="llm-d-lab",
        release_name="llm-d-lab", model="Qwen/Qwen2.5-1.5B-Instruct",
        coding_model="openai/gpt-4.1-mini", reasoning_model="deepseek/deepseek-r1",
    )

    with pytest.raises(Exception, match="selected source does not match"):
        main.plan_llmd_routing(int(lab5["id"]), request)


def test_lab5_default_router_name_is_unique_to_its_experiment_and_endpoint_needs_ownership(isolated_state: None) -> None:
    source = source_lab4()
    source_id = int(source["id"])
    state.set_setting(f"llmd:{source_id}", {
        "context": "oke-cpu", "namespace": "llm-d-lab", "release_name": "llm-d-lab",
        "model": "Qwen/Qwen2.5-1.5B-Instruct", "enable_autoscaling": True,
    })
    state.set_setting(f"lab4:{source_id}", {"context": "oke-cpu"})
    lab5 = state.insert_experiment("Lab 5 router", kind="llm-d-routing", source_experiment_id=source_id)
    request = LlmDRoutingConfiguration(
        source_experiment_id=source_id, context="ignored", namespace="ignored", release_name="ignored",
        model="Ignored/model", coding_model="openai/gpt-4.1-mini", reasoning_model="deepseek/deepseek-r1",
    )

    plan = main.plan_llmd_routing(int(lab5["id"]), request)

    assert plan.router_name == f"llm-d-routing-{lab5['id']}"
    with pytest.raises(RuntimeError, match="Deploy the Lab 5 LiteLLM router"):
        routing_endpoint.deployment_config(int(lab5["id"]))
