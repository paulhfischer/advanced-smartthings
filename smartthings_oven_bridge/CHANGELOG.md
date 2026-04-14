# Changelog

## 1.1.0

- fixed the add-on startup path so `python -m app.main` runs reliably in the container
- made `smartthings_device_id` optional for the initial OAuth step
- added SmartThings device discovery for finding the correct oven device ID
- exposed the add-on internal API base URL in the ingress UI
- added focused tests and wired `pytest` into `pre-commit`
- replaced placeholder docs with a full install, authorize, test, and Home Assistant usage guide
