"""Documented multicast reception, response matching and read-only LAN probing."""

import json
import socket
from unittest.mock import MagicMock, patch

import pytest

from custom_components.govee_lan.api import (
    CLIENT_PORT,
    MULTICAST_ADDR,
    GoveeLanClient,
    _make_socket,
)


def reply(cmd, data, host="192.0.2.1"):
    return json.dumps({"msg": {"cmd": cmd, "data": data}}).encode(), (host, 4003)


def test_reply_socket_joins_documented_multicast_group():
    with patch("socket.socket"):
        sock = _make_socket(CLIENT_PORT)
    sock.bind.assert_called_once_with(("", 4002))
    sock.setsockopt.assert_any_call(
        socket.IPPROTO_IP,
        socket.IP_ADD_MEMBERSHIP,
        socket.inet_aton(MULTICAST_ADDR) + socket.inet_aton("0.0.0.0"),
    )


def test_control_socket_does_not_join_or_bind_reply_port():
    with patch("socket.socket"):
        sock = _make_socket()
    sock.bind.assert_not_called()
    assert all(
        call.args[1] != socket.IP_ADD_MEMBERSHIP
        for call in sock.setsockopt.call_args_list
    )


@pytest.mark.parametrize("operation", ["bind", "membership"])
def test_socket_is_closed_if_receive_setup_fails(operation):
    with patch("socket.socket") as factory:
        sock = factory.return_value
        if operation == "bind":
            sock.bind.side_effect = OSError("port in use")
        else:
            sock.setsockopt.side_effect = [None, OSError("membership failed")]
        with pytest.raises(OSError):
            _make_socket(CLIENT_PORT)
        sock.close.assert_called_once()


def test_probe_reads_versions_and_status_without_changing_light_or_exposing_id():
    recv, send = MagicMock(), MagicMock()
    recv.__enter__.return_value = recv
    send.__enter__.return_value = send
    recv.recvfrom.side_effect = [
        reply("scan", {"sku": "wrong device"}, host="192.0.2.2"),
        (b"{invalid", ("192.0.2.1", 4003)),
        reply(
            "scan",
            {
                "sku": "H60A1",
                "device": "PRIVATE_IDENTIFIER",
                "ip": "192.0.2.1",
                "bleVersionHard": "1.04.03",
                "bleVersionSoft": "1.02.20",
                "wifiVersionHard": "4.01.00",
                "wifiVersionSoft": "1.00.10",
            },
        ),
        reply("devStatus", {"onOff": 1, "brightness": 51, "unexpected": "private"}),
    ]
    client = GoveeLanClient("192.0.2.1", "H60A1")
    with patch(
        "custom_components.govee_lan.api._make_socket", side_effect=[recv, send]
    ):
        result = client.probe_lan()
    assert result["scan_received"] and result["status_received"]
    assert result["versions"]["wifiVersionSoft"] == "1.00.10"
    assert result["status"] == {"onOff": 1, "brightness": 51}
    assert "PRIVATE_IDENTIFIER" not in json.dumps(result)
    sent = [
        (json.loads(call.args[0]), call.args[1]) for call in send.sendto.call_args_list
    ]
    assert sent == [
        (
            {"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}},
            ("192.0.2.1", 4001),
        ),
        ({"msg": {"cmd": "devStatus", "data": {}}}, ("192.0.2.1", 4003)),
    ]


def test_probe_timeout_is_not_reported_as_device_support_failure():
    recv, send = MagicMock(), MagicMock()
    recv.__enter__.return_value = recv
    send.__enter__.return_value = send
    recv.recvfrom.side_effect = TimeoutError
    with patch(
        "custom_components.govee_lan.api._make_socket", side_effect=[recv, send]
    ):
        result = GoveeLanClient("192.0.2.1", "H60A1").probe_lan()
    assert result == {"sku": "H60A1", "scan_received": False, "status_received": False}


def test_status_query_does_not_mistake_scan_reply_for_status():
    recv, send = MagicMock(), MagicMock()
    recv.recvfrom.side_effect = [
        reply("scan", {"sku": "H60A1"}),
        reply("devStatus", {"onOff": 1, "brightness": 51}),
    ]
    with patch(
        "custom_components.govee_lan.api._make_socket", side_effect=[recv, send]
    ):
        status = GoveeLanClient("192.0.2.1", "H60A1").get_status()
    assert status == {"onOff": 1, "brightness": 51}
    recv.close.assert_called_once()
    send.close.assert_called_once()


async def test_read_only_probe_action_returns_response_data(setup_light):
    hass, (ceiling, _), (client, _) = setup_light
    expected = {
        "sku": "H60A1",
        "scan_received": True,
        "versions": {"wifiVersionSoft": "1.00.10"},
    }
    with patch.object(client, "probe_lan", return_value=expected):
        result = await hass.services.async_call(
            "govee_lan",
            "probe_lan",
            {
                "entity_id": ceiling.entity_id,
            },
            blocking=True,
            return_response=True,
        )
    assert result == {ceiling.entity_id: expected}
    client._send.assert_not_called()
    ceiling.async_write_ha_state.assert_not_called()
