"""Shared Home Assistant service-registry fixture with client I/O mocked."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import EntityPlatform
from custom_components.govee_lan import light as light_platform
from custom_components.govee_lan.api import GoveeLanClient


@pytest.fixture
async def setup_light(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    # All client I/O is mocked; execute these jobs inline for deterministic
    # service tests without starting HA's thread pool in pytest's event loop.
    hass.async_add_executor_job = AsyncMock(side_effect=lambda job, *args: job(*args))
    platform = EntityPlatform(
        hass=hass,
        logger=logging.getLogger(__name__),
        domain="light",
        platform_name="govee_lan",
        platform=None,
        scan_interval=light_platform.SCAN_INTERVAL,
        entity_namespace=None,
    )
    lights = []
    clients = []
    for sku in ["H60A1", "H6022"]:
        client = GoveeLanClient("192.0.2.1", sku, f"id-{sku}")
        client._send = MagicMock()
        entry = SimpleNamespace(
            data={"name": sku, "sku": sku, "poll_status": False}, runtime_data=client
        )
        entities = []
        with patch.object(
            light_platform, "async_get_current_platform", return_value=platform
        ):
            await light_platform.async_setup_entry(
                hass, entry, lambda new, _: entities.extend(new)
            )
        (entity,) = entities
        entity.hass = hass
        entity.entity_id = f"light.{sku.lower()}"
        entity.async_write_ha_state = MagicMock()
        platform.domain_platform_entities[entity.entity_id] = entity
        lights.append(entity)
        clients.append(client)
    yield hass, lights, clients
    # HA normally owns the event loop. Keep pytest's loop callbacks usable
    # so asyncio.Runner can shut down its own executor after HA stops.
    with patch("homeassistant.core.shutdown_run_callback_threadsafe"):
        await hass.async_stop(force=True)
