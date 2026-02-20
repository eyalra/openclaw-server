"""Docker container statistics collection."""

from __future__ import annotations

from typing import Any

import docker.errors

from clawlib.core.docker_manager import DockerManager


def get_container_stats(docker_mgr: DockerManager, username: str) -> dict[str, Any] | None:
    """Get current stats for a container."""
    try:
        container_name = f"openclaw-{username}"
        container = docker_mgr.client.containers.get(container_name)
        stats = container.stats(stream=False)

        # Calculate CPU percentage
        cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - stats["precpu_stats"]["cpu_usage"]["total_usage"]
        system_delta = stats["cpu_stats"]["system_cpu_usage"] - stats["precpu_stats"]["system_cpu_usage"]
        num_cpus = len(stats["cpu_stats"]["cpu_usage"]["percpu_usage"] or [1])
        cpu_percent = (cpu_delta / system_delta) * num_cpus * 100.0 if system_delta > 0 else 0.0

        # Memory stats
        memory_usage = stats["memory_stats"].get("usage", 0)
        memory_limit = stats["memory_stats"].get("limit", 0)
        memory_percent = (memory_usage / memory_limit * 100.0) if memory_limit > 0 else 0.0

        # Network stats
        networks = stats.get("networks", {})
        network_rx = sum(net.get("rx_bytes", 0) for net in networks.values())
        network_tx = sum(net.get("tx_bytes", 0) for net in networks.values())

        return {
            "cpu_percent": round(cpu_percent, 2),
            "memory_usage": memory_usage,
            "memory_limit": memory_limit,
            "memory_percent": round(memory_percent, 2),
            "network_rx": network_rx,
            "network_tx": network_tx,
        }
    except docker.errors.NotFound:
        return None
    except Exception:
        return None
