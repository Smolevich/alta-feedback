"""Статичный справочник alta-bankruptcy на «/»: собранную CI папку отдаём как есть."""

from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from alta_feedback.aod_archive import ArchivedPdf

DEFAULT_SITE_DIR = Path("/var/www/alta-bankruptcy")

# Starlight вставляет встроенные скрипты и стили, а поиск Pagefind грузит wasm со своего же
# адреса; всё остальное закрыто. Формы сервиса в этот CSP не попадают: у них свой.
SITE_CSP = (
    "default-src 'none'; "
    "script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval' https://static.cloudflareinsights.com; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; "
    "connect-src 'self' https://cloudflareinsights.com; "
    "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
)
# Встроенный просмотр PDF на странице документов: страница разрешает object и frame со своего адреса,
# а сам PDF разрешает показывать себя только странице с того же адреса.
# aod.rs остаётся в списке ради запасного пути ArchiveFiles: пока копии нет, просмотр уходит на оригинал.
EMBED = "'self' https://www.aod.rs"
SITE_CSP = SITE_CSP.replace("form-action", f"object-src {EMBED}; frame-src {EMBED}; form-action")
PDF_CSP = SITE_CSP.replace("frame-ancestors 'none'", "frame-ancestors 'self'")
# Имена в /_astro/ содержат хэш содержимого, остальное (в том числе индекс поиска) меняется
# без смены имени, и Cloudflare не должен держать его в кэше.
IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"
# Копия документа AOD под своим именем не меняется (новая версия оригинала ложится рядом), но
# манифест могут перевести на другую — поэтому сутки, а не immutable.
ARCHIVE_CACHE = "public, max-age=86400"


class SiteFiles(StaticFiles):
    def __init__(self, directory: Path) -> None:
        super().__init__(directory=directory, html=True, check_dir=False)

    async def check_config(self) -> None:
        # До первого выката папки нет, и это не ошибка: сервис отвечает 404, а не 500.
        return

    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        response.headers["Content-Security-Policy"] = PDF_CSP if path.endswith(".pdf") else SITE_CSP
        cache = IMMUTABLE if path.startswith("_astro/") and response.status_code == 200 else REVALIDATE
        response.headers["Cache-Control"] = cache
        return response


class ArchiveFiles(StaticFiles):
    """Публичные копии PDF с сайта AOD (/docs/aod/<name>), см. aod_archive.

    Отдаём только то, что в манифесте помечено public: закрытые лежат в соседней папке,
    куда этот обработчик не смотрит.
    """

    def __init__(self, directory: Path, manifest: dict[str, ArchivedPdf]) -> None:
        super().__init__(directory=directory, check_dir=False)
        self.public = {name: item for name, item in manifest.items() if item.public}

    async def check_config(self) -> None:
        return

    async def get_response(self, path: str, scope: Scope) -> Response:
        item = self.public.get(path)
        if item is None:
            return PlainTextResponse("not found", status_code=404)
        try:
            response = await super().get_response(path, scope)
        except HTTPException as e:
            if e.status_code != 404:
                raise
            # Копии ещё нет (первый прогон проверки не прошёл) — показываем оригинал.
            return RedirectResponse(item.url, status_code=307)
        response.headers["Content-Security-Policy"] = PDF_CSP
        response.headers["Cache-Control"] = ARCHIVE_CACHE
        return response


def index_file(site_dir: Path) -> Path | None:
    index = site_dir / "index.html"
    return index if index.is_file() else None
