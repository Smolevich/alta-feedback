"""Форма правок и анонимные отчёты об открытии счетов для страницы про ALTA; чтение токеном."""

import hmac
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from jinja2 import Environment, PackageLoader, select_autoescape
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route

from alta_feedback.accounts import (
    ACCOUNT_STATUSES,
    ACCOUNT_TYPES,
    BANKS,
    CITIES,
    COMMENT_MAX,
    DOCUMENTS,
    OTHER_MAX,
    RESIDENCIES,
    RESULTS,
    labels,
    parse_account_form,
)
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
PUBLIC_ACCOUNTS_MAX = 2000
LOCAL_TZ = ZoneInfo("Europe/Belgrade")
STATIC_DIR = Path(__file__).parent / "static"
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

# Страница отчёта о счёте грузит один свой скрипт (микрофон) и больше ничего.
ACCOUNT_PAGE_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; img-src 'self' data:; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    ),
    "Permissions-Policy": "microphone=(self)",
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


def render(
    name: str, status_code: int = 200, headers: dict[str, str] | None = None, **context
) -> HTMLResponse:
    context.setdefault("return_url", os.environ.get("RETURN_URL", DEFAULT_RETURN_URL))
    context.setdefault("text_max", TEXT_MAX)
    html = templates.get_template(name).render(**context)
    return HTMLResponse(html, status_code=status_code, headers=headers)


def ip_hash_of(request: Request) -> str:
    return hash_ip(client_ip(request), request.app.state.ip_salt)


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
    ip_hash = ip_hash_of(request)
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


def admin_list(table: str, statuses: frozenset[str]) -> Callable[[Request], Awaitable[JSONResponse]]:
    async def handler(request: Request) -> JSONResponse:
        if not authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        since = parse_since(request.query_params.get("since"))
        if since is None:
            return JSONResponse({"error": "since: нужен ISO, напр. 2026-10-31T12:00:00Z"}, status_code=400)
        status = request.query_params.get("status") or None
        if status and status not in statuses:
            return JSONResponse({"error": f"status: одно из {sorted(statuses)}"}, status_code=400)
        items = request.app.state.store.since(since, status, ADMIN_PAGE_MAX, table=table)
        return JSONResponse({"count": len(items), "items": items})

    return handler


def admin_set_status(table: str, statuses: frozenset[str]) -> Callable[[Request], Awaitable[JSONResponse]]:
    async def handler(request: Request) -> JSONResponse:
        if not authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            status = (await request.json()).get("status")
        except ValueError:
            status = None
        if status not in statuses:
            return JSONResponse({"error": f"status: одно из {sorted(statuses)}"}, status_code=400)
        found = request.app.state.store.set_status(int(request.path_params["id"]), status, table=table)
        if not found:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({"id": request.path_params["id"], "status": status})

    return handler


def account_context(values: dict, errors: list[str]) -> dict:
    return {
        "banks": BANKS, "cities": CITIES, "account_types": ACCOUNT_TYPES, "results": RESULTS,
        "residencies": RESIDENCIES, "documents": DOCUMENTS, "comment_max": COMMENT_MAX,
        "other_max": OTHER_MAX, "values": values, "errors": errors,
    }


def today_local() -> datetime:
    return datetime.now(LOCAL_TZ)


async def account_page(request: Request) -> HTMLResponse:
    values = {"visit_date": today_local().date().isoformat(), "docs": []}
    return render("account.html", headers=ACCOUNT_PAGE_HEADERS, **account_context(values, []))


async def account_submit(request: Request) -> Response:
    raw = await request.form()
    form = {key: str(value) for key, value in raw.items()}
    if is_bot(form):
        return RedirectResponse("/account/spasibo", status_code=303)
    docs = [str(value) for value in raw.getlist("docs")]
    report, errors = parse_account_form(form, docs, today_local().date())
    if errors:
        values = {**form, "docs": docs}
        return render(
            "account.html", status_code=400, headers=ACCOUNT_PAGE_HEADERS, **account_context(values, errors)
        )
    store: Store = request.app.state.store
    now = datetime.now(UTC)
    ip_hash = ip_hash_of(request)
    if store.recent_from(ip_hash, now, RATE_WINDOW, table="accounts") >= RATE_LIMIT:
        return render("limit.html", status_code=429)
    store.add_account(report, ip_hash, request.headers.get("user-agent", "")[:UA_MAX], now)
    return RedirectResponse("/account/spasibo", status_code=303)


async def account_thanks(request: Request) -> HTMLResponse:
    return render("account_thanks.html")


async def public_accounts(request: Request) -> JSONResponse:
    items = request.app.state.store.public_accounts(PUBLIC_ACCOUNTS_MAX)
    return JSONResponse({"count": len(items), "items": items, "labels": labels()})


async def voice_script(request: Request) -> Response:
    body = (STATIC_DIR / "voice.js").read_text(encoding="utf-8")
    return Response(body, media_type="text/javascript; charset=utf-8", headers={"Cache-Control": "no-cache"})


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
            Route("/admin/suggestions", admin_list("suggestions", STATUSES), methods=["GET"]),
            Route(
                "/admin/suggestions/{id:int}/status",
                admin_set_status("suggestions", STATUSES), methods=["POST"],
            ),
            Route("/account", account_page, methods=["GET"]),
            Route("/account", account_submit, methods=["POST"]),
            Route("/account/spasibo", account_thanks, methods=["GET"]),
            Route("/static/voice.js", voice_script, methods=["GET"]),
            Route("/api/accounts/public", public_accounts, methods=["GET"]),
            Route("/admin/accounts", admin_list("accounts", ACCOUNT_STATUSES), methods=["GET"]),
            Route(
                "/admin/accounts/{id:int}/status",
                admin_set_status("accounts", ACCOUNT_STATUSES), methods=["POST"],
            ),
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
