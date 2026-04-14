# SmartThings Oven Bridge

Custom Home Assistant add-on repository for `smartthings_oven_bridge`.

The add-on provides:

- an ingress UI for SmartThings OAuth, device discovery, and basic smoke tests
- an internal HTTP API for Home Assistant `rest_command`, scripts, and automations
- persistent token and cache storage under the add-on `/data` directory

Use [smartthings_oven_bridge/DOCS.md](/Users/fischerp/Workspace/smartthings-oven-bridge/smartthings_oven_bridge/DOCS.md) for the full operator guide.

Local quality checks:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r smartthings_oven_bridge/requirements.txt -r requirements-dev.txt
pytest -q
pre-commit run --all-files
```
