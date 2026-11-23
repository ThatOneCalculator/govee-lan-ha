"""Exercise actual HA service registration, targeting, and light handlers."""

import base64
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.govee_lan import light as light_platform
from custom_components.govee_lan.h60a1_scenes import H60A1_SCENES


async def test_real_ha_service_targets_only_h60a1_and_uses_rear_mask(setup_light):
    hass, (ceiling, lamp), (client, lamp_client) = setup_light
    ceiling._attr_rgb_color = (100, 120, 140)
    ceiling._attr_brightness = 81
    ceiling._attr_effect = "Sunset"
    await hass.services.async_call(
        "govee_lan",
        "set_backlight",
        {
            "entity_id": ceiling.entity_id,
            "color": [0, 0, 0],
        },
        blocking=True,
    )
    client._send.assert_called_once()
    lamp_client._send.assert_not_called()
    frame = base64.b64decode(
        client._send.call_args.args[0]["msg"]["data"]["command"][0]
    )
    assert frame[12:14] == b"\xff\x1f"
    assert frame[4:7] == bytes(3)
    assert ceiling.rgb_color == (100, 120, 140)
    assert ceiling.brightness == 81
    assert ceiling.effect is None
    assert ceiling.extra_state_attributes["backlight_segment_count"] == 13
    assert "backlight_segment_count" not in lamp.extra_state_attributes


async def test_real_ha_segment_service(setup_light):
    hass, (ceiling, _), (client, _) = setup_light
    await hass.services.async_call(
        "govee_lan",
        "set_segment_colors",
        {
            "entity_id": ceiling.entity_id,
            "groups": [
                {"segments": [1], "color": [255, 0, 0]},
                {"segments": [13], "color": [0, 0, 255]},
            ],
        },
        blocking=True,
    )
    commands = client._send.call_args.args[0]["msg"]["data"]["command"]
    assert len(commands) == 2
    assert base64.b64decode(commands[1])[12:14] == b"\x00\x10"


@pytest.mark.parametrize(
    "data",
    [
        {"groups": []},
        {"groups": [{"segments": [14], "color": [0, 0, 0]}]},
        {"groups": [{"segments": [1], "color": [256, 0, 0]}]},
        {"groups": [{"segments": [1], "color": [1.5, 0, 0]}]},
        {"groups": [{"segments": [1], "color": [0, 0]}]},
        {
            "groups": [
                {"segments": [1], "color": [0, 0, 0]},
                {"segments": [1], "color": [0, 0, 255]},
            ]
        },
    ],
)
async def test_real_ha_action_rejects_invalid_data_without_send(setup_light, data):
    hass, (ceiling, _), (client, _) = setup_light
    with pytest.raises((HomeAssistantError, light_platform.vol.Invalid)):
        await hass.services.async_call(
            "govee_lan",
            "set_segment_colors",
            {
                "entity_id": ceiling.entity_id,
                **data,
            },
            blocking=True,
        )
    client._send.assert_not_called()


async def test_real_ha_action_rejects_h6022(setup_light):
    hass, (_, lamp), (_, client) = setup_light
    with pytest.raises(HomeAssistantError, match="not supported"):
        await hass.services.async_call(
            "govee_lan",
            "set_backlight",
            {
                "entity_id": lamp.entity_id,
                "color": [255, 0, 0],
            },
            blocking=True,
        )
    client._send.assert_not_called()


async def test_send_error_reaches_ha_and_does_not_clear_effect(setup_light):
    hass, (ceiling, _), (client, _) = setup_light
    ceiling._attr_effect = "Sunset"
    client._send.side_effect = OSError("network unavailable")
    with pytest.raises(HomeAssistantError, match="network unavailable"):
        await hass.services.async_call(
            "govee_lan",
            "set_backlight",
            {
                "entity_id": ceiling.entity_id,
                "color": [255, 0, 0],
            },
            blocking=True,
        )
    assert ceiling.effect == "Sunset"
    ceiling.async_write_ha_state.assert_not_called()


async def test_h60a1_effects_offline_and_no_h6022_controls(setup_light):
    hass, (ceiling, _), (client, _) = setup_light
    ceiling.async_on_remove = MagicMock()
    with patch("urllib.request.urlopen", side_effect=AssertionError("No cloud")):
        await ceiling.async_added_to_hass()
    assert set(ceiling.effect_list) == {scene["name"] for scene in H60A1_SCENES}
    assert len(ceiling.effect_list) == 79
    assert (ceiling.min_color_temp_kelvin, ceiling.max_color_temp_kelvin) == (
        2200,
        6500,
    )
    await ceiling.async_turn_on(effect="Sunset")
    calls = [call.args[0]["msg"] for call in client._send.call_args_list]
    assert calls[0] == {"cmd": "turn", "data": {"value": 1}}
    assert (
        base64.b64decode(calls[1]["data"]["command"][0])[:5] == b"\x33\x05\x04\x02\x00"
    )


async def test_h6022_effect_inventory_and_commands_preserved(setup_light):
    hass, (_, lamp), (_, client) = setup_light
    lamp.async_on_remove = MagicMock()
    with (
        patch.object(lamp, "_async_load_sg_scene_options", return_value={}),
        patch.object(lamp, "_async_load_matrix_scene_presets", return_value={}),
    ):
        await lamp.async_added_to_hass()
    assert "SG: Breathe" in lamp.effect_list
    assert "Music: Hopping" in lamp.effect_list
    assert (lamp.min_color_temp_kelvin, lamp.max_color_temp_kelvin) == (2700, 6500)
    await lamp.async_turn_on(effect="Music: Hopping")
    assert client._send.call_args.args[0]["msg"]["cmd"] == "ptReal"
    client._send.reset_mock()
    await lamp.async_turn_on(rgb_color=(1, 2, 3), brightness=128)
    messages = [call.args[0]["msg"] for call in client._send.call_args_list]
    assert [msg["cmd"] for msg in messages] == ["turn", "colorwc", "brightness"]
    assert messages[1]["data"] == {
        "color": {"r": 1, "g": 2, "b": 3},
        "colorTemInKelvin": 0,
    }
    assert messages[2]["data"] == {"value": 50}
    await lamp.async_turn_off()
    assert client._send.call_args.args[0]["msg"] == {
        "cmd": "turn",
        "data": {"value": 0},
    }
