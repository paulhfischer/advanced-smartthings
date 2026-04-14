# Changelog

## 1.1.4

- kept the Home Assistant ingress session cookie relaxed through the OAuth callback redirect so the final return to the add-on UI is not rejected with `401 Unauthorized`
- added a callback regression test that covers the final ingress redirect after SmartThings authorization

## 1.1.3

- reissued the Home Assistant ingress session cookie with `SameSite=Lax` for the SmartThings OAuth launch so the callback is still authorized after the external redirect
- restored the stricter ingress cookie policy on normal UI redirects after the callback returns
- documented that the SmartThings OAuth flow must complete in the same browser session that launched it

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
