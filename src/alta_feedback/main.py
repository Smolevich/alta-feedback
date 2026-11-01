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
from starlette.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from starlette.routing import Mount, Route

from alta_feedback.accounts import (
    ACCOUNT_STATUSES,
    ACCOUNT_TYPES,
    BANKS,
    CITIES,
    COMMENT_MAX,
    DOCUMENTS,
    FREE_TEXT_MAX,
    RESIDENCIES,
    RESULTS,
    labels,
    parse_account_form,
)
from alta_feedback.pow import CHALLENGE_TTL, Challenge, create_challenge, derive_key, verify_payload
from alta_feedback.site import DEFAULT_SITE_DIR, REVALIDATE, SITE_CSP, SiteFiles, index_file
from alta_feedback.stats import account_stats
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
# Сколько держим хэш IP и браузер: лимиту хватает часа, остальное — чтобы разобрать волну спама.
TRACE_TTL = timedelta(days=30)
ADMIN_PAGE_MAX = 500
PUBLIC_ACCOUNTS_MAX = 2000
LOCAL_TZ = ZoneInfo("Europe/Belgrade")
STATIC_DIR = Path(__file__).parent / "static"
SCRIPTS = frozenset({"combo.js", "pow.js", "voice.js"})
# Перебор запускает отметка «Я не робот»; среднее число попыток — половина, на Mac ~0,4 с, на телефоне 1–3 с.
POW_MAX_NUMBER = 200_000
POW_FAILED = "Не прошла проверка от ботов. Подождите пару секунд и отправьте ещё раз."
DEFAULT_RETURN_URL = "https://claude.ai/artifact/RrfqFLbzQh5wEkb9RxC7UQ"

# Счётчик посещений Cloudflare Web Analytics: единственный разрешённый чужой скрипт и адрес отправки данных.
CF_SCRIPT = "https://static.cloudflareinsights.com"
CF_CONNECT = "https://cloudflareinsights.com"

# Своих скриптов на странице нет; стили только встроенные.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        f"default-src 'none'; script-src {CF_SCRIPT}; connect-src {CF_CONNECT}; style-src 'unsafe-inline'; "
        "img-src 'self' data:; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}

# Страница отчёта о счёте грузит только свои скрипты: списки с поиском и микрофон;
# connect-src — только за новой задачей, когда старая протухла, пока форма была открыта.
ACCOUNT_PAGE_HEADERS = {
    "Content-Security-Policy": (
        f"default-src 'none'; script-src 'self' {CF_SCRIPT}; connect-src 'self' {CF_CONNECT}; "
        "style-src 'unsafe-inline'; img-src 'self' data:; "
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


async def home(request: Request) -> Response:
    """«/» — справочник; со ссылкой «Предложить правку» (?s=…, ?t=…) и без справочника — форма."""
    index = index_file(request.app.state.site_dir)
    if index is None or request.query_params.keys() & {"s", "t"}:
        return await form_page(request)
    return FileResponse(
        index, headers={"Content-Security-Policy": SITE_CSP, "Cache-Control": REVALIDATE}
    )


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
    store.forget_old_traces(now - TRACE_TTL)
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


def account_context(request: Request, values: dict, errors: list[str]) -> dict:
    return {
        "banks": BANKS, "cities": CITIES, "account_types": ACCOUNT_TYPES, "results": RESULTS,
        "residencies": RESIDENCIES, "documents": DOCUMENTS, "comment_max": COMMENT_MAX,
        "free_text_max": FREE_TEXT_MAX, "values": values, "errors": errors,
        "pow": new_challenge(request), "pow_ttl": int(CHALLENGE_TTL.total_seconds()),
    }


def new_challenge(request: Request) -> Challenge:
    state = request.app.state
    return create_challenge(state.pow_key, datetime.now(UTC), state.pow_max_number)


async def account_challenge(request: Request) -> JSONResponse:
    challenge = new_challenge(request)
    return JSONResponse({
        "algorithm": challenge.algorithm, "challenge": challenge.challenge, "salt": challenge.salt,
        "signature": challenge.signature, "maxnumber": challenge.maxnumber,
        "ttl": int(CHALLENGE_TTL.total_seconds()),
    })


def account_form(request: Request, values: dict, errors: list[str], status_code: int = 200) -> HTMLResponse:
    return render(
        "account.html", status_code=status_code, headers=ACCOUNT_PAGE_HEADERS,
        **account_context(request, values, errors),
    )


def today_local() -> datetime:
    return datetime.now(LOCAL_TZ)


async def account_page(request: Request) -> HTMLResponse:
    values = {"visit_date": today_local().date().isoformat(), "docs": []}
    return account_form(request, values, [])


async def account_submit(request: Request) -> Response:
    raw = await request.form()
    form = {key: str(value) for key, value in raw.items()}
    if is_bot(form):
        return RedirectResponse("/account/spasibo", status_code=303)
    # Без JS документы приходят одной строкой через запятую, со скриптом — тегами.
    docs = [str(value) for value in raw.getlist("docs")] + form.get("docs_text", "").split(",")
    report, errors = parse_account_form(form, docs, today_local().date())
    now = datetime.now(UTC)
    solved = verify_payload(request.app.state.pow_key, form.get("altcha", ""), now)
    if solved is None:
        errors.append(POW_FAILED)
    if errors:
        values = {**form, "docs": [doc.strip() for doc in docs if doc.strip()]}
        return account_form(request, values, errors, status_code=400)
    store: Store = request.app.state.store
    ip_hash = ip_hash_of(request)
    if store.recent_from(ip_hash, now, RATE_WINDOW, table="accounts") >= RATE_LIMIT:
        return render("limit.html", status_code=429)
    if not store.claim_challenge(solved.challenge, solved.expires_at, now):
        return account_form(request, {**form, "docs": docs}, [POW_FAILED], status_code=400)
    store.add_account(report, ip_hash, request.headers.get("user-agent", "")[:UA_MAX], now)
    store.forget_old_traces(now - TRACE_TTL)
    return RedirectResponse("/account/spasibo", status_code=303)


async def account_thanks(request: Request) -> HTMLResponse:
    return render("account_thanks.html")


async def account_stats_page(request: Request) -> HTMLResponse:
    items = request.app.state.store.public_accounts(PUBLIC_ACCOUNTS_MAX)
    return render("stats.html", stats=account_stats(items), results=RESULTS)


async def public_accounts(request: Request) -> JSONResponse:
    items = request.app.state.store.public_accounts(PUBLIC_ACCOUNTS_MAX)
    return JSONResponse({"count": len(items), "items": items, "labels": labels()})


async def static_script(request: Request) -> Response:
    name = request.path_params["name"]
    if name not in SCRIPTS:
        return PlainTextResponse("not found", status_code=404)
    body = (STATIC_DIR / name).read_text(encoding="utf-8")
    return Response(body, media_type="text/javascript; charset=utf-8", headers={"Cache-Control": "no-cache"})


async def healthz(request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


def create_app(
    data_dir: Path | None = None,
    admin_token: str | None = None,
    ip_salt: str | None = None,
    pow_max_number: int = POW_MAX_NUMBER,
    site_dir: Path | None = None,
) -> Starlette:
    site = site_dir or Path(os.environ.get("SITE_DIR", DEFAULT_SITE_DIR))
    app = Starlette(
        routes=[
            Route("/", home, methods=["GET"]),
            Route("/fix", form_page, methods=["GET"]),
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
            Route("/account/challenge", account_challenge, methods=["GET"]),
            Route("/account/spasibo", account_thanks, methods=["GET"]),
            Route("/account/stats", account_stats_page, methods=["GET"]),
            Route("/static/{name}", static_script, methods=["GET"]),
            Route("/api/accounts/public", public_accounts, methods=["GET"]),
            Route("/admin/accounts", admin_list("accounts", ACCOUNT_STATUSES), methods=["GET"]),
            Route(
                "/admin/accounts/{id:int}/status",
                admin_set_status("accounts", ACCOUNT_STATUSES), methods=["POST"],
            ),
            # Последним: всё, чего нет среди маршрутов выше, ищем в собранном справочнике.
            Mount("/", app=SiteFiles(site), name="site"),
        ],
        middleware=[Middleware(SecurityHeaders)],
    )
    data = data_dir or Path(os.environ.get("DATA_DIR", "data"))
    app.state.store = Store(data / "feedback.db")
    app.state.admin_token = admin_token if admin_token is not None else os.environ.get("ADMIN_TOKEN", "")
    app.state.ip_salt = ip_salt if ip_salt is not None else os.environ.get("IP_SALT", "")
    if not app.state.ip_salt:
        raise RuntimeError("IP_SALT не задан: без соли хэш IP подбирается перебором")
    app.state.pow_key = derive_key(app.state.ip_salt)
    app.state.pow_max_number = pow_max_number
    app.state.site_dir = site
    return app
