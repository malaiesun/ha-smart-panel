"""Options flow for MESH Smart Home Panel."""
import logging
from homeassistant import config_entries

_LOGGER = logging.getLogger(__name__)

class MeshPanelOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle an options flow for MESH Panel."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        """Initialize options flow."""
        pass

    async def async_step_init(self, user_input=None):
        """Handle the initial step."""
        return self.async_abort(reason="not_implemented")
