"""The existing Lovelace bundle is upgraded without adding a duplicate resource."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from custom_components.govee_lan import (
    _async_register_scene_card,
    SCENE_CARD_RESOURCE_URL,
)


@pytest.mark.parametrize(
    "url",
    [
        "/govee_lan/govee-scene-card.js",
        "/govee_lan/govee-scene-card.js?v=old",
        "/local/govee-scene-card.js",
    ],
)
async def test_existing_card_resource_upgraded(url):
    resources = SimpleNamespace(
        loaded=True,
        async_items=lambda: [{"id": "card", "url": url}],
        async_update_item=AsyncMock(),
        async_create_item=AsyncMock(),
    )
    hass = SimpleNamespace(
        data={"lovelace": {"resources": resources}},
        http=SimpleNamespace(async_register_static_paths=AsyncMock()),
    )
    await _async_register_scene_card(hass)
    resources.async_update_item.assert_awaited_once_with(
        "card", {"url": SCENE_CARD_RESOURCE_URL}
    )
    resources.async_create_item.assert_not_awaited()


async def test_current_card_resource_not_registered_twice():
    resources = SimpleNamespace(
        loaded=True,
        async_items=lambda: [{"id": "card", "url": SCENE_CARD_RESOURCE_URL}],
        async_update_item=AsyncMock(),
        async_create_item=AsyncMock(),
    )
    hass = SimpleNamespace(
        data={"lovelace": {"resources": resources}},
        http=SimpleNamespace(async_register_static_paths=AsyncMock()),
    )
    await _async_register_scene_card(hass)
    resources.async_update_item.assert_not_awaited()
    resources.async_create_item.assert_not_awaited()
