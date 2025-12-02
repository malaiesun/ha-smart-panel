import json
import logging
from homeassistant.core import HomeAssistant, callback
from homeassistant.components import mqtt
from homeassistant.const import (
    SERVICE_TURN_ON, SERVICE_TURN_OFF, ATTR_ENTITY_ID, ATTR_BRIGHTNESS, ATTR_RGB_COLOR
)
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_PANEL_ID,
    TOPIC_BASE_FMT, TOPIC_UI_FMT, TOPIC_STATE_FMT, TOPIC_ACTION_FMT, TOPIC_NOTIFY_FMT,
    CONF_DEVICES
)

_LOGGER = logging.getLogger(__name__)

class MeshPanelController:
    def __init__(self, hass: HomeAssistant, panel_id: str, devices_data: list):
        self.hass = hass
        self.panel_id = panel_id
        # Topic Setup
        self.topic_ui = TOPIC_UI_FMT.format(panel_id=panel_id)
        self.topic_state = TOPIC_STATE_FMT.format(panel_id=panel_id)
        self.topic_action = TOPIC_ACTION_FMT.format(panel_id=panel_id)
        self.topic_notify = TOPIC_NOTIFY_FMT.format(panel_id=panel_id)
        
        # Convert Options Flow format to C++ Format
        self.devices_config = self._convert_to_cpp_format(devices_data)
        
        self._unsub_action = None
        self._state_unsub = None
        self._watched = set()

    def _convert_to_cpp_format(self, raw_devices):
        """
        Transforms the flat list from Options Flow into the nested structure 
        the C++ Firmware expects.
        """
        final_list = []
        for d in raw_devices:
            # We treat every item as a Device with 1 Control for simplicity in the UI
            device_obj = {
                "name": d.get("name", "Unknown"),
                "icon": d.get("icon", ""),
                "state_entity": d.get("entity", ""),
                "controls": [
                    {
                        "label": d.get("name"), # Use Device name as label
                        "type": d.get("type"),
                        "entity": d.get("entity"),
                        "min": d.get("min", 0),
                        "max": d.get("max", 100),
                        "step": 1,
                        "options": "" # Dropdown options not implemented in simplified UI yet
                    }
                ]
            }
            final_list.append(device_obj)
        return final_list

    async def start(self):
        # 1. Subscribe to actions (Touch on Screen)
        async def _on_action(msg):
            await self._handle_action(msg.payload)

        self._unsub_action = await mqtt.async_subscribe(self.hass, self.topic_action, _on_action)

        # 2. Watch entities for State Changes (Push Updates)
        self._collect_watched_entities()
        if self._watched:
            # THIS IS THE "INSTANT UPDATE" MECHANISM
            # Home Assistant triggers this callback immediately when state changes
            self._state_unsub = async_track_state_change_event(
                self.hass, list(self._watched), self._handle_state_event
            )

        # 3. Publish Layout to Screen
        await self.publish_ui()

        # 4. Register Notify Service
        await self._register_services()

    async def publish_ui(self):
        payload = {"devices": self.devices_config}
        await mqtt.async_publish(self.hass, self.topic_ui, json.dumps(payload), retain=True)

    def _collect_watched_entities(self):
        self._watched.clear()
        for dev in self.devices_config:
            if dev.get("state_entity"):
                self._watched.add(dev["state_entity"])

    async def _register_services(self):
        async def _notify(call):
            payload = {
                "title": call.data.get("title", "Info"),
                "message": call.data.get("message", ""),
                "duration": call.data.get("duration", 5000),
            }
            await mqtt.async_publish(self.hass, self.topic_notify, json.dumps(payload))

        svc_name = f"notify_{self.panel_id}".replace("-", "_")
        if not self.hass.services.has_service("mesh_panel", svc_name):
            self.hass.services.async_register("mesh_panel", svc_name, _notify)

    async def _handle_action(self, payload: str):
        """Handle incoming MQTT messages from the Panel (Touch events)"""
        try:
            data = json.loads(payload or "{}")
            entity_id = data.get("id")
            if not entity_id: return

            domain = entity_id.split(".")[0]
            service_data = {ATTR_ENTITY_ID: entity_id}
            service = None

            if "state" in data:
                service = SERVICE_TURN_ON if data["state"] == "on" else SERVICE_TURN_OFF
            elif "value" in data:
                val = int(data["value"])
                if domain == "light":
                    service = SERVICE_TURN_ON
                    service_data[ATTR_BRIGHTNESS] = val
                elif domain == "media_player":
                    service = "volume_set"
                    service_data["volume_level"] = val / 100.0
                else:
                    service = "set_value"
                    service_data["value"] = val
            
            if service:
                await self.hass.services.async_call(domain, service, service_data)

        except Exception as e:
            _LOGGER.error("Action Error: %s", e)

    @callback
    async def _handle_state_event(self, event):
        """
        Triggered INSTANTLY when a device state changes in Home Assistant.
        This sends the update to the panel immediately.
        """
        s = event.data.get("new_state")
        if not s: return

        entity_id = event.data["entity_id"]
        attrs = s.attributes
        
        # Prepare payload
        payload = {"entity": entity_id, "state": s.state}
        
        # Enriched data for sliders/colors
        if "brightness" in attrs:
            payload["value"] = attrs["brightness"]
        if "volume_level" in attrs:
            payload["value"] = int(attrs["volume_level"] * 100)
        if "rgb_color" in attrs:
            payload["rgb_color"] = attrs["rgb_color"]

        await mqtt.async_publish(self.hass, self.topic_state, json.dumps(payload))