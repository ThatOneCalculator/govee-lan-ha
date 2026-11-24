# H60A1 protocol evidence and hardware validation

Implemented for the regular **H60A1**, with 13 rear RGBIC segments and the
2200–6500 K range reported in the supplied Home Assistant diagnostics.
This is a LAN integration; no Bluetooth pairing, cloud account, or API key is
added. H6022 scene, music, matrix, and ordinary light control paths are retained.

## Observed device result

On 2026-11-23, the user tested an H60A1 reporting firmware **1.02.20** (hardware
revision not yet supplied). Standard LAN color and brightness worked. Selecting
Dreamlike sent its six expected frames, but the user reported no visible effect.
The card's Fill all → Apply colors also had no visible effect. Logs show the
backend received the action and sent one rear-color frame after a long idle
period, followed by additional attempts. The first isolated failure is not
explained by an upload spanning multiple packets or by an immediately preceding
power command from this integration.

The logged Dreamlike frames match the bundled encoder byte-for-byte, are each
20 bytes, and have valid XOR checksums. The rear command uses mask `ff 1f` and
also has a valid checksum. These are framing checks, not evidence that the
device implements or accepts this LAN transport. No acknowledgement is provided.

Conclusion: **this integration's current `ptReal` route is not working on that
tested device**. This does not establish that every H60A1 revision rejects it,
nor does it identify a working alternative LAN envelope. The successful
[firmware 1.02.20 report](https://github.com/teh-hippo/ha-govee-led-ble/issues/340)
uses encrypted BLE through an ESPHome Bluetooth proxy, not LAN. The
[govee2mqtt H60A1 scene report](https://github.com/wez/govee2mqtt/issues/354)
also records normal controls working while LAN scenes do nothing; the original
fix reverted preferring LAN scene control. BLE support must not be treated as
proof of raw-over-LAN support.

The browser widget and static command encoding remain available for experimental
testing. There is no Bluetooth or cloud fallback in this integration. A future
fallback needs an explicitly implemented transport and device acceptance tests.

## Evidence

Inspected on 2026-11-23:

### Direct review of Govee's documentation

The [official WLAN guide](https://app-h5.govee.com/user-manual/wlan-guide)
currently lists H60A1. It specifies joining multicast group `239.255.255.250`,
scan requests on UDP 4001, reply reception on 4002, and control on 4003. The
documented control commands are `turn`, `brightness`, `colorwc`, and `devStatus`.
It does not specify scene or per-segment commands. Its scan reply identifies
Bluetooth and Wi-Fi software/hardware versions separately.

This review found a real client defect: reply sockets were bound to port 4002
without joining the multicast group. Version 0.1.6 joins that group and filters
status replies by command so a scan reply cannot masquerade as device state.
These receive-path fixes do not establish that the device accepts `ptReal`.

The read-only `govee_lan.probe_lan` action sends unicast scan/status queries to
one selected device and returns allowlisted version/state fields. It does not
send controls, enumerate other devices, or return MAC/device identifiers.

Govee's separate [Developer Platform control reference](https://developer.govee.com/reference/control-you-devices)
describes ceiling-light toggles and segmented controls through its authenticated
HTTPS API. Those request schemas are not documented LAN command envelopes.

### Implementation and capture evidence

- [Govee LAN guide](https://app-h5.govee.com/user-manual/wlan-guide): basic
  scan/control/status API on UDP 4001/4003/4002. The basic `colorwc` command
  does not supply a separate backlight selector.
- [govee-local-api message.py](https://github.com/Galorhallen/govee-local-api/blob/737617fcdf9b39c376010fc88ed6ca3f78329ed7/src/govee_local_api/message.py),
  `SegmentColorMessages`: static RGB carried in `ptReal` as base64 frames.
- [govee-local-api capabilities](https://github.com/Galorhallen/govee-local-api/blob/737617fcdf9b39c376010fc88ed6ca3f78329ed7/src/govee_local_api/light_capabilities.py):
  H60A1 has 13 segments; masks start at `01 00` and end at `00 10`.
- [H60A1 BLE report](https://github.com/teh-hippo/ha-govee-led-ble/issues/340):
  on the reported revision, 13 rear segments and a front panel use the static
  command family `33 05 15 01`. The report also describes coupling between
  front-panel Kelvin and rear-ring color. BLE evidence does not prove LAN behavior.
- [BLE model profile](https://github.com/teh-hippo/ha-govee-led-ble/blob/97c8cc354382ea73cc2b1757c28fdf488eac063c/custom_components/ha_govee_led_ble/const.py):
  revision gating, and segment brightness that acknowledges without rendering,
  support avoiding promises of per-zone brightness and white-temperature control.
- [Govee scene metadata](https://app2.govee.com/appsku/v1/light-effect-libraries?sku=H60A1),
  fetched with `AppVersion: 6.5.02`: **79 scene variants**, seven code-only and
  72 type-2 parameter-backed scenes. Sunny A/B retain distinct names and codes.
  The full snapshot lives in `h60a1_scenes.py`, independent of H6022's catalog.
- [BLE native scene encoder](https://github.com/teh-hippo/ha-govee-led-ble/blob/97c8cc354382ea73cc2b1757c28fdf488eac063c/custom_components/ha_govee_led_ble/native_scenes.py),
  `native_scene_upload_route` and `build_native_scene_packets`: the H60A1
  profile uses its catalogue scene type as the upload subtype. For this catalog,
  that is `0x02`, followed by the unmodified parameter body.
- [BLE A3 fragmentation](https://github.com/teh-hippo/ha-govee-led-ble/blob/97c8cc354382ea73cc2b1757c28fdf488eac063c/custom_components/ha_govee_led_ble/transport.py),
  `fragment_a3`, agrees with
  [govee2mqtt SetSceneCode](https://github.com/wez/govee2mqtt/blob/main/src/ble.rs)
  for all bundled H60A1 uploads: `a3 <sequence> 01 <frame count> 02 <body...>`,
  then `33 05 04 <code little-endian>`, with zero padding and XOR checksums.
  Tests reconstruct all 72 uploaded bodies and compare them with the catalog.

## Scene portability and the custom card

Govee does not publish every H6022 scene for H60A1. Shared names such as Rainbow,
Forest, Aurora, Fire, Wave, Christmas and Halloween use H60A1's native payloads.
H6022-only scenes (including pixel-matrix scenes and its SG generators) are not
advertised as supported H60A1 presets. Copying their scene codes would select the
wrong mode or upload the wrong renderer format.

`custom:govee-backlight-card` combines the full native preset picker with a
13-color static rear editor. Saved rear scenes are persisted in HA storage,
serialized under a shared lock, validated on load, and broadcast to loaded H60A1
entities as `Backlight: <name>` effects. Failed storage writes retain the last
published data. The card sends names as data and renders them as text.

The rear editor neither changes the native preset animation nor introduces a
browser-driven animation loop. Backend actions also work with the dashboard
closed. H6022 retains its existing scene and matrix cards.

## Static segment frame

| Offset | Bytes | Meaning |
| --- | --- | --- |
| 0–3 | `33 05 15 01` | Static segment RGB operation |
| 4–6 | `RR GG BB` | RGB channels |
| 7–11 | `00 00 00 00 00` | Unused fields for RGB operation |
| 12–13 | little-endian mask | Bit 0 = segment 1; bit 12 = segment 13 |
| 14–18 | zeros | Padding |
| 19 | XOR of bytes 0–18 | Checksum |

All 13 rear segments use mask `ff 1f`. Bit 13 is never set. Multiple disjoint
color groups are encoded in order in a single `ptReal.data.command` array.
Validation completes before sending anything. Numbers exposed in actions are
**1-based**, distinct from some cloud APIs' 0-based segment indices.

The actions send no global `turn`, `colorwc`, or `brightness` command. Thus the
implementation does not intentionally change the front panel or global power.
Actual front-panel preservation, segment geometry, black-as-off behavior, and
batched-command handling have not been validated. Current scene and rear-color
commands failed the device test described above.
The basic status response has no segment color/state readback. The light's main
RGB/brightness/power state is not replaced with invented rear-segment state.
UDP send success is not an acknowledgement from the lamp.

## Hardware-free validation

Tests run against Home Assistant 2026.11.3 and Python 3.14.10 on x86_64,
using mocked sockets/executor targets. Result: **139 passed** (one upstream
aiohttp inheritance deprecation warning). This does not validate Raspberry Pi
hardware or a running HA OS installation.

- Segment boundary masks, all-rear mask, payload placement, base64, 20-byte
  frames and XOR checksums; multiple disjoint colors in the UDP 4003 envelope.
- Invalid channels, indices, duplicate/overlapping groups, and wrong models
  fail before any command is sent.
- Real HA service registration, entity targeting, schemas and error propagation.
- Offline loading and full parameter reconstruction of all 79 H60A1 variants,
  effect activation and temperature bounds.
- Persistent save/reload/delete, concurrent writes, failed-write rollback, shared
  effects, model guards, and versioned Lovelace resource migration.
- H6022 baseline fixtures from commit `304c161` for scenes, simple animations,
  single/multi-layer matrix encoding, plus music and normal light handlers.

Python compilation, service-description YAML parsing, Ruff checks for undefined
or unused names in the new files, formatting of the new files, and
`git diff --check` also passed.

Run in an isolated environment:

```sh
uv venv --python python3.14 /tmp/govee-test-env
uv pip install --python /tmp/govee-test-env/bin/python -r requirements-test.txt
/tmp/govee-test-env/bin/python -m pytest -q
```

No physical device was contacted by these tests. No installed Home Assistant
configuration or native integration was modified.

## Device acceptance checklist

1. Enable LAN control and add H60A1 to **Govee LAN**. Avoid competing listeners
   on UDP 4002 (the supplied diagnostics are for the native `govee_light_local`
   integration). If retaining that controller, use this integration's manual
   setup with polling disabled via “Skip connection test”.
2. Turn the device on, choose a visible front-panel setting, then apply a rear
   color. Check whether the front panel retains its color/brightness/power.
3. Address segment 1, then 8, 9, and 13. Record physical positions/orientation;
   do not assume clockwise ordering or a particular starting position.
4. Apply two color groups and then all 13 different colors in one action.
   Check whether all frames take effect and unaddressed segments remain stable.
5. Apply black to one segment and then the full rear ring. Check that the front
   stays lit. Verify front temperature changes separately for mode coupling.
6. Try native presets (including Rainbow, Forest, Sunny A/B and the seven code-only presets), return to static rear colors, power-cycle,
   and test after a firmware update. Presets are whole-device effects and may
   change both front and rear output.

Per-segment brightness, an independently switched/temperature-controlled front
entity, animated rear-only scenes, arbitrary Govee app DIY uploads, and segment readback are not
implemented. They require revision-specific captures or hardware acceptance.

## Browser validation

The standalone card harness uses Chromium and a mocked HA object. It checks all
79 preset options, the exact service payloads, individual colors, save/apply/load/
delete, error recovery, unavailable devices, H6022 rejection, safe names, and
layout without horizontal scrolling at 320px. Screenshots were visually inspected.
This covers the custom element in a browser, not a running HA dashboard.

```sh
npm install --prefix /tmp/govee-card-test playwright@1.65.1
/tmp/govee-card-test/node_modules/.bin/playwright install chromium
NODE_PATH=/tmp/govee-card-test/node_modules node tests/test_card.cjs
```

For an existing compatible Chromium, set `GOVEE_TEST_BROWSER` to its executable.
