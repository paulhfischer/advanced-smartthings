# Changelog

## 1.1.2

- changed the SmartThings OAuth start action to escape the Home Assistant ingress iframe so the external SmartThings login flow is not blocked by iframe sandboxing
- documented that the OAuth flow intentionally leaves the ingress iframe and must use the callback URL shown in the add-on UI

## 1.1.1

- fixed ingress-aware UI navigation so OAuth start, action links, and flash redirects stay under the Home Assistant ingress path
- added focused ingress regression tests for rendered UI links and redirect targets

## 1.1.0

- fixed the add-on startup path so `python -m app.main` runs reliably in the container
- made `smartthings_device_id` optional for the initial OAuth step
- added SmartThings device discovery for finding the correct oven device ID
- exposed the add-on internal API base URL in the ingress UI
- added focused tests and wired `pytest` into `pre-commit`
- replaced placeholder docs with a full install, authorize, test, and Home Assistant usage guide
