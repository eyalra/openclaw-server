"""Docker container, network, and image management for OpenClaw instances."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterator

import docker
import docker.errors

from clawctl.core.paths import Paths
from clawctl.models.config import Config, UserConfig

CONTAINER_PREFIX = "openclaw"
NETWORK_PREFIX = "openclaw-net"


def _container_name(username: str) -> str:
    return f"{CONTAINER_PREFIX}-{username}"


def _network_name(username: str) -> str:
    return f"{NETWORK_PREFIX}-{username}"


class DockerManager:
    """Manages Docker resources for OpenClaw user instances."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.paths = Paths(config.clawctl.data_root)
        self.client = docker.from_env()

    @property
    def image_tag(self) -> str:
        return f"{self.config.clawctl.image_name}:{self.config.clawctl.openclaw_version}"

    # --- Image ---

    def build_image(self) -> None:
        """Build the OpenClaw Docker image at the configured version.

        Uses subprocess for reliable streaming build output.
        """
        dockerfile_dir = Path(__file__).resolve().parents[3] / "docker"
        cmd = [
            "docker",
            "build",
            "-t",
            self.image_tag,
            "--build-arg",
            f"OPENCLAW_VERSION={self.config.clawctl.openclaw_version}",
            str(dockerfile_dir),
        ]
        subprocess.run(cmd, check=True)

    def image_exists(self) -> bool:
        """Check if the configured image is already built."""
        try:
            self.client.images.get(self.image_tag)
            return True
        except docker.errors.ImageNotFound:
            return False

    # --- Network ---

    def create_network(self, username: str) -> None:
        """Create an isolated bridge network for a user."""
        name = _network_name(username)
        try:
            self.client.networks.get(name)
        except docker.errors.NotFound:
            self.client.networks.create(name, driver="bridge")

    def remove_network(self, username: str) -> None:
        """Remove a user's network."""
        name = _network_name(username)
        try:
            network = self.client.networks.get(name)
            network.remove()
        except docker.errors.NotFound:
            pass

    # --- Container ---

    def create_container(self, user: UserConfig) -> None:
        """Create a container for a user (does not start it)."""
        name = _container_name(user.name)

        # Ensure network exists
        self.create_network(user.name)

        openclaw_dir = str(self.paths.user_openclaw_dir(user.name))
        secrets_dir = str(self.paths.user_secrets_dir(user.name))

        self.client.containers.create(
            image=self.image_tag,
            name=name,
            user="1000:1000",
            network=_network_name(user.name),
            volumes={
                openclaw_dir: {"bind": "/home/node/.openclaw", "mode": "rw"},
                secrets_dir: {"bind": "/run/secrets", "mode": "ro"},
            },
            ports={"18789/tcp": None},  # random host port
            restart_policy={"Name": "unless-stopped"},
            detach=True,
        )

    def start_container(self, username: str) -> None:
        """Start a user's container."""
        container = self.client.containers.get(_container_name(username))
        container.start()

    def stop_container(self, username: str) -> None:
        """Stop a user's container."""
        try:
            container = self.client.containers.get(_container_name(username))
            container.stop(timeout=30)
        except docker.errors.NotFound:
            pass

    def restart_container(self, username: str) -> None:
        """Restart a user's container."""
        container = self.client.containers.get(_container_name(username))
        container.restart(timeout=30)

    def remove_container(self, username: str) -> None:
        """Stop and remove a user's container."""
        try:
            container = self.client.containers.get(_container_name(username))
            container.stop(timeout=30)
            container.remove()
        except docker.errors.NotFound:
            pass

    def container_exists(self, username: str) -> bool:
        """Check if a user's container exists."""
        try:
            self.client.containers.get(_container_name(username))
            return True
        except docker.errors.NotFound:
            return False

    def get_container_status(self, username: str) -> str:
        """Get the status of a user's container (running, exited, etc.)."""
        try:
            container = self.client.containers.get(_container_name(username))
            return container.status
        except docker.errors.NotFound:
            return "not found"

    def get_container_port(self, username: str) -> str | None:
        """Get the host port mapped to the container's gateway port."""
        try:
            container = self.client.containers.get(_container_name(username))
            ports = container.attrs.get("NetworkSettings", {}).get("Ports", {})
            bindings = ports.get("18789/tcp")
            if bindings:
                return bindings[0].get("HostPort")
        except docker.errors.NotFound:
            pass
        return None

    def get_all_statuses(self) -> dict[str, dict[str, str]]:
        """Get status info for all configured users.

        Returns dict of {username: {"status": ..., "port": ...}}
        """
        result = {}
        for user in self.config.users:
            status = self.get_container_status(user.name)
            port = self.get_container_port(user.name) if status == "running" else None
            result[user.name] = {"status": status, "port": port or "-"}
        return result

    def stream_logs(
        self, username: str, *, follow: bool = False, tail: int = 100
    ) -> Iterator[str]:
        """Stream container logs."""
        container = self.client.containers.get(_container_name(username))
        for chunk in container.logs(stream=True, follow=follow, tail=tail):
            yield chunk.decode("utf-8", errors="replace")

    # --- Lifecycle helpers ---

    def start_all(self) -> list[str]:
        """Start all configured user containers. Returns list of started usernames."""
        started = []
        for user in self.config.users:
            if self.container_exists(user.name):
                self.start_container(user.name)
                started.append(user.name)
        return started

    def stop_all(self) -> list[str]:
        """Stop all configured user containers. Returns list of stopped usernames."""
        stopped = []
        for user in self.config.users:
            if self.container_exists(user.name):
                self.stop_container(user.name)
                stopped.append(user.name)
        return stopped

    def rebuild_all(self) -> list[str]:
        """Rebuild image and recreate all containers (rolling update)."""
        self.build_image()
        updated = []
        for user in self.config.users:
            if self.container_exists(user.name):
                was_running = self.get_container_status(user.name) == "running"
                self.remove_container(user.name)
                self.create_container(user)
                if was_running:
                    self.start_container(user.name)
                updated.append(user.name)
        return updated
