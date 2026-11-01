"""Статичный справочник alta-bankruptcy на «/»: собранную CI папку отдаём как есть."""

from pathlib import Path

from starlette.staticfiles import StaticFiles
from starlette.types import Scope

DEFAULT_SITE_DIR = Path("/var/www/alta-bankruptcy")

# Starlight вставляет встроенные скрипты и стили, а поиск Pagefind грузит wasm со своего же
# адреса; всё остальное закрыто. Формы сервиса в этот CSP не попадают: у них свой.
SITE_CSP = (
    "default-src 'none'; script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; "
    "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
)
# Имена в /_astro/ содержат хэш содержимого, остальное (в том числе индекс поиска) меняется
# без смены имени, и Cloudflare не должен держать его в кэше.
IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"


class SiteFiles(StaticFiles):
    def __init__(self, directory: Path) -> None:
        super().__init__(directory=directory, html=True, check_dir=False)

    async def check_config(self) -> None:
        # До первого выката папки нет, и это не ошибка: сервис отвечает 404, а не 500.
        return

    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        response.headers["Content-Security-Policy"] = SITE_CSP
        cache = IMMUTABLE if path.startswith("_astro/") and response.status_code == 200 else REVALIDATE
        response.headers["Cache-Control"] = cache
        return response


def index_file(site_dir: Path) -> Path | None:
    index = site_dir / "index.html"
    return index if index.is_file() else None
