import hashlib
import io
import json
import os
import tarfile
import urllib.error
import urllib.request

import pytest
from starlette.testclient import TestClient

from alta_feedback import aod_archive
from alta_feedback.aod_archive import (
    ArchivedPdf,
    archive_root,
    backup,
    classify,
    fetch_url,
    load_manifest,
    run,
    summary,
)
from alta_feedback.main import create_app

PUBLIC = ArchivedPdf("report-1.pdf", "https://www.aod.rs/r1.pdf", True, "0" * 64, 10, "2026-11-03")
PRIVATE = ArchivedPdf("oglas-1.pdf", "https://www.aod.rs/o1.pdf", False, "0" * 64, 10, "2026-11-03")
MANIFEST = {p.name: p for p in (PUBLIC, PRIVATE)}


@pytest.fixture
def origin(monkeypatch):
    """Сайт AOD: url -> тело ответа; None — сайт не отвечает."""
    pages: dict[str, bytes | None] = {}

    def fake_urlopen(request, timeout):
        body = pages.get(request.full_url)
        if body is None:
            raise urllib.error.URLError("connection refused")
        return io.BytesIO(body)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return pages


def write_copy(data_dir, item, body: bytes):
    path = aod_archive.copy_path(archive_root(data_dir), item)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(aod_archive, "load_manifest", lambda: MANIFEST)
    monkeypatch.setattr("alta_feedback.main.load_manifest", lambda: MANIFEST)
    write_copy(tmp_path / "data", PUBLIC, b"%PDF-public")
    write_copy(tmp_path / "data", PRIVATE, b"%PDF-private")
    app = create_app(data_dir=tmp_path / "data", admin_token="t", ip_salt="salt", site_dir=tmp_path / "site")
    return TestClient(app, follow_redirects=False)


def test_public_copy_is_served_from_own_domain(client):
    response = client.get("/docs/aod/report-1.pdf")
    assert (response.status_code, response.content) == (200, b"%PDF-public")


def test_public_copy_can_be_embedded_by_the_site(client):
    assert "frame-ancestors 'self'" in client.get("/docs/aod/report-1.pdf").headers["content-security-policy"]


def test_public_copy_revalidates_by_etag(client):
    etag = client.get("/docs/aod/report-1.pdf").headers["etag"]
    assert client.get("/docs/aod/report-1.pdf", headers={"If-None-Match": etag}).status_code == 304


def test_unknown_document_is_404(client):
    assert client.get("/docs/aod/nope.pdf").status_code == 404


@pytest.mark.parametrize(
    "path",
    ["/docs/aod/oglas-1.pdf", "/docs/aod/../private/oglas-1.pdf", "/docs/aod/%2e%2e/private/oglas-1.pdf"],
)
def test_private_document_is_never_served(client, path):
    assert b"%PDF-private" not in client.get(path).content


def test_missing_copy_falls_back_to_the_original(client, tmp_path):
    (archive_root(tmp_path / "data") / "public" / "report-1.pdf").unlink()
    response = client.get("/docs/aod/report-1.pdf")
    assert (response.status_code, response.headers["location"]) == (307, PUBLIC.url)


def test_real_manifest_names_are_unique_and_point_to_aod():
    items = json.loads(aod_archive.MANIFEST_FILE.read_text(encoding="utf-8"))
    assert len({i["name"] for i in items}) == len(load_manifest()) == len(items)


def test_creditor_lists_stay_private():
    oglasi = [i for i in load_manifest().values() if "oglas" in i.url and i.name != "oglas-19-1.pdf"]
    assert oglasi and not any(i.public for i in oglasi)


def test_first_run_downloads_missing_copies(tmp_path, origin):
    origin[PUBLIC.url] = b"%PDF-one"
    origin[PRIVATE.url] = b"%PDF-two"
    run(tmp_path, None, MANIFEST)
    assert aod_archive.copy_path(archive_root(tmp_path), PRIVATE).read_bytes() == b"%PDF-two"


def test_changed_original_is_kept_beside_and_copy_stays(tmp_path, origin):
    copy = write_copy(tmp_path, PUBLIC, b"%PDF-old")
    origin[PUBLIC.url] = b"%PDF-new"
    origin[PRIVATE.url] = None
    run(tmp_path, None, {PUBLIC.name: PUBLIC})
    versions = list((archive_root(tmp_path) / "versions").glob("report-1-*.pdf"))
    assert (copy.read_bytes(), [v.read_bytes() for v in versions]) == (b"%PDF-old", [b"%PDF-new"])


def test_same_change_is_not_saved_twice(tmp_path, origin):
    write_copy(tmp_path, PUBLIC, b"%PDF-old")
    origin[PUBLIC.url] = b"%PDF-new"
    run(tmp_path, None, {PUBLIC.name: PUBLIC})
    second = run(tmp_path, None, {PUBLIC.name: PUBLIC})
    assert second[0].status == "ok"


def test_unavailable_original_keeps_the_copy(tmp_path, origin):
    copy = write_copy(tmp_path, PUBLIC, b"%PDF-old")
    result = run(tmp_path, None, {PUBLIC.name: PUBLIC})
    assert (result[0].status, copy.read_bytes()) == ("unavailable", b"%PDF-old")


def test_error_page_with_200_does_not_replace_the_copy(tmp_path, origin):
    write_copy(tmp_path, PUBLIC, b"%PDF-old")
    origin[PUBLIC.url] = b"<html>Service unavailable</html>"
    result = run(tmp_path, None, {PUBLIC.name: PUBLIC})
    assert (result[0].status, list((archive_root(tmp_path) / "versions").glob("*"))) == ("unavailable", [])


def test_html_is_not_saved_as_the_first_copy(tmp_path, origin):
    origin[PUBLIC.url] = b"<html>Service unavailable</html>"
    run(tmp_path, None, {PUBLIC.name: PUBLIC})
    assert not aod_archive.copy_path(archive_root(tmp_path), PUBLIC).exists()


def test_web_archive_links_are_fetched_raw():
    url = "https://web.archive.org/web/20160830214352/http://aod.rs/pdf/x.pdf"
    assert fetch_url(url) == "https://web.archive.org/web/20160830214352id_/http://aod.rs/pdf/x.pdf"


def test_every_run_is_logged(tmp_path, origin):
    origin[PUBLIC.url] = b"%PDF-one"
    run(tmp_path, None, {PUBLIC.name: PUBLIC})
    run(tmp_path, None, {PUBLIC.name: PUBLIC})
    assert len((archive_root(tmp_path) / "check.log").read_text().splitlines()) == 2


def test_backup_contains_private_documents_too(tmp_path, origin):
    origin[PUBLIC.url] = b"%PDF-one"
    origin[PRIVATE.url] = b"%PDF-two"
    run(tmp_path, tmp_path / "bk", MANIFEST)
    with tarfile.open(next((tmp_path / "bk").glob("*.tar.gz"))) as tar:
        assert "aod/private/oglas-1.pdf" in tar.getnames()


def test_unchanged_archive_refreshes_backup_instead_of_new_tar(tmp_path):
    copy = write_copy(tmp_path, PUBLIC, b"%PDF-one")
    os.utime(copy, (1000, 1000))
    first = backup(archive_root(tmp_path), tmp_path / "bk", "2026-11-03")
    os.utime(first, (2000, 2000))
    second = backup(archive_root(tmp_path), tmp_path / "bk", "2026-11-04")
    assert (second, second.stat().st_mtime > 2000) == (first, True)


def test_classify():
    sha = hashlib.sha256(b"x").hexdigest()
    assert [classify(False, sha, set()), classify(True, sha, {sha}), classify(True, sha, set())] == [
        "seeded",
        "ok",
        "changed",
    ]


def test_summary_names_documents_that_need_attention():
    results = [
        aod_archive.CheckResult("a.pdf", "ok"),
        aod_archive.CheckResult("b.pdf", "unavailable", detail="x"),
    ]
    assert "b.pdf: unavailable x" in summary(results)
