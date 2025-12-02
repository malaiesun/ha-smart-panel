import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN, CONF_MANUAL_CONFIG

class MeshPanelOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options.get(CONF_MANUAL_CONFIG, "")
        schema = vol.Schema({
            vol.Optional(CONF_MANUAL_CONFIG, default=current): str
        })
        return self.async_show_form(step_id="init", data_schema=schema)

async def async_get_options_flow(config_entry):
    return MeshPanelOptionsFlowHandler(config_entry)