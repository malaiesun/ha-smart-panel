import uuid
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.selector import (
    TextSelector,
    SelectSelector, SelectSelectorConfig, SelectSelectorMode,
    EntitySelector, EntitySelectorConfig,
    IconSelector,
    NumberSelector, NumberSelectorConfig
)
from .const import DOMAIN, CONF_DEVICES

CONF_NAME = "name"
CONF_ICON = "icon"
CONF_ENTITY = "entity"
CONF_TYPE = "type"
CONF_MIN = "min"
CONF_MAX = "max"
CONF_ID = "id"

DEVICE_TYPES = [
    {"value": "switch", "label": "Switch (On/Off)"},
    {"value": "slider", "label": "Slider (Brightness/Volume)"},
    {"value": "color", "label": "Color Wheel"},
    {"value": "select", "label": "Dropdown Selection"},
]

class MeshPanelOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self.config_entry = config_entry
        self.options = dict(config_entry.options)
        self.devices = self.options.get(CONF_DEVICES, [])

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        return await self.async_step_menu()

    async def async_step_menu(self, user_input=None):
        """Show the main menu."""
        if user_input is not None:
            if user_input["menu"] == "add":
                return await self.async_step_edit()
            else:
                # user_input["menu"] contains the ID of the device to edit
                return await self.async_step_edit(None, user_input["menu"])

        options = {"add": "➕ Add New Device"}
        for dev in self.devices:
            options[dev[CONF_ID]] = f"{dev.get(CONF_ICON, '')} {dev[CONF_NAME]}"

        return self.async_show_form(
            step_id="menu",
            data_schema=vol.Schema({
                vol.Required("menu"): vol.In(options)
            })
        )

    async def async_step_edit(self, user_input=None, device_id=None):
        """Edit or Add a device."""
        errors = {}
        
        # Find existing device if editing
        existing = {}
        if device_id:
            for d in self.devices:
                if d[CONF_ID] == device_id:
                    existing = d
                    break

        if user_input is not None:
            # Check if Delete was pressed
            if user_input.get("delete", False):
                self.devices = [d for d in self.devices if d[CONF_ID] != existing.get(CONF_ID)]
                self.options[CONF_DEVICES] = self.devices
                return self.async_create_entry(title="", data=self.options)

            # Save Logic
            new_device = {
                CONF_ID: existing.get(CONF_ID, str(uuid.uuid4())),
                CONF_NAME: user_input[CONF_NAME],
                CONF_ICON: user_input[CONF_ICON],
                CONF_ENTITY: user_input[CONF_ENTITY],
                CONF_TYPE: user_input[CONF_TYPE],
                CONF_MIN: user_input.get(CONF_MIN, 0),
                CONF_MAX: user_input.get(CONF_MAX, 100),
            }

            if device_id:
                # Update existing
                for i, d in enumerate(self.devices):
                    if d[CONF_ID] == device_id:
                        self.devices[i] = new_device
                        break
            else:
                # Add new
                self.devices.append(new_device)

            self.options[CONF_DEVICES] = self.devices
            return self.async_create_entry(title="", data=self.options)

        # Build Form
        schema = vol.Schema({
            vol.Required(CONF_NAME, default=existing.get(CONF_NAME, "")): TextSelector(),
            vol.Required(CONF_ICON, default=existing.get(CONF_ICON, "mdi:power")): IconSelector(),
            vol.Required(CONF_ENTITY, default=existing.get(CONF_ENTITY, "")): EntitySelector(EntitySelectorConfig()),
            vol.Required(CONF_TYPE, default=existing.get(CONF_TYPE, "switch")): SelectSelector(
                SelectSelectorConfig(options=DEVICE_TYPES, mode=SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(CONF_MIN, default=existing.get(CONF_MIN, 0)): NumberSelector(NumberSelectorConfig(min=0, max=1000)),
            vol.Optional(CONF_MAX, default=existing.get(CONF_MAX, 100)): NumberSelector(NumberSelectorConfig(min=0, max=1000)),
            vol.Optional("delete", default=False): bool,
        })

        return self.async_show_form(
            step_id="edit",
            data_schema=schema,
            errors=errors,
            description_placeholders={"device": existing.get(CONF_NAME, "New Device")}
        )

async def async_get_options_flow(config_entry):
    return MeshPanelOptionsFlowHandler(config_entry)