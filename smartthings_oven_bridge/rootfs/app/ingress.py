from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
from urllib.parse import urlencode

from fastapi import Request


QueryScalar = str | int | float | bool
QueryValue = QueryScalar | Sequence[QueryScalar] | None


def get_ingress_base_path(request: Request) -> str | None:
    raw_base_path = request.headers.get("x-ingress-path")
    if raw_base_path is None:
        root_path = request.scope.get("root_path")
        raw_base_path = root_path if isinstance(root_path, str) and root_path else None
    if raw_base_path is None:
        return None
    return _normalize_base_path(raw_base_path)


def ui_url(
    request: Request,
    route_path: str,
    *,
    query: Mapping[str, QueryValue] | None = None,
) -> str:
    base_path = get_ingress_base_path(request) or ""
    resolved_path = _join_paths(base_path, route_path)
    encoded_query = _encode_query(query)
    if not encoded_query:
        return resolved_path
    return f"{resolved_path}?{encoded_query}"


def build_callback_url(request: Request) -> str | None:
    if get_ingress_base_path(request) is None:
        return None
    return build_external_ui_url(request, "/oauth/callback")


def build_external_ui_url(
    request: Request,
    route_path: str,
    *,
    query: Mapping[str, QueryValue] | None = None,
) -> str | None:
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if not host:
        return None
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    return f"{scheme}://{host}{ui_url(request, route_path, query=query)}"


def _normalize_base_path(base_path: str) -> str:
    normalized = base_path.strip()
    if not normalized or normalized == "/":
        return ""
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized.rstrip("/")


def _normalize_route_path(route_path: str) -> str:
    if not route_path:
        return "/"
    if not route_path.startswith("/"):
        return f"/{route_path}"
    return route_path


def _join_paths(base_path: str, route_path: str) -> str:
    normalized_base = _normalize_base_path(base_path)
    normalized_route = _normalize_route_path(route_path)
    if not normalized_base:
        return normalized_route
    if normalized_route == "/":
        return f"{normalized_base}/"
    return f"{normalized_base}{normalized_route}"


def _encode_query(query: Mapping[str, QueryValue] | None) -> str:
    if not query:
        return ""

    encoded_query: dict[str, QueryScalar | list[QueryScalar]] = {}
    for key, value in query.items():
        if value is None:
            continue
        if isinstance(value, list | tuple):
            encoded_query[key] = list(value)
        else:
            encoded_query[key] = value
    return urlencode(encoded_query, doseq=True)
