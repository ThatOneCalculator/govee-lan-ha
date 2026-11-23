# H60A1 protocol evidence and hardware validation

Implemented for the regular **H60A1**, with 13 rear RGBIC segments and the
2200–6500 K range reported in the supplied Home Assistant diagnostics.
This is a LAN integration; no Bluetooth pairing, cloud account, or API key is
added. H6022 scene, music, matrix, and ordinary light control paths are retained.

## Evidence

Inspected on 2026-11-23:

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
Actual front-panel preservation, segment geometry, black-as-off behavior,
batched-command handling, and scene switching remain **unverified on hardware**.
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
