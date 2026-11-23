"""Saved scene validation, transactional storage and shared HA effects."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.govee_lan.backlight_scenes import BacklightSceneStore
from custom_components.govee_lan.govee_scene import GoveeLanError
from custom_components.govee_lan.segments import backlight_scene_groups


@pytest.mark.parametrize(
    "colors",
    [[], [[0, 0, 0]] * 12, [[0, 0, 0]] * 14, [[True, 0, 0]] * 13, [[256, 0, 0]] * 13],
)
def test_bad_editor_scenes_rejected(colors):
    with pytest.raises(GoveeLanError):
        backlight_scene_groups(colors)


@pytest.fixture
def store():
    with patch("custom_components.govee_lan.backlight_scenes.Store") as cls:
        cls.return_value.async_load = AsyncMock(
            return_value={
                "Old": {"colors": [[1, 2, 3]] * 13},
                "Corrupt": {"colors": []},
            }
        )
        cls.return_value.async_save = AsyncMock()
        yield BacklightSceneStore(MagicMock()), cls.return_value


async def test_store_sanitizes_and_serializes_concurrent_writes(store):
    scenes, storage = store
    assert list(await scenes.async_load()) == ["Old"]
    await asyncio.gather(
        scenes.async_save("Red", [[255, 0, 0]] * 13),
        scenes.async_save("Blue", [[0, 0, 255]] * 13),
    )
    assert set(await scenes.async_load()) == {"Old", "Red", "Blue"}
    assert set(storage.async_save.call_args.args[0]) == {"Old", "Red", "Blue"}
    storage.async_load.assert_awaited_once()
    snapshot = await scenes.async_load()
    snapshot["Red"]["colors"][0][0] = 99
    assert (await scenes.async_load())["Red"]["colors"][0][0] == 255


async def test_failed_save_or_delete_does_not_change_published_presets(store):
    scenes, storage = store
    await scenes.async_load()
    storage.async_save.side_effect = OSError("disk full")
    with pytest.raises(OSError):
        await scenes.async_save("New", [[2, 3, 4]] * 13)
    with pytest.raises(OSError):
        await scenes.async_delete("Old")
    assert list(await scenes.async_load()) == ["Old"]


@pytest.mark.parametrize("name", ["", " ", "a" * 81])
async def test_invalid_names_do_not_write(store, name):
    scenes, storage = store
    with pytest.raises(GoveeLanError):
        await scenes.async_save(name, [[1, 2, 3]] * 13)
    storage.async_save.assert_not_awaited()


async def test_actual_ha_save_reload_apply_and_delete(setup_light):
    hass, (ceiling, lamp), (client, lamp_client) = setup_light
    colors = [[1, 2, 3]] * 12 + [[255, 0, 0]]
    await hass.services.async_call(
        "govee_lan",
        "save_backlight_scene",
        {
            "entity_id": ceiling.entity_id,
            "name": "Evening",
            "colors": colors,
        },
        blocking=True,
    )
    client._send.assert_not_called()
    assert "Backlight: Evening" in ceiling.effect_list
    assert (
        ceiling.extra_state_attributes["backlight_scene_presets"]["Evening"]["colors"]
        == colors
    )
    # A fresh Store reads the HA storage file, not just the in-memory singleton.
    assert (await BacklightSceneStore(hass).async_load())["Evening"]["colors"] == colors
    await hass.services.async_call(
        "govee_lan",
        "set_backlight_scene",
        {
            "entity_id": ceiling.entity_id,
            "name": "Evening",
        },
        blocking=True,
    )
    client._send.assert_called_once()
    assert client._send.call_args.args[0]["msg"]["cmd"] == "ptReal"
    assert ceiling.effect == "Backlight: Evening"
    client._send.reset_mock()
    await ceiling.async_turn_on(effect="Backlight: Evening")
    assert [call.args[0]["msg"]["cmd"] for call in client._send.call_args_list] == [
        "turn",
        "ptReal",
    ]
    client._send.reset_mock()
    await hass.services.async_call(
        "govee_lan",
        "delete_backlight_scene",
        {
            "entity_id": ceiling.entity_id,
            "name": "Evening",
        },
        blocking=True,
    )
    assert "Backlight: Evening" not in ceiling.effect_list
    assert ceiling.effect is None
    client._send.assert_not_called()
    lamp_client._send.assert_not_called()
    assert not lamp._backlight_scene_presets


async def test_preset_changes_refresh_compatible_loaded_lights(setup_light):
    hass, (ceiling, lamp), _ = setup_light
    from custom_components.govee_lan.light import GoveeLanLight
    from custom_components.govee_lan.api import GoveeLanClient

    second = GoveeLanLight(
        GoveeLanClient("192.0.2.2", "H60A1", "second"),
        SimpleNamespace(data={"name": "Second", "poll_status": False}),
    )
    second.hass = hass
    second.async_write_ha_state = MagicMock()
    hass.data.setdefault("govee_lan", {})["matrix_lights"] = {ceiling, second, lamp}
    await ceiling.async_save_backlight_scene("Shared", [[0, 255, 0]] * 13)
    assert "Backlight: Shared" in second.effect_list
    await ceiling.async_delete_backlight_scene("Shared")
    assert "Backlight: Shared" not in second.effect_list


@pytest.mark.parametrize(
    "service,data",
    [
        ("save_backlight_scene", {"name": "Wrong model", "colors": [[0, 0, 0]] * 13}),
        ("delete_backlight_scene", {"name": "Wrong model"}),
        ("set_backlight_scene", {"name": "Wrong model"}),
    ],
)
async def test_saved_scene_actions_reject_h6022(setup_light, service, data):
    hass, (_, lamp), (_, client) = setup_light
    with pytest.raises(HomeAssistantError, match="only on H60A1"):
        await hass.services.async_call(
            "govee_lan",
            service,
            {
                "entity_id": lamp.entity_id,
                **data,
            },
            blocking=True,
        )
    client._send.assert_not_called()
