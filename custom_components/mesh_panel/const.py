DOMAIN = "mesh_panel"

CONF_PANEL_ID = "panel_id"
CONF_MANUAL_CONFIG = "manual_config"  # YAML string in options

TOPIC_ANNOUNCE = "smartpanel/announce"
TOPIC_BASE_FMT = "smartpanel/{panel_id}"
TOPIC_UI_FMT = "smartpanel/{panel_id}/ui"
TOPIC_STATE_FMT = "smartpanel/{panel_id}/state"
TOPIC_ACTION_FMT = "smartpanel/{panel_id}/action"
TOPIC_NOTIFY_FMT = "smartpanel/{panel_id}/notify"