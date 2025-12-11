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

# Button Grid keys
CONF_GRID = "grid"
CONF_GRID_LABEL = "grid_label"
CONF_GRID_BG = "grid_bg"
CONF_GRID_RADIUS = "grid_radius"
CONF_GRID_PADDING = "grid_padding"
CONF_ROWS = "rows"
CONF_ROW_HEIGHT = "row_height"
CONF_ROW_BG = "row_bg"
CONF_ROW_RADIUS = "row_radius"
CONF_ROW_PADDING = "row_padding"
CONF_BUTTONS = "buttons"
CONF_BUTTON_WIDTH = "width"
CONF_ACTION = "action"
CONF_LABEL_FORMULA = "label_formula"
CONF_BG_COLOR_FORMULA = "bg_color_formula"
CONF_TEXT_COLOR_FORMULA = "text_color_formula"

# Control types
CONTROL_TYPES = [
    {"value": "button_grid", "label": "Button Grid"},
    {"value": "switch", "label": "Switch (On/Off)"},
    {"value": "slider", "label": "Slider (Brightness/Volume)"},
    {"value": "color", "label": "Color Wheel"},
    {"value": "select", "label": "Dropdown Selection"},
    {"value": "text", "label": "Text Display"},
    {"value": "time", "label": "Time Input"},
]

# MQTT Topics
TOPIC_ANNOUNCE = "smartpanel/announce"
TOPIC_UI_FMT = "smartpanel/{panel_id}/ui"
TOPIC_STATE_FMT = "smartpanel/{panel_id}/state"
TOPIC_ACTION_FMT = "smartpanel/{panel_id}/action"
TOPIC_NOTIFY_FMT = "smartpanel/{panel_id}/notify"

SIGNAL_MQTT_PAYLOAD = f"{DOMAIN}.mqtt_payload"
