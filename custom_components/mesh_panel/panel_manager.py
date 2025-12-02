import logging
import json
import yaml
from homeassistant.core import HomeAssistant, callback, Context
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.components import mqtt

# --- FIXED IMPORTS BELOW ---
from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_RGB_COLOR
from homeassistant.const import (
    SERVICE_TURN_ON, 
    SERVICE_TURN_OFF, 
    STATE_ON, 
    STATE_OFF, 
    ATTR_ENTITY_ID
)
# ---------------------------

from .const import CONF_PANEL_ID, CONF_LAYOUT, DEFAULT_LAYOUT

_LOGGER = logging.getLogger(__name__)

class MeshPanelManager:
    def __init__(self, hass: HomeAssistant, entry):
        self.hass = hass
        self.entry = entry
        self.panel_id = entry.data[CONF_PANEL_ID]
        self.layout_yaml = entry.options.get(CONF_LAYOUT, DEFAULT_LAYOUT)
        self.entities_to_watch = set()
        self.remove_listeners = []
        self.mqtt_sub = None

    async def async_setup(self):
        """Initialize connection and listeners."""
        _LOGGER.info(f"Setting up Mesh Panel: {self.panel_id}")
        
        # 1. Parse Config and Extract Entities
        try:
            config_data = yaml.safe_load(self.layout_yaml)
            self._parse_entities(config_data)
        except Exception as e:
            _LOGGER.error(f"Failed to parse layout YAML: {e}")
            return

        # 2. Subscribe to Panel Actions (MQTT)
        topic = f"smartpanel/{self.panel_id}/action"
        self.mqtt_sub = await mqtt.async_subscribe(
            self.hass, topic, self._handle_mqtt_action
        )

        # 3. Listen to HA State Changes
        if self.entities_to_watch:
            self.remove_listeners.append(
                async_track_state_change_event(
                    self.hass, list(self.entities_to_watch), self._handle_ha_state_change
                )
            )

        # 4. Push initial UI Configuration to Panel
        await self._send_ui_config(config_data)

        # 5. Push initial states of all entities
        for entity_id in self.entities_to_watch:
            state = self.hass.states.get(entity_id)
            if state:
                await self._push_state_update(entity_id, state)

    async def async_unload(self):
        """Clean up."""
        if self.mqtt_sub:
            self.mqtt_sub() # Unsubscribe MQTT
        for remove in self.remove_listeners:
            remove()

    def _parse_entities(self, config_data):
        """Extract all entity_ids from the config to watch them."""
        devices = config_data.get("devices", [])
        for dev in devices:
            if "state_entity" in dev:
                self.entities_to_watch.add(dev["state_entity"])
            for ctrl in dev.get("controls", []):
                if "entity" in ctrl:
                    self.entities_to_watch.add(ctrl["entity"])

    async def _send_ui_config(self, config_data):
        """Send the JSON UI definition to the panel."""
        topic = f"smartpanel/{self.panel_id}/ui"
        payload = json.dumps(config_data)
        await mqtt.async_publish(self.hass, topic, payload, retain=True)

    async def _handle_mqtt_action(self, msg):
        """Handle incoming actions from the panel."""
        try:
            payload = json.loads(msg.payload)
            entity_id = payload.get("id")
            
            if not entity_id:
                return

            domain = entity_id.split(".")[0]
            service_data = {ATTR_ENTITY_ID: entity_id}
            service = None

            # === LOGIC MAPPING C++ PAYLOAD TO HA SERVICE ===
            
            # Case 1: Switch/Toggle ("state": "on" or "off")
            if "state" in payload:
                if payload["state"] == "on":
                    service = SERVICE_TURN_ON
                else:
                    service = SERVICE_TURN_OFF
            
            # Case 2: Slider Value ("value": 123)
            elif "value" in payload:
                val = int(payload["value"])
                if domain == "light":
                    service = SERVICE_TURN_ON
                    service_data[ATTR_BRIGHTNESS] = val
                elif domain == "cover":
                    service = "set_cover_position"
                    service_data["position"] = val
                elif domain == "number" or domain == "input_number":
                    service = "set_value"
                    service_data["value"] = val
                elif domain == "fan":
                    service = SERVICE_TURN_ON
                    service_data["percentage"] = val

            # Case 3: RGB Color ("rgb_color": [255, 0, 0])
            elif "rgb_color" in payload:
                if domain == "light":
                    service = SERVICE_TURN_ON
                    service_data[ATTR_RGB_COLOR] = payload["rgb_color"]

            # Case 4: Dropdown/Select ("option": "Mode A")
            elif "option" in payload:
                if domain == "input_select" or domain == "select":
                    service = "select_option"
                    service_data["option"] = payload["option"]

            # Execute
            if service:
                await self.hass.services.async_call(
                    domain, service, service_data, context=Context()
                )

        except Exception as e:
            _LOGGER.error(f"Error handling MQTT action: {e}")

    @callback
    async def _handle_ha_state_change(self, event):
        """When an HA entity changes, update the panel."""
        entity_id = event.data["entity_id"]
        new_state = event.data.get("new_state")
        if new_state:
            await self._push_state_update(entity_id, new_state)

    async def _push_state_update(self, entity_id, state_obj):
        """Format HA state to Panel JSON protocol."""
        topic = f"smartpanel/{self.panel_id}/state"
        
        # Base payload
        payload = {
            "entity": entity_id,
            "state": state_obj.state
        }

        # Add Brightness / Value
        if ATTR_BRIGHTNESS in state_obj.attributes:
            payload["value"] = state_obj.attributes[ATTR_BRIGHTNESS]
        elif "current_position" in state_obj.attributes:
             payload["value"] = state_obj.attributes["current_position"]
        elif state_obj.domain in ["number", "input_number", "sensor"]:
            try:
                payload["value"] = float(state_obj.state)
            except:
                pass

        # Add Color
        if ATTR_RGB_COLOR in state_obj.attributes:
            payload["rgb_color"] = state_obj.attributes[ATTR_RGB_COLOR]

        await mqtt.async_publish(self.hass, topic, json.dumps(payload))