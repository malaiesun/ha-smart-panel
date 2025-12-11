"""
Options Flow for MESH Smart Home Panel
- Consistent Back + Save & Exit on every screen
- Sensible defaults for grid/row/button styling
- Button YAML action editor (paste from HA Dev Tools)
- Fix: persist grid edits even if Save & Exit from deep steps
"""

from __future__ import annotations

import copy
import logging
import uuid
from typing import Any, Dict, List, Tuple

import voluptuous as vol
import yaml  # safe_load used for pasted YAML

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers.selector import (
    ActionSelector,  # optional power users
    EntitySelector,
    IconSelector,
    NumberSelector, NumberSelectorConfig,
    SelectSelector, SelectSelectorConfig, SelectSelectorMode,
    TextSelector, TextSelectorConfig,
)

from .const import (
    DOMAIN,
    CONF_DEVICES,
    CONF_ID, CONF_NAME, CONF_ICON, CONF_CONTROLS,
    CONF_LABEL, CONF_TYPE, CONF_ENTITY,
    CONF_MIN, CONF_MAX, CONF_STEP, CONF_OPTIONS,
    # grid
    CONF_GRID, CONF_GRID_LABEL, CONF_GRID_BG, CONF_GRID_RADIUS, CONF_GRID_PADDING,
    CONF_ROWS, CONF_ROW_HEIGHT, CONF_ROW_BG, CONF_ROW_RADIUS, CONF_ROW_PADDING,
    CONF_BUTTONS, CONF_BUTTON_WIDTH,
    CONF_ACTION, CONF_LABEL_FORMULA, CONF_BG_COLOR_FORMULA, CONF_TEXT_COLOR_FORMULA,
    CONTROL_TYPES,
)

_LOGGER = logging.getLogger(__name__)

# -------------------------- sensible UI defaults --------------------------

DEFAULT_GRID = {
    CONF_GRID_LABEL: "Scenes",
    CONF_GRID_BG: "#101010",
    CONF_GRID_RADIUS: "12",
    CONF_GRID_PADDING: "10",
    CONF_ROWS: [],
}

DEFAULT_ROW = {
    CONF_ROW_HEIGHT: 1.0,
    CONF_ROW_BG: "#1a1a1a",
    CONF_ROW_RADIUS: "8",
    CONF_ROW_PADDING: "6",
    CONF_BUTTONS: [],
}

DEFAULT_BUTTON = {
    CONF_ID: "",
    CONF_BUTTON_WIDTH: 1,
    CONF_LABEL_FORMULA: "Press",
    CONF_TEXT_COLOR_FORMULA: "#FFFFFF",
    CONF_BG_COLOR_FORMULA: "#2d2d2d",
    CONF_ACTION: {},  # will be filled from YAML or ActionSelector
}

# --------- numeric attribute helpers (from your previous logic) ---------

def _is_number(val: Any) -> bool:
    try:
        float(val)
        return True
    except Exception:
        return False

_NUMERIC_LIGHT_ATTRS = {
    "brightness",
    "color_temp",
    "color_temp_kelvin",
    "min_mireds",
    "max_mireds",
    "min_color_temp_kelvin",
    "max_color_temp_kelvin",
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

def _numeric_attribute_names_for_entity(hass: HomeAssistant, entity_id: str) -> List[str]:
    names: List[str] = []
    st = hass.states.get(entity_id)
    if not st:
        return ["state"]

    for k, v in st.attributes.items():
        if _is_number(v):
            names.append(k)

    domain = (entity_id.split(".")[0]) if entity_id else ""

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
        "supported_color_modes", "supported_features", "restored",
        "icon", "friendly_name", "effect_list"
    }
    names = [n for n in names if n not in noisy]
    return names or ["state"]

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

    domain = (entity_id.split(".")[0]) if entity_id else ""
    if domain == "fan":
        return (0, 100, 1)
    if domain == "climate":
        return (10, 40, 1)
    if domain == "media_player":
        return (0, 100, 1)

    return _DEFAULT_RANGES["__generic__"]

def _autodetect_select_options(hass: HomeAssistant, entity_id: str) -> List[str]:
    if not entity_id:
        return []
    st = hass.states.get(entity_id)
    if not st:
        return []

    candidates = [
        "options", "source_list", "effect_list",
        "preset_modes", "hvac_modes", "fan_mode_list",
        "swing_modes", "fan_speed_list", "operation_list",
    ]
    for attr in candidates:
        val = st.attributes.get(attr)
        if isinstance(val, list) and val:
            return [str(v) for v in val]
    return []

# =============================== Options Flow ===============================

class MeshPanelOptionsFlowHandler(config_entries.OptionsFlow):
    """Visual options editor with staged changes and explicit Save."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        self.config_entry = config_entry
        self.options = dict(config_entry.options or {})
        self.working = copy.deepcopy(self.options)
        self.working.setdefault(CONF_DEVICES, [])

        self.current_device_id: str | None = None
        self.current_control_id: str | None = None
        self.control_data: Dict[str, Any] = {}
        self.current_row_index: int | None = None
        self.current_button_index: int | None = None

        self._errors: Dict[str, str] = {}

    # ---------------- util helpers ----------------

    def _with_nav(self, options: Dict[str, str]) -> Dict[str, str]:
        """Append Back + Save & Exit everywhere."""
        return {**options, "back": "Back", "save_exit": "Save & Exit"}

    def _get_device_mut(self) -> Dict[str, Any] | None:
        devices = self.working.setdefault(CONF_DEVICES, [])
        return next((d for d in devices if d[CONF_ID] == self.current_device_id), None)

    def _get_or_create_device(self) -> Dict[str, Any]:
        d = self._get_device_mut()
        if d is None:
            d = {CONF_ID: str(uuid.uuid4()), CONF_NAME: "Device", CONF_ICON: "mdi:power", CONF_CONTROLS: []}
            self.current_device_id = d[CONF_ID]
            self.working[CONF_DEVICES].append(d)
        d.setdefault(CONF_CONTROLS, [])
        return d

    def _get_or_create_control(self) -> Dict[str, Any]:
        """Ensure a control exists in working that matches self.control_data."""
        device = self._get_or_create_device()
        controls = device.setdefault(CONF_CONTROLS, [])

        if self.current_control_id:
            for i, c in enumerate(controls):
                if c[CONF_ID] == self.current_control_id:
                    # merge current scratch into stored
                    merged = {**c, **self.control_data}
                    controls[i] = merged
                    return merged

        # If not found, create new control with current scratch data
        new_id = self.control_data.get(CONF_ID) or str(uuid.uuid4())
        self.current_control_id = new_id
        control = {CONF_ID: new_id, **self.control_data}
        controls.append(control)
        return control

    def _merge_current_edits_into_working(self) -> None:
        """
        Persist any in-flight edits (grid/row/button) into self.working
        even if we haven't explicitly saved this control yet.
        """
        if not self.control_data:
            return
        control = self._get_or_create_control()
        # Ensure grid defaults present when type is button_grid
        if control.get(CONF_TYPE) == "button_grid":
            g = control.setdefault(CONF_GRID, copy.deepcopy(DEFAULT_GRID))
            g.setdefault(CONF_ROWS, [])
            # normalize row/button defaults
            for i, row in enumerate(g.get(CONF_ROWS, [])):
                if not isinstance(row, dict):
                    g[CONF_ROWS][i] = copy.deepcopy(DEFAULT_ROW)
                    continue
                for k, v in DEFAULT_ROW.items():
                    row.setdefault(k, v)
                btns = row.setdefault(CONF_BUTTONS, [])
                for j, b in enumerate(btns):
                    if not isinstance(b, dict):
                        btns[j] = copy.deepcopy(DEFAULT_BUTTON)
                        continue
                    for k, v in DEFAULT_BUTTON.items():
                        b.setdefault(k, v)

    async def _save_control(self, stay_in_flow: bool = False):
        """Upsert current control into working and optionally exit."""
        self._merge_current_edits_into_working()
        if not stay_in_flow:
            return await self._do_save_and_exit()

    async def _do_save_and_exit(self):
        """Save whole options snapshot."""
        # Final merge for safety
        self._merge_current_edits_into_working()
        res = self.async_create_entry(title="", data=self.working)
        try:
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
        except Exception as e:
            _LOGGER.debug("Reload after save failed: %s", e)
        return res

    # ---------------- Devices root ----------------

    async def async_step_init(self, user_input=None):
        if user_input:
            act = user_input["action"]
            if act == "add_device":
                self.current_device_id = None
                return await self.async_step_device()
            if act == "save_exit":
                return await self._do_save_and_exit()
            if act == "back":
                return await self._do_save_and_exit()

            self.current_device_id = act
            return await self.async_step_device_menu()

        devices = self.working.get(CONF_DEVICES, [])
        dev_map = {d[CONF_ID]: d.get(CONF_NAME, "Device") for d in devices}

        options = self._with_nav({
            "add_device": "Add a new device",
            **dev_map,
        })

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
            if act == "edit":          return await self.async_step_device()
            if act == "controls":      return await self.async_step_controls()
            if act == "delete":
                self.working[CONF_DEVICES] = [
                    d for d in self.working.get(CONF_DEVICES, [])
                    if d[CONF_ID] != self.current_device_id
                ]
                # clear context if we deleted the current device
                self.current_control_id = None
                self.control_data = {}
                return await self.async_step_init()
            if act == "save_exit":     return await self._do_save_and_exit()
            if act == "back":          return await self.async_step_init()

        return self.async_show_form(
            step_id="device_menu",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In(self._with_nav({
                    "edit": "Edit Device",
                    "controls": "Manage Controls",
                    "delete": "Delete Device",
                }))
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
            # Navigation keys can come together with fields
            nav = user_input.pop("nav", None)

            devs = self.working.setdefault(CONF_DEVICES, [])
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

            if nav == "save_exit":
                return await self._do_save_and_exit()
            if nav == "back":
                return await self.async_step_device_menu()

            return await self.async_step_device_menu()

        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, default=device_data.get(CONF_NAME, "")): TextSelector(),
                vol.Required(CONF_ICON, default=device_data.get(CONF_ICON, "mdi:power")): IconSelector(),
                vol.Required("nav", default="continue"): vol.In({
                    "continue": "Continue",
                    "back": "Back",
                    "save_exit": "Save & Exit",
                })
            })
        )

    # ---------------- Controls list ----------------

    async def async_step_controls(self, user_input=None):
        device = self._get_or_create_device()
        controls = device.get(CONF_CONTROLS, [])

        if user_input:
            act = user_input["action"]
            if act == "add":
                self.current_control_id = None
                self.control_data = {}
                return await self.async_step_control()
            if act == "save_exit": return await self._do_save_and_exit()
            if act == "back":      return await self.async_step_device_menu()

            self.current_control_id = act
            return await self.async_step_control_menu()

        ctrl_map = {c[CONF_ID]: c.get(CONF_LABEL, c[CONF_ID]) for c in controls}
        return self.async_show_form(
            step_id="controls",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In(self._with_nav({
                    "add": "Add a new control",
                    **ctrl_map,
                }))
            })
        )

    # ---------------- Control menu ----------------

    async def async_step_control_menu(self, user_input=None):
        if user_input:
            act = user_input["action"]
            if act == "edit":      return await self.async_step_control()
            if act == "delete":
                device = self._get_device_mut()
                if device:
                    device[CONF_CONTROLS] = [
                        c for c in device.get(CONF_CONTROLS, [])
                        if c[CONF_ID] != self.current_control_id
                    ]
                self.current_control_id = None
                self.control_data = {}
                return await self.async_step_controls()
            if act == "save_exit": return await self._do_save_and_exit()
            if act == "back":      return await self.async_step_controls()

        return self.async_show_form(
            step_id="control_menu",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In(self._with_nav({
                    "edit": "Edit Control",
                    "delete": "Delete Control",
                }))
            })
        )

    # ---------------- Control base ----------------

    async def async_step_control(self, user_input=None):
        if self.current_control_id:
            device = self._get_device_mut()
            if device:
                controls = device.get(CONF_CONTROLS, [])
                self.control_data = next(
                    (c for c in controls if c[CONF_ID] == self.current_control_id),
                    {}
                )

        if user_input:
            nav = user_input.get("nav")
            # merge fields first
            self.control_data.update({k: v for k, v in user_input.items() if k != "nav"})

            # route
            if self.control_data.get(CONF_TYPE) == "button_grid":
                # ensure grid defaults
                self.control_data.setdefault(CONF_GRID, copy.deepcopy(DEFAULT_GRID))
                if nav == "save_exit":
                    # persist then exit
                    await self._save_control(stay_in_flow=False)
                    return  # _do_save_and_exit returns
                if nav == "back":
                    # persist partial then go back to controls list
                    await self._save_control(stay_in_flow=True)
                    return await self.async_step_controls()
                return await self.async_step_control_grid()

            # non-grid controls need entity step
            if nav == "save_exit":
                await self._save_control(stay_in_flow=False)
                return
            if nav == "back":
                await self._save_control(stay_in_flow=True)
                return await self.async_step_controls()
            return await self.async_step_control_entity()

        # defaults
        default_type = self.control_data.get(CONF_TYPE, "switch")
        default_label = self.control_data.get(CONF_LABEL, "")

        return self.async_show_form(
            step_id="control",
            data_schema=vol.Schema({
                vol.Required(CONF_LABEL, default=default_label): TextSelector(),
                vol.Required(CONF_TYPE, default=default_type):
                    SelectSelector(SelectSelectorConfig(
                        options=CONTROL_TYPES,
                        mode=SelectSelectorMode.DROPDOWN
                    )),
                vol.Required("nav", default="continue"): vol.In({
                    "continue": "Continue",
                    "back": "Back",
                    "save_exit": "Save & Exit",
                })
            })
        )

    async def async_step_control_entity(self, user_input=None):
        """Handle entity selection for non-grid controls."""
        if user_input:
            nav = user_input.get("nav")
            self.control_data.update({k: v for k, v in user_input.items() if k != "nav"})

            if self.control_data[CONF_TYPE] == "slider":
                if nav == "save_exit":
                    await self._save_control(stay_in_flow=False)
                    return
                if nav == "back":
                    await self._save_control(stay_in_flow=True)
                    return await self.async_step_controls()
                return await self.async_step_control_slider()

            if self.control_data[CONF_TYPE] == "select":
                if nav == "save_exit":
                    await self._save_control(stay_in_flow=False)
                    return
                if nav == "back":
                    await self._save_control(stay_in_flow=True)
                    return await self.async_step_controls()
                return await self.async_step_control_select()

            # switch/color/time/text etc -> save now
            if nav == "save_exit":
                await self._save_control(stay_in_flow=False)
                return
            if nav == "back":
                await self._save_control(stay_in_flow=True)
                return await self.async_step_controls()

            await self._save_control(stay_in_flow=True)
            return await self.async_step_controls()

        return self.async_show_form(
            step_id="control_entity",
            data_schema=vol.Schema({
                vol.Required(CONF_ENTITY, default=self.control_data.get(CONF_ENTITY, "")): EntitySelector(),
                vol.Required("nav", default="continue"): vol.In({
                    "continue": "Continue",
                    "back": "Back",
                    "save_exit": "Save & Exit",
                })
            })
        )

    # ---------------- Slider config ----------------

    async def async_step_control_slider(self, user_input=None):
        ent = self.control_data.get(CONF_ENTITY, "")
        hass = self.hass

        attrs = _numeric_attribute_names_for_entity(hass, ent)
        attr_default = self.control_data.get(
            "attribute", "brightness" if (ent or "").startswith("light.") else "state"
        )

        if user_input:
            nav = user_input.get("nav")
            # merge numeric config
            self.control_data.update({
                k: v for k, v in user_input.items()
                if k in {"attribute", CONF_MIN, CONF_MAX, CONF_STEP}
            })

            # encode entity with attribute if needed
            attribute = self.control_data.get("attribute", "state")
            encoded = ent if attribute == "state" else f"{ent} ({attribute})"
            self.control_data[CONF_ENTITY] = encoded

            if nav == "save_exit":
                await self._save_control(stay_in_flow=False)
                return
            if nav == "back":
                await self._save_control(stay_in_flow=True)
                return await self.async_step_controls()

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
                vol.Required("nav", default="continue"): vol.In({
                    "continue": "Continue",
                    "back": "Back",
                    "save_exit": "Save & Exit",
                })
            })
        )

    # ---------------- Select config ----------------

    async def async_step_control_select(self, user_input=None):
        if user_input is not None:
            nav = user_input.get("nav")
            raw_text = user_input.get(CONF_OPTIONS, "")

            # Always store newline-separated internally
            if "," in raw_text:
                cleaned = [o.strip() for o in raw_text.split(",") if o.strip()]
                self.control_data[CONF_OPTIONS] = "\n".join(cleaned)
            else:
                self.control_data[CONF_OPTIONS] = raw_text

            if nav == "save_exit":
                await self._save_control(stay_in_flow=False)
                return
            if nav == "back":
                await self._save_control(stay_in_flow=True)
                return await self.async_step_controls()

            await self._save_control(stay_in_flow=True)
            return await self.async_step_controls()

        default_text = self.control_data.get(CONF_OPTIONS, "")
        if not default_text:
            ent = self.control_data.get(CONF_ENTITY, "")
            detected = _autodetect_select_options(self.hass, ent)
            if detected:
                default_text = ", ".join(detected)
        elif "\n" in default_text:
            default_text = default_text.replace("\n", ", ")

        return self.async_show_form(
            step_id="control_select",
            data_schema=vol.Schema({
                vol.Required(CONF_OPTIONS, default=default_text): TextSelector(),
                vol.Required("nav", default="continue"): vol.In({
                    "continue": "Continue",
                    "back": "Back",
                    "save_exit": "Save & Exit",
                })
            })
        )

    # ======================= Button Grid (new UX) =======================

    async def async_step_control_grid(self, user_input=None):
        """Top-level Button Grid editor (with defaults)."""
        grid = self.control_data.setdefault(CONF_GRID, copy.deepcopy(DEFAULT_GRID))

        if user_input is not None:
            nav = user_input.get("nav")
            # merge grid fields
            for k in (CONF_GRID_LABEL, CONF_GRID_BG, CONF_GRID_RADIUS, CONF_GRID_PADDING):
                if k in user_input:
                    grid[k] = user_input[k]
            self.control_data[CONF_GRID] = grid

            if nav == "save_exit":
                await self._save_control(stay_in_flow=False)
                return
            if nav == "back":
                await self._save_control(stay_in_flow=True)
                return await self.async_step_controls()

            return await self.async_step_grid_rows_menu()

        return self.async_show_form(
            step_id="control_grid",
            data_schema=vol.Schema({
                vol.Optional(CONF_GRID_LABEL,  default=grid.get(CONF_GRID_LABEL,  DEFAULT_GRID[CONF_GRID_LABEL])): TextSelector(),
                vol.Optional(CONF_GRID_BG,     default=grid.get(CONF_GRID_BG,     DEFAULT_GRID[CONF_GRID_BG])): TextSelector(),
                vol.Optional(CONF_GRID_RADIUS, default=grid.get(CONF_GRID_RADIUS, DEFAULT_GRID[CONF_GRID_RADIUS])): TextSelector(),
                vol.Optional(CONF_GRID_PADDING,default=grid.get(CONF_GRID_PADDING,DEFAULT_GRID[CONF_GRID_PADDING])): TextSelector(),
                vol.Required("nav", default="rows"): vol.In({
                    "rows": "Manage Rows",
                    "back": "Back",
                    "save_exit": "Save & Exit",
                })
            }),
        )

    async def async_step_grid_rows_menu(self, user_input=None):
        grid = self.control_data.setdefault(CONF_GRID, copy.deepcopy(DEFAULT_GRID))
        rows = grid.setdefault(CONF_ROWS, [])

        if user_input:
            act = user_input["action"]
            if act == "add_row":
                self.current_row_index = None
                return await self.async_step_row()
            if act == "save_exit":
                return await self._do_save_and_exit()
            if act == "back":
                # persist to working but stay in flow
                await self._save_control(stay_in_flow=True)
                return await self.async_step_control_grid()

            # select row index
            try:
                self.current_row_index = int(act)
            except Exception:
                self.current_row_index = None
                return await self.async_step_grid_rows_menu()
            return await self.async_step_row_menu()

        row_labels = {
            str(i): f"Row {i+1} — {len(r.get(CONF_BUTTONS, []))} buttons"
            for i, r in enumerate(rows)
        }

        return self.async_show_form(
            step_id="grid_rows_menu",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In(self._with_nav({
                    "add_row": "+ Add Row",
                    **row_labels,
                }))
            })
        )

    async def async_step_row_menu(self, user_input=None):
        if user_input:
            act = user_input["action"]
            if act == "edit_row":    return await self.async_step_row()
            if act == "buttons":     return await self.async_step_row_buttons_menu()
            if act == "delete_row":
                rows = self.control_data[CONF_GRID][CONF_ROWS]
                if self.current_row_index is not None and 0 <= self.current_row_index < len(rows):
                    rows.pop(self.current_row_index)
                self.current_row_index = None
                return await self.async_step_grid_rows_menu()
            if act == "save_exit":   return await self._do_save_and_exit()
            if act == "back":        return await self.async_step_grid_rows_menu()

        return self.async_show_form(
            step_id="row_menu",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In(self._with_nav({
                    "edit_row": "Edit Row Properties",
                    "buttons": "Manage Buttons",
                    "delete_row": "Delete Row",
                }))
            })
        )

    async def async_step_row(self, user_input=None):
        grid = self.control_data.setdefault(CONF_GRID, copy.deepcopy(DEFAULT_GRID))
        rows = grid.setdefault(CONF_ROWS, [])
        row = (rows[self.current_row_index]
               if self.current_row_index is not None and self.current_row_index < len(rows)
               else copy.deepcopy(DEFAULT_ROW))

        if user_input is not None:
            nav = user_input.get("nav")
            # merge submitted row fields
            for k in (CONF_ROW_HEIGHT, CONF_ROW_BG, CONF_ROW_PADDING, CONF_ROW_RADIUS):
                if k in user_input and user_input[k] is not None:
                    row[k] = user_input[k]

            if self.current_row_index is None:
                rows.append(row)
                self.current_row_index = len(rows) - 1
            else:
                rows[self.current_row_index] = row
            self.control_data[CONF_GRID][CONF_ROWS] = rows

            if nav == "save_exit":
                await self._save_control(stay_in_flow=False)
                return
            if nav == "back":
                await self._save_control(stay_in_flow=True)
                return await self.async_step_grid_rows_menu()

            return await self.async_step_row_menu()

        return self.async_show_form(
            step_id="row",
            data_schema=vol.Schema({
                vol.Required(CONF_ROW_HEIGHT,
                    default=row.get(CONF_ROW_HEIGHT, DEFAULT_ROW[CONF_ROW_HEIGHT])):
                    NumberSelector(NumberSelectorConfig(min=0.5, max=5.0, step=0.1)),
                vol.Optional(CONF_ROW_BG,
                    default=row.get(CONF_ROW_BG, DEFAULT_ROW[CONF_ROW_BG])): TextSelector(),
                vol.Optional(CONF_ROW_PADDING,
                    default=row.get(CONF_ROW_PADDING, DEFAULT_ROW[CONF_ROW_PADDING])): TextSelector(),
                vol.Optional(CONF_ROW_RADIUS,
                    default=row.get(CONF_ROW_RADIUS, DEFAULT_ROW[CONF_ROW_RADIUS])): TextSelector(),
                vol.Required("nav", default="buttons"): vol.In({
                    "buttons": "Manage Buttons",
                    "back": "Back",
                    "save_exit": "Save & Exit",
                })
            })
        )

    async def async_step_row_buttons_menu(self, user_input=None):
        row = self.control_data[CONF_GRID][CONF_ROWS][self.current_row_index]
        buttons = row.setdefault(CONF_BUTTONS, [])

        if user_input:
            act = user_input["action"]
            if act == "add_button":
                self.current_button_index = None
                return await self.async_step_button()
            if act == "save_exit":
                return await self._do_save_and_exit()
            if act == "back":
                await self._save_control(stay_in_flow=True)
                return await self.async_step_row_menu()

            self.current_button_index = int(act)
            return await self.async_step_button_menu()

        button_names = {
            str(i): f"{b.get(CONF_ID,'(no id)')} — {b.get(CONF_LABEL_FORMULA,'')}"
            for i, b in enumerate(buttons)
        }

        return self.async_show_form(
            step_id="row_buttons_menu",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In(self._with_nav({
                    "add_button": "+ Add Button",
                    **button_names,
                }))
            })
        )

    async def async_step_button_menu(self, user_input=None):
        if user_input:
            act = user_input["action"]
            if act == "edit":      return await self.async_step_button()
            if act == "delete":
                row = self.control_data[CONF_GRID][CONF_ROWS][self.current_row_index]
                if self.current_button_index is not None and 0 <= self.current_button_index < len(row[CONF_BUTTONS]):
                    row[CONF_BUTTONS].pop(self.current_button_index)
                self.current_button_index = None
                return await self.async_step_row_buttons_menu()
            if act == "save_exit": return await self._do_save_and_exit()
            if act == "back":      return await self.async_step_row_buttons_menu()

        return self.async_show_form(
            step_id="button_menu",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In(self._with_nav({
                    "edit": "Edit Button",
                    "delete": "Delete Button",
                }))
            })
        )

    def _normalize_action_dict(self, action_cfg: Dict[str, Any]) -> Dict[str, Any]:
        """
        Accept both:
          service: light.toggle
          data: {...}
        and
          action: localtuya.reload
          data: {...}
        Normalize to {service: ..., data: ...}
        """
        if not isinstance(action_cfg, dict):
            return {}
        if "service" in action_cfg:
            return action_cfg
        if "action" in action_cfg:
            norm = {"service": action_cfg["action"]}
            if isinstance(action_cfg.get("data"), dict):
                norm["data"] = action_cfg["data"]
            if isinstance(action_cfg.get("target"), dict):
                norm["target"] = action_cfg["target"]
            return norm
        return action_cfg

    async def async_step_button(self, user_input=None):
        row = self.control_data[CONF_GRID][CONF_ROWS][self.current_row_index]
        buttons = row.setdefault(CONF_BUTTONS, [])
        b = (buttons[self.current_button_index]
             if self.current_button_index is not None and self.current_button_index < len(buttons)
             else copy.deepcopy(DEFAULT_BUTTON))

        errors: Dict[str, str] = {}

        if user_input is not None:
            nav = user_input.get("nav")

            # split out YAML text (if provided) and parse
            yaml_text = user_input.pop("action_yaml", None)
            if yaml_text is not None:
                yaml_text = yaml_text.strip()
                if yaml_text:
                    try:
                        parsed = yaml.safe_load(yaml_text)
                        if not isinstance(parsed, dict):
                            errors["base"] = "action_yaml_not_mapping"
                        else:
                            user_input[CONF_ACTION] = parsed
                    except Exception as e:
                        _LOGGER.debug("YAML parse error: %s", e)
                        errors["base"] = "action_yaml_invalid"

            # normalize action dict to {service, data, target}
            if CONF_ACTION in user_input and isinstance(user_input[CONF_ACTION], dict):
                user_input[CONF_ACTION] = self._normalize_action_dict(user_input[CONF_ACTION])

            if not errors:
                # merge and store
                merged = {**b, **{k: v for k, v in user_input.items() if k != "nav"}}
                if self.current_button_index is None:
                    buttons.append(merged)
                    self.current_button_index = len(buttons) - 1
                else:
                    buttons[self.current_button_index] = merged
                row[CONF_BUTTONS] = buttons
                self.control_data[CONF_GRID][CONF_ROWS][self.current_row_index] = row

                if nav == "save_exit":
                    await self._save_control(stay_in_flow=False)
                    return
                if nav == "back":
                    await self._save_control(stay_in_flow=True)
                    return await self.async_step_row_buttons_menu()

                return await self.async_step_row_buttons_menu()

        # Pretty default YAML if none set
        existing_yaml = ""
        if b.get(CONF_ACTION):
            try:
                existing_yaml = yaml.safe_dump(b[CONF_ACTION], sort_keys=False)
            except Exception:
                existing_yaml = ""
        if not existing_yaml:
            existing_yaml = (
                "service: homeassistant.toggle\n"
                "data: {}\n"
                "# or:\n"
                "# action: localtuya.reload\n"
                "# data: {}\n"
            )

        # Use a multiline text selector for YAML editor
        yaml_editor = TextSelector(TextSelectorConfig(multiline=True))

        return self.async_show_form(
            step_id="button",
            data_schema=vol.Schema({
                vol.Required(CONF_ID, default=b.get(CONF_ID, "")): TextSelector(),
                vol.Required(CONF_BUTTON_WIDTH, default=b.get(CONF_BUTTON_WIDTH, 1)):
                    NumberSelector(NumberSelectorConfig(min=1, max=6, step=1)),
                vol.Optional(CONF_LABEL_FORMULA, default=b.get(CONF_LABEL_FORMULA, DEFAULT_BUTTON[CONF_LABEL_FORMULA])): TextSelector(),
                vol.Optional(CONF_TEXT_COLOR_FORMULA, default=b.get(CONF_TEXT_COLOR_FORMULA, DEFAULT_BUTTON[CONF_TEXT_COLOR_FORMULA])): TextSelector(),
                vol.Optional(CONF_BG_COLOR_FORMULA, default=b.get(CONF_BG_COLOR_FORMULA, DEFAULT_BUTTON[CONF_BG_COLOR_FORMULA])): TextSelector(),
                # Optional picker for advanced users
                vol.Optional(CONF_ACTION, default=b.get(CONF_ACTION, {})): ActionSelector(),
                # YAML editor for paste-from-DevTools
                vol.Optional("action_yaml", default=existing_yaml): yaml_editor,
                vol.Required("nav", default="back"): vol.In({
                    "back": "Back",
                    "save_exit": "Save & Exit",
                })
            }),
            errors=errors
        )
