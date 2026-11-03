"""Своя копия PDF с сайта AOD (www.aod.rs), на которые ссылается справочник.

Справочник показывает их с нашего адреса, чтобы документы не пропали вместе с сайтом AOD.
Раз в день `python -m alta_feedback.aod_archive` сверяет копию с оригиналом: недостающее
докачивает, изменившийся оригинал кладёт рядом новой версией с датой, а отдаём всё равно
первую копию — ту, что описана в манифесте.

На диске (`$DATA_DIR/aod/`):
  public/<name>    — отдаётся по /docs/aod/<name>
  private/<name>   — документы со списками кредиторов-частных лиц, наружу не отдаются
  versions/<stem>-<YYYY-MM-DD>.pdf — оригинал, который поменялся после первой копии
  check.log        — строка JSON на каждый прогон
"""

import hashlib
import json
import os
import re
import sys
import tarfile
import time
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

MANIFEST_FILE = Path(__file__).parent / "data" / "aod_archive.json"
FETCH_TIMEOUT = 300
CHUNK = 1 << 20
USER_AGENT = "alta.smolevich.com archive check (+https://alta.smolevich.com)"


@dataclass(frozen=True)
class ArchivedPdf:
    name: str
    url: str
    public: bool
    sha256: str
    bytes: int
    fetched: str


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str  # ok | seeded | changed | unavailable
    sha256: str | None = None
    detail: str = ""


def load_manifest(path: Path = MANIFEST_FILE) -> dict[str, ArchivedPdf]:
    items = [ArchivedPdf(**raw) for raw in json.loads(path.read_text(encoding="utf-8"))]
    return {item.name: item for item in items}


def archive_root(data_dir: Path) -> Path:
    return data_dir / "aod"


def copy_path(root: Path, item: ArchivedPdf) -> Path:
    return root / ("public" if item.public else "private") / item.name


def version_path(root: Path, item: ArchivedPdf, day: str) -> Path:
    return root / "versions" / f"{Path(item.name).stem}-{day}.pdf"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def known_hashes(root: Path, item: ArchivedPdf) -> set[str]:
    """Хэши всего, что у нас уже лежит для документа: копия и сохранённые версии."""
    stem = Path(item.name).stem
    paths = [copy_path(root, item), *(root / "versions").glob(f"{stem}-*.pdf")]
    return {file_sha256(p) for p in paths if p.is_file()}


def classify(has_copy: bool, fetched_sha: str, known: set[str]) -> str:
    if not has_copy:
        return "seeded"
    return "ok" if fetched_sha in known else "changed"


def fetch_url(url: str) -> str:
    """Веб-архив без `id_` отдаёт программам HTML-обёртку, а не сам файл."""
    return re.sub(r"(web\.archive\.org/web/\d+)/", r"\1id_/", url)


class NotPdf(OSError):
    pass


def download(url: str, dest: Path) -> str:
    """Скачивает в dest и возвращает sha256; в память целиком не читает — монография 100 МБ.

    Ответ, который не начинается с %PDF (страница ошибки с кодом 200), — NotPdf.
    """
    request = urllib.request.Request(fetch_url(url), headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response, dest.open("wb") as out:
        first = True
        while chunk := response.read(CHUNK):
            if first and not chunk.startswith(b"%PDF"):
                raise NotPdf(f"not a PDF: {chunk[:40]!r}")
            first = False
            digest.update(chunk)
            out.write(chunk)
    return digest.hexdigest()


def check_one(root: Path, item: ArchivedPdf, day: str) -> CheckResult:
    copy = copy_path(root, item)
    copy.parent.mkdir(parents=True, exist_ok=True)
    tmp = root / f".{item.name}.part"
    try:
        sha = download(item.url, tmp)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        return CheckResult(item.name, "unavailable", detail=str(e)[:200])
    status = classify(copy.is_file(), sha, known_hashes(root, item))
    if status == "seeded":
        tmp.replace(copy)
    elif status == "changed":
        target = version_path(root, item, day)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp.replace(target)
    else:
        tmp.unlink()
    detail = "differs from manifest" if status == "seeded" and sha != item.sha256 else ""
    return CheckResult(item.name, status, sha, detail)


def archive_files(root: Path) -> Iterator[Path]:
    for sub in ("public", "private", "versions"):
        yield from (p for p in sorted((root / sub).glob("*.pdf")) if p.is_file())


def backup(root: Path, backup_dir: Path, day: str) -> Path:
    """Архив целиком в <backup_dir>/<day>.tar.gz для ночной копии в R2.

    Новый tar — только если в архиве появилось что-то новее прошлого; иначе прошлый
    просто «освежается», чтобы недельная проверка бэкапов видела, что задача жива.
    """
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    previous = max(backup_dir.glob("*.tar.gz"), key=lambda p: p.stat().st_mtime, default=None)
    files = list(archive_files(root))
    if previous and all(p.stat().st_mtime <= previous.stat().st_mtime for p in files):
        previous.touch()
        return previous
    out = backup_dir / f"{day}.tar.gz"
    tmp = out.with_suffix(".tmp")
    with tarfile.open(tmp, "w:gz", compresslevel=1) as tar:
        for path in files:
            tar.add(path, arcname=str(path.relative_to(root.parent)))
    tmp.replace(out)
    return out


def summary(results: list[CheckResult]) -> str:
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    head = ", ".join(f"{status} {n}" for status, n in sorted(counts.items()))
    notable = [f"{r.name}: {r.status} {r.detail}".strip() for r in results if r.status != "ok"]
    return "; ".join([f"aod-archive: {head}", *notable])


def run(data_dir: Path, backup_dir: Path | None, manifest: dict[str, ArchivedPdf]) -> list[CheckResult]:
    root = archive_root(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    results = [check_one(root, item, day) for item in manifest.values()]
    line = {"at": datetime.now(UTC).isoformat(timespec="seconds"), "results": [r.__dict__ for r in results]}
    with (root / "check.log").open("a", encoding="utf-8") as log:
        log.write(json.dumps(line, ensure_ascii=False) + "\n")
    if backup_dir:
        backup(root, backup_dir, day)
    return results


def main() -> int:
    data_dir = Path(os.environ.get("DATA_DIR", "data"))
    backup_dir = os.environ.get("AOD_BACKUP_DIR")
    started = time.monotonic()
    results = run(data_dir, Path(backup_dir) if backup_dir else None, load_manifest())
    print(f"{summary(results)} ({time.monotonic() - started:.0f}s)")
    # Недоступный оригинал — не сбой задачи: сайт продолжает отдавать свою копию.
    return 0


if __name__ == "__main__":
    sys.exit(main())
