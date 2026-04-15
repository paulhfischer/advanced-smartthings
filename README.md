# Advanced SmartThings

English | [Deutsch](README.de.md)

`Advanced SmartThings` is a Home Assistant custom integration for a narrow, explicit subset of Samsung/SmartThings appliance features.

This repository no longer ships a Home Assistant add-on. It now provides a native custom integration under `custom_components/advanced_smartthings/`.

## What v1 supports

Only the following device classes and features are intentionally supported:

- Oven
  - remote control enabled as a read-only `binary_sensor`
  - current program / off state as a read-only `sensor`
  - current timer as a read-only `sensor`
  - current target temperature as a read-only `sensor`
  - current temperature as a read-only `sensor`
  - running state as a read-only `binary_sensor`
  - mode/program input as a writable `select`
  - timer duration as a writable `number`
  - temperature setpoint as a writable `number`
  - running control as a writable `switch`
  - lamp as a writable `switch`
- Refrigerator
  - refrigerator door open as a read-only `binary_sensor`
  - freezer door open as a read-only `binary_sensor`
  - refrigerator temperature setpoint as a writable `number`
  - freezer temperature setpoint as a writable `number`
  - current power consumption as a read-only `sensor`
  - water filter usage as a read-only `sensor`
- Cooktop / hob
  - cooktop active state as a read-only `binary_sensor`

Everything else is intentionally ignored for now.

## What is explicitly unsupported

- Generic SmartThings capability passthrough
- Raw command execution from Home Assistant
- Hood features, per-burner cooktop control, and cooktop write control
- Fridge camera, icemaker, vacation mode, power cool/freeze, and other advanced Samsung-only features
- Appliance classes outside the supported oven / refrigerator / cooktop scope

## Language support

Home Assistant user-facing strings are prepared for:

- English
- German

This includes config-flow labels, abort/error text, options-flow labels, and entity names.

Oven mode labels are rendered in English or German based on the Home Assistant system language when a known mapping exists. Unknown SmartThings mode names fall back to a readable label.

## Installation

### HACS custom repository

1. Open HACS.
2. Add this repository as a custom repository of type `Integration`.
3. Search for `Advanced SmartThings`.
4. Install it.
5. Restart Home Assistant.

### Manual installation

1. Copy `custom_components/advanced_smartthings` into your Home Assistant configuration directory:

   `config/custom_components/advanced_smartthings`

2. Restart Home Assistant.

## SmartThings OAuth setup

Create a SmartThings OAuth-In app and use your Home Assistant external URL as the redirect URI.

Required SmartThings settings:

- Redirect URI:
  - `https://YOUR_HOME_ASSISTANT_EXTERNAL_URL/auth/external/callback`
- Scopes:
  - `r:devices:*`
  - `x:devices:*`
  - `r:locations:*`

Notes:

- The Home Assistant external URL must be reachable by the browser you use for setup.
- The redirect URI must exactly match the URL registered in SmartThings.
- The integration setup dialog shows the exact callback URL that your Home Assistant instance is using.
- Client ID and client secret are entered during the Home Assistant config flow.

## Home Assistant setup

1. In Home Assistant, go to `Settings > Devices & services > Add integration`.
2. Add `Advanced SmartThings`.
3. Enter the SmartThings client ID and client secret.
4. Complete the SmartThings authorization step in the browser.
5. Select the supported devices you want Home Assistant to include.
6. Finish the flow.

## Mapping notes

- Oven mode uses `samsungce.ovenMode`.
- Oven program state is exposed as a read-only sensor and shows translated values such as `Off`, `Bake`, or `Keep Warm`.
- Oven timer is exposed both as a read-only status sensor and as a writable duration `number` in minutes.
- Oven target temperature is exposed both as a read-only status sensor and as a writable `number`.
- Oven current temperature is exposed as a read-only sensor.
- Oven running state is exposed both as a read-only binary sensor and as a writable running switch that internally maps to SmartThings start/stop commands.
- Oven remote-control readiness uses `remoteControlStatus.remoteControlEnabled`.
- Oven lamp uses `samsungce.lamp`, mapped to a switch using supported brightness levels.
- Oven mode input only exposes the supported v1 programs `Bake` / `Heißluft` and `Keep Warm` / `Warmhalten`; `Off` is represented by the running switch plus the read-only program sensor.
- When the oven is off, the program input stays available as a staged control and falls back to the SmartThings default program.
- When switching between supported oven modes while the oven is already running, the integration stops the oven, applies the new mode, repairs any now-invalid timer or temperature values using the SmartThings per-mode defaults, and then starts again.
- Oven mode, timer, target temperature, and running control are unavailable when SmartThings reports remote control as disabled. The read-only status entities stay available and lamp control remains available.
- Refrigerator temperature numbers use `thermostatCoolingSetpoint` on the `cooler` and `freezer` components.
- Refrigerator doors use `contactSensor` on the `cooler` and `freezer` components.
- Refrigerator power consumption uses `powerConsumptionReport.powerConsumption.value.power`.
- Refrigerator water filter usage uses `custom.waterFilter.waterFilterUsage`.
- Cooktop state uses the read-only `switch` state and is exposed as a binary sensor, not a writable switch.

## Development

Recommended local setup:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q tests
pre-commit run --all-files
```

## Logo / branding note

This repository now includes official SmartThings branding assets for Home Assistant integration branding under [custom_components/advanced_smartthings/brand](/Users/fischerp/Workspace/smartthings-oven-bridge/custom_components/advanced_smartthings/brand).

Source:

- SmartThings Brand Guidelines: [partners.smartthings.com/brand-guidelines](https://partners.smartthings.com/brand-guidelines)

These assets are used to brand the Home Assistant custom integration and should continue to follow SmartThings brand-guideline usage terms.
