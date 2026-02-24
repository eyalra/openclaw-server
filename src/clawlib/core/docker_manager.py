"""Docker container, network, and image management for OpenClaw instances."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Iterator

import docker
import docker.errors

from clawlib.core.paths import Paths
from clawlib.models.config import Config, UserConfig

CONTAINER_PREFIX = "openclaw"
NETWORK_PREFIX = "openclaw-net"

# Resolve the docker/ directory from the project root
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DOCKER_DIR = _PROJECT_ROOT / "docker"

# Well-known Docker socket paths (checked in order)
_DOCKER_SOCKET_CANDIDATES = [
    Path.home() / ".colima" / "default" / "docker.sock",
    Path.home() / ".docker" / "run" / "docker.sock",
    Path("/var/run/docker.sock"),
]


def _discover_docker_host() -> str | None:
    """Return a DOCKER_HOST URI if the default socket isn't available.

    Checks DOCKER_HOST env var first, then probes well-known socket paths.
    Returns None if the standard /var/run/docker.sock exists (let the SDK
    use its default).
    """
    if os.environ.get("DOCKER_HOST"):
        return os.environ["DOCKER_HOST"]

    # If the standard socket exists, no override needed
    if Path("/var/run/docker.sock").exists():
        return None

    for candidate in _DOCKER_SOCKET_CANDIDATES:
        if candidate.exists():
            return f"unix://{candidate}"

    return None


def _container_name(username: str) -> str:
    return f"{CONTAINER_PREFIX}-{username}"


def _network_name(username: str) -> str:
    return f"{NETWORK_PREFIX}-{username}"


class DockerManager:
    """Manages Docker resources for OpenClaw user instances."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.paths = Paths(config.clawctl.data_root, config.clawctl.build_root)
        self._docker_host = _discover_docker_host()
        if self._docker_host:
            self.client = docker.DockerClient(base_url=self._docker_host)
        else:
            self.client = docker.from_env()

    @property
    def image_tag(self) -> str:
        return f"{self.config.clawctl.image_name}:{self.config.clawctl.openclaw_version}"

    # --- Image ---

    def build_image(self) -> None:
        """Build the OpenClaw Docker image at the configured version.

        Uses subprocess for reliable streaming build output.
        """
        cmd = [
            "docker",
            "build",
            "-t",
            self.image_tag,
            "--build-arg",
            f"OPENCLAW_VERSION={self.config.clawctl.openclaw_version}",
            str(_DOCKER_DIR),
        ]
        env = None
        if self._docker_host:
            env = {**os.environ, "DOCKER_HOST": self._docker_host}
        subprocess.run(cmd, check=True, env=env)

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

        openclaw_dir = self.paths.user_openclaw_dir(user.name)
        workspace_dir = self.paths.user_workspace_dir(user.name)
        config_dir = self.paths.user_config_dir(user.name)
        secrets_dir = self.paths.user_secrets_dir(user.name)

        # Ensure workspace directory exists with correct permissions
        workspace_dir.mkdir(parents=True, exist_ok=True)
        openclaw_dir.mkdir(parents=True, exist_ok=True)
        try:
            # Try to set ownership to 1000:1000 (container user)
            subprocess.run(
                ["chown", "-R", "1000:1000", str(openclaw_dir)],
                check=False,
                capture_output=True,
            )
            # Ensure workspace is writable
            os.chmod(workspace_dir, 0o775)
            os.chmod(openclaw_dir, 0o775)
        except (PermissionError, FileNotFoundError):
            # Non-fatal - deployment script should handle permissions
            pass

        # Build volumes dictionary
        volumes = {
            str(openclaw_dir): {"bind": "/home/node/.openclaw", "mode": "rw"},
            # Persist ~/.config so tools like gog store credentials across restarts
            str(config_dir): {"bind": "/home/node/.config", "mode": "rw"},
            str(secrets_dir): {"bind": "/run/secrets", "mode": "ro"},
        }

        # Mount Tailscale socket if available (for Tailscale Serve mode)
        tailscale_socket = Path("/var/run/tailscale/tailscaled.sock")
        if tailscale_socket.exists() and tailscale_socket.is_socket():
            volumes["/var/run/tailscale"] = {"bind": "/var/run/tailscale", "mode": "ro"}

        # Add knowledge directory mount if configured and exists
        knowledge_dir = self.config.clawctl.knowledge_dir
        if knowledge_dir:
            knowledge_path = Path(knowledge_dir)
            # Resolve relative to data_root if not absolute
            if not knowledge_path.is_absolute():
                knowledge_path = self.paths.data_root / knowledge_path
            else:
                knowledge_path = knowledge_path.resolve()

            if knowledge_path.exists() and knowledge_path.is_dir():
                volumes[str(knowledge_path)] = {"bind": "/mnt/knowledge", "mode": "ro"}
            # If not exists, silently skip (knowledge dir is optional)

        # Build environment variables from UserSecretsConfig.
        # Each key in secrets config maps a secret filename to an env var:
        #   openrouter_api_key = "openrouter_api_key"
        #   → reads /run/secrets/openrouter_api_key (i.e. secrets_dir/openrouter_api_key)
        #   → sets OPENROUTER_API_KEY=<value> in container env
        env_vars: dict[str, str] = {}
        for field_name, secret_filename in user.secrets.model_extra.items():
            if not secret_filename:
                continue
            secret_path = secrets_dir / str(secret_filename)
            if secret_path.exists():
                try:
                    value = secret_path.read_text().strip()
                    if value:
                        env_var_name = field_name.upper()
                        env_vars[env_var_name] = value
                except OSError:
                    pass

        self.client.containers.create(
            image=self.image_tag,
            name=name,
            user="1000:1000",
            network=_network_name(user.name),
            volumes=volumes,
            ports={"18789/tcp": user.port or None},  # fixed port if configured, else random
            environment=env_vars if env_vars else None,
            restart_policy={"Name": "unless-stopped"},
            healthcheck={
                "Test": ["CMD-SHELL", "curl -so /dev/null http://127.0.0.1:18789/ || exit 1"],
                "Interval": 30_000_000_000,
                "Timeout": 10_000_000_000,
                "StartPeriod": 15_000_000_000,
                "Retries": 3,
            },
            detach=True,
        )

    def start_container(self, username: str) -> None:
        """Start a user's container."""
        container = self.client.containers.get(_container_name(username))
        container.start()

    def run_doctor_fix(self, username: str, *, wait_ready: bool = True, timeout: int = 60) -> bool:
        """Run `openclaw doctor --fix` inside a container to ensure full authentication.
        
        This ensures the gateway URL is properly authenticated and Discord/other plugins
        are enabled. This is the recommended OpenClaw mechanism for ensuring full
        authentication after container startup/restart.
        
        Args:
            username: The username whose container to run doctor in.
            wait_ready: If True, wait for container to be running before executing.
            timeout: Maximum seconds to wait for container to be ready and doctor to complete.
            
        Returns:
            True if doctor ran successfully, False otherwise.
        """
        import time
        
        container_name = _container_name(username)
        try:
            container = self.client.containers.get(container_name)
            logger.info(f"Running openclaw doctor --fix for {username}...")
            
            # Wait for container to be running if requested
            if wait_ready:
                start_time = time.time()
                logger.debug(f"Waiting for container {container_name} to be running...")
                while container.status != "running":
                    if time.time() - start_time > timeout:
                        logger.error(f"Timeout waiting for container {container_name} to be running")
                        return False
                    time.sleep(1)
                    container.reload()
                
                logger.debug(f"Container {container_name} is running, waiting 3s for gateway to start...")
                # Give gateway a moment to start up
                time.sleep(3)
            
            # Run openclaw doctor --fix
            # Use user 1000:1000 to match container user
            logger.debug(f"Executing 'openclaw doctor --fix' in container {container_name}")
            exec_result = container.exec_run(
                "openclaw doctor --fix",
                user="1000:1000",
                workdir="/home/node",
            )
            
            if exec_result.exit_code == 0:
                output = exec_result.output.decode("utf-8", errors="replace") if exec_result.output else ""
                logger.info(f"Successfully ran openclaw doctor --fix for {username}")
                if output:
                    logger.debug(f"Doctor output: {output[:500]}")  # Log first 500 chars
                return True
            else:
                output = exec_result.output.decode("utf-8", errors="replace") if exec_result.output else ""
                logger.error(
                    f"openclaw doctor --fix failed for {username} (exit code {exec_result.exit_code})"
                )
                if output:
                    logger.error(f"Doctor error output: {output[:1000]}")  # Log first 1000 chars
                return False
            
        except docker.errors.NotFound:
            logger.error(f"Container {container_name} not found when trying to run doctor --fix")
            return False
        except docker.errors.APIError as e:
            logger.error(f"Docker API error running doctor --fix for {username}: {e}")
            return False
        except Exception as e:
            logger.exception(f"Unexpected error running doctor --fix for {username}: {e}")
            return False

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

    def recreate_container(self, user: UserConfig) -> None:
        """Stop, remove, and recreate a user's container (picks up new env vars/config)."""
        self.remove_container(user.name)
        self.create_container(user)
        self.start_container(user.name)

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
