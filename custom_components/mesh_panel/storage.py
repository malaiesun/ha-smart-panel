"""Storage for MESH Panel devices."""
from homeassistant.helpers.storage import Store
from .const import DOMAIN, CONF_DEVICES

class DevicesStore:
    """Class to handle the storage of MESH Panel devices."""

    def __init__(self, hass, panel_id):
        """Initialize the devices store."""
        self._hass = hass
        self._store = Store(hass, 1, f"{DOMAIN}_{panel_id}_devices")

    async def async_load_devices(self):
        """Load the devices."""
        data = await self._store.async_load()
        return data.get(CONF_DEVICES, []) if data else []

    async def async_save_devices(self, devices):
        """Save the devices."""
        await self._store.async_save({CONF_DEVICES: devices})
