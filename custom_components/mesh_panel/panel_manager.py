import json
import logging
import yaml

from homeassistant.core import HomeAssistant, callback
from homeassistant.components import mqtt
from homeassistant.const import (
    SERVICE_TURN_ON, SERVICE_TURN_OFF, ATTR_ENTITY_ID, ATTR_BRIGHTNESS, ATTR_RGB_COLOR
)
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_PANEL_ID,
    TOPIC_BASE_FMT, TOPIC_UI_FMT, TOPIC_STATE_FMT, TOPIC_ACTION_FMT, TOPIC_NOTIFY_FMT,
    CONF_MANUAL_CONFIG
)

_LOGGER = logging.getLogger(__name__)

class MeshPanelController:
    def __init__(self, hass: HomeAssistant, panel_id: str, devices_config: list):
        self.hass = hass
        self.panel_id = panel_id
        self.topic_base = TOPIC_BASE_FMT.format(panel_id=panel_id)
        self.topic_ui = TOPIC_UI_FMT.format(panel_id=panel_id)
        self.topic_state = TOPIC_STATE_FMT.format(panel_id=panel_id)
        self.topic_action = TOPIC_ACTION_FMT.format(panel_id=panel_id)
        self.topic_notify = TOPIC_NOTIFY_FMT.format(panel_id=panel_id)
        self.devices_config = devices_config or []
        self._unsub_action = None
        self._state_unsub = None
        self._watched = set()

    async def start(self):
        # Subscribe to action
        async def _on_action(msg):
            await self._handle_action(msg.payload)

        self._unsub_action = await mqtt.async_subscribe(self.hass, self.topic_action, _on_action)

        # Watch entities from config
        self._collect_watched_entities()
        if self._watched:
            self._state_unsub = async_track_state_change_event(
                self.hass, list(self._watched), self._handle_state_event
            )

        # Publish current UI (retain)
        await self.publish_ui()

        # Register notify service (scoped by panel)
        async def _notify(call):
            payload = {
                "title": call.data.get("title", "MESH Alert"),
                "message": call.data.get("message", ""),
                "duration": call.data.get("duration", 5000),
            }
            await mqtt.async_publish(self.hass, self.topic_notify, json.dumps(payload))

        svc_name = f"notify_{self.panel_id}".replace("-", "_")
        if not self.hass.services.has_service("mesh_panel", svc_name):
            self.hass.services.async_register("mesh_panel", svc_name, _notify)

    async def publish_ui(self):
        payload = {"devices": self.devices_config}
        await mqtt.async_publish(self.hass, self.topic_ui, json.dumps(payload), retain=True)

    def _collect_watched_entities(self):
        self._watched.clear()
        for dev in self.devices_config:
            se = dev.get("state_entity")
            if se:
                self._watched.add(se)
            for c in dev.get("controls", []):
                ent = c.get("entity")
                if ent:
                    self._watched.add(ent)

    async def _handle_action(self, payload: str):
        try:
            data = json.loads(payload or "{}")
            entity_id = data.get("id")
            if not entity_id:
                return

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
                elif domain == "fan":
                    service = "set_percentage"
                    service_data["percentage"] = val
                elif domain == "media_player":
                    service = "volume_set"
                    service_data["volume_level"] = val / 100.0 if val > 1 else val
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
                    service_data = {"entity_id": entity_id, "source": data["option"]}

            if service:
                await self.hass.services.async_call(domain, service, service_data, blocking=False)

        except Exception as e:
            _LOGGER.error("MESH action error: %s", e)

    @callback
    async def _handle_state_event(self, event):
        s = event.data.get("new_state")
        if not s:
            return

        entity_id = event.data["entity_id"]
        attrs = s.attributes

        # Send on/off string state
        await mqtt.async_publish(self.hass, self.topic_state, json.dumps({
            "entity": entity_id, "state": s.state
        }))

        # Brightness
        if "brightness" in attrs:
            await mqtt.async_publish(self.hass, self.topic_state, json.dumps({
                "entity": entity_id, "value": int(attrs["brightness"])
            }))

        # RGB
        if "rgb_color" in attrs:
            await mqtt.async_publish(self.hass, self.topic_state, json.dumps({
                "entity": entity_id, "rgb_color": list(attrs["rgb_color"])
            }))

        # Media player volume
        if "volume_level" in attrs:
            await mqtt.async_publish(self.hass, self.topic_state, json.dumps({
                "entity": entity_id, "value": int(attrs["volume_level"] * 100)
            }))