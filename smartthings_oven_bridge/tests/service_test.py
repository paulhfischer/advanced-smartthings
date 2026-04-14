from __future__ import annotations

import asyncio
from datetime import datetime
from datetime import timedelta
from datetime import UTC
from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import urlparse

from fastapi import Request
from fastapi.testclient import TestClient

from app.main import create_api_app
from app.models import TokenBundle
from app.service import BridgeService
from app.settings import ServiceSettings
from app.storage import StateStorage


class FakeSmartThingsClient:
    def __init__(self, devices: list[dict[str, object]]) -> None:
        self._devices = devices

    async def list_devices(self) -> list[dict[str, object]]:
        return self._devices


class FakeApiService:
    async def get_status_payload(self, request: Request | None = None) -> dict[str, object]:
        del request
        return {
            "configured": True,
            "auth_state": "authorized",
            "internal_api": {
                "ready": True,
                "base_url": "http://addon-host:8080",
                "hostname": "addon-host",
                "source": "supervisor",
            },
            "device_cache": {},
            "discovered_devices": [],
            "recent_errors": [],
        }

    async def get_cached_device_payload(self) -> dict[str, object]:
        return {"status": "cached"}

    async def refresh_device_payload(self) -> dict[str, object]:
        return {"status": "refreshed"}

    async def get_cached_discovered_devices(self) -> list[dict[str, object]]:
        return [{"device_id": "oven-1"}]

    async def refresh_discovered_devices(self) -> list[dict[str, object]]:
        return [{"device_id": "oven-1"}, {"device_id": "oven-2"}]

    async def stop_oven(self) -> object:
        raise AssertionError("not used in this test")

    async def start_warming(self, request_model: object) -> object:
        raise AssertionError(f"unexpected request: {request_model!r}")

    async def send_raw_commands(self, request_model: object) -> object:
        raise AssertionError(f"unexpected request: {request_model!r}")

    async def record_exception(self, err: object) -> None:
        raise AssertionError(f"unexpected exception: {err!r}")


def test_start_oauth_flow_requires_only_oauth_credentials(tmp_path: Path) -> None:
    settings = ServiceSettings(
        smartthings_client_id="client-id",
        smartthings_client_secret="client-secret",
        smartthings_device_id=None,
        state_path=tmp_path / "state.json",
    )
    service = BridgeService(settings=settings, storage=StateStorage(settings.state_path))

    async def scenario() -> None:
        await service.startup()
        try:
            authorization_url = await service.start_oauth_flow(_ingress_request())
            query = parse_qs(urlparse(authorization_url).query)
            assert query["client_id"] == ["client-id"]
            assert query["redirect_uri"] == ["https://ha.example.com/api/hassio_ingress/bridge/oauth/callback"]
            snapshot = await service._state_store.snapshot()  # noqa: SLF001
            assert snapshot.pending_oauth_state is not None
        finally:
            await service.shutdown()

    asyncio.run(scenario())


def test_refresh_discovered_devices_works_without_device_id(tmp_path: Path) -> None:
    settings = ServiceSettings(
        smartthings_client_id="client-id",
        smartthings_client_secret="client-secret",
        smartthings_device_id=None,
        state_path=tmp_path / "state.json",
    )
    service = BridgeService(settings=settings, storage=StateStorage(settings.state_path))

    async def scenario() -> None:
        await service.startup()
        try:
            await service._state_store.set_token(  # noqa: SLF001
                TokenBundle(
                    access_token="access-token",
                    refresh_token="refresh-token",
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )
            service._smartthings = FakeSmartThingsClient(  # noqa: SLF001
                [
                    {
                        "deviceId": "oven-1",
                        "label": "Kitchen Oven",
                        "name": "Samsung Range",
                        "type": "Appliance",
                        "manufacturerName": "Samsung",
                        "components": [{"id": "main", "capabilities": [{"id": "ovenMode"}, {"id": "switch"}]}],
                    },
                    {
                        "deviceId": "lamp-1",
                        "label": "Desk Lamp",
                        "name": "Lamp",
                        "type": "Light",
                        "manufacturerName": "Acme",
                        "components": [{"id": "main", "capabilities": [{"id": "switch"}]}],
                    },
                ]
            )

            devices = await service.refresh_discovered_devices()
            assert [device["device_id"] for device in devices] == ["oven-1", "lamp-1"]
            assert devices[0]["looks_like_oven"] is True
            cached = await service.get_cached_discovered_devices()
            assert cached == devices
        finally:
            await service.shutdown()

    asyncio.run(scenario())


def test_status_payload_includes_callback_and_internal_api_from_supervisor(tmp_path: Path) -> None:
    settings = ServiceSettings(
        smartthings_client_id="client-id",
        smartthings_client_secret="client-secret",
        smartthings_device_id=None,
        state_path=tmp_path / "state.json",
        supervisor_token="supervisor-token",
    )
    service = BridgeService(settings=settings, storage=StateStorage(settings.state_path))

    async def fake_core_request(path: str) -> dict[str, object]:
        assert path == "/config"
        return {"external_url": "https://ha.example.com"}

    async def fake_supervisor_request(
        path: str,
        unwrap_data: bool | None = None,
    ) -> dict[str, object]:
        del unwrap_data
        assert path == "/addons/self/info"
        return {
            "data": {
                "hostname": "addon-host",
                "ingress_url": "/api/hassio_ingress/bridge",
            }
        }

    async def scenario() -> None:
        await service.startup()
        try:
            service._supervisor_core_request = fake_core_request  # type: ignore[method-assign]  # noqa: SLF001
            service._supervisor_request = fake_supervisor_request  # type: ignore[method-assign]  # noqa: SLF001
            payload = await service.get_status_payload()
            assert payload["oauth_callback"]["callback_url"] == "https://ha.example.com/api/hassio_ingress/bridge/oauth/callback"
            assert payload["internal_api"]["base_url"] == "http://addon-host:8080"
            assert payload["device_id_configured"] is False
        finally:
            await service.shutdown()

    asyncio.run(scenario())


def test_api_routes_surface_status_and_device_discovery() -> None:
    client = TestClient(create_api_app(FakeApiService()))

    status_response = client.get("/api/status")
    assert status_response.status_code == 200
    assert status_response.json()["data"]["internal_api"]["base_url"] == "http://addon-host:8080"

    devices_response = client.get("/api/devices", params={"refresh": "false"})
    assert devices_response.status_code == 200
    assert devices_response.json()["data"] == [{"device_id": "oven-1"}]


def _ingress_request() -> Request:
    return Request(
        {
            "type": "http",
            "scheme": "https",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [
                (b"host", b"ha.example.com"),
                (b"x-forwarded-host", b"ha.example.com"),
                (b"x-forwarded-proto", b"https"),
                (b"x-ingress-path", b"/api/hassio_ingress/bridge"),
            ],
            "client": ("172.30.32.2", 1234),
            "server": ("ha.example.com", 443),
        }
    )
