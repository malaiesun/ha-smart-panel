"""
Manages a MESH panel with proper entity/attribute decoding
and one-by-one live update syncing.
"""
import json
import logging
import copy

from homeassistant.core import HomeAssistant, callback
from homeassistant.components import mqtt
from homeassistant.const import (
    SERVICE_TURN_ON,
    SERVICE_TURN_OFF,
    ATTR_ENTITY_ID
)
from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_RGB_COLOR
from homeassistant.helpers.event import async_track_state_change_event
import homeassistant.util.color as color_util  # Import moved to top

from .const import *

_LOGGER = logging.getLogger(__name__)


def decode_entity(raw: str):
    """Decode 'entity (attr)' → ('entity', 'attr')."""
    raw = raw.strip()
    if "(" in raw and raw.endswith(")"):
        try:
            base = raw[:raw.index("(")].strip()
            attr = raw[raw.index("(") + 1:-1].strip()
            return base, attr
        except Exception:
            return raw, None
    return raw, None


class MeshPanelController:
    """Controller handling a MESH Smart Panel."""

    def __init__(self, hass: HomeAssistant, panel_id: str, devices_data: list):
        self.hass = hass
        self.panel_id = panel_id
        self.topic_ui = TOPIC_UI_FMT.format(panel_id=panel_id)
        self.topic_state = TOPIC_STATE_FMT.format(panel_id=panel_id)
        self.topic_action = TOPIC_ACTION_FMT.format(panel_id=panel_id)
        self.topic_notify = TOPIC_NOTIFY_FMT.format(panel_id=panel_id)

        self.devices_config = devices_data

        self._unsub_action = None
        self._state_unsub = None
        self._watched = set()

    async def start(self):
        """Start the controller."""
        async def _on_action(msg):
            await self._handle_action(msg.payload)

        self._unsub_action = await mqtt.async_subscribe(
            self.hass, self.topic_action, _on_action
        )

        self._collect_watched_entities()
        if self._watched:
            self._state_unsub = async_track_state_change_event(
                self.hass,
                list(self._watched),
                self._handle_state_event
            )

        await self.publish_ui()
        await self._register_services()

    async def stop(self):
        """Stop everything."""
        if self._unsub_action:
            self._unsub_action()
        if self._state_unsub:
            self._state_unsub()

    async def publish_ui(self):
        """Push configuration to the panel."""
        config_to_publish = copy.deepcopy(self.devices_config)

        # Auto-fill options for select
        for dev in config_to_publish:
            for control in dev.get("controls", []):
                if control.get("type") == "select":
                    entity_id = control.get("entity")
                    if not entity_id:
                        continue

                    ha_entity, _ = decode_entity(entity_id)
                    state = self.hass.states.get(ha_entity)
                    if not state or not state.attributes:
                        continue

                    options_attr = None
                    domain = ha_entity.split(".")[0]

                    if domain == "input_select":
                        options_attr = "options"
                    elif domain == "fan":
                        if "preset_modes" in state.attributes:
                            options_attr = "preset_modes"
                        else:
                            options_attr = "speed_list"
                    elif domain == "media_player":
                        options_attr = "source_list"

                    if options_attr and options_attr in state.attributes:
                        options_list = state.attributes[options_attr]
                        if options_list:
                            control["options"] = "\n".join(options_list)

        await mqtt.async_publish(
            self.hass, self.topic_ui,
            json.dumps({"devices": config_to_publish}),
            retain=True
        )

    def _collect_watched_entities(self):
        """Collect entities to listen for."""
        self._watched.clear()
        for dev in self.devices_config:
            if dev.get("state_entity"):
                self._watched.add(dev["state_entity"])
            for control in dev.get("controls", []):
                ent = control.get("entity")
                if not ent:
                    continue
                ha_entity, _ = decode_entity(ent)
                self._watched.add(ha_entity)

    def _find_control(self, raw_id):
        """Find a control by its EXACT encoded id."""
        for dev in self.devices_config:
            for control in dev.get("controls", []):
                if control.get("entity") == raw_id:
                    return control
        return None

    async def _register_services(self):
        """Notify support."""
        async def _notify(call):
            payload = {
                "title": call.data.get("title", "Info"),
                "message": call.data.get("message", ""),
                "duration": call.data.get("duration", 5000),
            }
            await mqtt.async_publish(self.hass, self.topic_notify, json.dumps(payload))

        svc_name = f"notify_{self.panel_id}".replace("-", "_")
        if not self.hass.services.has_service(DOMAIN, svc_name):
            self.hass.services.async_register(DOMAIN, svc_name, _notify)

    async def _handle_action(self, payload: str):
        """Handle commands from the panel."""
        try:
            data = json.loads(payload or "{}")
            raw_id = data.get("id")
            if not raw_id:
                return

            if data.get("get_state"):
                await self._publish_entity_state(raw_id)
                return

            control = self._find_control(raw_id)
            if not control:
                return

            ha_entity, attribute = decode_entity(raw_id)
            domain = ha_entity.split(".")[0]
            state = self.hass.states.get(ha_entity)

            service_data = {ATTR_ENTITY_ID: ha_entity}
            service = None

            # SWITCH
            if "state" in data:
                service = SERVICE_TURN_ON if data["state"] == "on" else SERVICE_TURN_OFF

            # SLIDER
            elif "value" in data:
                val = int(data["value"])

                if attribute:
                    if domain == "light":
                        service = SERVICE_TURN_ON
                        numeric_attrs = {
                            "brightness", "color_temp", "color_temp_kelvin",
                            "min_mireds", "max_mireds", 
                            "min_color_temp_kelvin", "max_color_temp_kelvin"
                        }
                        if attribute in numeric_attrs:
                            service_data[attribute] = val
                        elif attribute == "hs_hue":
                            cur = state.attributes.get("hs_color", [0, 100])
                            service_data["hs_color"] = [val, cur[1]]
                        elif attribute == "hs_saturation":
                            cur = state.attributes.get("hs_color", [0, 100])
                            service_data["hs_color"] = [cur[0], val]
                        elif attribute == "xy_x":
                            cur = state.attributes.get("xy_color", [0.5, 0.5])
                            service_data["xy_color"] = [val / 1000.0, cur[1]]
                        elif attribute == "xy_y":
                            cur = state.attributes.get("xy_color", [0.5, 0.5])
                            service_data["xy_color"] = [cur[0], val / 1000.0]
                        else:
                            service_data[attribute] = val
                    elif domain == "climate":
                        service = "set_temperature"
                        service_data["temperature"] = val
                    elif domain == "fan":
                        service = "set_percentage"
                        service_data["percentage"] = val
                    elif domain == "media_player":
                        service = "volume_set"
                        service_data["volume_level"] = val / 100.0
                    else:
                        service = "set_value"
                        service_data["value"] = val
                else:
                    if domain == "light":
                        service = SERVICE_TURN_ON
                        service_data[ATTR_BRIGHTNESS] = val
                    elif domain == "fan":
                        service = "set_percentage"
                        service_data["percentage"] = val
                    elif domain == "media_player":
                        service = "volume_set"
                        service_data["volume_level"] = val / 100.0
                    elif domain == "climate":
                        service = "set_temperature"
                        service_data["temperature"] = val
                    else:
                        service = "set_value"
                        service_data["value"] = val

            # COLOR
            elif "rgb_color" in data:
                service = SERVICE_TURN_ON
                service_data[ATTR_RGB_COLOR] = data["rgb_color"]

            # SELECT
            elif "option" in data:
                if domain == "media_player":
                    service = "select_source"
                    service_data["source"] = data["option"]
                else:
                    service = "select_option"
                    service_data["option"] = data["option"]

            if service:
                await self.hass.services.async_call(domain, service, service_data)

        except Exception as e:
            _LOGGER.exception("Action error: %s", e)

    def _to_rgb_list(self, rgb_tuple):
        """Ensure RGB is a simple list of integers [r,g,b]."""
        if not rgb_tuple:
            return None
        try:
            return [int(c) for c in rgb_tuple][:3]
        except:
            return None

    async def _publish_entity_state(self, raw_id: str):
        """Send ONLY ONE entity update to panel."""
        ha_entity, attribute = decode_entity(raw_id)
        state = self.hass.states.get(ha_entity)
        if not state:
            return

        payload = {"entity": raw_id}
        control = self._find_control(raw_id)

        if not control:
            # device state entity
            for dev in self.devices_config:
                if dev.get("state_entity") == raw_id:
                    payload["state"] = state.state
                    await mqtt.async_publish(self.hass, self.topic_state, json.dumps(payload))
                    return
            return

        ctype = control.get("type")
        domain = ha_entity.split(".")[0]

        if ctype == "switch":
            payload["state"] = state.state

        elif ctype == "slider":
            if attribute:
                val = state.attributes.get(attribute)
            elif domain == "light":
                val = state.attributes.get(ATTR_BRIGHTNESS)
            else:
                val = state.state

            try:
                payload["value"] = int(float(val))
            except:
                payload["value"] = 0

        elif ctype == "color":
            # Default to [0, 0, 0] (Black/Off)
            final_rgb = [0, 0, 0]

            # Only calculate color if the light is actually ON
            if state.state == "on":
                attrs = state.attributes
                
                # 1. Try Direct RGB (Best)
                if ATTR_RGB_COLOR in attrs:
                    final_rgb = self._to_rgb_list(attrs[ATTR_RGB_COLOR])
                
                # 2. Try RGBWW / RGBW (Strip extra white channels)
                elif "rgbww_color" in attrs:
                    final_rgb = self._to_rgb_list(attrs["rgbww_color"])
                elif "rgbw_color" in attrs:
                    final_rgb = self._to_rgb_list(attrs["rgbw_color"])

                # 3. Try HS Color (Convert to RGB)
                elif "hs_color" in attrs:
                    try:
                        h, s = attrs["hs_color"]
                        # Convert HS to RGB
                        rgb_tuple = color_util.color_hs_to_RGB(h, s)
                        final_rgb = self._to_rgb_list(rgb_tuple)
                    except Exception:
                        pass
                
                # 4. Try XY Color (Convert to RGB - common for Zigbee/Hue)
                elif "xy_color" in attrs:
                    try:
                        x, y = attrs["xy_color"]
                        # Convert XY to RGB (assuming max brightness for color wheel)
                        rgb_tuple = color_util.color_xy_to_RGB(x, y, 255)
                        final_rgb = self._to_rgb_list(rgb_tuple)
                    except Exception:
                        pass

            payload["rgb_color"] = final_rgb or [0, 0, 0]

        elif ctype == "select":
            payload["option"] = state.state

        await mqtt.async_publish(self.hass, self.topic_state, json.dumps(payload))

    @callback
    def _handle_state_event(self, event):
        """HA entity changed → push update."""
        new = event.data.get("new_state")
        if not new:
            return

        entity_id = event.data["entity_id"]

        for dev in self.devices_config:
            for control in dev.get("controls", []):
                ent = control.get("entity")
                if not ent:
                    continue

                ha_entity, _ = decode_entity(ent)
                if ha_entity == entity_id:
                    self.hass.async_create_task(
                        self._publish_entity_state(ent)
                    )