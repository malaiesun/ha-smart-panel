# ESP32 Smart Panel - Home Assistant Integration

A custom integration to control the **CrowPanel ESP32 HMI Display**.
It allows you to define a "Virtual Device Panel" using YAML inside Home Assistant, which is then rendered dynamically on the screen via MQTT.

## Features
* **Auto-Discovery:** No coding on the ESP32 required after flashing.
* **Live Updates:** Two-way synchronization. Change a slider on the panel, HA updates. Change HA, the panel updates.
* **Supported Controls:** Switches, Sliders (Brightness/Volume/Temp), Dropdowns (Input Select/Sources), and RGB Color Pickers.
* **Notifications:** Send "Toast" popups to the screen via Automations.

## Installation (HACS)
1.  Go to **HACS > Integrations**.
2.  Click the 3 dots > **Custom Repositories**.
3.  Add this repository URL.
4.  Category: **Integration**.
5.  Click **Download** and restart Home Assistant.

## Configuration
1.  Go to **Settings > Devices & Services > Add Integration**.
2.  Search for **ESP32 Smart Panel**.
3.  Enter your **MQTT Topic Base** (default: `smartpanel/panel_01`).
4.  **Device Setup:** Paste your YAML configuration.

### Example Configuration YAML
Paste this into the setup window:

```yaml
- name: Gaming Setup
  icon: mdi:controller
  state_entity: light.gaming_pc
  controls:
    - label: Power
      type: switch
      entity: light.gaming_pc
    - label: RGB Color
      type: color
      entity: light.gaming_pc
    - label: Volume
      type: slider
      entity: number.pc_volume
      min: 0
      max: 100
      step: 2

- name: Master AC
  icon: mdi:air-conditioner
  state_entity: climate.master
  controls:
    - label: AC Power
      type: switch
      entity: climate.master
    - label: Temp
      type: slider
      entity: number.target_temp
      min: 16
      max: 30
      step: 1
    - label: Mode
      type: select
      entity: select.ac_mode
      options: "Cool\nHeat\nDry"