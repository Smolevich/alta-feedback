"""Форма правок к странице про ALTA и закрытое токеном чтение для координатора."""

import hmac
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from jinja2 import Environment, PackageLoader, select_autoescape
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route

from alta_feedback.store import Store
from alta_feedback.validate import (
    STATUSES,
    TEXT_MAX,
    TITLE_MAX,
    UA_MAX,
    clean_section_id,
    clip,
    hash_ip,
    is_bot,
    parse_form,
)

BODY_MAX = 16_384
RATE_LIMIT = 5
RATE_WINDOW = timedelta(hours=1)
ADMIN_PAGE_MAX = 500
DEFAULT_RETURN_URL = "https://claude.ai/artifact/RrfqFLbzQh5wEkb9RxC7UQ"

# Ни одного скрипта на странице нет; стили только встроенные.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}

templates = Environment(
    loader=PackageLoader("alta_feedback", "templates"),
    autoescape=select_autoescape(["html"]),
)


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        declared = request.headers.get("content-length", "0")
        if declared.isdigit() and int(declared) > BODY_MAX:
            response: Response = PlainTextResponse("Слишком большой запрос", status_code=413)
        else:
            response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response


def client_ip(request: Request) -> str:
    """cloudflared ставит CF-Connecting-IP; uvicorn слушает только петлю, поэтому заголовку верим."""
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "")


def render(name: str, status_code: int = 200, **context) -> HTMLResponse:
    context.setdefault("return_url", os.environ.get("RETURN_URL", DEFAULT_RETURN_URL))
    context.setdefault("text_max", TEXT_MAX)
    return HTMLResponse(templates.get_template(name).render(**context), status_code=status_code)


async def form_page(request: Request) -> HTMLResponse:
    params = request.query_params
    return render(
        "form.html",
        section_id=clean_section_id(params.get("s")),
        section_title=clip(params.get("t"), TITLE_MAX),
        values={},
        errors=[],
    )


async def submit(request: Request) -> Response:
    form = {key: str(value) for key, value in (await request.form()).items()}
    if is_bot(form):
        return RedirectResponse("/spasibo", status_code=303)
    suggestion, errors = parse_form(form)
    if errors:
        return render(
            "form.html", status_code=400, section_id=suggestion.section_id,
            section_title=suggestion.section_title, values=form, errors=errors,
        )
    store: Store = request.app.state.store
    now = datetime.now(UTC)
    ip_hash = hash_ip(client_ip(request), request.app.state.ip_salt)
    if store.recent_from(ip_hash, now, RATE_WINDOW) >= RATE_LIMIT:
        return render("limit.html", status_code=429)
    user_agent = request.headers.get("user-agent", "")[:UA_MAX]
    store.add(suggestion, ip_hash, user_agent, now)
    query = urlencode({"s": suggestion.section_id}) if suggestion.section_id else ""
    return RedirectResponse(f"/spasibo?{query}" if query else "/spasibo", status_code=303)


async def thanks(request: Request) -> HTMLResponse:
    return render("thanks.html", section_id=clean_section_id(request.query_params.get("s")))


def authorized(request: Request) -> bool:
    expected = request.app.state.admin_token
    given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    return bool(expected) and hmac.compare_digest(given.encode(), expected.encode())


def parse_since(raw: str | None) -> str | None:
    """since — ISO-время в UTC; пусто значит «с начала»."""
    if not raw:
        return "0000"
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


async def admin_list(request: Request) -> JSONResponse:
    if not authorized(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    since = parse_since(request.query_params.get("since"))
    if since is None:
        return JSONResponse({"error": "since: нужен ISO, напр. 2026-10-31T12:00:00Z"}, status_code=400)
    status = request.query_params.get("status") or None
    if status and status not in STATUSES:
        return JSONResponse({"error": f"status: одно из {sorted(STATUSES)}"}, status_code=400)
    items = request.app.state.store.since(since, status, ADMIN_PAGE_MAX)
    return JSONResponse({"count": len(items), "items": items})


async def admin_set_status(request: Request) -> JSONResponse:
    if not authorized(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        status = (await request.json()).get("status")
    except ValueError:
        status = None
    if status not in STATUSES:
        return JSONResponse({"error": f"status: одно из {sorted(STATUSES)}"}, status_code=400)
    found = request.app.state.store.set_status(int(request.path_params["id"]), status)
    if not found:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"id": request.path_params["id"], "status": status})


async def healthz(request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


def create_app(
    data_dir: Path | None = None, admin_token: str | None = None, ip_salt: str | None = None
) -> Starlette:
    app = Starlette(
        routes=[
            Route("/", form_page, methods=["GET"]),
            Route("/", submit, methods=["POST"]),
            Route("/spasibo", thanks, methods=["GET"]),
            Route("/healthz", healthz, methods=["GET"]),
            Route("/admin/suggestions", admin_list, methods=["GET"]),
            Route("/admin/suggestions/{id:int}/status", admin_set_status, methods=["POST"]),
        ],
        middleware=[Middleware(SecurityHeaders)],
    )
    data = data_dir or Path(os.environ.get("DATA_DIR", "data"))
    app.state.store = Store(data / "feedback.db")
    app.state.admin_token = admin_token if admin_token is not None else os.environ.get("ADMIN_TOKEN", "")
    app.state.ip_salt = ip_salt if ip_salt is not None else os.environ.get("IP_SALT", "")
    if not app.state.ip_salt:
        raise RuntimeError("IP_SALT не задан: без соли хэш IP подбирается перебором")
    return app
