from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    selector,
    TextSelector, TextSelectorConfig, TextSelectorType,
)

from .const import CONF_LAYOUT, DEFAULT_LAYOUT


# ---------- helpers ----------
def _load_layout(raw: str) -> Dict[str, Any]:
    try:
        data = json.loads(raw or DEFAULT_LAYOUT)
        if isinstance(data, dict) and "devices" in data and isinstance(data["devices"], list):
            return data
    except Exception:  # noqa: BLE001
        pass
    return {"devices": []}


def _dump_layout(layout: Dict[str, Any]) -> str:
    return json.dumps(layout, ensure_ascii=False, separators=(",", ":"), indent=2)


def _pretty_label_from_entity(entity_id: str) -> str:
    # "light.table_lamp" -> "Table Lamp"
    base = entity_id.split(".", 1)[-1].replace("_", " ").strip()
    return base[:1].upper() + base[1:]


def _autogen_controls(hass: HomeAssistant, entity_id: str) -> List[Dict[str, Any]]:
    """Append-friendly control suggestions. Never destructive."""
    st = hass.states.get(entity_id)
    attrs = st.attributes if st else {}
    domain = entity_id.split(".", 1)[0]

    controls: List[Dict[str, Any]] = []

    # Always a power switch for common domains
    if domain in ("light", "switch", "fan", "media_player", "cover", "climate"):
        controls.append({"label": "Power", "type": "switch", "entity": entity_id})

    if domain == "light":
        if "brightness" in attrs or "supported_color_modes" in attrs:
            controls.append(
                {"label": "Brightness", "type": "slider", "entity": entity_id, "min": 0, "max": 255, "step": 1}
            )
        scm = set(attrs.get("supported_color_modes", []))
        if scm.intersection({"hs", "rgb", "xy"}) or "rgb_color" in attrs or "hs_color" in attrs:
            controls.append({"label": "Color", "type": "color", "entity": entity_id})

    if domain == "fan":
        controls.append({"label": "Speed", "type": "slider", "entity": entity_id, "min": 0, "max": 100, "step": 1})

    if domain == "cover":
        controls.append({"label": "Position", "type": "slider", "entity": entity_id, "min": 0, "max": 100, "step": 1})

    if domain == "media_player":
        controls.append({"label": "Volume", "type": "slider", "entity": entity_id, "min": 0, "max": 100, "step": 1})
        sources = attrs.get("source_list")
        if isinstance(sources, list) and sources:
            controls.append({"label": "Source", "type": "select", "entity": entity_id, "options": "\n".join(map(str, sources))})

    if domain in ("number", "input_number"):
        controls.append({"label": _pretty_label_from_entity(entity_id), "type": "slider", "entity": entity_id, "min": 0, "max": 100, "step": 1})

    if domain in ("select", "input_select"):
        opts = attrs.get("options", [])
        if isinstance(opts, list) and opts:
            controls.append({"label": _pretty_label_from_entity(entity_id), "type": "select", "entity": entity_id, "options": "\n".join(map(str, opts))})

    return controls


# ---------- Options Flow ----------
class MeshPanelOptionsFlowHandler(config_entries.OptionsFlow):
    """Clean tab-style builder; unlimited devices and controls."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry
        self._layout: Dict[str, Any] = _load_layout(entry.options.get(CONF_LAYOUT, DEFAULT_LAYOUT))
        self._devices: List[Dict[str, Any]] = list(self._layout.get("devices", []))
        self._edit_idx: Optional[int] = None
        self._edit_ctrl_idx: Optional[int] = None

    # --- root: device list ---
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            action = user_input["action"]
            idx_str = user_input.get("device_index")
            idx = int(idx_str) if idx_str not in (None, "") else None

            if action == "add":
                return await self.async_step_device_add()
            if action == "edit" and idx is not None and 0 <= idx < len(self._devices):
                self._edit_idx = idx
                return await self.async_step_device_edit()
            if action == "delete" and idx is not None and 0 <= idx < len(self._devices):
                self._devices.pop(idx)
            if action == "save":
                layout = {"devices": self._devices}
                return self.async_create_entry(title="", data={CONF_LAYOUT: _dump_layout(layout)})

        options = [str(i) for i in range(len(self._devices))]
        listing = "\n".join(
            f"{i}. {d.get('name','(unnamed)')}  [{len(d.get('controls',[]))} controls]"
            for i, d in enumerate(self._devices)
        ) or "No devices yet. Click Add."

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional("device_index"): selector({"select": {"options": options}}) if options else str,
                vol.Required("action", default="save"): selector({"select": {"options": [
                    {"label": "💾 Save & Apply", "value": "save"},
                    {"label": "➕ Add Device", "value": "add"},
                    {"label": "✏️ Edit Selected", "value": "edit"},
                    {"label": "🗑 Delete Selected", "value": "delete"},
                ]}})
            }),
            description_placeholders={"devices": listing},
        )

    # --- device add ---
    async def async_step_device_add(self, user_input=None):
        if user_input is not None:
            dev = {
                "name": user_input["name"].strip(),
                "icon": user_input.get("icon", "settings").strip() or "settings",
                "state_entity": user_input.get("state_entity") or "",
                "controls": [],
            }
            self._devices.append(dev)
            self._edit_idx = len(self._devices) - 1
            return await self.async_step_device_edit()

        return self.async_show_form(
            step_id="device_add",
            data_schema=vol.Schema({
                vol.Required("name"): str,
                vol.Optional("icon", default="settings"): str,
                vol.Optional("state_entity"): selector({"entity": {}}),
            }),
        )

    # --- device edit ---
    async def async_step_device_edit(self, user_input=None):
        dev = self._devices[self._edit_idx]

        if user_input is not None:
            action = user_input["action"]
            if action == "autogen":
                ent = user_input.get("autogen_entity")
                if ent:
                    dev["controls"].extend(_autogen_controls(self.hass, ent))
            elif action == "addctrl":
                return await self.async_step_control_add()
            elif action == "editctrl":
                sel = user_input.get("control_index")
                if sel not in (None, ""):
                    idx = int(sel)
                    if 0 <= idx < len(dev["controls"]):
                        self._edit_ctrl_idx = idx
                        return await self.async_step_control_edit()
            elif action == "delctrl":
                sel = user_input.get("control_index")
                if sel not in (None, ""):
                    idx = int(sel)
                    if 0 <= idx < len(dev["controls"]):
                        dev["controls"].pop(idx)
            elif action == "done":
                return await self.async_step_init()

        ctrl_labels = [f'{i}. {c.get("label","(no label)")} [{c.get("type")}] → {c.get("entity","")}'
                       for i, c in enumerate(dev.get("controls", []))]
        options = [str(i) for i in range(len(dev.get("controls", [])))]

        return self.async_show_form(
            step_id="device_edit",
            data_schema=vol.Schema({
                vol.Required("action", default="autogen"): selector({"select": {"options": [
                    {"label": "⚡ Auto-Generate Controls from Entity", "value": "autogen"},
                    {"label": "➕ Add Control (Manual)", "value": "addctrl"},
                    {"label": "✏️ Edit Selected Control", "value": "editctrl"},
                    {"label": "🗑 Delete Selected Control", "value": "delctrl"},
                    {"label": "✔ Done", "value": "done"},
                ]}}),
                vol.Optional("autogen_entity"): selector({"entity": {}}),
                vol.Optional("control_index"): selector({"select": {"options": options}}) if options else str,
            }),
            description_placeholders={
                "device": f'{dev.get("name")} ({dev.get("icon","settings")})',
                "controls": "\n".join(ctrl_labels) or "No controls yet.",
            },
        )

    # --- control add ---
    async def async_step_control_add(self, user_input=None):
        if user_input is not None:
            ent = user_input["entity"]
            ctype = user_input["type"]
            ctrl: Dict[str, Any] = {
                "label": user_input.get("label") or _pretty_label_from_entity(ent),
                "type": ctype,
                "entity": ent,
            }
            if ctype == "slider":
                ctrl.update({
                    "min": int(user_input.get("min", 0)),
                    "max": int(user_input.get("max", 100)),
                    "step": int(user_input.get("step", 1)),
                })
            if ctype == "select":
                ctrl["options"] = user_input.get("options", "")
            self._devices[self._edit_idx]["controls"].append(ctrl)
            return await self.async_step_device_edit()

        return self._control_form("control_add")

    # --- control edit ---
    async def async_step_control_edit(self, user_input=None):
        dev = self._devices[self._edit_idx]
        ctrl = dev["controls"][self._edit_ctrl_idx]

        if user_input is not None:
            ent = user_input["entity"]
            ctype = user_input["type"]
            ctrl.update({
                "label": user_input.get("label") or _pretty_label_from_entity(ent),
                "type": ctype,
                "entity": ent,
            })
            if ctype == "slider":
                ctrl.update({
                    "min": int(user_input.get("min", 0)),
                    "max": int(user_input.get("max", 100)),
                    "step": int(user_input.get("step", 1)),
                })
                ctrl.pop("options", None)
            elif ctype == "select":
                ctrl["options"] = user_input.get("options", "")
                ctrl.pop("min", None)
                ctrl.pop("max", None)
                ctrl.pop("step", None)
            else:
                ctrl.pop("min", None)
                ctrl.pop("max", None)
                ctrl.pop("step", None)
                ctrl.pop("options", None)

            return await self.async_step_device_edit()

        return self._control_form(
            "control_edit",
            defaults=ctrl,
        )

    # --- common control form builder ---
    def _control_form(self, step_id: str, defaults: Optional[Dict[str, Any]] = None):
        defaults = defaults or {}
        schema = vol.Schema({
            vol.Optional("label", default=defaults.get("label", "")): str,
            vol.Required("type", default=defaults.get("type", "switch")): selector({
                "select": {"options": [
                    {"label": "Switch", "value": "switch"},
                    {"label": "Slider", "value": "slider"},
                    {"label": "Color",  "value": "color"},
                    {"label": "Select", "value": "select"},
                ]}
            }),
            vol.Required("entity", default=defaults.get("entity")): selector({"entity": {}}),
            vol.Optional("min",  default=defaults.get("min", 0)): int,
            vol.Optional("max",  default=defaults.get("max", 100)): int,
            vol.Optional("step", default=defaults.get("step", 1)): int,
            vol.Optional("options", default=defaults.get("options", "")): TextSelector(
                TextSelectorConfig(multiline=True, type=TextSelectorType.TEXT)
            ),
        })
        return self.async_show_form(step_id=step_id, data_schema=schema)
