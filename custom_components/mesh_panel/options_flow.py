"""
Options Flow for MESH Smart Panel
Handles devices + controls with:
- Numeric-only attribute filtering for sliders
- Big sensible slider ranges (entity-driven where possible)
- Add-Another flow (doesn't finish until Save & Exit)
- Auto-detected select options (input_select/fan/media_player/light effects)
- Proper "Done" navigation
"""
from __future__ import annotations

import logging
import uuid
import copy
from typing import Any, Dict, List, Tuple

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers.selector import (
    TextSelector,
    SelectSelector, SelectSelectorConfig, SelectSelectorMode,
    EntitySelector,
    IconSelector,
    NumberSelector, NumberSelectorConfig,
)

from .const import (
    DOMAIN,
    CONF_DEVICES,
    CONF_ID, CONF_NAME, CONF_ICON, CONF_CONTROLS,
    CONF_LABEL, CONF_TYPE, CONF_ENTITY,
    CONF_MIN, CONF_MAX, CONF_STEP, CONF_OPTIONS,
)

_LOGGER = logging.getLogger(__name__)

# --------- Attribute helpers ---------

_NUMERIC_LIGHT_ATTRS = {
    "brightness",
    "color_temp",
    "color_temp_kelvin",
    "min_mireds",
    "max_mireds",
    "min_color_temp_kelvin",
    "max_color_temp_kelvin",
}

# Pseudo attributes we expose as independent sliders
# (split HS and XY so each axis can be controlled)
_PSEUDO_LIGHT_ATTRS = {
    "hs_hue",          # 0..360
    "hs_saturation",   # 0..100
    "xy_x",            # 0..1000 (scaled)
    "xy_y",            # 0..1000 (scaled)
}

# Max “safe” ranges (used when entity doesn’t expose bounds)
_DEFAULT_RANGES = {
    "brightness": (0, 255, 1),
    "color_temp": (100, 600, 1),           # mireds; typical 153..500; keep wide
    "color_temp_kelvin": (1000, 20000, 50),
    "min_mireds": (1, 1000, 1),
    "max_mireds": (1, 1000, 1),
    "min_color_temp_kelvin": (500, 20000, 50),
    "max_color_temp_kelvin": (500, 20000, 50),
    "hs_hue": (0, 360, 1),
    "hs_saturation": (0, 100, 1),
    "xy_x": (0, 1000, 1),
    "xy_y": (0, 1000, 1),
    # Generic fallback
    "__generic__": (0, 999999, 1),
}


def _is_number(val: Any) -> bool:
    try:
        float(val)
        return True
    except Exception:
        return False


def _numeric_attribute_names_for_entity(hass: HomeAssistant, entity_id: str) -> List[str]:
    """
    Build a filtered attribute list for sliders:
    - include known useful light attrs
    - include numeric attributes from the entity
    - add pseudo attrs for hs/xy if present on the entity
    - include 'state' as a last resort (not recommended for light)
    """
    names: List[str] = []
    st = hass.states.get(entity_id)
    if not st:
        return ["state"]

    # First, numeric attributes from the entity itself
    for k, v in st.attributes.items():
        if _is_number(v):
            names.append(k)

    # Domain-specific enrichments
    domain = entity_id.split(".")[0]

    if domain == "light":
        # Ensure our preferred light attrs are present
        for a in _NUMERIC_LIGHT_ATTRS:
            if a not in names:
                names.append(a)

        # If hs_color present, expose hue/saturation split
        if "hs_color" in st.attributes and "hs_hue" not in names:
            names.extend(["hs_hue", "hs_saturation"])

        # If xy_color present, expose x/y split
        if "xy_color" in st.attributes and "xy_x" not in names:
            names.extend(["xy_x", "xy_y"])

        # Brightness is always useful even if missing right now
        if "brightness" not in names:
            names.append("brightness")

    # Deduplicate preserving order
    seen = set()
    filtered = []
    for n in names:
        if n not in seen:
            seen.add(n)
            filtered.append(n)

    # 'state' only as last fallback if list ends empty
    if not filtered:
        filtered = ["state"]

    # Remove noisy non-control attrs commonly seen
    noisy = {
        "supported_color_modes", "supported_features", "restored",
        "icon", "friendly_name", "effect_list"  # effect_list belongs to select, not slider
    }
    filtered = [n for n in filtered if n not in noisy]

    return filtered


def _range_for_attribute(hass: HomeAssistant, entity_id: str, attr: str) -> Tuple[int, int, int]:
    """
    Provide min/max/step defaults for a given attribute,
    using entity bounds if available, otherwise wide safe defaults.
    """
    st = hass.states.get(entity_id)
    # Entity-informed bounds for color temperature (kelvin/mireds)
    if st:
        if attr == "color_temp_kelvin":
            lo = st.attributes.get("min_color_temp_kelvin")
            hi = st.attributes.get("max_color_temp_kelvin")
            if _is_number(lo) and _is_number(hi):
                return int(lo), int(hi), 50
        if attr == "color_temp":
            lo = st.attributes.get("min_mireds")
            hi = st.attributes.get("max_mireds")
            if _is_number(lo) and _is_number(hi):
                return int(lo), int(hi), 1

    # Defaults
    if attr in _DEFAULT_RANGES:
        return _DEFAULT_RANGES[attr]

    # Fan, climate, media_player defaults (if someone uses attribute sliders)
    domain = entity_id.split(".")[0]
    if domain == "fan":
        return (0, 100, 1)
    if domain == "climate":
        return (10, 40, 1)  # Celsius-ish sensible default
    if domain == "media_player":
        return (0, 100, 1)

    return _DEFAULT_RANGES["__generic__"]


def _autodetect_select_options(hass: HomeAssistant, entity_id: str) -> List[str]:
    """
    Try to extract a select-like list from the entity:
    - input_select: options
    - fan: preset_modes or speed_list
    - media_player: source_list
    - light: effect_list (WLED/Wiz etc.)
    """
    st = hass.states.get(entity_id)
    if not st:
        return []

    domain = entity_id.split(".")[0]
    attrs = st.attributes

    if domain == "input_select":
        opts = attrs.get("options")
        if isinstance(opts, list):
            return [str(o) for o in opts]

    if domain == "fan":
        opts = attrs.get("preset_modes") or attrs.get("speed_list")
        if isinstance(opts, list):
            return [str(o) for o in opts]

    if domain == "media_player":
        opts = attrs.get("source_list")
        if isinstance(opts, list):
            return [str(o) for o in opts]

    if domain == "light":
        opts = attrs.get("effect_list")
        if isinstance(opts, list):
            return [str(o) for o in opts]

    # Nothing recognized
    return []


class MeshPanelOptionsFlowHandler(config_entries.OptionsFlow):
    """Visual options editor with staged changes and explicit Save."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        self.config_entry = config_entry
        # Keep working copy; only persist on Save & Exit
        self.options = dict(config_entry.options)
        self.working = copy.deepcopy(self.options)

        self.current_device_id: str | None = None
        self.current_control_id: str | None = None
        self.control_data: Dict[str, Any] = {}

    # ---------------- Top-level: Devices page ----------------

    async def async_step_init(self, user_input=None):
        """Initial menu: list devices + add + Save & Exit."""
        if user_input:
            action = user_input["action"]
            if action == "add_device":
                self.current_device_id = None
                return await self.async_step_device()
            if action == "save_exit":
                # Persist working options and reload the entry so panel updates
                result = await self._do_save_and_exit()
                return result
            # Otherwise it's a device id
            self.current_device_id = action
            return await self.async_step_device_menu()

        devices = self.working.get(CONF_DEVICES, [])
        dev_map = {d[CONF_ID]: d[CONF_NAME] for d in devices}

        options = {
            "add_device": "Add a new device",
            **dev_map,
            "save_exit": "Save & Exit",
        }

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("action", default="add_device"): vol.In(options)
            })
        )

    # ---------------- Device menu ----------------

    async def async_step_device_menu(self, user_input=None):
        if user_input:
            a = user_input["action"]
            if a == "edit":
                return await self.async_step_device()
            if a == "controls":
                return await self.async_step_controls()
            if a == "delete":
                devs = [d for d in self.working.get(CONF_DEVICES, [])
                        if d[CONF_ID] != self.current_device_id]
                self.working[CONF_DEVICES] = devs
                # Stay on devices page
                return await self.async_step_init()
            if a == "back":
                return await self.async_step_init()

        return self.async_show_form(
            step_id="device_menu",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In({
                    "edit": "Edit Device",
                    "controls": "Manage Controls",
                    "delete": "Delete Device",
                    "back": "Back",
                })
            })
        )

    # ---------------- Device add/edit ----------------

    async def async_step_device(self, user_input=None):
        device_data: Dict[str, Any] = {}
        if self.current_device_id:
            device_data = next(
                (d for d in self.working.get(CONF_DEVICES, [])
                 if d[CONF_ID] == self.current_device_id), {}
            )

        if user_input:
            devs = self.working.get(CONF_DEVICES, [])

            if self.current_device_id:
                # Edit existing
                for i, d in enumerate(devs):
                    if d[CONF_ID] == self.current_device_id:
                        devs[i] = {**d, **user_input}
                        break
            else:
                # Add new device
                user_input[CONF_ID] = str(uuid.uuid4())
                user_input.setdefault(CONF_CONTROLS, [])
                devs.append(user_input)
                self.current_device_id = user_input[CONF_ID]

            self.working[CONF_DEVICES] = devs
            return await self.async_step_device_menu()

        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, default=device_data.get(CONF_NAME, "")): TextSelector(),
                vol.Required(CONF_ICON, default=device_data.get(CONF_ICON, "mdi:power")): IconSelector(),
            })
        )

    # ---------------- Controls list ----------------

    async def async_step_controls(self, user_input=None):
        device = next(
            (d for d in self.working.get(CONF_DEVICES, [])
             if d[CONF_ID] == self.current_device_id), {}
        )
        controls = device.get(CONF_CONTROLS, [])

        if user_input:
            a = user_input["action"]
            if a == "add":
                self.current_control_id = None
                self.control_data = {}
                return await self.async_step_control()
            if a == "done":
                # Go back to device page (to add more devices or Save & Exit)
                return await self.async_step_device_menu()
            # Existing control
            self.current_control_id = a
            return await self.async_step_control_menu()

        ctrl_map = {c[CONF_ID]: c[CONF_LABEL] for c in controls}
        options = {
            "add": "Add a new control",
            **ctrl_map,
            "done": "Done",
        }

        return self.async_show_form(
            step_id="controls",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In(options)
            })
        )

    # ---------------- Control menu ----------------

    async def async_step_control_menu(self, user_input=None):
        if user_input:
            a = user_input["action"]
            if a == "edit":
                return await self.async_step_control()
            if a == "delete":
                for d in self.working.get(CONF_DEVICES, []):
                    if d[CONF_ID] == self.current_device_id:
                        d[CONF_CONTROLS] = [
                            c for c in d.get(CONF_CONTROLS, [])
                            if c[CONF_ID] != self.current_control_id
                        ]
                        break
                # Return to controls list
                return await self.async_step_controls()
            if a == "back":
                return await self.async_step_controls()

        return self.async_show_form(
            step_id="control_menu",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In({
                    "edit": "Edit Control",
                    "delete": "Delete Control",
                    "back": "Back",
                })
            })
        )

    # ---------------- Control add/edit (base) ----------------

    async def async_step_control(self, user_input=None):
        # Load existing control for edit
        if self.current_control_id:
            device = next(
                (d for d in self.working.get(CONF_DEVICES, [])
                 if d[CONF_ID] == self.current_device_id), {}
            )
            controls = device.get(CONF_CONTROLS, [])
            self.control_data = next(
                (c for c in controls if c[CONF_ID] == self.current_control_id), {}
            )

        if user_input:
            self.control_data.update(user_input)

            # Route to type-specific config
            if self.control_data[CONF_TYPE] == "slider":
                return await self.async_step_control_slider()
            if self.control_data[CONF_TYPE] == "select":
                return await self.async_step_control_select()

            # Simple types (switch/color) save immediately and go back to controls list
            await self._save_control(stay_in_flow=True)
            return await self.async_step_controls()

        return self.async_show_form(
            step_id="control",
            data_schema=vol.Schema({
                vol.Required(CONF_LABEL, default=self.control_data.get(CONF_LABEL, "")): TextSelector(),
                vol.Required(CONF_TYPE, default=self.control_data.get(CONF_TYPE, "switch")):
                    SelectSelector(SelectSelectorConfig(
                        options=[
                            {"label": "Switch (On/Off)", "value": "switch"},
                            {"label": "Slider (Numeric)", "value": "slider"},
                            {"label": "Color Wheel", "value": "color"},
                            {"label": "Dropdown Selection", "value": "select"},
                        ],
                        mode=SelectSelectorMode.DROPDOWN
                    )),
                vol.Required(CONF_ENTITY, default=self.control_data.get(CONF_ENTITY, "")): EntitySelector(),
            })
        )

    # ---------------- Slider config ----------------

    async def async_step_control_slider(self, user_input=None):
        ent = self.control_data.get(CONF_ENTITY, "")
        hass = self.hass

        # Build attribute list (numeric/meaningful only)
        attrs = _numeric_attribute_names_for_entity(hass, ent)

        # Determine current attribute choice
        attr_default = self.control_data.get("attribute", "brightness" if ent.startswith("light.") else "state")

        # If user submitted, update control, compute encoding and save
        if user_input:
            self.control_data.update(user_input)

            # Encode entity as "entity (attribute)" if attribute != "state"
            attribute = self.control_data.get("attribute", "state")
            encoded = ent if attribute == "state" else f"{ent} ({attribute})"
            self.control_data[CONF_ENTITY] = encoded

            # Save and return to controls list (stay in flow)
            await self._save_control(stay_in_flow=True)
            return await self.async_step_controls()

        # Compute sensible defaults based on attribute/entity bounds
        min_d, max_d, step_d = _range_for_attribute(hass, ent, attr_default)

        # If user pre-filled min/max/step earlier, preserve those as defaults
        min_def = int(self.control_data.get(CONF_MIN, min_d))
        max_def = int(self.control_data.get(CONF_MAX, max_d))
        step_def = int(self.control_data.get(CONF_STEP, step_d))

        return self.async_show_form(
            step_id="control_slider",
            data_schema=vol.Schema({
                vol.Required("attribute", default=attr_default): vol.In({a: a for a in attrs}),
                vol.Optional(CONF_MIN, default=min_def):
                    NumberSelector(NumberSelectorConfig(min=-999999, max=999999, step=1)),
                vol.Optional(CONF_MAX, default=max_def):
                    NumberSelector(NumberSelectorConfig(min=-999999, max=999999, step=1)),
                vol.Optional(CONF_STEP, default=step_def):
                    NumberSelector(NumberSelectorConfig(min=1, max=100000, step=1)),
            })
        )

    # ---------------- Select config (auto options) ----------------

async def async_step_control_select(self, user_input=None):
    ent = self.control_data.get(CONF_ENTITY, "")
    detected = _autodetect_select_options(self.hass, ent)

    if user_input:
        # ensure entity stays valid
        self.control_data[CONF_ENTITY] = ent  

        # persist options
        self.control_data[CONF_OPTIONS] = "\n".join(detected) if detected else ""

        await self._save_control(stay_in_flow=True)
        return await self.async_step_controls()

    desc = "Auto-detected dropdown options."
    if detected:
        desc += "\n\nDetected:\n- " + "\n- ".join(detected)
    else:
        desc += "\n\nNo options detected for this entity."

    return self.async_show_form(
        step_id="control_select",
        description=desc,
        data_schema=vol.Schema({
            vol.Required("confirm", default=True): bool
        })
    )


    # ---------------- Save helpers ----------------

    async def _save_control(self, stay_in_flow: bool = False):
        """Merge current control into working set. When stay_in_flow=True, do not finish the flow."""
        devices = self.working.get(CONF_DEVICES, [])
        device = next((d for d in devices if d[CONF_ID] == self.current_device_id), None)
        if not device:
            return self.async_abort(reason="unknown")

        controls = device.get(CONF_CONTROLS, [])

        if self.current_control_id:
            for i, c in enumerate(controls):
                if c[CONF_ID] == self.current_control_id:
                    controls[i] = {**c, **self.control_data}
                    break
        else:
            self.control_data[CONF_ID] = str(uuid.uuid4())
            controls.append(self.control_data)

        device[CONF_CONTROLS] = controls
        self.working[CONF_DEVICES] = devices

        if not stay_in_flow:
            # Not used in this flow; kept for completeness
            return await self._do_save_and_exit()

    async def _do_save_and_exit(self):
        """Persist working options, reload the entry, and finish the flow."""
        # Persist
        res = self.async_create_entry(title="", data=self.working)
        try:
            # Force reload so the panel gets updated immediately
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
        except Exception as e:
            _LOGGER.debug("Reload after save failed: %s", e)
        return res
