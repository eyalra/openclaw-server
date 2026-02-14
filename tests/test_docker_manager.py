"""Tests for DockerManager (mocked Docker SDK)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import docker.errors
import pytest

from clawctl.core.docker_manager import (
    DockerManager,
    _container_name,
    _network_name,
)
from clawctl.models.config import Config


class TestNaming:
    def test_container_name(self):
        assert _container_name("alice") == "openclaw-alice"

    def test_network_name(self):
        assert _network_name("alice") == "openclaw-net-alice"


class TestDockerManager:
    @pytest.fixture
    def mock_client(self):
        with patch("clawctl.core.docker_manager.docker.from_env") as mock_from_env:
            client = MagicMock()
            mock_from_env.return_value = client
            yield client

    @pytest.fixture
    def manager(self, sample_config: Config, mock_client):
        return DockerManager(sample_config)

    def test_image_tag(self, manager: DockerManager):
        assert manager.image_tag == "openclaw-instance:latest"

    def test_image_exists_true(self, manager: DockerManager, mock_client):
        mock_client.images.get.return_value = MagicMock()
        assert manager.image_exists() is True

    def test_image_exists_false(self, manager: DockerManager, mock_client):
        mock_client.images.get.side_effect = docker.errors.ImageNotFound("not found")
        assert manager.image_exists() is False

    def test_create_network(self, manager: DockerManager, mock_client):
        mock_client.networks.get.side_effect = docker.errors.NotFound("not found")
        manager.create_network("alice")
        mock_client.networks.create.assert_called_once_with(
            "openclaw-net-alice", driver="bridge"
        )

    def test_create_network_already_exists(self, manager: DockerManager, mock_client):
        mock_client.networks.get.return_value = MagicMock()
        manager.create_network("alice")
        mock_client.networks.create.assert_not_called()

    def test_container_exists(self, manager: DockerManager, mock_client):
        mock_client.containers.get.return_value = MagicMock()
        assert manager.container_exists("alice") is True

    def test_container_not_exists(self, manager: DockerManager, mock_client):
        mock_client.containers.get.side_effect = docker.errors.NotFound("not found")
        assert manager.container_exists("alice") is False

    def test_get_container_status(self, manager: DockerManager, mock_client):
        container = MagicMock()
        container.status = "running"
        mock_client.containers.get.return_value = container
        assert manager.get_container_status("alice") == "running"

    def test_get_container_status_not_found(self, manager: DockerManager, mock_client):
        mock_client.containers.get.side_effect = docker.errors.NotFound("not found")
        assert manager.get_container_status("alice") == "not found"

    def test_get_all_statuses(self, manager: DockerManager, mock_client):
        container = MagicMock()
        container.status = "running"
        container.attrs = {
            "NetworkSettings": {"Ports": {"18789/tcp": [{"HostPort": "54321"}]}}
        }
        mock_client.containers.get.return_value = container
        statuses = manager.get_all_statuses()
        assert "testuser" in statuses
        assert statuses["testuser"]["status"] == "running"
        assert statuses["testuser"]["port"] == "54321"
