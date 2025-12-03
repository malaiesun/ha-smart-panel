"""The MESH Smart Home Panel integration."""
import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components import mqtt
from .const import DOMAIN, CONF_PANEL_ID, CONF_DEVICES, TOPIC_ANNOUNCE
from .panel_manager import MeshPanelController
import json

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass: HomeAssistant, config):
    """Set up the MESH Smart Home Panel integration."""
    async def _announce(msg):
        """Handle a discovered panel."""
        try:
            data = json.loads(msg.payload or "{}")
            panel_id = data.get("panel_id")
            if panel_id:
                await hass.config_entries.flow.async_init(
                    DOMAIN, context={"source": "mqtt"}, data={CONF_PANEL_ID: panel_id}
                )
        except Exception as e:
            _LOGGER.warning("Could not parse MQTT discovery message: %s", e)
    
    await mqtt.async_subscribe(hass, TOPIC_ANNOUNCE, _announce)
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up MESH panel from a config entry."""
    panel_id = entry.data[CONF_PANEL_ID]
    devices_data = entry.options.get(CONF_DEVICES, []) 

    ctrl = MeshPanelController(hass, panel_id, devices_data)
    await ctrl.start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = ctrl
    
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    ctrl = hass.data[DOMAIN].pop(entry.entry_id, None)
    if ctrl:
        await ctrl.stop()
    return True

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
