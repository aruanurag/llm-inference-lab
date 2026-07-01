from __future__ import annotations

from pathlib import Path

from app.oci_cli import build_base_command, parse_profiles


def test_parse_profiles_reads_default_and_named_profile(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.write_text(
        """
[DEFAULT]
region=us-ashburn-1
tenancy=ocid1.tenancy.oc1..root
user=ocid1.user.oc1..default

[dev]
region=us-phoenix-1
tenancy=ocid1.tenancy.oc1..dev
user=ocid1.user.oc1..dev
""".strip(),
        encoding="utf-8",
    )

    profiles = parse_profiles(config)

    assert [profile.name for profile in profiles] == ["DEFAULT", "dev"]
    assert profiles[0].region == "us-ashburn-1"
    assert profiles[1].tenancy == "ocid1.tenancy.oc1..dev"


def test_build_base_command_accepts_explicit_profile_and_region() -> None:
    assert build_base_command("dev", "us-ashburn-1") == [
        "oci",
        "--profile",
        "dev",
        "--region",
        "us-ashburn-1",
    ]
