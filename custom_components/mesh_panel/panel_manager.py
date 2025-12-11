"""Manages a MESH panel with proper entity/attribute decoding and one-by-one live update syncing."""
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
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
import homeassistant.util.color as color_util

from .const import (
    DOMAIN,
    CONF_DEVICES,
    CONF_ID, CONF_NAME, CONF_ICON, CONF_CONTROLS,
    CONF_LABEL, CONF_TYPE, CONF_ENTITY,
    CONF_MIN, CONF_MAX, CONF_STEP, CONF_OPTIONS,
    CONF_GRID, CONF_ROWS, CONF_BUTTONS, CONF_ACTION,
    CONTROL_TYPES,
    TOPIC_ANNOUNCE, TOPIC_UI_FMT, TOPIC_STATE_FMT,
    TOPIC_ACTION_FMT, TOPIC_NOTIFY_FMT,
    SIGNAL_MQTT_PAYLOAD,
)
from .const import SIGNAL_MQTT_PAYLOAD

_LOGGER = logging.getLogger(__name__)


def decode_entity(raw: str):
    """Decode 'entity (attr)' -> ('entity', 'attr')."""
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
        """Find a control by its EXACT encoded id (config name)."""
        for dev in self.devices_config:
            for control in dev.get("controls", []):
                if control.get("entity") == raw_id:
                    return control
        return None

    def _find_button_action(self, button_id: str):
        """Find a button's action config by its ID."""
        for dev in self.devices_config:
            for control in dev.get(CONF_CONTROLS, []):
                if control.get(CONF_TYPE) == "button_grid":
                    grid = control.get(CONF_GRID, {})
                    for row in grid.get(CONF_ROWS, []):
                        for button in row.get(CONF_BUTTONS, []):
                            if button.get(CONF_ID) == button_id:
                                return button.get(CONF_ACTION)
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
        """Handle commands FROM the panel."""
        try:
            data = json.loads(payload or "{}")
            # Panel sends "id" for commands
            raw_id = data.get("id")
            if not raw_id:
                return

            if data.get("action") == "pressed":
                action_config = self._find_button_action(raw_id)
                if action_config:
                    await self.hass.helpers.service.async_call_from_config(
                        action_config,
                    )
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

            # TIME
            elif "time" in data:
                if domain == "input_datetime":
                    service = "set_datetime"
                    service_data["time"] = data["time"]

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

    def _get_active_rgb(self, state):
        """Robustly determine RGB color from state attributes."""
        # 1. Check explicit RGB
        rgb = state.attributes.get(ATTR_RGB_COLOR)
        if rgb:
            return self._to_rgb_list(rgb)
            
        # 2. Check HS (Hue/Saturation)
        hs = state.attributes.get("hs_color")
        if hs:
            return color_util.color_hs_to_RGB(*hs)

        # 3. Check XY 
        xy = state.attributes.get("xy_color")
        if xy:
            return color_util.color_xy_to_RGB(*xy)

        # 4. Check Color Temp
        kelvin = state.attributes.get("color_temp_kelvin")
        if kelvin:
            return color_util.color_temperature_kelvin_to_rgb(kelvin)
            
        # Legacy Mireds check
        mireds = state.attributes.get("color_temp")
        if mireds:
            try:
                kelvin = int(1000000 / mireds)
                return color_util.color_temperature_kelvin_to_rgb(kelvin)
            except:
                pass

        return [255, 255, 255] if state.state == "on" else [0, 0, 0]

    async def _publish_entity_state(self, raw_id: str):
        """Send ONLY ONE entity update to panel."""
        ha_entity, attribute = decode_entity(raw_id)
        state = self.hass.states.get(ha_entity)
        if not state:
            return

        # FIXED: Send "entity" key because C++ code reads doc["entity"]
        payload = {"entity": raw_id}
        
        control = self._find_control(raw_id)

        # Handle Device State Entity (Header status)
        if not control:
            for dev in self.devices_config:
                if dev.get("state_entity") == raw_id:
                    payload["state"] = state.state
                    await mqtt.async_publish(self.hass, self.topic_state, json.dumps(payload))
                    return
            return

        ctype = control.get("type")
        domain = ha_entity.split(".")[0]

        # --- SWITCH ---
        if ctype == "switch":
            payload["state"] = state.state

        # --- SLIDER ---
        elif ctype == "slider":
            val = None
            if attribute:
                val = state.attributes.get(attribute)
            elif domain == "light":
                val = state.attributes.get(ATTR_BRIGHTNESS)
            elif domain == "media_player":
                val = (state.attributes.get("volume_level", 0) * 100)
            elif domain == "fan":
                val = state.attributes.get("percentage")
            elif domain == "climate":
                val = state.attributes.get("temperature")
            else:
                val = state.state

            try:
                payload["value"] = int(float(val))
            except (ValueError, TypeError):
                payload["value"] = 0

        # --- TIME (Formatted for C++ sscanf %d:%d) ---
        elif ctype == "time":
            try:
                val = state.state.split(":")
                if len(val) >= 2:
                    payload["time"] = f"{val[0]}:{val[1]}"
                else:
                    payload["time"] = "00:00"
            except:
                payload["time"] = "00:00"

        # --- SELECT ---
        elif ctype == "select":
            payload["option"] = state.state

        # --- TEXT ---
        elif ctype == "text":
            payload["value"] = state.state
            
        # --- SEND RGB IN SEPARATE MESSAGE ---
        if domain == "light":
            rgb = self._get_active_rgb(state)
            if rgb:
                rgb_payload = {
                    "entity": raw_id,
                    "rgb_color": rgb
                }
                await mqtt.async_publish(
                    self.hass,
                    self.topic_state,
                    json.dumps(rgb_payload)
                )
            
        payload_str = json.dumps(payload)
        async_dispatcher_send(self.hass, SIGNAL_MQTT_PAYLOAD, payload_str)
        await mqtt.async_publish(self.hass, self.topic_state, payload_str)

    @callback
    def _handle_state_event(self, event):
        """HA entity changed -> push update."""
        new_state = event.data.get("new_state")
        if not new_state:
            return

        entity_id = event.data["entity_id"]
        raw_ids_to_update = set()

        for dev in self.devices_config:
            if dev.get("state_entity") == entity_id:
                raw_ids_to_update.add(entity_id)

            for control in dev.get("controls", []):
                ent = control.get("entity")
                if not ent:
                    continue
                ha_entity, _ = decode_entity(ent)
                if ha_entity == entity_id:
                    raw_ids_to_update.add(ent)

        if raw_ids_to_update:
            for raw_id in raw_ids_to_update:
                self.hass.async_create_task(self._publish_entity_state(raw_id))