"""Invariants of the fork's Portainer production stack (deploy/portainer/compose.yaml)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

COMPOSE = Path(__file__).resolve().parents[2] / "deploy" / "portainer" / "compose.yaml"
IMAGE_LINE = re.compile(r"(?m)^    image: ghcr\.io/reannu123/codex-lb@sha256:[0-9a-f]{64}$")


def test_image_is_one_pinned_digest_line() -> None:
    text = COMPOSE.read_text()
    assert len(IMAGE_LINE.findall(text)) == 1
    assert text.count("image:") == 1


def test_matches_the_hand_managed_production_service() -> None:
    services = yaml.safe_load(COMPOSE.read_text())["services"]
    assert list(services) == ["codex-lb"]
    service = services["codex-lb"]
    # A fixed name makes a second stack on the same data dir fail to start.
    assert service["container_name"] == "codex-lb"
    assert service["restart"] == "unless-stopped"
    assert service["stop_grace_period"] == "45s"
    # All interfaces, no host IP: Nginx Proxy Manager forwards codex-lb.home to the
    # LAN address, operators use Tailscale, and neither address change can stop
    # the container from starting.
    assert service["ports"] == ["2455:2455"]
    assert service["volumes"] == ["/docker/appdata/codex-lb:/var/lib/codex-lb:Z"]
    assert "/health/ready" in " ".join(service["healthcheck"]["test"])
    # Nothing sensitive or host-specific is injected through the file.
    assert "environment" not in service and "env_file" not in service
