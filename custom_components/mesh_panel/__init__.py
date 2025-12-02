import json
import logging
import yaml
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.components import mqtt

from .const import (
    DOMAIN, CONF_PANEL_ID, CONF_MANUAL_CONFIG,
    TOPIC_ANNOUNCE
)
from .panel_manager import MeshPanelController
from .config_flow import ConfigFlow  # Add this import

_LOGGER = logging.getLogger(__name__)

PLATFORMS = []  # Add if you have platforms

async def async_setup(hass: HomeAssistant, config):
    # Subscribe for auto-discovery announces
    async def _announce(msg):
        try:
            data = json.loads(msg.payload or "{}")
            panel_id = data.get("panel_id")
            if not panel_id:
                return

            # Skip if already configured
            for e in hass.config_entries.async_entries(DOMAIN):
                if e.data.get(CONF_PANEL_ID) == panel_id:
                    return

            # Start discovery flow
            await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "mqtt"},
                data={CONF_PANEL_ID: panel_id},
            )
            _LOGGER.info("Discovered MESH Panel via MQTT: %s", panel_id)

        except Exception as e:
            _LOGGER.warning("Bad smartpanel/announce payload: %s", e)

    await mqtt.async_subscribe(hass, TOPIC_ANNOUNCE, _announce)
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    panel_id = entry.data[CONF_PANEL_ID]
    manual_yaml = entry.options.get(CONF_MANUAL_CONFIG, "") or ""
    devices_data = []
    if manual_yaml.strip():
        try:
            devices_data = yaml.safe_load(manual_yaml) or []
        except Exception as e:
            _LOGGER.error("Invalid YAML in options: %s", e)

    ctrl = MeshPanelController(hass, panel_id, devices_data)
    await ctrl.start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = ctrl

    async def _options_updated(_entry: ConfigEntry):
        await async_reload_entry(hass, _entry)

    entry.async_on_unload(entry.add_update_listener(_options_updated))
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    # Nothing persistent to unload beyond unsubscribes handled by panel manager
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_reload(entry.entry_id)