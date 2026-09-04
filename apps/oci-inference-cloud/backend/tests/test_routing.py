from __future__ import annotations

import json

import pytest

from app import routing


FAKE_OPENROUTER_KEY = "fake-openrouter-key-for-redaction-tests"


def config(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "source_experiment_id": 4,
        "context": "oci-cpu",
        "namespace": "llm-d-lab",
        "release_name": "llm-d-lab",
        "model": "Qwen/Qwen2.5-1.5B-Instruct",
        "coding_model": "qwen/qwen3-coder",
        "reasoning_model": "deepseek/deepseek-r1",
        "router_name": "llm-d-routing",
        "openrouter_api_key": FAKE_OPENROUTER_KEY,
    }
    values.update(overrides)
    return values


def test_routing_plan_is_redacted_and_exposes_only_fixed_aliases() -> None:
    plan = routing.routing_plan(config())
    rendered = json.dumps(plan)

    assert FAKE_OPENROUTER_KEY not in rendered
    assert plan["secret"] == {
        "name": routing.ROUTER_SECRET,
        "namespace": "llm-d-lab",
        "keys": [routing.ROUTER_SECRET_KEY, routing.ROUTER_MASTER_KEY],
        "provided": True,
    }
    assert [item["alias"] for item in plan["aliases"]] == list(routing.ALIASES)
    assert [item["destination"] for item in plan["aliases"]] == ["llm-d", "llm-d", "openrouter", "openrouter"]
    assert plan["aliases"][2]["max_tokens"] == routing.EXTERNAL_MAX_TOKENS
    assert all("secret" not in " ".join(command).lower() for command in plan["commands"])


def test_rendered_config_uses_local_llmd_and_strict_openrouter_routes() -> None:
    manifests = routing.render_manifests(config())
    proxy = json.loads(manifests["configmap"]["data"]["config.yaml"])
    model_list = {item["model_name"]: item["litellm_params"] for item in proxy["model_list"]}

    for alias in routing.LOCAL_ALIASES:
        assert model_list[alias]["model"] == "openai/Qwen/Qwen2.5-1.5B-Instruct"
        assert model_list[alias]["api_base"] == "http://llm-d-lab-epp.llm-d-lab.svc.cluster.local/v1"
        assert model_list[alias]["api_key"] == "not-needed"
        assert "openrouter/" not in model_list[alias]["model"]
    for alias in routing.EXTERNAL_ALIASES:
        assert model_list[alias]["model"].startswith("openrouter/")
        assert model_list[alias]["api_key"] == "os.environ/OPENROUTER_API_KEY"
        assert model_list[alias]["extra_body"]["provider"] == {"data_collection": "deny", "allow_fallbacks": False}
        assert "api_base" not in model_list[alias]
    assert proxy["router_settings"] == {"fallbacks": [], "context_window_fallbacks": []}
    assert proxy["litellm_settings"]["callbacks"] == ["prometheus"]
    assert proxy["litellm_settings"]["turn_off_message_logging"] is True
    assert {"hashed_api_key", "client_ip", "user_agent"} <= set(proxy["litellm_settings"]["prometheus_exclude_labels"])
    assert proxy["general_settings"]["master_key"] == "os.environ/LITELLM_MASTER_KEY"
    assert FAKE_OPENROUTER_KEY not in manifests["configmap"]["data"]["config.yaml"]


def test_all_resources_are_owned_and_service_is_private() -> None:
    manifests = routing.render_manifests(config())

    for manifest in manifests.values():
        labels = manifest["metadata"]["labels"]
        assert labels["app.kubernetes.io/managed-by"] == "oci-inference-cloud"
        assert labels["lab.llm-inference.ai"] == routing.LAB_NAME
        assert labels["lab.llm-inference.ai/owned"] == "true"

    deployment = manifests["deployment"]
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    assert deployment["spec"]["replicas"] == 1
    assert "@sha256:" in container["image"]
    assert container["env"][1]["valueFrom"]["secretKeyRef"] == {
        "name": routing.ROUTER_SECRET,
        "key": routing.ROUTER_SECRET_KEY,
    }
    assert container["env"][2]["valueFrom"]["secretKeyRef"] == {
        "name": routing.ROUTER_SECRET,
        "key": routing.ROUTER_MASTER_KEY,
    }
    assert manifests["service"]["spec"]["type"] == "ClusterIP"
    assert manifests["service_monitor"]["spec"]["endpoints"][0]["path"] == "/metrics"
    dropped = manifests["service_monitor"]["spec"]["endpoints"][0]["metricRelabelings"][0]["regex"]
    assert "client_ip" in dropped
    assert "hashed_api_key" in dropped
    assert manifests["service_monitor"]["spec"]["endpoints"][0]["authorization"] == {
        "type": "Bearer",
        "credentials": {"name": routing.ROUTER_SECRET, "key": routing.ROUTER_MASTER_KEY},
    }


def test_resource_names_are_isolated_per_router_name() -> None:
    first = routing.routing_plan(config(router_name="lab5-router-a"))
    second = routing.routing_plan(config(router_name="lab5-router-b"))
    first_resources = first["resource_names"]
    second_resources = second["resource_names"]

    assert first_resources["router"] != second_resources["router"]
    assert first_resources["config_map"] == "lab5-router-a-config"
    assert first_resources["secret"] == "lab5-router-a-openrouter"
    assert first_resources["dashboard"] == "lab5-router-a-overview"
    assert first_resources != second_resources
    first_dashboard = json.loads(
        routing.render_manifests(config(router_name="lab5-router-a"))["grafana_dashboard"]["data"]
        ["llm-d-routing-overview.json"]
    )
    second_dashboard = json.loads(
        routing.render_manifests(config(router_name="lab5-router-b"))["grafana_dashboard"]["data"]
        ["llm-d-routing-overview.json"]
    )
    assert first_dashboard["uid"] != second_dashboard["uid"]
    with pytest.raises(ValueError, match="at most 51"):
        routing.validate_config(config(router_name="a" * 52))


def test_plan_restarts_router_when_a_secret_rotation_requires_a_redeploy() -> None:
    plan = routing.routing_plan(config())

    assert plan["commands"][2][-4:] == ["rollout", "restart", "deployment", routing.ROUTER_NAME]
    assert plan["commands"][3][-5:] == ["rollout", "status", "deployment", routing.ROUTER_NAME, "--timeout=180s"]


def test_apply_time_secret_is_separate_from_the_safe_plan() -> None:
    master_key = routing.new_router_master_key()
    secret = routing.secret_manifest(config(router_name="lab5-router-a"), master_key)
    plan = routing.routing_plan(config(router_name="lab5-router-a"))

    assert secret["metadata"]["name"] == "lab5-router-a-openrouter"
    assert secret["stringData"][routing.ROUTER_SECRET_KEY] == FAKE_OPENROUTER_KEY
    assert secret["stringData"][routing.ROUTER_MASTER_KEY] == master_key
    assert secret["metadata"]["labels"]["lab.llm-inference.ai/owned"] == "true"
    assert '"kind": "Secret"' not in plan["manifest"]
    assert master_key not in json.dumps(plan)


def test_external_token_cap_and_alias_allowlist() -> None:
    assert routing.validate_inference_request("private", 4096)["destination"] == "llm-d"
    assert routing.validate_inference_request("coding", 512)["destination"] == "openrouter"
    with pytest.raises(ValueError, match="512"):
        routing.validate_inference_request("reasoning", 513)
    with pytest.raises(ValueError, match="private, fast, coding, reasoning"):
        routing.validate_inference_request("anything-else", 20)


def test_config_validation_and_redaction_cover_untrusted_input() -> None:
    with pytest.raises(ValueError, match="newline"):
        routing.validate_config(config(coding_model="qwen/coder\nunsafe"))
    with pytest.raises(ValueError, match="required"):
        routing.validate_config(config(reasoning_model=""))
    with pytest.raises(ValueError, match="OpenRouter API key"):
        routing.validate_config(config(openrouter_api_key=""), require_openrouter_key=True)

    redacted = routing.redact({"openrouter_api_key": "secret", "nested": {"password": "also-secret"}, "model": "safe"})
    assert redacted == {"openrouter_api_key": "[REDACTED]", "nested": {"password": "[REDACTED]"}, "model": "safe"}


def test_preflight_and_dashboard_are_safe_and_actionable() -> None:
    preflight = routing.preflight_manifest(config())
    plan = routing.routing_plan(config())
    dashboard = json.loads(routing.render_manifests(config())["grafana_dashboard"]["data"]["llm-d-routing-overview.json"])

    assert preflight["epp_service_name"] == "llm-d-lab-epp"
    assert preflight["epp_url"] == "http://llm-d-lab-epp.llm-d-lab.svc.cluster.local/v1"
    assert {check["kind"] for check in preflight["checks"]} == {"Service", "CustomResourceDefinition"}
    assert FAKE_OPENROUTER_KEY not in json.dumps(preflight)
    assert FAKE_OPENROUTER_KEY not in plan["dashboard_manifest"]
    titles = {panel["title"] for panel in dashboard["panels"]}
    assert {"Route request rate", "Route p95 latency", "Route error rate", "Router in-flight requests", "Route share"} <= titles
