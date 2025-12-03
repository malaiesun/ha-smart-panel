"""Manages a MESH panel."""
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
from .const import *

_LOGGER = logging.getLogger(__name__)

class MeshPanelController:
    """Controller for a MESH panel."""

    def __init__(self, hass: HomeAssistant, panel_id: str, devices_data: list):
        """Initialize the controller."""
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

        self._unsub_action = await mqtt.async_subscribe(self.hass, self.topic_action, _on_action)

        self._collect_watched_entities()
        if self._watched:
            self._state_unsub = async_track_state_change_event(
                self.hass, list(self._watched), self._handle_state_event
            )

        await self.publish_ui()
        await self._register_services()

    async def stop(self):
        """Stop the controller."""
        if self._unsub_action:
            self._unsub_action()
        if self._state_unsub:
            self._state_unsub()

    async def publish_ui(self):
        """Publish the UI configuration to the panel."""
        config_to_publish = copy.deepcopy(self.devices_config)

        for dev in config_to_publish:
            for control in dev.get("controls", []):
                if control.get("type") == "select":
                    entity_id = control.get("entity")
                    if not entity_id: continue
                    
                    state = self.hass.states.get(entity_id)
                    if not state or not state.attributes: continue

                    options_attr = None
                    domain = entity_id.split(".")[0]
                    if domain == "input_select":
                        options_attr = "options"
                    elif domain == "fan":
                        options_attr = "preset_modes" if "preset_modes" in state.attributes else "speed_list"
                    elif domain == "media_player":
                        options_attr = "source_list"
                    
                    if options_attr and options_attr in state.attributes:
                        options_list = state.attributes[options_attr]
                        if options_list:
                            control["options"] = "\n".join(options_list)

        payload = {"devices": config_to_publish}
        await mqtt.async_publish(self.hass, self.topic_ui, json.dumps(payload), retain=True)

    def _collect_watched_entities(self):
        """Collect all entities to watch for state changes."""
        self._watched.clear()
        for dev in self.devices_config:
            if dev.get("state_entity"):
                self._watched.add(dev["state_entity"])
            for control in dev.get("controls", []):
                if control.get("entity"):
                    self._watched.add(control["entity"])

    def _find_control(self, entity_id):
        """Find a control by its entity ID."""
        for dev in self.devices_config:
            for control in dev.get("controls", []):
                if control.get("entity") == entity_id:
                    return control
        return None

    async def _register_services(self):
        """Register the notify service."""
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
        """Handle an action from the panel."""
        try:
            data = json.loads(payload or "{}")
            entity_id = data.get("id")
            if not entity_id: return

            if data.get("get_state"):
                await self._publish_entity_state(entity_id)
                return

            control = self._find_control(entity_id)
            if not control: return

            domain = entity_id.split(".")[0]
            service_data = {ATTR_ENTITY_ID: entity_id}
            service = None

            if "state" in data:
                service = SERVICE_TURN_ON if data["state"] == "on" else SERVICE_TURN_OFF
            elif "value" in data:
                val = int(data["value"])
                attribute = control.get("attribute")
                if attribute and attribute != "state":
                    service = f"set_{attribute}"
                    service_data[attribute] = val
                elif domain == "light":
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
            elif "rgb_color" in data:
                service = SERVICE_TURN_ON
                service_data[ATTR_RGB_COLOR] = data["rgb_color"]
            elif "option" in data:
                service = "select_option"
                service_data["option"] = data["option"]
                if domain == "media_player":
                    service = "select_source"
                    service_data["source"] = data["option"]

            if service:
                await self.hass.services.async_call(domain, service, service_data)

        except Exception as e:
            _LOGGER.error("Action error: %s", e)

    async def _publish_entity_state(self, entity_id: str):
        """Get the current state of an entity and publish it to the panel."""
        state = self.hass.states.get(entity_id)
        if not state:
            return

        payload = {"entity": entity_id}
        found = False

        control = self._find_control(entity_id)
        if control:
            found = True
            ctype = control.get("type")
            domain = entity_id.split(".")[0]

            if ctype == "switch":
                payload["state"] = state.state
            elif ctype == "slider":
                attribute = control.get("attribute")
                val = None
                if attribute: 
                    val = state.attributes.get(attribute)
                elif domain == "light":
                    val = state.attributes.get(ATTR_BRIGHTNESS)
                else:
                    val = state.state
                
                if val is not None:
                    try:
                        payload["value"] = int(float(val))
                    except (ValueError, TypeError):
                        _LOGGER.debug(f"Could not convert slider value '{val}' to number for {entity_id}")
                elif domain == 'light': # If brightness is None, light is off
                    payload['value'] = 0

            elif ctype == "color":
                rgb = state.attributes.get(ATTR_RGB_COLOR)
                if rgb:
                    payload['rgb_color'] = rgb
                else:
                    payload['rgb_color'] = [0, 0, 0] # Default to black/off
            elif ctype == "select":
                payload["option"] = state.state
        
        else: # Is it a primary state_entity for a device?
            for dev in self.devices_config:
                if dev.get("state_entity") == entity_id:
                    payload["state"] = state.state
                    found = True
                    break
        
        if found:
            self.hass.async_create_task(
                mqtt.async_publish(self.hass, self.topic_state, json.dumps(payload))
            )

    @callback
    def _handle_state_event(self, event):
        """Handle a state change event."""
        if not event.data.get("new_state"):
            return
            
        entity_id = event.data["entity_id"]
        self.hass.async_create_task(self._publish_entity_state(entity_id))
