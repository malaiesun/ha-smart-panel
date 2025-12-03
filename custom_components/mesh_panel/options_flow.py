"""Options flow for MESH Smart Home Panel."""
import logging
import voluptuous as vol
import yaml
import uuid
from homeassistant import config_entries
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig
from .const import *

_LOGGER = logging.getLogger(__name__)

class MeshPanelOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle an options flow for MESH Panel."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        
        panel_id = self.config_entry.data[CONF_PANEL_ID]
        store = self.hass.data[DOMAIN][self.config_entry.entry_id]["store"]

        if user_input is not None:
            try:
                devices = yaml.safe_load(user_input[CONF_DEVICES])
                if devices is None:
                    devices = []
                if not isinstance(devices, list):
                    raise ValueError("YAML must be a list of devices")
                
                # Basic validation and add IDs
                for device in devices:
                    if not isinstance(device, dict) or not device.get("name") or not isinstance(device.get("controls"), list):
                        raise ValueError("Invalid device structure in YAML")
                    if "id" not in device or not device.get("id"):
                        device["id"] = str(uuid.uuid4())
                    for control in device.get("controls", []):
                        if not isinstance(control, dict) or not control.get("label"):
                            raise ValueError("Invalid control structure in YAML")
                        if "id" not in control or not control.get("id"):
                            control["id"] = str(uuid.uuid4())

                await store.async_save_devices(devices)
                
                async def _reload():
                    await self.hass.config_entries.async_reload(self.config_entry.entry_id)

                self.hass.async_create_task(_reload())
                return self.async_create_entry(title="", data={})

            except (yaml.YAMLError, ValueError) as e:
                _LOGGER.error("YAML parsing error: %s", e)
                errors["base"] = "invalid_yaml"

        current_devices = await store.async_load_devices()
        current_yaml = ""
        if current_devices:
            try:
                current_yaml = yaml.dump(current_devices)
            except Exception as e:
                _LOGGER.error("Error dumping current config to YAML: %s", e)
                errors["base"] = "yaml_dump_error"

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_DEVICES, default=current_yaml): TextSelector(TextSelectorConfig(multiline=True))
            }),
            errors=errors,
            description_placeholders={"description": "Configure devices using YAML. After saving, the integration will be reloaded."}
        )