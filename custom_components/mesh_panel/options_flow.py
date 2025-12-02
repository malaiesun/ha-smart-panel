from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers.selector import selector, TextSelector, TextSelectorConfig, TextSelectorType

from .const import CONF_LAYOUT, DEFAULT_LAYOUT


def _load_layout(raw: str) -> Dict[str, Any]:
    try:
        data = json.loads(raw or DEFAULT_LAYOUT)
        if isinstance(data, dict) and isinstance(data.get("devices"), list):
            return data
    except Exception:
        pass
    return {"devices": []}

def _dump_layout(d: Dict[str, Any]) -> str:
    return json.dumps(d, ensure_ascii=False, indent=2)

def _pretty_label(entity_id: str) -> str:
    base = entity_id.split(".", 1)[-1].replace("_", " ").strip()
    return base[:1].upper() + base[1:]

def _autogen(hass: HomeAssistant, entity_id: str) -> List[Dict[str, Any]]:
    st = hass.states.get(entity_id)
    attrs = st.attributes if st else {}
    domain = entity_id.split(".", 1)[0]
    out: List[Dict[str, Any]] = []

    if domain in ("light", "switch", "fan", "media_player", "cover", "climate"):
        out.append({"label": "Power", "type": "switch", "entity": entity_id})
    if domain == "light":
        if "brightness" in attrs or "supported_color_modes" in attrs:
            out.append({"label": "Brightness", "type": "slider", "entity": entity_id, "min": 0, "max": 255, "step": 1})
        scm = set(attrs.get("supported_color_modes", []))
        if scm.intersection({"hs", "rgb", "xy"}) or "rgb_color" in attrs or "hs_color" in attrs:
            out.append({"label": "Color", "type": "color", "entity": entity_id})
    if domain == "fan":
        out.append({"label": "Speed", "type": "slider", "entity": entity_id, "min": 0, "max": 100, "step": 1})
    if domain == "cover":
        out.append({"label": "Position", "type": "slider", "entity": entity_id, "min": 0, "max": 100, "step": 1})
    if domain == "media_player":
        out.append({"label": "Volume", "type": "slider", "entity": entity_id, "min": 0, "max": 100, "step": 1})
        sources = attrs.get("source_list")
        if isinstance(sources, list) and sources:
            out.append({"label": "Source", "type": "select", "entity": entity_id, "options": "\n".join(map(str, sources))})
    if domain in ("number", "input_number"):
        out.append({"label": _pretty_label(entity_id), "type": "slider", "entity": entity_id, "min": 0, "max": 100, "step": 1})
    if domain in ("select", "input_select"):
        opts = attrs.get("options", [])
        if isinstance(opts, list) and opts:
            out.append({"label": _pretty_label(entity_id), "type": "select", "entity": entity_id, "options": "\n".join(map(str, opts))})
    return out


class MeshPanelOptionsFlowHandler(config_entries.OptionsFlow):
    """Single-page builder with simple actions."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry
        self._layout: Dict[str, Any] = _load_layout(entry.options.get(CONF_LAYOUT, DEFAULT_LAYOUT))
        self._devices: List[Dict[str, Any]] = list(self._layout.get("devices", []))

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            act = user_input["action"]

            # add device
            if act == "add_device":
                self._devices.append({
                    "name": user_input["dev_name"].strip(),
                    "icon": (user_input.get("dev_icon") or "settings").strip(),
                    "state_entity": user_input.get("dev_state_entity") or "",
                    "controls": [],
                })

            # autogen controls (append) for device index
            elif act == "autogen":
                di = user_input.get("dev_index")
                ent = user_input.get("auto_entity")
                if di not in (None, "") and ent:
                    i = int(di)
                    if 0 <= i < len(self._devices):
                        self._devices[i].setdefault("controls", []).extend(_autogen(self.hass, ent))

            # add manual control
            elif act == "add_control":
                di = user_input.get("dev_index")
                if di not in (None, ""):
                    i = int(di)
                    if 0 <= i < len(self._devices):
                        ctype = user_input["ctrl_type"]
                        ent = user_input["ctrl_entity"]
                        ctrl: Dict[str, Any] = {
                            "label": user_input.get("ctrl_label") or _pretty_label(ent),
                            "type": ctype,
                            "entity": ent,
                        }
                        if ctype == "slider":
                            ctrl.update({
                                "min": int(user_input.get("ctrl_min", 0)),
                                "max": int(user_input.get("ctrl_max", 100)),
                                "step": int(user_input.get("ctrl_step", 1)),
                            })
                        if ctype == "select":
                            ctrl["options"] = user_input.get("ctrl_options", "")
                        self._devices[i].setdefault("controls", []).append(ctrl)

            # delete device
            elif act == "del_device":
                di = user_input.get("dev_index")
                if di not in (None, ""):
                    i = int(di)
                    if 0 <= i < len(self._devices):
                        self._devices.pop(i)

            # delete control
            elif act == "del_control":
                di = user_input.get("dev_index")
                ci = user_input.get("ctrl_index")
                if di not in (None, "") and ci not in (None, ""):
                    i, j = int(di), int(ci)
                    if 0 <= i < len(self._devices):
                        ctrls = self._devices[i].get("controls", [])
                        if 0 <= j < len(ctrls):
                            ctrls.pop(j)

            # save
            elif act == "save":
                return self.async_create_entry(title="", data={CONF_LAYOUT: _dump_layout({"devices": self._devices})})

        # Build simple lists for selection
        dev_opts = [str(i) for i in range(len(self._devices))]
        ctrl_opts_for_dev0 = [str(i) for i in range(len(self._devices[0].get("controls", [])))] if self._devices else []

        # Printable current config
        listing = []
        for i, d in enumerate(self._devices):
            listing.append(f"{i}. {d.get('name','(unnamed)')}  [{len(d.get('controls',[]))} controls]")
            for j, c in enumerate(d.get("controls", [])):
                listing.append(f"   - {j}. {c.get('label','(no label)')} [{c.get('type')}] → {c.get('entity','')}")
        summary = "\n".join(listing) or "No devices yet. Add one below."

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                # action
                vol.Required("action", default="save"): selector({"select": {"options": [
                    {"label": "💾 Save & Apply", "value": "save"},
                    {"label": "➕ Add Device", "value": "add_device"},
                    {"label": "⚡ Auto-Generate Controls (Append)", "value": "autogen"},
                    {"label": "➕ Add Control (Manual)", "value": "add_control"},
                    {"label": "🗑 Delete Device", "value": "del_device"},
                    {"label": "🗑 Delete Control", "value": "del_control"},
                ]}}),

                # device-level inputs
                vol.Optional("dev_name"): str,
                vol.Optional("dev_icon", default="settings"): str,
                vol.Optional("dev_state_entity"): selector({"entity": {}}),

                # indexes for actions on existing
                vol.Optional("dev_index"): selector({"select": {"options": dev_opts}}) if dev_opts else str,
                vol.Optional("ctrl_index"): selector({"select": {"options": ctrl_opts_for_dev0}}) if ctrl_opts_for_dev0 else str,

                # autogen target
                vol.Optional("auto_entity"): selector({"entity": {}}),

                # control inputs
                vol.Optional("ctrl_label"): str,
                vol.Optional("ctrl_type", default="switch"): selector({"select": {"options": [
                    {"label": "Switch", "value": "switch"},
                    {"label": "Slider", "value": "slider"},
                    {"label": "Color",  "value": "color"},
                    {"label": "Select", "value": "select"},
                ]}}),
                vol.Optional("ctrl_entity"): selector({"entity": {}}),
                vol.Optional("ctrl_min", default=0): int,
                vol.Optional("ctrl_max", default=100): int,
                vol.Optional("ctrl_step", default=1): int,
                vol.Optional("ctrl_options", default=""): TextSelector(TextSelectorConfig(multiline=True, type=TextSelectorType.TEXT)),
            }),
            description_placeholders={"devices": summary},
        )
