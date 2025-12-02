import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from .const import DOMAIN, CONF_PANEL_ID, CONF_DEVICES

class MeshPanelConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for MESH Panel."""
    DOMAIN = DOMAIN 
    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        errors = {}
        if user_input is not None:
            panel_id = user_input[CONF_PANEL_ID].strip()
            await self.async_set_unique_id(panel_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"MESH Panel ({panel_id})",
                data={CONF_PANEL_ID: panel_id},
                options={CONF_DEVICES: []} # Initialize empty list
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_PANEL_ID): str}),
            errors=errors,
        )

    async def async_step_mqtt(self, discovery_info=None) -> FlowResult:
        panel_id = (discovery_info or {}).get(CONF_PANEL_ID)
        if not panel_id:
            return self.async_abort(reason="unknown")

        await self.async_set_unique_id(panel_id)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=f"MESH Panel ({panel_id})",
            data={CONF_PANEL_ID: panel_id},
            options={CONF_DEVICES: []}
        )