import voluptuous as vol
import requests
from homeassistant import config_entries
from .const import DOMAIN, CONF_TOPIC, DEFAULT_TOPIC

class MeshPanelConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Step 1: Ask for Panel Details"""
        errors = {}
        
        if user_input is not None:
            ip_address = user_input["ip_address"]
            panel_id = user_input["panel_id"]
            
            # 1. Try to push config to ESP32
            try:
                # Get HA MQTT Info (Auto-discovery)
                # Note: In a real custom component, you'd pull this from the MQTT entry.
                # For simplicity, we ask the user or hardcode defaults, 
                # OR we assume the user fills it in.
                
                payload = {
                    "mqtt_server": user_input["mqtt_host"],
                    "mqtt_port": 1883,
                    "mqtt_user": user_input["mqtt_user"],
                    "mqtt_pass": user_input["mqtt_pass"],
                    "panel_id": panel_id
                }
                
                # Send to ESP32
                url = f"http://{ip_address}/config"
                await self.hass.async_add_executor_job(
                    lambda: requests.post(url, json=payload, timeout=5)
                )
                
                # Success! Create Entry
                return self.async_create_entry(
                    title=panel_id, 
                    data={"mqtt_topic": f"mesh/{panel_id}"}
                )
                
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("ip_address"): str, # User enters IP shown on screen
                vol.Required("panel_id", default="panel_01"): str,
                vol.Required("mqtt_host"): str,
                vol.Optional("mqtt_user"): str,
                vol.Optional("mqtt_pass"): str,
            }),
            errors=errors
        )