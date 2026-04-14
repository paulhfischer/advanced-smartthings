# SmartThings Oven Bridge

`smartthings_oven_bridge` is a Home Assistant add-on that:

- stores SmartThings OAuth tokens inside the add-on data directory
- exposes an ingress UI for authorization, device discovery, and smoke tests
- exposes an internal HTTP API for Home Assistant `rest_command`, scripts, and automations

## Quick Start

1. Add the Git URL that hosts this repository to Home Assistant as a custom add-on repository.
2. Install **SmartThings Oven Bridge**.
3. Configure only the SmartThings client ID and client secret first.
4. Start the add-on and open its Web UI.
5. Copy the **OAuth callback URL** shown in the UI into your SmartThings OAuth app.
6. Complete the SmartThings OAuth login from the add-on UI.
7. Click **Discover devices**, copy the oven `device_id`, add it to the add-on config, and restart the add-on.
8. Use the UI test buttons or the internal API from Home Assistant.

## What This Requires

Before you start, make sure you have all of the following:

- A Home Assistant installation with Supervisor support for add-ons.
- A Samsung oven that already appears as a device in SmartThings.
- A SmartThings account with permission to control that oven.
- A Home Assistant external URL configured with HTTPS.
  SmartThings requires an HTTPS redirect URI for OAuth.
- A SmartThings OAuth app that can issue a client ID and client secret.

## Install This As A Home Assistant Add-on Repository

1. Host this repository somewhere Home Assistant can reach over Git, such as GitHub.
2. In Home Assistant, open **Settings > Add-ons > Add-on Store**.
3. Open the three-dot menu in the upper-right corner and choose **Repositories**.
4. Paste the Git URL for the repository that contains this add-on.
5. Close the dialog, refresh the store if needed, and install **SmartThings Oven Bridge**.

## Add-on Configuration

For the first start, use this minimum configuration:

```yaml
smartthings_client_id: "YOUR_CLIENT_ID"
smartthings_client_secret: "YOUR_CLIENT_SECRET"
log_level: info
```

`smartthings_device_id` is intentionally optional for the first OAuth step.
Set it only after the add-on has authenticated and shown you the available devices.

Once you know the oven device ID, update the config to:

```yaml
smartthings_client_id: "YOUR_CLIENT_ID"
smartthings_client_secret: "YOUR_CLIENT_SECRET"
smartthings_device_id: "YOUR_OVEN_DEVICE_ID"
log_level: info
```

## SmartThings OAuth Setup

This add-on uses the SmartThings OAuth authorization code flow.

### Recommended order

1. Start the add-on before creating the final SmartThings redirect URI.
2. Open the add-on Web UI in Home Assistant.
3. Wait until the **OAuth callback URL** field shows a real HTTPS URL.
   The add-on derives this from the Home Assistant ingress base path exposed in the `X-Ingress-Path` header.
4. Use that exact URL in SmartThings as the redirect URI.

### What to create in SmartThings

Create an OAuth app / OAuth-In SmartApp and record the generated:

- client ID
- client secret

Use these values when SmartThings asks for app details:

- Redirect URI:
  use the exact **OAuth callback URL** shown in the add-on UI, including `/oauth/callback`
- Scopes:
  `r:devices:*` and `x:devices:*`
- Target URL / hosting URL, if SmartThings requires it during app creation:
  use the same add-on ingress URL, but without the trailing `/oauth/callback`

Example:

- If the add-on UI shows `https://ha.example.com/api/hassio_ingress/abc123/oauth/callback`
- then register:
  - redirect URI: `https://ha.example.com/api/hassio_ingress/abc123/oauth/callback`
  - target/base URL, if requested: `https://ha.example.com/api/hassio_ingress/abc123`

If Home Assistant later changes the ingress path, you must update the SmartThings redirect URI to match.
Always copy the callback URL exactly as shown by the add-on UI.

## Start The Add-on

1. Save the add-on configuration.
2. Start the add-on.
3. Open **Web UI**.
4. Confirm these values in the UI:
   - **OAuth config present** is `true`
   - **OAuth callback ready** is `true`
   - **OAuth callback URL** is an HTTPS URL

If the callback is not ready:

- check that Home Assistant `external_url` is configured
- check that the external URL starts with `https://`
- reload the add-on UI after the add-on has fully started

## Complete First Authorization

1. In the add-on UI, click **Start OAuth login**.
   This intentionally escapes the Home Assistant ingress iframe because the SmartThings login flow cannot complete inside the sandboxed ingress frame.
2. Sign in to SmartThings and approve access.
3. Let SmartThings redirect back into Home Assistant.
4. Return to the add-on UI.
5. Confirm the status badge changes to `authorized`.

## Discover The Oven Device ID

1. In the add-on UI, click **Discover devices**.
2. Look at the **Discovered devices** panel.
3. Find the device whose label/name matches your oven.
4. Prefer entries with `looks_like_oven: true`.
5. Copy that `device_id`.
6. Add `smartthings_device_id` to the add-on config.
7. Restart the add-on.

## How To Know It Is Working

After setting `smartthings_device_id` and restarting:

1. Open the add-on UI.
2. Confirm **Device ID configured** is `true`.
3. Click **Refresh configured device**.
4. Confirm the **Configured device snapshot** panel fills with SmartThings device metadata/status.
5. Use **Test stop** or **Test start warming** for a smoke test.

The API health endpoint is also available internally:

- `GET /health`
- `GET /api/status`

## Internal API

The add-on UI shows the exact **Internal API Base URL** that Home Assistant should use.
It is normally:

```text
http://<addon-hostname>:8080
```

Do not guess this hostname. Copy the value shown in the add-on UI.

## Test It From Home Assistant

Once the add-on UI shows **Internal API Base URL**, you can test from Home Assistant with `rest_command`.

Example `configuration.yaml`:

```yaml
rest_command:
  smartthings_oven_bridge_stop:
    url: "REPLACE_WITH_UI_BASE_URL/api/oven/stop"
    method: POST
    timeout: 30

  smartthings_oven_bridge_start_warming:
    url: "REPLACE_WITH_UI_BASE_URL/api/oven/start_warming"
    method: POST
    content_type: application/json
    timeout: 30
    payload: >
      {
        "setpoint": {{ setpoint | int }},
        "duration_seconds": {{ duration_seconds | int }}
      }

  smartthings_oven_bridge_raw_command:
    url: "REPLACE_WITH_UI_BASE_URL/api/oven/command"
    method: POST
    content_type: application/json
    timeout: 30
    payload: >
      {
        "commands": [
          {
            "component": "main",
            "capability": "ovenMode",
            "command": "setOvenMode",
            "arguments": ["warming"]
          }
        ]
      }
```

Replace `REPLACE_WITH_UI_BASE_URL` with the exact value from the add-on UI, for example:

```text
http://addon-hostname:8080
```

Then test from **Developer Tools > Actions**:

- call `rest_command.smartthings_oven_bridge_stop`
- call `rest_command.smartthings_oven_bridge_start_warming` with variables like:

```yaml
setpoint: 55
duration_seconds: 1800
```

## Example Home Assistant Scripts

```yaml
script:
  oven_keep_warm_30m:
    alias: Oven keep warm for 30 minutes
    sequence:
      - action: rest_command.smartthings_oven_bridge_start_warming
        data:
          setpoint: 55
          duration_seconds: 1800

  oven_stop_now:
    alias: Oven stop now
    sequence:
      - action: rest_command.smartthings_oven_bridge_stop
```

## API Endpoints

The add-on exposes these internal endpoints:

- `GET /health`
- `GET /api/status`
- `GET /api/devices`
- `GET /api/device`
- `POST /api/oven/stop`
- `POST /api/oven/start_warming`
- `POST /api/oven/command`

### `POST /api/oven/start_warming`

Request body:

```json
{
  "setpoint": 55,
  "duration_seconds": 1800
}
```

### `POST /api/oven/command`

Request body:

```json
{
  "commands": [
    {
      "component": "main",
      "capability": "ovenMode",
      "command": "setOvenMode",
      "arguments": ["warming"]
    }
  ]
}
```

## Known Limitations

- SmartThings oven capabilities vary by model and region.
  The built-in `start_warming` and `stop` mappings are best-effort.
- Some ovens may require different capabilities or commands than the default mappings used here.
- If your oven does not accept the built-in commands, use `POST /api/oven/command` with a raw SmartThings command payload that matches your device.
- If the add-on is reinstalled or Home Assistant changes the ingress path, the SmartThings redirect URI may need to be updated.
- This add-on stores OAuth tokens in the add-on data directory so they survive restarts.

## What Was Verified Locally

From the repository itself, this was verified:

- the add-on repository now contains the files Home Assistant expects
- the add-on container startup path is coherent
- config values used by the code match the documented config values
- state is persisted under `/data`
- OAuth callback URL discovery and internal hostname discovery are covered by tests
- device discovery without an initial `smartthings_device_id` is covered by tests
- `pytest` and `pre-commit` are part of the local quality path

## What Still Requires A Live Environment

These steps still require real systems and cannot be proven offline from the repo alone:

- a full Home Assistant add-on install through the Supervisor UI
- a real SmartThings OAuth app and SmartThings account
- live token exchange against SmartThings
- live command acceptance by your exact Samsung oven model
