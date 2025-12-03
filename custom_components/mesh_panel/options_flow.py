"""Options flow for MESH Smart Home Panel."""
import logging
import uuid
import voluptuous as vol
import yaml
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    TextSelector, TextSelectorConfig,
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
        self.store = self.hass.data[DOMAIN][self.config_entry.entry_id]["store"]
        self.devices = []
        self.current_device_id = None
        self.current_control_id = None
        self.control_data = {}

    async def _save_and_reload(self):
        """Save devices to store and reload the integration."""
        await self.store.async_save_devices(self.devices)
        self.hass.async_create_task(self.hass.config_entries.async_reload(self.config_entry.entry_id))
        return self.async_create_entry(title="", data={})

    async def async_step_init(self, user_input=None):
        """Manage the devices."""
        self.devices = await self.store.async_load_devices()

        if user_input is not None:
            if "add" == user_input["action"]:
                self.current_device_id = None
                return await self.async_step_device()
            if "yaml" == user_input["action"]:
                return await self.async_step_yaml()
            
            self.current_device_id = user_input["action"]
            return await self.async_step_device_menu()

        device_map = {d["id"]: d["name"] for d in self.devices}
        
        options = {"add": "Add a new device", "yaml": "Configure with YAML", **device_map}

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({vol.Required("action", default="add"): vol.In(options)})
        )

    async def async_step_yaml(self, user_input=None):
        """Handle YAML configuration of devices."""
        errors = {}
        if user_input is not None:
            try:
                devices = yaml.safe_load(user_input[CONF_DEVICES])
                if devices is None: devices = []
                if not isinstance(devices, list):
                    raise ValueError("YAML must be a list of devices")
                
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
                
                self.devices = devices
                return await self._save_and_reload()

            except (yaml.YAMLError, ValueError) as e:
                _LOGGER.error("YAML parsing error: %s", e)
                errors["base"] = "invalid_yaml"

        current_yaml = yaml.dump(self.devices) if self.devices else ""
        return self.async_show_form(
            step_id="yaml",
            data_schema=vol.Schema({
                vol.Optional(CONF_DEVICES, default=current_yaml): TextSelector(TextSelectorConfig(multiline=True))
            }),
            errors=errors
        )

    async def async_step_device_menu(self, user_input=None):
        """Handle the device menu."""
        if user_input is not None:
            if "edit" == user_input["action"]:
                return await self.async_step_device()
            if "delete" == user_input["action"]:
                self.devices = [d for d in self.devices if d["id"] != self.current_device_id]
                return await self._save_and_reload()
            if "controls" == user_input["action"]:
                return await self.async_step_controls()
            if "back" == user_input["action"]:
                return await self.async_step_init()

        return self.async_show_form(
            step_id="device_menu",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In({"edit": "Edit Device", "delete": "Delete Device", "controls": "Manage Controls", "back": "Back"})
            })
        )

    async def async_step_device(self, user_input=None):
        """Handle device add/edit."""
        device_data = {}
        if self.current_device_id:
            device_data = next((d for d in self.devices if d["id"] == self.current_device_id), {})

        if user_input is not None:
            if self.current_device_id: # Edit
                for i, d in enumerate(self.devices):
                    if d["id"] == self.current_device_id:
                        self.devices[i] = {**d, **user_input}
                        break
            else: # Add
                user_input["id"] = str(uuid.uuid4())
                user_input["controls"] = []
                self.devices.append(user_input)
            
            return await self._save_and_reload()

        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, default=device_data.get(CONF_NAME, "")): TextSelector(),
                vol.Required(CONF_ICON, default=device_data.get(CONF_ICON, "mdi:power")):
                    IconSelector(),
            })
        )

    async def async_step_controls(self, user_input=None):
        """Manage controls for a device."""
        device = next((d for d in self.devices if d["id"] == self.current_device_id), None)
        if not device:
            return await self.async_step_init()
        
        controls = device.get("controls", [])
        
        if user_input is not None:
            if "add" == user_input["action"]:
                self.current_control_id = None
                self.control_data = {}
                return await self.async_step_control()
            if "back" == user_input["action"]:
                return await self.async_step_device_menu()
            
            self.current_control_id = user_input["action"]
            return await self.async_step_control_menu()

        control_map = {c["id"]: c["label"] for c in controls}
        options = {"add": "Add a new control", **control_map, "back": "Back"}

        return self.async_show_form(
            step_id="controls",
            data_schema=vol.Schema({vol.Required("action"): vol.In(options)})
        )

    async def async_step_control_menu(self, user_input=None):
        """Handle the control menu."""
        if user_input is not None:
            if "edit" == user_input["action"]:
                return await self.async_step_control()
            if "delete" == user_input["action"]:
                device = next((d for d in self.devices if d["id"] == self.current_device_id), None)
                if device:
                    controls = [c for c in device.get("controls", []) if c["id"] != self.current_control_id]
                    device["controls"] = controls
                return await self._save_and_reload()
            if "back" == user_input["action"]:
                return await self.async_step_controls()

        return self.async_show_form(
            step_id="control_menu",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In({"edit": "Edit Control", "delete": "Delete Control", "back": "Back"})
            })
        )

    async def async_step_control(self, user_input=None):
        """Handle control add/edit."""
        if self.current_control_id:
            device = next((d for d in self.devices if d["id"] == self.current_device_id), {{}})
            controls = device.get("controls", [])
            self.control_data = next((c for c in controls if c["id"] == self.current_control_id), {{}})

        if user_input is not None:
            self.control_data.update(user_input)
            if self.control_data[CONF_TYPE] == "slider":
                return await self.async_step_control_slider()
            if self.control_data[CONF_TYPE] == "select":
                return await self.async_step_control_select()
            
            return await self._save_control()

        return self.async_show_form(
            step_id="control",
            data_schema=vol.Schema({
                vol.Required(CONF_LABEL, default=self.control_data.get(CONF_LABEL, "")):
                    TextSelector(),
                vol.Required(CONF_TYPE, default=self.control_data.get(CONF_TYPE, "switch")):
                    SelectSelector(SelectSelectorConfig(options=CONTROL_TYPES, mode=SelectSelectorMode.DROPDOWN)),
                vol.Required(CONF_ENTITY, default=self.control_data.get(CONF_ENTITY, "")):
                    EntitySelector(),
            })
        )

    async def async_step_control_slider(self, user_input=None):
        """Handle slider control options."""
        if user_input is not None:
            self.control_data.update(user_input)
            return await self._save_control()
        
        attributes = ["state"]
        if self.control_data.get(CONF_ENTITY):
            entity = self.hass.states.get(self.control_data[CONF_ENTITY])
            if entity:
                attributes.extend(entity.attributes.keys())

        return self.async_show_form(
            step_id="control_slider",
            data_schema=vol.Schema({
                vol.Optional(CONF_MIN, default=self.control_data.get(CONF_MIN, 0)): NumberSelector(NumberSelectorConfig(min=0, max=1000, step=1, mode="slider")),
                vol.Optional(CONF_MAX, default=self.control_data.get(CONF_MAX, 100)): NumberSelector(NumberSelectorConfig(min=0, max=1000, step=1, mode="slider")),
                vol.Optional(CONF_STEP, default=self.control_data.get(CONF_STEP, 1)): NumberSelector(NumberSelectorConfig(min=1, max=100, step=1, mode="slider")),
                vol.Optional("attribute", default=self.control_data.get("attribute", "state")):
                    vol.In(attributes),
            })
        )

    async def async_step_control_select(self, user_input=None):
        """Handle select control options."""
        if user_input is not None:
            self.control_data.update(user_input)
            return await self._save_control()

        return self.async_show_form(
            step_id="control_select",
            data_schema=vol.Schema({
                vol.Optional(CONF_OPTIONS, default=self.control_data.get(CONF_OPTIONS, "")):
                    TextSelector(),
            }),
            description_placeholders={"description": "Enter a comma-separated list of options."}
        )

    async def _save_control(self):
        """Save the control data."""
        device = next((d for d in self.devices if d["id"] == self.current_device_id), None)
        if not device:
            return self.async_abort(reason="unknown")
        
        if self.control_data.get(CONF_TYPE) == "select" and isinstance(self.control_data.get(CONF_OPTIONS), str):
            options_list = [opt.strip() for opt in self.control_data[CONF_OPTIONS].split(",")]
            self.control_data[CONF_OPTIONS] = "\n".join(options_list)

        controls = device.get("controls", [])
        if self.current_control_id: # Edit
            for i, c in enumerate(controls):
                if c["id"] == self.current_control_id:
                    controls[i] = self.control_data
                    break
        else: # Add
            self.control_data["id"] = str(uuid.uuid4())
            controls.append(self.control_data)
        
        device["controls"] = controls
        return await self._save_and_reload()
