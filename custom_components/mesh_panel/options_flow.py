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
    TextSelector,TextSelectorConfig,
    SelectSelector, SelectSelectorConfig, SelectSelectorMode,
    EntitySelector,
    IconSelector,
    NumberSelector, NumberSelectorConfig,
    ActionSelector,
)

from .const import (
    DOMAIN,
    CONF_DEVICES,
    CONF_ID, CONF_NAME, CONF_ICON, CONF_CONTROLS,
    CONF_LABEL, CONF_TYPE, CONF_ENTITY,
    CONF_MIN, CONF_MAX, CONF_STEP, CONF_OPTIONS,
    CONF_GRID, CONF_GRID_LABEL, CONF_GRID_BG, CONF_GRID_RADIUS,
    CONF_GRID_PADDING, CONF_ROWS, CONF_ROW_HEIGHT, CONF_ROW_BG,
    CONF_ROW_RADIUS, CONF_ROW_PADDING, CONF_BUTTONS, CONF_BUTTON_WIDTH,
    CONF_ACTION, CONF_LABEL_FORMULA, CONF_BG_COLOR_FORMULA,
    CONF_TEXT_COLOR_FORMULA,
    CONTROL_TYPES,
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

_PSEUDO_LIGHT_ATTRS = {
    "hs_hue",
    "hs_saturation",
    "xy_x",
    "xy_y",
}

_DEFAULT_RANGES = {
    "brightness": (0, 255, 1),
    "color_temp": (100, 600, 1),
    "color_temp_kelvin": (1000, 20000, 50),
    "min_mireds": (1, 1000, 1),
    "max_mireds": (1, 1000, 1),
    "min_color_temp_kelvin": (500, 20000, 50),
    "max_color_temp_kelvin": (500, 20000, 50),
    "hs_hue": (0, 360, 1),
    "hs_saturation": (0, 100, 1),
    "xy_x": (0, 1000, 1),
    "xy_y": (0, 1000, 1),
    "__generic__": (0, 999999, 1),
}


def _is_number(val: Any) -> bool:
    try:
        float(val)
        return True
    except Exception:
        return False


def _numeric_attribute_names_for_entity(
    hass: HomeAssistant, entity_id: str
) -> List[str]:
    names: List[str] = []
    st = hass.states.get(entity_id)
    if not st:
        return ["state"]

    for k, v in st.attributes.items():
        if _is_number(v):
            names.append(k)

    domain = entity_id.split(".")[0]

    if domain == "light":
        for a in _NUMERIC_LIGHT_ATTRS:
            if a not in names:
                names.append(a)

        if "hs_color" in st.attributes and "hs_hue" not in names:
            names.extend(["hs_hue", "hs_saturation"])

        if "xy_color" in st.attributes and "xy_x" not in names:
            names.extend(["xy_x", "xy_y"])

        if "brightness" not in names:
            names.append("brightness")

    noisy = {
        "supported_color_modes", "supported_features",
        "restored", "icon", "friendly_name", "effect_list"
    }
    names = [n for n in names if n not in noisy]

    if not names:
        names = ["state"]

    return names


def _range_for_attribute(hass: HomeAssistant, entity_id: str, attr: str) -> Tuple[int, int, int]:
    st = hass.states.get(entity_id)

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

    if attr in _DEFAULT_RANGES:
        return _DEFAULT_RANGES[attr]

    domain = entity_id.split(".")[0]
    if domain == "fan":
        return (0, 100, 1)
    if domain == "climate":
        return (10, 40, 1)
    if domain == "media_player":
        return (0, 100, 1)

    return _DEFAULT_RANGES["__generic__"]


def _autodetect_select_options(hass: HomeAssistant, entity_id: str) -> List[str]:
    """Aggressively try to find list options from an entity."""
    if not entity_id:
        return []
        
    st = hass.states.get(entity_id)
    if not st:
        return []

    # Common attributes that hold lists of options
    candidates = [
        "options",          # select, input_select
        "source_list",      # media_player
        "effect_list",      # light
        "preset_modes",     # fan, climate
        "hvac_modes",       # climate
        "fan_mode_list",    # climate
        "swing_modes",      # climate
        "fan_speed_list",   # vacuum, fan (legacy)
        "operation_list",   # legacy
    ]

    for attr in candidates:
        val = st.attributes.get(attr)
        if isinstance(val, list) and len(val) > 0:
            # Return the first valid list we find, converted to strings
            return [str(v) for v in val]

    return []

class MeshPanelOptionsFlowHandler(config_entries.OptionsFlow):
    """Visual options editor with staged changes and explicit Save."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        self.config_entry = config_entry
        self.options = dict(config_entry.options)
        self.working = copy.deepcopy(self.options)

        self.current_device_id: str | None = None
        self.current_control_id: str | None = None
        self.control_data: Dict[str, Any] = {}
        self.current_row_index: int | None = None
        self.current_button_index: int | None = None

    # ---------------- Devices root ----------------

    async def async_step_init(self, user_input=None):
        if user_input:
            act = user_input["action"]
            if act == "add_device":
                self.current_device_id = None
                return await self.async_step_device()
            if act == "save_exit":
                return await self._do_save_and_exit()
            self.current_device_id = act
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
            act = user_input["action"]
            if act == "edit":
                return await self.async_step_device()
            if act == "controls":
                return await self.async_step_controls()
            if act == "delete":
                self.working[CONF_DEVICES] = [
                    d for d in self.working.get(CONF_DEVICES, [])
                    if d[CONF_ID] != self.current_device_id
                ]
                return await self.async_step_init()
            if act == "back":
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
        device_data = {}
        if self.current_device_id:
            device_data = next(
                (d for d in self.working.get(CONF_DEVICES, [])
                 if d[CONF_ID] == self.current_device_id),
                {}
            )

        if user_input:
            devs = self.working.get(CONF_DEVICES, [])

            if self.current_device_id:
                for i, d in enumerate(devs):
                    if d[CONF_ID] == self.current_device_id:
                        devs[i] = {**d, **user_input}
                        break
            else:
                new_id = str(uuid.uuid4())
                user_input[CONF_ID] = new_id
                user_input.setdefault(CONF_CONTROLS, [])
                devs.append(user_input)
                self.current_device_id = new_id

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
             if d[CONF_ID] == self.current_device_id),
            {}
        )
        controls = device.get(CONF_CONTROLS, [])

        if user_input:
            act = user_input["action"]
            if act == "add":
                self.current_control_id = None
                self.control_data = {}
                return await self.async_step_control()
            if act == "done":
                return await self.async_step_device_menu()

            self.current_control_id = act
            return await self.async_step_control_menu()

        ctrl_map = {c[CONF_ID]: c[CONF_LABEL] for c in controls}

        return self.async_show_form(
            step_id="controls",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In({
                    "add": "Add a new control",
                    **ctrl_map,
                    "done": "Done",
                })
            })
        )

    # ---------------- Control menu ----------------

    async def async_step_control_menu(self, user_input=None):
        if user_input:
            act = user_input["action"]
            if act == "edit":
                return await self.async_step_control()
            if act == "delete":
                for d in self.working.get(CONF_DEVICES, []):
                    if d[CONF_ID] == self.current_device_id:
                        d[CONF_CONTROLS] = [
                            c for c in d.get(CONF_CONTROLS, [])
                            if c[CONF_ID] != self.current_control_id
                        ]
                        break
                return await self.async_step_controls()
            if act == "back":
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

    # ---------------- Control base ----------------

    async def async_step_control(self, user_input=None):
        if self.current_control_id:
            device = next(
                (d for d in self.working.get(CONF_DEVICES, [])
                 if d[CONF_ID] == self.current_device_id),
                {}
            )
            controls = device.get(CONF_CONTROLS, [])
            self.control_data = next(
                (c for c in controls if c[CONF_ID] == self.current_control_id),
                {}
            )

        if user_input:
            self.control_data.update(user_input)

            if self.control_data.get(CONF_TYPE) == "button_grid":
                return await self.async_step_control_grid()
            
            return await self.async_step_control_entity()

        return self.async_show_form(
            step_id="control",
            data_schema=vol.Schema({
                vol.Required(CONF_LABEL, default=self.control_data.get(CONF_LABEL, "")): TextSelector(),
                vol.Required(CONF_TYPE, default=self.control_data.get(CONF_TYPE, "switch")):
                    SelectSelector(SelectSelectorConfig(
                        options=CONTROL_TYPES,
                        mode=SelectSelectorMode.DROPDOWN
                    )),
            })
        )


    async def async_step_control_entity(self, user_input=None):
        """Handle entity selection for a control."""
        if user_input:
            self.control_data.update(user_input)

            if self.control_data[CONF_TYPE] == "slider":
                return await self.async_step_control_slider()
            if self.control_data[CONF_TYPE] == "select":
                return await self.async_step_control_select()

            await self._save_control(stay_in_flow=True)
            return await self.async_step_controls()

        return self.async_show_form(
            step_id="control_entity",
            data_schema=vol.Schema({
                vol.Required(CONF_ENTITY, default=self.control_data.get(CONF_ENTITY, "")): EntitySelector(),
            })
        )

    # ---------------- Slider config ----------------

    async def async_step_control_slider(self, user_input=None):
        ent = self.control_data.get(CONF_ENTITY, "")
        hass = self.hass

        attrs = _numeric_attribute_names_for_entity(hass, ent)
        attr_default = self.control_data.get(
            "attribute", "brightness" if ent.startswith("light.") else "state"
        )

        if user_input:
            self.control_data.update(user_input)

            attribute = self.control_data.get("attribute", "state")
            encoded = ent if attribute == "state" else f"{ent} ({attribute})"
            self.control_data[CONF_ENTITY] = encoded

            await self._save_control(stay_in_flow=True)
            return await self.async_step_controls()

        min_d, max_d, step_d = _range_for_attribute(hass, ent, attr_default)

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

# ---------------- Select config (AUTOFILL + COMMA SEPARATED) ----------------

    async def async_step_control_select(self, user_input=None):
        if user_input is not None:
            raw_text = user_input.get(CONF_OPTIONS, "")
            
            # LOGIC: Always split by comma for storage
            # This handles "Red, Green, Blue" -> "Red\nGreen\nBlue" (internal storage format)
            if "," in raw_text:
                cleaned_opts = [o.strip() for o in raw_text.split(",") if o.strip()]
                self.control_data[CONF_OPTIONS] = "\n".join(cleaned_opts)
            else:
                # Fallback if they somehow managed to type newlines or just one option
                self.control_data[CONF_OPTIONS] = raw_text

            await self._save_control(stay_in_flow=True)
            return await self.async_step_controls()

        # --- PRE-FILL LOGIC ---
        default_text = self.control_data.get(CONF_OPTIONS, "")
        
        # If empty, try to auto-detect
        if not default_text:
            ent = self.control_data.get(CONF_ENTITY, "")
            detected = _autodetect_select_options(self.hass, ent)
            if detected:
                # Join with comma+space so it looks nice in the text box
                default_text = ", ".join(detected)

        # If we have existing newline-separated data (from previous saves), 
        # convert it to commas for display so the user can edit it easily.
        elif "\n" in default_text:
            default_text = default_text.replace("\n", ", ")

        return self.async_show_form(
            step_id="control_select",
            data_schema=vol.Schema({
                # We use a standard TextSelector (single line by default)
                # This prevents the "Enter key submit" confusion.
                vol.Required(CONF_OPTIONS, default=default_text): TextSelector(),
            }),
            description_placeholders={
                "entity_id": self.control_data.get(CONF_ENTITY, "Unknown"),
            }
        )

    # ---------------- Button Grid Rows & Buttons ----------------

    async def async_step_row_menu(self, user_input=None):
        if user_input:
            action = user_input["action"]
            if action == "edit_row":
                return await self.async_step_row()
            if action == "manage_buttons":
                return await self.async_step_row_buttons_menu()
            if action == "delete_row":
                grid_data = self.control_data.get(CONF_GRID, {})
                rows = grid_data.get(CONF_ROWS, [])
                rows.pop(self.current_row_index)
                grid_data[CONF_ROWS] = rows
                self.control_data[CONF_GRID] = grid_data
                return await self.async_step_grid_rows_menu()
            if action == "back":
                return await self.async_step_grid_rows_menu()

        return self.async_show_form(
            step_id="row_menu",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In({
                    "edit_row": "Edit Row Properties",
                    "manage_buttons": "Manage Buttons",
                    "delete_row": "Delete Row",
                    "back": "Back to Rows",
                })
            })
        )

    async def async_step_row(self, user_input=None):
        grid_data = self.control_data.get(CONF_GRID, {})
        rows = grid_data.get(CONF_ROWS, [])
        row_data = {}
        if self.current_row_index is not None and self.current_row_index < len(rows):
            row_data = rows[self.current_row_index]

        if user_input is not None:
            if self.current_row_index is None:
                user_input[CONF_BUTTONS] = []
                rows.append(user_input)
                self.current_row_index = len(rows) - 1
            else:
                row_data.update(user_input)
                rows[self.current_row_index] = row_data
            
            grid_data[CONF_ROWS] = rows
            self.control_data[CONF_GRID] = grid_data
            return await self.async_step_row_menu()

        return self.async_show_form(
            step_id="row",
            data_schema=vol.Schema({
                vol.Optional(CONF_ROW_HEIGHT, default=row_data.get(CONF_ROW_HEIGHT, 1.0)): NumberSelector(NumberSelectorConfig(min=0.1, max=10.0, step=0.1)),
                vol.Optional(CONF_ROW_BG, default=row_data.get(CONF_ROW_BG, "")): TextSelector(),
                vol.Optional(CONF_ROW_RADIUS, default=row_data.get(CONF_ROW_RADIUS, "")): TextSelector(),
                vol.Optional(CONF_ROW_PADDING, default=row_data.get(CONF_ROW_PADDING, "")): TextSelector(),
            })
        )

    async def async_step_row_buttons_menu(self, user_input=None):
        grid_data = self.control_data.get(CONF_GRID, {})
        row_data = grid_data.get(CONF_ROWS, [])[self.current_row_index]
        buttons = row_data.get(CONF_BUTTONS, [])

        if user_input:
            action = user_input["action"]
            if action == "add_button":
                self.current_button_index = None
                return await self.async_step_button()
            if action == "back":
                return await self.async_step_row_menu()
            
            self.current_button_index = int(action)
            return await self.async_step_button_menu()

        button_map = {str(i): b.get(CONF_ID, f"Button {i+1}") for i, b in enumerate(buttons)}

        return self.async_show_form(
            step_id="row_buttons_menu",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In({
                    "add_button": "Add a new button",
                    **button_map,
                    "back": "Back to Row Menu",
                })
            })
        )

    async def async_step_button_menu(self, user_input=None):
        if user_input:
            action = user_input["action"]
            if action == "edit_button":
                return await self.async_step_button()
            if action == "delete_button":
                grid_data = self.control_data.get(CONF_GRID, {})
                row_data = grid_data.get(CONF_ROWS, [])[self.current_row_index]
                buttons = row_data.get(CONF_BUTTONS, [])
                buttons.pop(self.current_button_index)
                row_data[CONF_BUTTONS] = buttons
                self.control_data[CONF_GRID][CONF_ROWS][self.current_row_index] = row_data
                return await self.async_step_row_buttons_menu()
            if action == "back":
                return await self.async_step_row_buttons_menu()

        return self.async_show_form(
            step_id="button_menu",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In({
                    "edit_button": "Edit Button",
                    "delete_button": "Delete Button",
                    "back": "Back to Buttons",
                })
            })
        )

    async def async_step_button(self, user_input=None):
        grid_data = self.control_data.get(CONF_GRID, {})
        row_data = grid_data.get(CONF_ROWS, [])[self.current_row_index]
        buttons = row_data.get(CONF_BUTTONS, [])
        button_data = {}
        if self.current_button_index is not None and self.current_button_index < len(buttons):
            button_data = buttons[self.current_button_index]

        if user_input is not None:
            if self.current_button_index is None:
                buttons.append(user_input)
            else:
                buttons[self.current_button_index] = user_input
            
            row_data[CONF_BUTTONS] = buttons
            self.control_data[CONF_GRID][CONF_ROWS][self.current_row_index] = row_data
            return await self.async_step_row_buttons_menu()

        return self.async_show_form(
            step_id="button",
            data_schema=vol.Schema({
                vol.Required(CONF_ID, default=button_data.get(CONF_ID, "")): TextSelector(),
                vol.Optional(CONF_BUTTON_WIDTH, default=button_data.get(CONF_BUTTON_WIDTH, 1)): NumberSelector(NumberSelectorConfig(min=1, max=10, step=1)),
                vol.Optional(CONF_LABEL_FORMULA, default=button_data.get(CONF_LABEL_FORMULA, "")): TextSelector(),
                vol.Optional(CONF_BG_COLOR_FORMULA, default=button_data.get(CONF_BG_COLOR_FORMULA, "")): TextSelector(),
                vol.Optional(CONF_TEXT_COLOR_FORMULA, default=button_data.get(CONF_TEXT_COLOR_FORMULA, "")): TextSelector(),
                vol.Optional(CONF_ACTION, default=button_data.get(CONF_ACTION, {})): ActionSelector(),
            })
        )

    async def async_step_control_grid(self, user_input=None):
        """Handle Button Grid configuration."""
        if user_input is not None:
            self.control_data.setdefault(CONF_GRID, {})
            self.control_data[CONF_GRID].update(user_input)
            return await self.async_step_grid_rows_menu()

        grid_data = self.control_data.get(CONF_GRID, {})

        return self.async_show_form(
            step_id="control_grid",
            data_schema=vol.Schema({
                vol.Optional(CONF_GRID_LABEL, default=grid_data.get(CONF_GRID_LABEL, "")): TextSelector(),
                vol.Optional(CONF_GRID_BG, default=grid_data.get(CONF_GRID_BG, "")): TextSelector(),
                vol.Optional(CONF_GRID_RADIUS, default=grid_data.get(CONF_GRID_RADIUS, "")): TextSelector(),
                vol.Optional(CONF_GRID_PADDING, default=grid_data.get(CONF_GRID_PADDING, "")): TextSelector(),
            })
        )

    async def async_step_grid_rows_menu(self, user_input=None):
        """Menu for adding/editing rows in a grid."""
        
        grid_data = self.control_data.get(CONF_GRID, {})
        rows = grid_data.get(CONF_ROWS, [])

        if user_input:
            action = user_input["action"]
            if action == "add_row":
                self.current_row_index = None
                return await self.async_step_row()
            if action == "back":
                # This will save the grid config and return to the main controls list
                await self._save_control(stay_in_flow=True)
                return await self.async_step_controls()
            
            self.current_row_index = int(action)
            return await self.async_step_row_menu()

        row_map = {str(i): f"Row {i+1}" for i, r in enumerate(rows)}

        return self.async_show_form(
            step_id="grid_rows_menu",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In({
                    "add_row": "Add a new row",
                    **row_map,
                    "back": "Save and go back",
                })
            })
        )
        
    # ---------------- Save helpers ----------------

    async def _save_control(self, stay_in_flow: bool = False):
        devices = self.working.get(CONF_DEVICES, [])
        device = next(
            (d for d in devices if d[CONF_ID] == self.current_device_id),
            None
        )
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
            return await self._do_save_and_exit()

    async def _do_save_and_exit(self):
        res = self.async_create_entry(title="", data=self.working)
        try:
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
        except Exception as e:
            _LOGGER.debug("Reload after save failed: %s", e)
        return res