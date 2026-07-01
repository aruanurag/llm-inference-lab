from __future__ import annotations

import socket
import subprocess
from pathlib import Path

from .config import KEYS_DIR


def sanitize_name(name: str) -> str:
    allowed = [char if char.isalnum() or char in ("-", "_") else "-" for char in name.strip()]
    return "".join(allowed).strip("-") or "key"


def generate_ed25519_key(name: str) -> tuple[Path, Path, str]:
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    KEYS_DIR.chmod(0o700)
    key_path = KEYS_DIR / sanitize_name(name)
    if key_path.exists():
        raise FileExistsError(f"SSH key already exists: {key_path}")
    subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key_path), "-C", name],
        check=True,
        capture_output=True,
        text=True,
    )
    key_path.chmod(0o600)
    public_key_path = key_path.with_suffix(".pub")
    public_key = public_key_path.read_text(encoding="utf-8").strip()
    return key_path, public_key_path, public_key


def ssh_base_command(private_key_path: str, user: str, host: str) -> list[str]:
    return [
        "ssh",
        "-i",
        private_key_path,
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ServerAliveInterval=30",
        f"{user}@{host}",
    ]


def run_ssh(private_key_path: str, user: str, host: str, command: str, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    ssh_command = ssh_base_command(private_key_path, user, host) + ["bash", "-lc", command]
    return subprocess.run(ssh_command, capture_output=True, text=True, timeout=timeout, check=False)


def free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_tunnel(private_key_path: str, user: str, host: str, local_port: int, remote_port: int = 8080) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            "ssh",
            "-i",
            private_key_path,
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-N",
            "-L",
            f"{local_port}:127.0.0.1:{remote_port}",
            f"{user}@{host}",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
