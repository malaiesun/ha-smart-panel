from __future__ import annotations
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from .const import DOMAIN, CONF_PANEL_ID

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    panel_id = entry.data[CONF_PANEL_ID]
    async_add_entities([MeshPanelStatusSensor(panel_id, entry.entry_id)], update_before_add=True)

class MeshPanelStatusSensor(BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Status"
    _attr_icon = "mdi:tablet-dashboard"
    _attr_is_on = True  # always on; acts as presence

    def __init__(self, panel_id: str, entry_id: str) -> None:
        self._panel_id = panel_id
        self._attr_unique_id = f"{DOMAIN}_{panel_id}_status"
        self._entry_id = entry_id

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._panel_id)},
            "name": f"MESH Panel ({self._panel_id})",
            "manufacturer": "MESH",
            "model": "Smart Panel",
            "sw_version": "1.0",
        }
