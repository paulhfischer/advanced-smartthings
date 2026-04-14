from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from collections.abc import Callable
import json
from pathlib import Path
import signal
from typing import Annotated
from urllib.parse import quote_plus

from fastapi import FastAPI
from fastapi import Query
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse
from fastapi.responses import JSONResponse
from fastapi.responses import RedirectResponse
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
import uvicorn

from .errors import BridgeError
from .models import RawCommandRequest
from .models import StartWarmingRequest
from .service import BridgeService
from .settings import configure_logging
from .settings import load_settings


TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "ui_templates"))
INGRESS_ALLOWED_HOSTS = {"127.0.0.1", "::1", "172.30.32.2"}
BoolQuery = Annotated[bool | None, Query()]
SetpointQuery = Annotated[int, Query(ge=1, le=300)]
DurationQuery = Annotated[int, Query(ge=1, le=86_400)]
CallNext = Callable[[Request], Awaitable[Response]]


def create_api_app(service: BridgeService) -> FastAPI:
    app = FastAPI(title="SmartThings Oven Bridge API")
    app.state.bridge_service = service

    @app.exception_handler(BridgeError)
    async def bridge_error_handler(_: Request, err: BridgeError) -> JSONResponse:
        await service.record_exception(err)
        return JSONResponse(
            status_code=err.status_code,
            content={"ok": False, "error": err.to_response()},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, err: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": {
                    "code": "invalid_request",
                    "message": "Request validation failed.",
                    "details": err.errors(),
                },
            },
        )

    @app.get("/health")
    async def health() -> dict[str, object]:
        payload = await service.get_status_payload()
        return {
            "ok": True,
            "message": "healthy",
            "data": {
                "auth_state": payload["auth_state"],
                "configured": payload["configured"],
            },
        }

    @app.get("/api/status")
    async def api_status() -> dict[str, object]:
        return {"ok": True, "message": "status", "data": await service.get_status_payload()}

    @app.get("/api/device")
    async def api_device(refresh: BoolQuery = None) -> dict[str, object]:
        should_refresh = True if refresh is None else refresh
        data = await (service.refresh_device_payload() if should_refresh else service.get_cached_device_payload())
        return {"ok": True, "message": "device", "data": data}

    @app.get("/api/devices")
    async def api_devices(refresh: BoolQuery = None) -> dict[str, object]:
        should_refresh = True if refresh is None else refresh
        data = await (service.refresh_discovered_devices() if should_refresh else service.get_cached_discovered_devices())
        return {"ok": True, "message": "devices", "data": data}

    @app.post("/api/oven/stop")
    async def api_stop() -> dict[str, object]:
        result = await service.stop_oven()
        return {"ok": True, "message": "stop command sent", "data": result.model_dump()}

    @app.post("/api/oven/start_warming")
    async def api_start_warming(request_model: StartWarmingRequest) -> dict[str, object]:
        result = await service.start_warming(request_model)
        return {"ok": True, "message": "warming command handled", "data": result.model_dump()}

    @app.post("/api/oven/command")
    async def api_command(request_model: RawCommandRequest) -> dict[str, object]:
        result = await service.send_raw_commands(request_model)
        return {"ok": True, "message": "command sent", "data": result.model_dump()}

    return app


def create_ui_app(service: BridgeService) -> FastAPI:
    app = FastAPI(title="SmartThings Oven Bridge UI")
    app.state.bridge_service = service

    @app.middleware("http")
    async def enforce_ingress_source(request: Request, call_next: CallNext) -> Response:
        client_host = request.client.host if request.client else None
        if client_host not in INGRESS_ALLOWED_HOSTS:
            return Response("Ingress access only.", status_code=403)
        return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        context = await _build_ui_context(request, service)
        return TEMPLATES.TemplateResponse(request, "index.html", context)

    @app.get("/oauth/start")
    async def oauth_start(request: Request) -> RedirectResponse:
        try:
            authorization_url = await service.start_oauth_flow(request)
        except BridgeError as err:
            await service.record_exception(err)
            return _redirect_with_flash("/", err.message, "error")
        return RedirectResponse(authorization_url, status_code=302)

    @app.get("/oauth/callback")
    async def oauth_callback(
        request: Request,
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
        error_description: str | None = None,
    ) -> RedirectResponse:
        if error:
            await service.record_exception(
                BridgeError(
                    code="oauth_error",
                    message=f"SmartThings OAuth returned error: {error}.",
                    status_code=400,
                    details={"description": error_description},
                )
            )
            return _redirect_with_flash("/", "SmartThings OAuth returned an error.", "error")
        if code is None or state is None:
            return _redirect_with_flash("/", "Missing code or state in OAuth callback.", "error")

        try:
            await service.complete_oauth_flow(code, state)
        except BridgeError as err:
            await service.record_exception(err)
            return _redirect_with_flash("/", err.message, "error")
        return _redirect_with_flash("/", "SmartThings authorization completed.", "success")

    @app.get("/ui/actions/discover_devices")
    async def ui_discover_devices() -> RedirectResponse:
        try:
            devices = await service.refresh_discovered_devices()
        except BridgeError as err:
            await service.record_exception(err)
            return _redirect_with_flash("/", err.message, "error")
        return _redirect_with_flash(
            "/",
            f"Discovered {len(devices)} SmartThings devices.",
            "success",
        )

    @app.get("/ui/actions/refresh")
    async def ui_refresh() -> RedirectResponse:
        try:
            await service.refresh_device_payload()
        except BridgeError as err:
            await service.record_exception(err)
            return _redirect_with_flash("/", err.message, "error")
        return _redirect_with_flash("/", "Device metadata refreshed.", "success")

    @app.get("/ui/actions/stop")
    async def ui_stop() -> RedirectResponse:
        try:
            result = await service.stop_oven()
        except BridgeError as err:
            await service.record_exception(err)
            return _redirect_with_flash("/", err.message, "error")
        return _redirect_with_flash("/", f"Stop result: {result.result}.", "success")

    @app.get("/ui/actions/start_warming")
    async def ui_start_warming(
        setpoint: SetpointQuery = 55,
        duration_seconds: DurationQuery = 1800,
    ) -> RedirectResponse:
        try:
            result = await service.start_warming(StartWarmingRequest(setpoint=setpoint, duration_seconds=duration_seconds))
        except BridgeError as err:
            await service.record_exception(err)
            return _redirect_with_flash("/", err.message, "error")
        suffix = " (duration not applied upstream)" if not result.duration_applied else ""
        return _redirect_with_flash(
            "/",
            f"Warming result: {result.result}.{suffix}",
            "success",
        )

    return app


async def serve() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    service = BridgeService(settings=settings)
    await service.startup()

    api_app = create_api_app(service)
    ui_app = create_ui_app(service)

    api_server = uvicorn.Server(
        uvicorn.Config(
            api_app,
            host="0.0.0.0",
            port=settings.api_port,
            log_config=None,
            access_log=False,
        )
    )
    ui_server = uvicorn.Server(
        uvicorn.Config(
            ui_app,
            host="0.0.0.0",
            port=settings.ingress_port,
            log_config=None,
            access_log=False,
        )
    )
    api_server.install_signal_handlers = lambda: None
    ui_server.install_signal_handlers = lambda: None

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop_event.set)

    api_task = asyncio.create_task(api_server.serve())
    ui_task = asyncio.create_task(ui_server.serve())

    try:
        await stop_event.wait()
    finally:
        api_server.should_exit = True
        ui_server.should_exit = True
        await asyncio.gather(api_task, ui_task, return_exceptions=True)
        await service.shutdown()


def _redirect_with_flash(path: str, message: str, level: str) -> RedirectResponse:
    return RedirectResponse(
        f"{path}?flash={quote_plus(message)}&flash_level={quote_plus(level)}",
        status_code=302,
    )


async def _build_ui_context(request: Request, service: BridgeService) -> dict[str, object]:
    status = await service.get_status_payload(request)
    return {
        "request": request,
        "status": status,
        "flash": request.query_params.get("flash"),
        "flash_level": request.query_params.get("flash_level", "info"),
        "device_cache_json": _pretty_json(status["device_cache"]),
        "discovered_devices_json": _pretty_json(status["discovered_devices"]),
        "recent_errors_json": _pretty_json(status["recent_errors"]),
    }


def _pretty_json(value: object) -> str:
    return json_dumps(value)


def json_dumps(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, default=str)


if __name__ == "__main__":
    asyncio.run(serve())
