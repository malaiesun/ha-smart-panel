import json
import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components import mqtt

from .const import DOMAIN
from .panel_manager import MeshPanelManager

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict):
    hass.data.setdefault(DOMAIN, {})

    async def _on_announce(msg):
        try:
            p = json.loads(msg.payload or "{}")
            panel_id = p.get("panel_id")
            if not panel_id:
                return
            # Skip if already configured
            for e in hass.config_entries.async_entries(DOMAIN):
                if e.unique_id == panel_id:
                    return
            await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "discovery"},
                data={"panel_id": panel_id, "ip": p.get("ip")},
            )
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("mesh_panel announce error: %s", e)

    await mqtt.async_subscribe(hass, "smartpanel/announce", _on_announce)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    mgr = MeshPanelManager(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = mgr
    await mgr.async_setup()
    entry.async_on_unload(entry.add_update_listener(_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    mgr: MeshPanelManager = hass.data[DOMAIN].pop(entry.entry_id)
    await mgr.async_unload()
    return True


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_reload(entry.entry_id)
