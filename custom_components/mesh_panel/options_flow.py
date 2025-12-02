"""Options flow for MESH Smart Home Panel."""
import logging
import uuid
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    TextSelector,
    SelectSelector, SelectSelectorConfig, SelectSelectorMode,
    EntitySelector,
    IconSelector,
    NumberSelector, NumberSelectorConfig,
)
from .const import *

_LOGGER = logging.getLogger(__name__)

class MeshPanelOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle an options flow for MESH Panel."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        """Initialize options flow."""
        self.config_entry = config_entry
        self.options = dict(config_entry.options)
        self.current_device_id = None
        self.current_control_id = None

    async def async_step_init(self, user_input=None):
        """Manage the devices."""
        if user_input is not None:
            if "add" == user_input["action"]:
                self.current_device_id = None
                return await self.async_step_device()
            
            self.current_device_id = user_input["action"]
            return await self.async_step_device_menu()

        devices = self.options.get(CONF_DEVICES, [])
        device_map = {d[CONF_ID]: d[CONF_NAME] for d in devices}
        
        options = {"add": "Add a new device", **device_map}

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("action", default="add"): vol.In(options)
            }),
            last_step=False
        )

    async def async_step_device_menu(self, user_input=None):
        """Handle the device menu."""
        if user_input is not None:
            if "edit" == user_input["action"]:
                return await self.async_step_device()
            if "delete" == user_input["action"]:
                devices = [d for d in self.options.get(CONF_DEVICES, []) if d[CONF_ID] != self.current_device_id]
                self.options[CONF_DEVICES] = devices
                return self.async_create_entry(title="", data=self.options)
            if "controls" == user_input["action"]:
                return await self.async_step_controls()
            if "back" == user_input["action"]:
                return await self.async_step_init()

        return self.async_show_form(
            step_id="device_menu",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In({"edit": "Edit Device", "delete": "Delete Device", "controls": "Manage Controls", "back": "Back"})
            }),
            last_step=False
        )

    async def async_step_device(self, user_input=None):
        """Handle device add/edit."""
        errors = {}
        device_data = {}
        if self.current_device_id:
            device_data = next((d for d in self.options.get(CONF_DEVICES, []) if d[CONF_ID] == self.current_device_id), {})

        if user_input is not None:
            devices = self.options.get(CONF_DEVICES, [])
            if self.current_device_id: # Edit
                for i, d in enumerate(devices):
                    if d[CONF_ID] == self.current_device_id:
                        devices[i] = {**d, **user_input}
                        break
            else: # Add
                user_input[CONF_ID] = str(uuid.uuid4())
                user_input[CONF_CONTROLS] = []
                devices.append(user_input)
                self.current_device_id = user_input[CONF_ID]
            
            self.options[CONF_DEVICES] = devices
            return await self.async_step_device_menu()

        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, default=device_data.get(CONF_NAME, "")): TextSelector(),
                vol.Required(CONF_ICON, default=device_data.get(CONF_ICON, "mdi:power")): IconSelector(),
                vol.Optional("state_entity", default=device_data.get("state_entity", "")): EntitySelector(),
            }),
            errors=errors,
            last_step=False
        )

    async def async_step_controls(self, user_input=None):
        """Manage controls for a device."""
        device = next((d for d in self.options.get(CONF_DEVICES, []) if d[CONF_ID] == self.current_device_id), {})
        controls = device.get(CONF_CONTROLS, [])
        
        if user_input is not None:
            if "add" == user_input["action"]:
                self.current_control_id = None
                return await self.async_step_control()
            if "back" == user_input["action"]:
                return await self.async_step_device_menu()
            
            self.current_control_id = user_input["action"]
            return await self.async_step_control_menu()

        control_map = {c[CONF_ID]: c[CONF_LABEL] for c in controls}
        options = {"add": "Add a new control", **control_map, "back": "Back"}

        return self.async_show_form(
            step_id="controls",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In(options)
            }),
            last_step=False
        )

    async def async_step_control_menu(self, user_input=None):
        """Handle the control menu."""
        if user_input is not None:
            if "edit" == user_input["action"]:
                return await self.async_step_control()
            if "delete" == user_input["action"]:
                devices = self.options.get(CONF_DEVICES, [])
                for i, d in enumerate(devices):
                    if d[CONF_ID] == self.current_device_id:
                        controls = [c for c in d.get(CONF_CONTROLS, []) if c[CONF_ID] != self.current_control_id]
                        devices[i][CONF_CONTROLS] = controls
                        break
                self.options[CONF_DEVICES] = devices
                return await self.async_step_controls()
            if "back" == user_input["action"]:
                return await self.async_step_controls()

        return self.async_show_form(
            step_id="control_menu",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In({"edit": "Edit Control", "delete": "Delete Control", "back": "Back"})
            }),
            last_step=False
        )

    async def async_step_control(self, user_input=None):
        """Handle control add/edit."""
        errors = {}
        control_data = {}
        device = next((d for d in self.options.get(CONF_DEVICES, []) if d[CONF_ID] == self.current_device_id), {})
        controls = device.get(CONF_CONTROLS, [])
        if self.current_control_id:
            control_data = next((c for c in controls if c[CONF_ID] == self.current_control_id), {})

        if user_input is not None:
            if self.current_control_id: # Edit
                for i, c in enumerate(controls):
                    if c[CONF_ID] == self.current_control_id:
                        controls[i] = {**c, **user_input}
                        break
            else: # Add
                user_input[CONF_ID] = str(uuid.uuid4())
                controls.append(user_input)

            for i, d in enumerate(self.options.get(CONF_DEVICES, [])):
                if d[CONF_ID] == self.current_device_id:
                    self.options[CONF_DEVICES][i][CONF_CONTROLS] = controls
                    break
            
            return await self.async_step_controls()

        return self.async_show_form(
            step_id="control",
            data_schema=vol.Schema({
                vol.Required(CONF_LABEL, default=control_data.get(CONF_LABEL, "")): TextSelector(),
                vol.Required(CONF_TYPE, default=control_data.get(CONF_TYPE, "switch")): SelectSelector(SelectSelectorConfig(options=CONTROL_TYPES, mode=SelectSelectorMode.DROPDOWN)),
                vol.Required(CONF_ENTITY, default=control_data.get(CONF_ENTITY, "")): EntitySelector(),
                vol.Optional(CONF_MIN, default=control_data.get(CONF_MIN, 0)): NumberSelector(NumberSelectorConfig(min=0, max=1000, step=1, mode="slider")),
                vol.Optional(CONF_MAX, default=control_data.get(CONF_MAX, 100)): NumberSelector(NumberSelectorConfig(min=0, max=1000, step=1, mode="slider")),
                vol.Optional(CONF_STEP, default=control_data.get(CONF_STEP, 1)): NumberSelector(NumberSelectorConfig(min=1, max=100, step=1, mode="slider")),
                vol.Optional(CONF_OPTIONS, default=control_data.get(CONF_OPTIONS, "")): TextSelector(),
            }),
            errors=errors
        )