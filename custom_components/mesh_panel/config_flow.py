"""Config flow for MESH Smart Home Panel."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from .const import DOMAIN, CONF_PANEL_ID, CONF_DEVICES

from .options_flow import MeshPanelOptionsFlowHandler


class MeshPanelConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for MESH Panel."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return MeshPanelOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the initial setup step."""
        errors = {}

        if user_input is not None:
            panel_id = user_input[CONF_PANEL_ID].strip()
            panel_name = user_input["panel_name"].strip()

            # Set unique ID so only one config per panel
            await self.async_set_unique_id(panel_id)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=panel_name,  # This is what shows in HA device list
                data={
                    CONF_PANEL_ID: panel_id,
                    "panel_name": panel_name
                },
                options={CONF_DEVICES: []},
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_PANEL_ID, description="Panel ID (example: panel_01)"): str,
                vol.Required("panel_name", description="Display name in Home Assistant"): str,
            }),
            errors=errors,
        )

    async def async_step_mqtt(self, discovery_info=None) -> FlowResult:
        """Handle MQTT auto-discovery."""
        panel_id = (discovery_info or {}).get(CONF_PANEL_ID)
        if not panel_id:
            return self.async_abort(reason="unknown")

        await self.async_set_unique_id(panel_id)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=f"MESH Panel ({panel_id})",
            data={
                CONF_PANEL_ID: panel_id,
                "panel_name": f"MESH Panel ({panel_id})"
            },
            options={CONF_DEVICES: []},
        )
