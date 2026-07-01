from __future__ import annotations

import configparser
import json
import subprocess
from pathlib import Path
from typing import Any

from .schemas import Profile
from .state import get_setting


OCI_CONFIG_PATH = Path("~/.oci/config").expanduser()


class OciCliError(RuntimeError):
    pass


def parse_profiles(config_path: Path = OCI_CONFIG_PATH) -> list[Profile]:
    if not config_path.exists():
        return []

    parser = configparser.ConfigParser()
    parser.read(config_path)
    profiles: list[Profile] = []

    if parser.defaults():
        profiles.append(
            Profile(
                name="DEFAULT",
                region=parser.defaults().get("region"),
                tenancy=parser.defaults().get("tenancy"),
                user=parser.defaults().get("user"),
            )
        )

    for section in parser.sections():
        profiles.append(
            Profile(
                name=section,
                region=parser.get(section, "region", fallback=None),
                tenancy=parser.get(section, "tenancy", fallback=None),
                user=parser.get(section, "user", fallback=None),
            )
        )

    return profiles


def profile_by_name(name: str) -> Profile | None:
    return next((profile for profile in parse_profiles() if profile.name == name), None)


def active_context() -> dict[str, Any]:
    return get_setting("context", {})


def build_base_command(profile: str | None = None, region: str | None = None) -> list[str]:
    command = ["oci"]
    if profile is None or region is None:
        context = active_context()
    else:
        context = {}
    selected_profile = profile or context.get("profile")
    selected_region = region or context.get("region")
    if selected_profile:
        command.extend(["--profile", selected_profile])
    if selected_region:
        command.extend(["--region", selected_region])
    return command


def run_oci(args: list[str], *, profile: str | None = None, region: str | None = None) -> Any:
    command = build_base_command(profile, region) + args + ["--output", "json"]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise OciCliError(completed.stderr.strip() or completed.stdout.strip())
    if not completed.stdout.strip():
        return None
    return json.loads(completed.stdout)


def data_items(response: Any) -> list[dict[str, Any]]:
    if not isinstance(response, dict):
        return []
    items = response.get("data") or []
    return items if isinstance(items, list) else []


def data_object(response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    item = response.get("data") or {}
    return item if isinstance(item, dict) else {}


def current_compartment_id() -> str:
    context = active_context()
    if context.get("compartment_id"):
        return context["compartment_id"]
    profile = profile_by_name(context.get("profile") or "DEFAULT")
    if profile and profile.tenancy:
        return profile.tenancy
    raise OciCliError("Set a compartment or use an OCI profile with tenancy configured.")


def tenancy_id() -> str:
    context = active_context()
    profile = profile_by_name(context.get("profile") or "DEFAULT")
    if profile and profile.tenancy:
        return profile.tenancy
    raise OciCliError("Selected OCI profile does not include tenancy.")


def normalize_options(items: list[dict[str, Any]], id_key: str = "id", name_key: str = "display-name") -> list[dict[str, Any]]:
    normalized = []
    for item in items:
        identifier = item.get(id_key) or item.get("name")
        name = item.get(name_key) or item.get("name") or identifier
        normalized.append({"id": identifier, "name": name, "extra": item})
    return normalized


def list_compartments() -> list[dict[str, Any]]:
    root = tenancy_id()
    data = run_oci(
        [
            "iam",
            "compartment",
            "list",
            "--compartment-id",
            root,
            "--compartment-id-in-subtree",
            "true",
            "--access-level",
            "ACCESSIBLE",
            "--all",
        ]
    )
    items = [{"id": root, "name": "Root tenancy", "extra": {"id": root, "lifecycle-state": "ACTIVE"}}]
    active = [item for item in data_items(data) if item.get("lifecycle-state") == "ACTIVE"]
    items.extend(normalize_options(active, name_key="name"))
    return items


def list_availability_domains() -> list[dict[str, Any]]:
    data = run_oci(["iam", "availability-domain", "list", "--compartment-id", tenancy_id()])
    return normalize_options(data_items(data), id_key="name", name_key="name")


def shape_class(shape_name: str) -> str:
    upper = shape_name.upper()
    if "GPU" in upper:
        return "gpu"
    if "HPC" in upper or "OPTIMIZED" in upper:
        return "hpc"
    return "cpu"


def list_shapes(
    compartment_id: str | None = None,
    availability_domain: str | None = None,
    include_gpu_shapes: bool = False,
) -> list[dict[str, Any]]:
    args = ["compute", "shape", "list", "--compartment-id", compartment_id or current_compartment_id(), "--all"]
    if availability_domain:
        args.extend(["--availability-domain", availability_domain])
    data = run_oci(args)
    shapes = []
    for item in data_items(data):
        shape_name = item.get("shape", "")
        category = shape_class(shape_name)
        if category == "gpu" and not include_gpu_shapes:
            continue
        extra = dict(item)
        extra["llm_inference_shape_class"] = category
        shapes.append({"id": shape_name, "name": shape_name, "extra": extra})
    return sorted(shapes, key=lambda item: (item["extra"].get("llm_inference_shape_class") == "gpu", item["name"]))


def list_vcns(compartment_id: str | None = None) -> list[dict[str, Any]]:
    data = run_oci(["network", "vcn", "list", "--compartment-id", compartment_id or current_compartment_id(), "--all"])
    return normalize_options(data_items(data))


def list_subnets(compartment_id: str | None = None, vcn_id: str | None = None) -> list[dict[str, Any]]:
    args = ["network", "subnet", "list", "--compartment-id", compartment_id or current_compartment_id(), "--all"]
    if vcn_id:
        args.extend(["--vcn-id", vcn_id])
    data = run_oci(args)
    return normalize_options(data_items(data))


def list_images(compartment_id: str | None = None, shape: str | None = None) -> list[dict[str, Any]]:
    args = [
        "compute",
        "image",
        "list",
        "--compartment-id",
        compartment_id or current_compartment_id(),
        "--operating-system",
        "Oracle Linux",
        "--sort-by",
        "TIMECREATED",
        "--sort-order",
        "DESC",
        "--all",
    ]
    if shape:
        args.extend(["--shape", shape])
    data = run_oci(args)
    images = data_items(data)[:25]
    return normalize_options(images)


def launch_instance(payload: dict[str, Any], public_key: str) -> dict[str, Any]:
    if payload["shape"].endswith(".Flex") and (not payload.get("ocpus") or not payload.get("memory_gbs")):
        raise OciCliError("Flexible shapes require OCPUs and Memory GB. For a small CPU model test, start with 4 OCPUs and 32 GB.")

    metadata = json.dumps({"ssh_authorized_keys": public_key})
    command = [
        "compute",
        "instance",
        "launch",
        "--compartment-id",
        payload["compartment_id"],
        "--availability-domain",
        payload["availability_domain"],
        "--shape",
        payload["shape"],
        "--subnet-id",
        payload["subnet_id"],
        "--display-name",
        payload["display_name"],
        "--image-id",
        payload["image_id"],
        "--metadata",
        metadata,
        "--assign-public-ip",
        str(payload.get("assign_public_ip", True)).lower(),
        "--boot-volume-size-in-gbs",
        str(payload.get("boot_volume_size_gbs", 100)),
    ]
    if payload.get("ocpus") and payload.get("memory_gbs"):
        command.extend(
            [
                "--shape-config",
                json.dumps({"ocpus": payload["ocpus"], "memoryInGBs": payload["memory_gbs"]}),
            ]
        )
    launched = data_object(run_oci(command))
    if not launched.get("id"):
        raise OciCliError("OCI launch did not return an instance id.")
    return launched


def get_instance(oci_instance_id: str) -> dict[str, Any]:
    return data_object(run_oci(["compute", "instance", "get", "--instance-id", oci_instance_id]))


def terminate_instance(oci_instance_id: str) -> dict[str, Any]:
    return data_object(
        run_oci(
            [
                "compute",
                "instance",
                "terminate",
                "--instance-id",
                oci_instance_id,
                "--force",
            ]
        )
    )


def get_instance_vnic(compartment_id: str, oci_instance_id: str) -> dict[str, Any]:
    attachments = data_items(
        run_oci(
            [
                "compute",
                "vnic-attachment",
                "list",
                "--compartment-id",
                compartment_id,
                "--instance-id",
                oci_instance_id,
            ]
        )
    )
    if not attachments:
        return {}
    vnic_id = attachments[0]["vnic-id"]
    return data_object(run_oci(["network", "vnic", "get", "--vnic-id", vnic_id]))
