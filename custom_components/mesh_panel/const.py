"""Constants for the MESH Smart Home Panel integration."""

DOMAIN = "mesh_panel"

# Config entry keys
CONF_PANEL_ID = "panel_id"
CONF_DEVICES = "devices"

# Device keys
CONF_NAME = "name"
CONF_ICON = "icon"
CONF_CONTROLS = "controls"
CONF_ID = "id"

# Control keys
CONF_LABEL = "label"
CONF_TYPE = "type"
CONF_ENTITY = "entity"
CONF_MIN = "min"
CONF_MAX = "max"
CONF_STEP = "step"
CONF_OPTIONS = "options"

# Control types
CONTROL_TYPES = [
    {"value": "switch", "label": "Switch (On/Off)"},
    {"value": "slider", "label": "Slider (Brightness/Volume)"},
    {"value": "color", "label": "Color Wheel"},
    {"value": "select", "label": "Dropdown Selection"},
]

# MQTT Topics
TOPIC_ANNOUNCE = "smartpanel/announce"
TOPIC_UI_FMT = "smartpanel/{panel_id}/ui"
TOPIC_STATE_FMT = "smartpanel/{panel_id}/state"
TOPIC_ACTION_FMT = "smartpanel/{panel_id}/action"
TOPIC_NOTIFY_FMT = "smartpanel/{panel_id}/notify"
