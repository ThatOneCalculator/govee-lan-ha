"""Hardware-free wire-format, transport and H6022 regression tests."""

import base64
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from custom_components.govee_lan.api import GoveeLanClient, _music_mode_packets
from custom_components.govee_lan.govee_scene import (
    GoveeLanError,
    _scene_packets,
    build_h6022_matrix_scene,
    build_h6022_matrix_scene_multi,
    simple_scene_packets,
)
from custom_components.govee_lan.scenes import H60A1_SCENES
from custom_components.govee_lan.segments import segment_color_packets


def decode(packets):
    frames = [base64.b64decode(packet, validate=True) for packet in packets]
    for frame in frames:
        assert len(frame) == 20
        checksum = 0
        for byte in frame:
            checksum ^= byte
        assert checksum == 0
    return frames


@pytest.mark.parametrize(
    "segment,mask",
    [(1, b"\x01\x00"), (8, b"\x80\x00"), (9, b"\x00\x01"), (13, b"\x00\x10")],
)
def test_segment_mask_matches_reference_layout(segment, mask):
    (frame,) = decode(
        segment_color_packets(
            "h60a1", [{"segments": [segment], "color": [255, 110, 84]}]
        )
    )
    # Independent layout from govee-local-api SegmentColorMessages.
    assert frame[:19] == bytes.fromhex(
        "33 05 15 01 ff 6e 54 00 00 00 00 00"
    ) + mask + bytes(5)


def test_all_thirteen_segments_exclude_front_panel_bit():
    (frame,) = decode(
        segment_color_packets(
            "H60A1", [{"segments": list(range(1, 14)), "color": [0, 0, 0]}]
        )
    )
    assert frame[4:7] == bytes(3)
    assert frame[12:14] == b"\xff\x1f"


@pytest.mark.parametrize(
    "groups",
    [
        [],
        [{"segments": [], "color": [0, 0, 0]}],
        [{"segments": [0], "color": [0, 0, 0]}],
        [{"segments": [14], "color": [0, 0, 0]}],
        [{"segments": [True], "color": [0, 0, 0]}],
        [{"segments": [1.5], "color": [0, 0, 0]}],
        [{"segments": [1, 1], "color": [0, 0, 0]}],
        [{"segments": [1], "color": [-1, 0, 0]}],
        [{"segments": [1], "color": [256, 0, 0]}],
        [{"segments": [1], "color": [1.1, 0, 0]}],
        [{"segments": [1], "color": [True, 0, 0]}],
        [{"segments": [1], "color": [1, 0]}],
        [{"segments": [1]}],
        [{"segments": [1], "color": [0, 0, 0], "brightness": 50}],
        [
            {"segments": [1], "color": [0, 0, 0]},
            {"segments": [1], "color": [255, 0, 0]},
        ],
        [
            {"segments": [1], "color": [255, 0, 0]},
            {"segments": [14], "color": [0, 0, 0]},
        ],
    ],
)
def test_bad_input_never_sends_partial_commands(groups):
    client = GoveeLanClient("192.0.2.1", "H60A1")
    with patch.object(client, "_send") as send, pytest.raises(GoveeLanError):
        client.set_segment_colors(groups)
    send.assert_not_called()


@pytest.mark.parametrize("sku", ["H6022", "H60A6", "unknown"])
def test_model_guard_preserves_other_models(sku):
    client = GoveeLanClient("192.0.2.1", sku)
    with patch.object(client, "_send") as send:
        with pytest.raises(GoveeLanError):
            client.set_backlight((255, 0, 0))
        with pytest.raises(GoveeLanError):
            client.set_segment_colors([{"segments": [1], "color": [0, 0, 0]}])
    send.assert_not_called()


def test_segment_udp_envelope_and_no_global_commands():
    client = GoveeLanClient("192.0.2.1", "H60A1")
    groups = [
        {"segments": [1, 2], "color": [255, 0, 0]},
        {"segments": [12, 13], "color": [0, 0, 255]},
    ]
    sock = MagicMock()
    sock.__enter__.return_value = sock
    with patch("custom_components.govee_lan.api._make_socket", return_value=sock):
        client.set_segment_colors(groups)
    sock.sendto.assert_called_once()
    payload, address = sock.sendto.call_args.args
    assert address == ("192.0.2.1", 4003)
    msg = json.loads(payload)["msg"]
    assert msg["cmd"] == "ptReal"
    frames = decode(msg["data"]["command"])
    assert [frame[12:14] for frame in frames] == [b"\x03\x00", b"\x00\x18"]


def test_backlight_routes_only_to_rear_mask():
    client = GoveeLanClient("192.0.2.1", "h60a1")
    with patch.object(client, "_send") as send:
        client.set_backlight((0, 255, 0))
    (frame,) = decode(send.call_args.args[0]["msg"]["data"]["command"])
    assert frame[4:7] == b"\x00\xff\x00"
    assert frame[12:14] == b"\xff\x1f"


@pytest.mark.parametrize("scene", H60A1_SCENES, ids=lambda scene: scene["name"])
def test_h60a1_offline_presets(scene):
    client = GoveeLanClient("192.0.2.1", "H60A1")
    with patch("urllib.request.urlopen", side_effect=AssertionError("No cloud")):
        assert client.fetch_scenes() == H60A1_SCENES
    frames = decode(_scene_packets("H60A1", scene["code"], scene["param"]))
    assert frames[-1][:5] == b"\x33\x05\x04" + scene["code"].to_bytes(2, "little")
    if scene["param"]:
        upload = frames[:-1]
        assert [f[1] for f in upload] == list(range(len(upload) - 1)) + [255]
        envelope = b"".join(f[2:19] for f in upload)
        expected = bytes([1, len(upload), 2]) + base64.b64decode(
            scene["param"], validate=True
        )
        assert envelope == expected.ljust(len(envelope), b"\x00")
    else:
        assert len(frames) == 1


def test_metadata_reads_govee_misspelled_parameter_field():
    client = GoveeLanClient("192.0.2.1", "H6072")
    metadata = {
        "data": {
            "categories": [
                {
                    "categoryName": "Natural",
                    "scenes": [
                        {
                            "sceneName": "Forest",
                            "lightEffects": [{"sceneCode": 212, "scenceParam": "AQID"}],
                        }
                    ],
                }
            ]
        }
    }
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = json.dumps(metadata).encode()
    with patch("urllib.request.urlopen", return_value=response):
        assert client.fetch_scenes() == [
            {"category": "Natural", "name": "Forest", "code": 212, "param": "AQID"}
        ]


def test_h6022_existing_packets_unchanged():
    baseline = json.loads(
        (Path(__file__).parent / "fixtures/h6022_baseline.json").read_text()
    )
    assert (
        _scene_packets("H6022", 8505, "AA8OYBj/ZAD/ZAD/ZAD/ZAD/ZAD/ZAD/ZAD/ZAA=")
        == baseline["scene"]
    )
    assert (
        simple_scene_packets(5, 0, 30, [(255, 0, 0), (0, 0, 255)]) == baseline["simple"]
    )
    assert (
        build_h6022_matrix_scene([((255, 0, 0), [0, 1, 12, 131])])
        == baseline["matrix_param"]
    )
    assert (
        build_h6022_matrix_scene_multi(
            [
                {"groups": [((255, 0, 0), [0, 1, 12])], "mode": 1},
                {"groups": [((0, 0, 255), [12, 13, 131])], "mode": 0},
            ]
        )
        == baseline["matrix_multi_param"]
    )
    decode(baseline["scene"])
    decode(baseline["simple"])
    decode(_music_mode_packets(0x33, 100))


def test_thirteen_individual_colors_fit_one_valid_command_array():
    client = GoveeLanClient("192.0.2.1", "H60A1")
    groups = [
        {"segments": [segment], "color": [segment * 10, 0, 255 - segment * 10]}
        for segment in range(1, 14)
    ]
    with patch.object(client, "_send") as send:
        client.set_segment_colors(groups)
    send.assert_called_once()
    frames = decode(send.call_args.args[0]["msg"]["data"]["command"])
    assert len(frames) == 13
    for segment, frame in enumerate(frames, 1):
        assert int.from_bytes(frame[12:14], "little") == 1 << (segment - 1)
        assert frame[4:7] == bytes(groups[segment - 1]["color"])
