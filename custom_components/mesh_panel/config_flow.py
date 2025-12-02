import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN, CONF_PANEL_ID, CONF_LAYOUT, DEFAULT_LAYOUT


class MeshPanelConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_PANEL_ID])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=user_input["name"],
                data={CONF_PANEL_ID: user_input[CONF_PANEL_ID]},
                options={CONF_LAYOUT: DEFAULT_LAYOUT},
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("name"): str,
                vol.Required(CONF_PANEL_ID): str,
            }),
        )

    async def async_step_discovery(self, user_input=None):
        panel_id = user_input.get("panel_id") if user_input else None
        if not panel_id:
            return self.async_abort(reason="unknown")
        await self.async_set_unique_id(panel_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"Mesh Panel ({panel_id})",
            data={CONF_PANEL_ID: panel_id},
            options={CONF_LAYOUT: DEFAULT_LAYOUT},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        from .options_flow import MeshPanelOptionsFlowHandler  # lazy import to avoid cycles
        return MeshPanelOptionsFlowHandler(config_entry)
