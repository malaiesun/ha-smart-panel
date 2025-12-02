import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components import mqtt
from .const import DOMAIN, CONF_PANEL_ID, CONF_DEVICES, TOPIC_ANNOUNCE
from .panel_manager import MeshPanelController
import json

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass: HomeAssistant, config):
    async def _announce(msg):
        try:
            data = json.loads(msg.payload or "{}")
            panel_id = data.get("panel_id")
            if panel_id:
                await hass.config_entries.flow.async_init(
                    DOMAIN, context={"source": "mqtt"}, data={CONF_PANEL_ID: panel_id}
                )
        except: pass
    await mqtt.async_subscribe(hass, TOPIC_ANNOUNCE, _announce)
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    panel_id = entry.data[CONF_PANEL_ID]
    # GET CONFIG FROM VISUAL EDITOR STORAGE
    devices_data = entry.options.get(CONF_DEVICES, []) 

    ctrl = MeshPanelController(hass, panel_id, devices_data)
    await ctrl.start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = ctrl
    
    # Reload when options change (Visual Editor save)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_reload(entry.entry_id)