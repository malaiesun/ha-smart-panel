import json
import logging
import yaml
from homeassistant.const import (
    SERVICE_TURN_ON, SERVICE_TURN_OFF, 
    ATTR_ENTITY_ID, ATTR_BRIGHTNESS, ATTR_RGB_COLOR
)
from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN, CONF_TOPIC, CONF_MANUAL_CONFIG, DEFAULT_TOPIC

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    topic_base = entry.data.get(CONF_TOPIC, DEFAULT_TOPIC)
    
    manual_config_str = entry.options.get(CONF_MANUAL_CONFIG, "")
    devices_data = []
    if manual_config_str:
        try:
            devices_data = yaml.safe_load(manual_config_str)
        except Exception as e:
            _LOGGER.error(f"MESH Panel Config Error: {e}")

    controller = MeshPanelController(hass, topic_base, devices_data)
    await controller.start()
    
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = controller
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    return True

class MeshPanelController:
    def __init__(self, hass, topic, devices_config):
        self.hass = hass
        self.topic_ui = f"{topic}/ui"
        self.topic_state = f"{topic}/state"
        self.topic_action = f"{topic}/action"
        self.topic_notify = f"{topic}/notify"
        self.devices_config = devices_config
        self.watched_entities = set()

    async def start(self):
        await mqtt.async_subscribe(self.hass, self.topic_action, self.handle_action)
        await self.register_services()
        
        if self.devices_config:
            for dev in self.devices_config:
                if "state_entity" in dev:
                    self.watched_entities.add(dev["state_entity"])
                for c in dev.get("controls", []):
                    if "entity" in c:
                        self.watched_entities.add(c["entity"])

            if self.watched_entities:
                async_track_state_change_event(
                    self.hass, list(self.watched_entities), self.handle_ha_state_change
                )
            await self.publish_ui()

    async def publish_ui(self):
        payload = {"devices": self.devices_config}
        await mqtt.async_publish(self.hass, self.topic_ui, json.dumps(payload), retain=True)

    async def handle_action(self, msg):
        try:
            data = json.loads(msg.payload)
            entity_id = data.get("id")
            domain = entity_id.split('.')[0]
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
                    service = SERVICE_TURN_ON
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
                service_data["option"] = data["option"]
                service = "select_option"
                if domain == "media_player":
                    service = "select_source"
                    service_data["source"] = data["option"]
                    del service_data["option"]

            if service:
                await self.hass.services.async_call(domain, service, service_data)

        except Exception as e:
            _LOGGER.error(f"MESH Action Error: {e}")

    @callback
    async def handle_ha_state_change(self, event):
        entity_id = event.data["entity_id"]
        new_state = event.data["new_state"]
        if not new_state: return

        # Publish State
        await mqtt.async_publish(self.hass, self.topic_state, json.dumps({
            "entity": entity_id, "state": new_state.state
        }))

        attrs = new_state.attributes
        # Publish Attributes
        if "brightness" in attrs:
            await mqtt.async_publish(self.hass, self.topic_state, json.dumps({
                "entity": entity_id, "value": attrs["brightness"]
            }))
        if "rgb_color" in attrs:
            await mqtt.async_publish(self.hass, self.topic_state, json.dumps({
                "entity": entity_id, "rgb_color": attrs["rgb_color"]
            }))
        if "volume_level" in attrs:
            await mqtt.async_publish(self.hass, self.topic_state, json.dumps({
                "entity": entity_id, "value": int(attrs["volume_level"] * 100)
            }))

    async def register_services(self):
        async def handle_notify(call):
            payload = {
                "title": call.data.get("title", "MESH Alert"),
                "message": call.data.get("message", ""),
                "duration": call.data.get("duration", 5000)
            }
            await mqtt.async_publish(self.hass, self.topic_notify, json.dumps(payload))

        self.hass.services.async_register(DOMAIN, "send_notification", handle_notify)