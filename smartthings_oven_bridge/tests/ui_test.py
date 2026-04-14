from __future__ import annotations

from urllib.parse import parse_qs
from urllib.parse import urlparse

from fastapi import Request
from fastapi.testclient import TestClient

from app import main as app_main


class FakeUiService:
    async def get_status_payload(self, request: Request | None = None) -> dict[str, object]:
        del request
        return {
            "auth_state": "authorized",
            "oauth_configured": True,
            "device_id_configured": True,
            "device_id": "oven-1",
            "token_expires_at": None,
            "last_successful_contact_at": None,
            "reauth_required": False,
            "device_cache": {},
            "discovered_devices": [],
            "recent_errors": [],
            "oauth_callback": {
                "ready": True,
                "callback_url": "https://ha.example.com/api/hassio_ingress/bridge/oauth/callback",
                "source": "request",
                "reason": None,
            },
            "internal_api": {
                "ready": True,
                "hostname": "addon-host",
                "base_url": "http://addon-host:8080",
                "source": "supervisor",
                "reason": None,
            },
        }

    async def start_oauth_flow(self, request: Request) -> str:
        del request
        return "https://api.smartthings.com/oauth/authorize?state=test-state"

    async def complete_oauth_flow(self, code: str, state: str) -> None:
        assert code == "auth-code"
        assert state == "oauth-state"

    async def refresh_discovered_devices(self) -> list[dict[str, object]]:
        return [{"device_id": "oven-1"}]

    async def record_exception(self, err: object) -> None:
        raise AssertionError(f"unexpected exception: {err!r}")


def test_index_renders_ingress_prefixed_ui_links() -> None:
    client = _ui_client()

    response = client.get("/", headers=_ingress_headers())

    assert response.status_code == 200
    assert 'href="/api/hassio_ingress/bridge/oauth/start"' in response.text
    assert 'target="_top"' in response.text
    assert 'href="/api/hassio_ingress/bridge/ui/actions/discover_devices"' in response.text
    assert 'href="/api/hassio_ingress/bridge/ui/actions/refresh"' in response.text
    assert 'href="/api/hassio_ingress/bridge/ui/actions/start_warming?setpoint=55&amp;duration_seconds=1800"' in response.text


def test_flash_redirects_keep_ingress_prefix() -> None:
    client = _ui_client()
    client.cookies.set("ingress_session", "session-123")

    response = client.get(
        "/ui/actions/discover_devices",
        headers=_ingress_headers(),
        follow_redirects=False,
    )

    assert response.status_code == 302
    redirect_url = urlparse(response.headers["location"])
    assert redirect_url.path == "/api/hassio_ingress/bridge/"
    query = parse_qs(redirect_url.query)
    assert query["flash"] == ["Discovered 1 SmartThings devices."]
    assert query["flash_level"] == ["success"]
    set_cookie = response.headers["set-cookie"]
    assert "ingress_session=session-123" in set_cookie
    assert "Path=/api/hassio_ingress/" in set_cookie
    assert "SameSite=strict" in set_cookie
    assert "Secure" in set_cookie


def test_oauth_start_relaxes_ingress_session_cookie_for_callback_round_trip() -> None:
    client = _ui_client()
    client.cookies.set("ingress_session", "session-123")

    response = client.get(
        "/oauth/start",
        headers=_ingress_headers(),
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "https://api.smartthings.com/oauth/authorize?state=test-state"
    set_cookie = response.headers["set-cookie"]
    assert "ingress_session=session-123" in set_cookie
    assert "Path=/api/hassio_ingress/" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Secure" in set_cookie


def test_oauth_callback_keeps_relaxed_ingress_session_cookie_for_final_ui_redirect() -> None:
    client = _ui_client()
    client.cookies.set("ingress_session", "session-123")

    response = client.get(
        "/oauth/callback",
        headers=_ingress_headers(),
        params={"code": "auth-code", "state": "oauth-state"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    redirect_url = urlparse(response.headers["location"])
    assert redirect_url.path == "/api/hassio_ingress/bridge/"
    query = parse_qs(redirect_url.query)
    assert query["flash"] == ["SmartThings authorization completed."]
    assert query["flash_level"] == ["success"]
    set_cookie = response.headers["set-cookie"]
    assert "ingress_session=session-123" in set_cookie
    assert "Path=/api/hassio_ingress/" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Secure" in set_cookie


def test_index_renders_local_links_without_ingress_prefix() -> None:
    client = _ui_client()

    response = client.get("/")

    assert response.status_code == 200
    assert 'href="/oauth/start"' in response.text
    assert 'target="_top"' in response.text
    assert 'href="/ui/actions/discover_devices"' in response.text


def test_oauth_start_keeps_local_redirect_behavior_without_ingress_cookie() -> None:
    client = _ui_client()

    response = client.get("/oauth/start", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "https://api.smartthings.com/oauth/authorize?state=test-state"
    assert "set-cookie" not in response.headers


def _ingress_headers() -> dict[str, str]:
    return {
        "host": "ha.example.com",
        "x-forwarded-host": "ha.example.com",
        "x-forwarded-proto": "https",
        "x-ingress-path": "/api/hassio_ingress/bridge",
    }


def _ui_client() -> TestClient:
    app_main.INGRESS_ALLOWED_HOSTS.add("testclient")
    return TestClient(app_main.create_ui_app(FakeUiService()))
