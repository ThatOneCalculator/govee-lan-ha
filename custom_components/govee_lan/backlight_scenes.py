"""Persistent H60A1 custom rear-segment scenes, shared across loaded devices."""

from __future__ import annotations

import asyncio
from copy import deepcopy

from homeassistant.helpers.storage import Store

from .govee_scene import GoveeLanError
from .segments import backlight_scene_groups

BACKLIGHT_EFFECT_PREFIX = "Backlight: "
BACKLIGHT_STORE_KEY = "govee_lan_h60a1_backlight_scenes"


def scene_name(name: str) -> str:
    """Normalize a custom scene name without allowing empty or oversized keys."""
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise GoveeLanError("Scene names must contain 1–80 characters")
    return name.strip()


class BacklightSceneStore:
    """Serialize writes and publish in-memory data only after a successful save."""

    def __init__(self, hass) -> None:
        self._store = Store(hass, 1, BACKLIGHT_STORE_KEY)
        self._lock = asyncio.Lock()
        self._presets: dict | None = None

    async def _load(self) -> None:
        if self._presets is not None:
            return
        data = await self._store.async_load()
        presets = {}
        if isinstance(data, dict):
            for name, preset in data.items():
                try:
                    normalized = scene_name(name)
                    backlight_scene_groups(preset["colors"])
                except (GoveeLanError, TypeError, KeyError):
                    continue
                presets[normalized] = {"colors": deepcopy(preset["colors"])}
        self._presets = presets

    async def async_load(self) -> dict:
        async with self._lock:
            await self._load()
            return deepcopy(self._presets)

    async def async_save(self, name: str, colors: list) -> None:
        name = scene_name(name)
        backlight_scene_groups(colors)
        async with self._lock:
            await self._load()
            presets = deepcopy(self._presets)
            presets[name] = {"colors": deepcopy(colors)}
            await self._store.async_save(presets)
            self._presets = presets

    async def async_delete(self, name: str) -> None:
        name = scene_name(name)
        async with self._lock:
            await self._load()
            presets = deepcopy(self._presets)
            if name not in presets:
                raise GoveeLanError(f"No backlight scene named '{name}'")
            del presets[name]
            await self._store.async_save(presets)
            self._presets = presets
